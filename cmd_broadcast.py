"""
cmd_broadcast.py — /broadcast  Unified Broadcast & Schedule Hub
────────────────────────────────────────────────────────────────
Admin-only. Runs entirely in DM.
Replaces: /newsched /announce /editannounce /delannounce

Menu:
  /broadcast → Home ─┬─ 📤 Post Now         → target → message → tag all? → confirm
                      ├─ 📅 Schedule         → target → recurrence → date/time → message → tag all → confirm
                      ├─ 📋 List Schedules   → paginated, with delete buttons
                      └─ 🗑️ Delete Schedule  → pick from list

Recurrence options: Once | Daily (Weekdays) | Daily (All Days) | Weekly
Target options: All Groups | Custom ID (typed)

Callback prefix: bc_
Owner-locked, 120-second auto-expiry.
"""

import datetime
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import (
    delete_cmd, is_bot_admin,
    schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership, log_action,
    schedule_text_input_timeout, cancel_text_input_timeout,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────

def _home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Post Now",        callback_data="bc_postnow"),
         InlineKeyboardButton("📅 Schedule",        callback_data="bc_schedule")],
        [InlineKeyboardButton("📋 List Schedules",  callback_data="bc_list_0"),
         InlineKeyboardButton("🗑️ Delete Schedule", callback_data="bc_del_pick")],
        [InlineKeyboardButton("🚪 Close",           callback_data="bc_close")],
    ])


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",  callback_data="bc_home"),
        InlineKeyboardButton("🚪 Close", callback_data="bc_close"),
    ]])


def _target_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 All Groups",    callback_data="bc_target_all"),
         InlineKeyboardButton("🎯 Custom ID",     callback_data="bc_target_custom")],
        [InlineKeyboardButton("🏠 Home", callback_data="bc_home"),
         InlineKeyboardButton("🚪 Close", callback_data="bc_close")],
    ])


def _recurrence_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Once",               callback_data="bc_freq_once"),
         InlineKeyboardButton("📅 Daily (Weekdays)",   callback_data="bc_freq_weekday")],
        [InlineKeyboardButton("📆 Daily (All Days)",   callback_data="bc_freq_daily"),
         InlineKeyboardButton("📅 Weekly",             callback_data="bc_freq_weekly")],
        [InlineKeyboardButton("🏠 Home", callback_data="bc_home"),
         InlineKeyboardButton("🚪 Close", callback_data="bc_close")],
    ])


def _tag_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Tag All (@here)",  callback_data="bc_tag_yes"),
         InlineKeyboardButton("🔕 No Tag",           callback_data="bc_tag_no")],
        [InlineKeyboardButton("🏠 Home", callback_data="bc_home"),
         InlineKeyboardButton("🚪 Close", callback_data="bc_close")],
    ])


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm",  callback_data="bc_confirm"),
        InlineKeyboardButton("✏️ Edit",    callback_data="bc_edit"),
        InlineKeyboardButton("❌ Cancel",  callback_data="bc_home"),
    ]])


def _draft_summary(d: dict) -> str:
    freq_labels = {
        "once": "Once", "weekday": "Daily (Weekdays)",
        "daily": "Daily (All Days)", "weekly": "Weekly"
    }
    tag_label = "Yes 🔔" if d.get("tag_all") else "No 🔕"
    sched     = d.get("scheduled_at")
    sched_str = sched.strftime("%m/%d/%Y %H:%M WIB") if sched else "Post immediately"
    freq      = freq_labels.get(d.get("frequency", "once"), "Once")
    msg_prev  = (d.get("message", "")[:60] + "…") if len(d.get("message","")) > 60 else (d.get("message") or "_Not set_")
    return (
        f"📢 *Broadcast Draft*\n\n"
        f"📡 Target: `{d.get('chat_id', 'all')}`\n"
        f"🔁 Frequency: `{freq}`\n"
        f"⏰ When: `{sched_str}`\n"
        f"🔔 Tag All: `{tag_label}`\n"
        f"📝 Message:\n_{msg_prev}_"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool     = context.bot_data.get("db_pool")
    username = update.effective_user.username or str(update.effective_user.id)
    uid      = update.effective_user.id

    if not await is_bot_admin(username, pool):
        return

    context.user_data.pop("bc_draft", None)
    context.user_data.pop("bc_state", None)

    try:
        msg = await context.bot.send_message(
            uid,
            "📢 *Broadcast Hub*\n\nCreate and manage team broadcasts.\n"
            "_(Panel closes after 120 s of inactivity.)_",
            reply_markup=_home_kb(),
            parse_mode="Markdown"
        )
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
        await update.message.reply_text("❌ Please start a DM with me first (/start), then try again.")


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uid  = q.from_user.id
    username = q.from_user.username or str(uid)

    if not await check_kb_ownership(q, context):
        return await q.answer("This panel isn't yours.", show_alert=True)

    if not await is_bot_admin(username, pool):
        return await q.answer("Admins only.", show_alert=True)

    await q.answer()

    # ── Home ─────────────────────────────────────────────────────────────────
    if data == "bc_home":
        context.user_data.pop("bc_draft", None)
        context.user_data.pop("bc_state", None)
        await q.message.edit_text(
            "📢 *Broadcast Hub*\n\nCreate and manage team broadcasts.",
            reply_markup=_home_kb(), parse_mode="Markdown"
        )

    # ── Close ─────────────────────────────────────────────────────────────────
    elif data == "bc_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("bc_draft", None)
        context.user_data.pop("bc_state", None)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── Post Now — start ──────────────────────────────────────────────────────
    elif data == "bc_postnow":
        context.user_data["bc_draft"] = {"frequency": "once", "scheduled_at": None}
        context.user_data["bc_state"] = "postnow_target"
        await q.message.edit_text(
            "📤 *Post Now — Step 1 of 3*\n\nChoose the target:",
            reply_markup=_target_kb(), parse_mode="Markdown"
        )

    # ── Schedule — start ──────────────────────────────────────────────────────
    elif data == "bc_schedule":
        context.user_data["bc_draft"] = {}
        context.user_data["bc_state"] = "sched_target"
        await q.message.edit_text(
            "📅 *Schedule Broadcast — Step 1 of 5*\n\nChoose the target:",
            reply_markup=_target_kb(), parse_mode="Markdown"
        )

    # ── Target selection ──────────────────────────────────────────────────────
    elif data == "bc_target_all":
        _get_draft(context)["chat_id"] = "all"
        await _next_step(q, context)

    elif data == "bc_target_custom":
        base = context.user_data.get("bc_state", "")
        context.user_data["bc_state"]     = base + "_custom_id"
        context.user_data["bc_panel_chat"] = q.message.chat_id
        context.user_data["bc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "🎯 *Custom Target*\n\n"
            "Type the Group/Channel ID:\n"
            "_e.g._ `-1001234567890`\n\n"
            "_Run /groupid inside the target group to find its ID._\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "bc_state", base + "_custom_id", q.message.chat_id, q.message.message_id)

    # ── Frequency ────────────────────────────────────────────────────────────
    elif data.startswith("bc_freq_"):
        freq = data[8:]
        _get_draft(context)["frequency"] = freq
        await _next_step(q, context)

    # ── Tag All ───────────────────────────────────────────────────────────────
    elif data in ("bc_tag_yes", "bc_tag_no"):
        _get_draft(context)["tag_all"] = (data == "bc_tag_yes")
        await _next_step(q, context)

    # ── Edit draft (go back to message step) ─────────────────────────────────
    elif data == "bc_edit":
        context.user_data["bc_state"] = "await_message"
        await q.message.edit_text(
            "✏️ *Edit Message*\n\nType the new broadcast message:",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Confirm ───────────────────────────────────────────────────────────────
    elif data == "bc_confirm":
        await _do_confirm(q, context, pool, username)

    # ── List schedules ────────────────────────────────────────────────────────
    elif data.startswith("bc_list_"):
        page = int(data[8:])
        await _show_list(q, pool, page)

    # ── Delete pick ───────────────────────────────────────────────────────────
    elif data == "bc_del_pick":
        await _show_del_pick(q, pool)

    elif data.startswith("bc_edit_msg_"):
        s_id = int(data[12:])
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT message FROM scheduled_announcements WHERE id=$1", s_id
            )
        if not row:
            return await q.answer("Schedule not found.", show_alert=True)
        context.user_data["bc_state"]    = f"await_edit_msg_{s_id}"
        context.user_data["bc_edit_id"]  = s_id
        old_msg = (row["message"] or "").strip()
        await q.message.edit_text(
            f"✏️ *Edit Message for Schedule #{s_id}*\n\n"
            f"Current message:\n_{old_msg[:400]}_\n\n"
            "Type the new message below\n"
            "_(long-press the current message above to copy it as a starting point)_",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="bc_list_0")
            ]]),
            parse_mode="Markdown"
        )
        from core import schedule_text_input_timeout
        await schedule_text_input_timeout(
            context, uid, "bc_state", f"await_edit_msg_{s_id}",
            q.message.chat_id, q.message.message_id
        )

    elif data.startswith("bc_delid_"):
        s_id = int(data[9:])
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM scheduled_announcements WHERE id=$1", s_id)
        await log_action(pool, uid, uid, "Broadcast", "Deleted", f"Schedule #{s_id}")
        await q.message.edit_text(
            f"✅ Schedule `#{s_id}` deleted.",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )


# ─────────────────────────────────────────────────────────────────────────────
# FLOW HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_draft(context) -> dict:
    if "bc_draft" not in context.user_data:
        context.user_data["bc_draft"] = {}
    return context.user_data["bc_draft"]


async def _next_step(q, context):
    """Advance to the next wizard step based on current state."""
    state = context.user_data.get("bc_state", "")
    draft = _get_draft(context)
    uid   = q.from_user.id

    # Post Now flow: target → tag → message → confirm
    if state == "postnow_target":
        context.user_data["bc_state"] = "postnow_tag"
        await q.message.edit_text(
            "📤 *Post Now — Step 2 of 3*\n\nTag all group members?",
            reply_markup=_tag_kb(), parse_mode="Markdown"
        )
    elif state == "postnow_tag":
        context.user_data["bc_state"]     = "await_message"
        context.user_data["bc_panel_chat"] = q.message.chat_id
        context.user_data["bc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "📤 *Post Now — Step 3 of 3*\n\nType the broadcast message:\n⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, uid, "bc_state", "await_message", q.message.chat_id, q.message.message_id)

    # Schedule flow: target → frequency → datetime → tag → message → confirm
    elif state == "sched_target":
        context.user_data["bc_state"] = "sched_freq"
        await q.message.edit_text(
            "📅 *Schedule Broadcast — Step 2 of 5*\n\nChoose recurrence:",
            reply_markup=_recurrence_kb(), parse_mode="Markdown"
        )
    elif state == "sched_freq":
        context.user_data["bc_state"]     = "await_sched_datetime"
        context.user_data["bc_panel_chat"] = q.message.chat_id
        context.user_data["bc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "📅 *Schedule Broadcast — Step 3 of 5*\n\n"
            "Type the date and time:\n`MM/DD/YYYY HH:MM`\n\n"
            "_e.g._ `07/01/2026 09:00`\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, uid, "bc_state", "await_sched_datetime", q.message.chat_id, q.message.message_id)
    elif state == "sched_datetime":
        context.user_data["bc_state"] = "sched_tag"
        await q.message.edit_text(
            "📅 *Schedule Broadcast — Step 4 of 5*\n\nTag all group members?",
            reply_markup=_tag_kb(), parse_mode="Markdown"
        )
    elif state == "sched_tag":
        context.user_data["bc_state"]     = "await_message"
        context.user_data["bc_panel_chat"] = q.message.chat_id
        context.user_data["bc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "📅 *Schedule Broadcast — Step 5 of 5*\n\nType the broadcast message:\n⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, uid, "bc_state", "await_message", q.message.chat_id, q.message.message_id)


async def _do_confirm(q, context, pool, username: str):
    draft = _get_draft(context)
    if not draft.get("message"):
        return await q.answer("Message is required.", show_alert=True)

    msg     = draft["message"]
    tag     = draft.get("tag_all", False)
    chat_id = draft.get("chat_id", "all")
    sched   = draft.get("scheduled_at")
    freq    = draft.get("frequency", "once")
    uid     = q.from_user.id

    if tag:
        # Tag all non-bot registered members
        async with pool.acquire() as conn:
            if chat_id == "all":
                members = await conn.fetch(
                    "SELECT username FROM users WHERE username IS NOT NULL ORDER BY username"
                )
            else:
                members = await conn.fetch(
                    "SELECT username FROM users WHERE username IS NOT NULL ORDER BY username"
                )
        mentions = " ".join(f"@{r['username']}" for r in members if r["username"])
        msg = (mentions + "\n\n" + msg) if mentions else msg

    if sched is None:
        # Post immediately
        await _do_post_now(context.bot, pool, chat_id, msg, q)
        await log_action(pool, uid, uid, "Broadcast", "Posted Now", f"target={chat_id}")
        context.user_data.pop("bc_draft", None)
        context.user_data.pop("bc_state", None)
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        try:
            await q.message.delete()
        except Exception:
            pass
        await context.bot.send_message(q.from_user.id, "✅ *Broadcast sent!*", parse_mode="Markdown")
    else:
        # Save schedule
        run_time = sched.strftime("%H:%M")
        run_date = sched.strftime("%Y-%m-%d")
        async with pool.acquire() as conn:
            # Ensure scheduled_date column exists (added in v1.3)
            try:
                await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN IF NOT EXISTS scheduled_date TEXT")
            except Exception:
                pass
            s_id = await conn.fetchval(
                "INSERT INTO scheduled_announcements (chat_id, frequency, run_time, mention, message, created_by, scheduled_date) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id",
                chat_id, freq, run_time, tag, draft["message"], username, run_date
            )
        await log_action(pool, uid, uid, "Broadcast", "Scheduled", f"#{s_id} target={chat_id} freq={freq}")
        context.user_data.pop("bc_draft", None)
        context.user_data.pop("bc_state", None)
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        try:
            await q.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            q.from_user.id,
            f"✅ *Broadcast scheduled!*\n\n"
            f"🔑 Schedule ID: `#{s_id}`\n"
            f"⏰ {sched.strftime('%m/%d/%Y %H:%M WIB')}\n"
            f"🔁 {freq}",
            parse_mode="Markdown"
        )


async def _do_post_now(bot, pool, chat_id: str, message: str, q):
    async with pool.acquire() as conn:
        if chat_id == "all":
            chats = await conn.fetch("SELECT DISTINCT chat_id FROM group_settings")
            if not chats:
                chats = await conn.fetch("SELECT DISTINCT chat_id FROM active_groups")
            chats = [{"chat_id": int(r["chat_id"])} for r in chats]
        else:
            try:
                chats = [{"chat_id": int(chat_id)}]
            except (ValueError, TypeError):
                await q.answer("❌ Invalid target chat ID.", show_alert=True)
                return

    if not chats:
        await q.answer("❌ No target groups found. Use /registergroup in your group first.", show_alert=True)
        return

    sent = failed = 0
    for ch in chats:
        try:
            await bot.send_message(ch["chat_id"], message, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast to {ch['chat_id']} failed: {e}")
            failed += 1

    result = f"✅ Sent to {sent} group{'s' if sent != 1 else ''}"
    if failed:
        result += f", {failed} failed"
    await q.answer(result, show_alert=True)


# ─────────────────────────────────────────────────────────────────────────────
# LIST & DELETE SCHEDULES
# ─────────────────────────────────────────────────────────────────────────────

async def _show_list(q, pool, page: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chat_id, frequency, run_time, mention, message, scheduled_at "
            "FROM scheduled_announcements ORDER BY id DESC"
        )

    if not rows:
        return await q.message.edit_text(
            "📋 *Scheduled Broadcasts*\n\n_No schedules set up yet._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    PAGE = 3   # fewer per page so full message fits
    total = len(rows)
    pages = max(1, (total + PAGE - 1) // PAGE)
    page  = max(0, min(page, pages - 1))
    chunk = rows[page * PAGE: (page + 1) * PAGE]

    freq_labels = {
        "once": "Once", "weekday": "Daily (Mon–Fri)",
        "daily": "Daily (All Days)", "weekly": "Weekly (Mon)"
    }

    lines = [f"📋 *Scheduled Broadcasts* ({total} total) — Page {page+1}/{pages}\n"]
    for r in chunk:
        freq = freq_labels.get(r["frequency"], r["frequency"])
        tag  = "🔔 Tag all" if r["mention"] else "🔕 No tag"

        # First fire time (asyncpg Record has no .get() — use bracket + try/except)
        sched_at = None
        try:
            sched_at = r["scheduled_at"]
        except (KeyError, IndexError):
            sched_at = None

        if r["frequency"] == "once" and sched_at:
            from core import WIB as _WIB
            first_str = sched_at.astimezone(_WIB).strftime("%b %d %Y at %H:%M WIB")
        else:
            first_str = f"Daily at {r['run_time']} WIB"

        # Full message (up to 300 chars to keep panel readable)
        full_msg = (r["message"] or "").strip()
        msg_display = full_msg[:300] + ("…" if len(full_msg) > 300 else "")

        lines.append(
            f"─────────────────\n"
            f"🔹 *Schedule #{r['id']}*\n"
            f"📡 Target: `{r['chat_id']}`\n"
            f"🔁 {freq}\n"
            f"⏰ First run: {first_str}\n"
            f"🔔 {tag}\n"
            f"📝 Message:\n_{msg_display}_"
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"bc_list_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"bc_list_{page+1}"))

    # Edit and Delete buttons for each schedule in view
    action_rows = []
    for r in chunk:
        action_rows.append([
            InlineKeyboardButton(f"✏️ Edit #{r['id']}",  callback_data=f"bc_edit_msg_{r['id']}"),
            InlineKeyboardButton(f"🗑️ Delete #{r['id']}", callback_data=f"bc_delid_{r['id']}"),
        ])

    rows_kb = action_rows
    if nav:
        rows_kb.append(nav)
    rows_kb.append([InlineKeyboardButton("🏠 Home", callback_data="bc_home"),
                    InlineKeyboardButton("🚪 Close", callback_data="bc_close")])

    await q.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows_kb),
        parse_mode="Markdown"
    )


async def _show_del_pick(q, pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chat_id, frequency, run_time FROM scheduled_announcements ORDER BY id DESC LIMIT 15"
        )

    if not rows:
        return await q.answer("No schedules to delete.", show_alert=True)

    freq_labels = {"once":"Once","weekday":"Wkday","daily":"Daily","weekly":"Weekly"}
    btn_rows = []
    for r in rows:
        freq  = freq_labels.get(r["frequency"], r["frequency"])
        label = f"🗑️ #{r['id']} → {r['chat_id']} | {freq} {r['run_time']}"
        btn_rows.append([InlineKeyboardButton(label[:50], callback_data=f"bc_delid_{r['id']}")])

    btn_rows.append([InlineKeyboardButton("🏠 Home", callback_data="bc_home"),
                     InlineKeyboardButton("🚪 Close", callback_data="bc_close")])

    await q.message.edit_text(
        "🗑️ *Delete Schedule*\n\nSelect a schedule to remove:",
        reply_markup=InlineKeyboardMarkup(btn_rows),
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("bc_state")
    if not state:
        return False
    if update.effective_chat.type != "private":
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)
    draft    = _get_draft(context)

    async def _invalid(error_text: str, guide_text: str):
        try:
            await update.message.reply_text(f"❌ {error_text}", parse_mode="Markdown")
        except Exception:
            pass
        panel_chat = context.user_data.get("bc_panel_chat", uid)
        panel_msg  = context.user_data.get("bc_panel_msg")
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text=guide_text, reply_markup=_back_kb(), parse_mode="Markdown",
                )
            except Exception:
                pass

    if not await is_bot_admin(username, pool):
        context.user_data.pop("bc_state", None)
        return False

    # ── Custom Group/Channel ID ────────────────────────────────────────────
    if state.endswith("_custom_id"):
        base_state = state[:-len("_custom_id")]
        if not re.match(r'^-?\d+$', text):
            await _invalid(
                "That doesn't look like a valid ID.\n_e.g._ `-1001234567890`",
                "🎯 *Custom Target*\n\nType the Group/Channel ID:\n_e.g._ `-1001234567890`\n\n_Run /groupid inside the target group to find its ID._\n⏰ _Times out in 120 seconds._",
            )
            return True
        draft["chat_id"] = text
        cancel_text_input_timeout(context, uid, "bc_state")
        # Advance and edit the panel in-place
        panel_chat = context.user_data.get("bc_panel_chat", uid)
        panel_msg  = context.user_data.get("bc_panel_msg")
        if base_state == "postnow_target":
            context.user_data["bc_state"] = "postnow_tag"
            panel_text = "📤 *Post Now — Step 2 of 3*\n\nTag all group members?"
            panel_kb   = _tag_kb()
        else:  # sched_target
            context.user_data["bc_state"] = "sched_freq"
            panel_text = "📅 *Schedule Broadcast — Step 2 of 5*\n\nChoose recurrence:"
            panel_kb   = _recurrence_kb()
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text=panel_text, reply_markup=panel_kb, parse_mode="Markdown",
                )
            except Exception:
                pass
        else:
            msg = await update.message.reply_text(panel_text, reply_markup=panel_kb, parse_mode="Markdown")
            await schedule_kb_timeout(context, uid, msg.message_id, uid)
            context.user_data["bc_panel_chat"] = uid
            context.user_data["bc_panel_msg"]  = msg.message_id
        return True

    # ── Scheduled datetime input ───────────────────────────────────────────
    elif state == "await_sched_datetime":
        try:
            from core import WIB
            dt = WIB.localize(datetime.datetime.strptime(text, "%m/%d/%Y %H:%M"))
            if dt < datetime.datetime.now(WIB):
                raise ValueError("past")
        except ValueError:
            await _invalid(
                "Invalid date or it's in the past.\nFormat: `MM/DD/YYYY HH:MM` — e.g. `07/01/2026 09:00`",
                "📅 *Schedule Broadcast — Step 3 of 5*\n\n"
                "Type the date and time:\n`MM/DD/YYYY HH:MM`\n\n"
                "_e.g._ `07/01/2026 09:00`\n"
                "⏰ _Times out in 120 seconds._",
            )
            return True
        cancel_text_input_timeout(context, uid, "bc_state")
        draft["scheduled_at"] = dt
        context.user_data["bc_state"] = "sched_datetime"
        context.user_data["bc_draft"]  = draft
        # Edit the panel message in place so ownership/timeout remain on the same msg
        panel_chat = context.user_data.get("bc_panel_chat", uid)
        panel_msg  = context.user_data.get("bc_panel_msg")
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text="📅 *Schedule Broadcast — Step 4 of 5*\n\nTag all group members?",
                    reply_markup=_tag_kb(), parse_mode="Markdown",
                )
            except Exception:
                pass
        else:
            msg = await update.message.reply_text(
                "📅 *Schedule Broadcast — Step 4 of 5*\n\nTag all group members?",
                reply_markup=_tag_kb(), parse_mode="Markdown"
            )
            await schedule_kb_timeout(context, uid, msg.message_id, uid)
            context.user_data["bc_panel_chat"] = uid
            context.user_data["bc_panel_msg"]  = msg.message_id
        return True

    # ── Edit existing schedule message ────────────────────────────────────
    elif state.startswith("await_edit_msg_"):
        s_id = int(state.split("_")[-1])
        if not text:
            await update.message.reply_text("❌ Message cannot be empty.")
            return True
        from core import cancel_text_input_timeout
        cancel_text_input_timeout(context, uid, "bc_state")
        context.user_data.pop("bc_state", None)
        context.user_data.pop("bc_edit_id", None)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scheduled_announcements SET message=$1 WHERE id=$2",
                text, s_id
            )
        await update.message.reply_text(
            f"✅ *Schedule #{s_id} message updated!*\n\n_{text[:200]}_",
            parse_mode="Markdown"
        )
        return True

    # ── Message input ──────────────────────────────────────────────────────
    elif state == "await_message":
        if not text:
            await _invalid(
                "Message cannot be empty.",
                "📝 *Broadcast Message*\n\nType the broadcast message:\n⏰ _Times out in 120 seconds._",
            )
            return True
        cancel_text_input_timeout(context, uid, "bc_state")
        draft["message"] = text
        context.user_data["bc_draft"] = draft
        context.user_data["bc_state"] = "confirm"
        # Edit the panel in place for confirm step too
        panel_chat = context.user_data.get("bc_panel_chat", uid)
        panel_msg  = context.user_data.get("bc_panel_msg")
        summary    = _draft_summary(draft) + "\n\n_Confirm to send/save._"
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text=summary, reply_markup=_confirm_kb(), parse_mode="Markdown",
                )
            except Exception:
                pass
        else:
            msg = await update.message.reply_text(summary, reply_markup=_confirm_kb(), parse_mode="Markdown")
            await schedule_kb_timeout(context, uid, msg.message_id, uid)
            context.user_data["bc_panel_chat"] = uid
            context.user_data["bc_panel_msg"]  = msg.message_id
        return True

    return False
