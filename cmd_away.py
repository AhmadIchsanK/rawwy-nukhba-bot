"""
cmd_away.py — /away  Inline Away Hub
──────────────────────────────────────
All setup flows in DM. /back must still be typed manually.
Appearing in chat does NOT auto-cancel away — instead there's
a prompt on the inline keyboard: "Cancel away when I send a message?"
Owner-locked, 120-second auto-expiry.

Menu:
  /away  →  Home  ─┬─ 🏖️ Set Away     → DM: reason → return date/time
                    ├─ 🟢 I'm Back     → confirm → clear away
                    ├─ ⚙️ Auto-Cancel   → toggle (cancel away on next group message)
                    └─ 📋 My Status    → show current away info

Callback prefix: aw_
"""

import datetime
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import (
    WIB, delete_cmd, schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership, log_action,
    schedule_text_input_timeout, cancel_text_input_timeout,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────

def _home_kb(is_away: bool) -> InlineKeyboardMarkup:
    if is_away:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 I'm Back",       callback_data="aw_back_confirm")],
            [InlineKeyboardButton("⚙️ Auto-Cancel Toggle", callback_data="aw_toggle_auto")],
            [InlineKeyboardButton("📋 My Status",      callback_data="aw_status")],
            [InlineKeyboardButton("🚪 Close",           callback_data="aw_close")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏖️ Set Away",           callback_data="aw_set")],
        [InlineKeyboardButton("📋 My Status",           callback_data="aw_status")],
        [InlineKeyboardButton("🚪 Close",               callback_data="aw_close")],
    ])


def _back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home", callback_data="aw_home"),
        InlineKeyboardButton("🚪 Close", callback_data="aw_close"),
    ]])


def _confirm_back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, I'm Back", callback_data="aw_back_do"),
        InlineKeyboardButton("❌ Cancel",         callback_data="aw_home"),
    ]])


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def away_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    user = update.effective_user
    uid  = user.id
    pool = context.bot_data.get("db_pool")
    username = user.username or str(uid)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT end_time, reason FROM away_status WHERE username=$1", username)
    is_away = row is not None

    if is_away:
        end_str = row["end_time"].astimezone(WIB).strftime("%b %d at %H:%M WIB")
        text = (
            f"🏖️ *Away Hub*\n\n"
            f"You are currently *away*.\n"
            f"📝 Reason: _{row['reason']}_\n"
            f"⏰ Until: {end_str}\n\n"
            f"_(Panel closes after 120 s of inactivity.)_"
        )
    else:
        text = (
            "🏖️ *Away Hub*\n\n"
            "You are currently *available*.\n\n"
            "_(Panel closes after 120 s of inactivity.)_"
        )

    try:
        msg = await context.bot.send_message(uid, text, reply_markup=_home_kb(is_away), parse_mode="Markdown")
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
        if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
            bot_uname = (await context.bot.get_me()).username
            url = f"https://t.me/{bot_uname}?start=open_away"
            kb  = InlineKeyboardMarkup([[InlineKeyboardButton("🏖️ Open Away in DM", url=url)]])
            await update.effective_chat.send_message(
                f"👋 {user.first_name} — tap below to manage your Away status in DM.",
                reply_markup=kb
            )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def away_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uid  = q.from_user.id
    username = q.from_user.username or str(uid)

    if not await check_kb_ownership(q, context):
        return await q.answer("This panel isn't yours.", show_alert=True)
    await q.answer()

    # ── Home ─────────────────────────────────────────────────────────────────
    if data == "aw_home":
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT end_time, reason FROM away_status WHERE username=$1", username)
        is_away = row is not None
        if is_away:
            end_str = row["end_time"].astimezone(WIB).strftime("%b %d at %H:%M WIB")
            text = (f"🏖️ *Away Hub*\n\nYou are *away*.\n📝 Reason: _{row['reason']}_\n⏰ Until: {end_str}")
        else:
            text = "🏖️ *Away Hub*\n\nYou are currently *available*."
        await q.message.edit_text(text, reply_markup=_home_kb(is_away), parse_mode="Markdown")
        context.user_data.pop("aw_state", None)

    # ── Close ────────────────────────────────────────────────────────────────
    elif data == "aw_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("aw_state", None)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── Status ───────────────────────────────────────────────────────────────
    elif data == "aw_status":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT reason, end_time FROM away_status WHERE username=$1", username
            )
            mention_count = await conn.fetchval(
                "SELECT COUNT(*) FROM away_mentions WHERE away_username=$1", username
            ) if row else 0

        if not row:
            text = "📋 *My Away Status*\n\n🟢 You are currently *available*."
        else:
            end_str = row["end_time"].astimezone(WIB).strftime("%b %d at %H:%M WIB")
            text = (
                f"📋 *My Away Status*\n\n"
                f"🔴 *Away*\n"
                f"📝 Reason: _{row['reason']}_\n"
                f"⏰ Until: {end_str}\n"
                f"📩 Mentions while away: *{mention_count}*"
            )
        await q.message.edit_text(text, reply_markup=_back_kb(), parse_mode="Markdown")

    # ── Set Away — start ─────────────────────────────────────────────────────
    elif data == "aw_set":
        async with pool.acquire() as conn:
            existing = await conn.fetchrow("SELECT end_time FROM away_status WHERE username=$1", username)
        if existing:
            end_str = existing["end_time"].astimezone(WIB).strftime("%b %d at %H:%M WIB")
            return await q.answer(f"You're already away until {end_str}.", show_alert=True)

        context.user_data["aw_state"]     = "await_reason"
        context.user_data["aw_panel_chat"] = q.message.chat_id
        context.user_data["aw_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "🏖️ *Set Away — Step 1 of 2*\n\n"
            "Type your *away reason*:\n\n"
            "_e.g. On leave, At a conference, Out sick_\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "aw_state", "await_reason", q.message.chat_id, q.message.message_id)

    # ── Back — confirm ───────────────────────────────────────────────────────
    elif data == "aw_back_confirm":
        await q.message.edit_text(
            "🟢 *Mark yourself as back?*\n\n"
            "This will clear your away status and deliver any missed mentions.",
            reply_markup=_confirm_back_kb(), parse_mode="Markdown"
        )

    # ── Back — do it ─────────────────────────────────────────────────────────
    elif data == "aw_back_do":
        import cmd_user
        msg = await cmd_user.process_return(username, pool, context.bot)
        for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
            j.schedule_removal()
        context.user_data.pop("aw_state", None)
        context.user_data.pop(f"aw_autocancel_{username}", None)
        await q.message.edit_text(msg[:4000], reply_markup=None, parse_mode="Markdown")

    # ── Auto-cancel toggle ───────────────────────────────────────────────────
    elif data == "aw_toggle_auto":
        key  = f"aw_autocancel_{username}"
        cur  = context.user_data.get(key, False)
        new  = not cur
        context.user_data[key] = new
        state = "ON ✅" if new else "OFF ❌"
        await q.answer(f"Auto-cancel on message: {state}", show_alert=True)

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT end_time, reason FROM away_status WHERE username=$1", username)
        is_away = row is not None
        end_str = row["end_time"].astimezone(WIB).strftime("%b %d at %H:%M WIB") if row else ""
        text = (
            f"🏖️ *Away Hub*\n\n"
            f"You are *away*.\n"
            f"📝 Reason: _{row['reason']}_\n"
            f"⏰ Until: {end_str}\n\n"
            f"⚙️ Auto-cancel on message: *{state}*"
        ) if is_away else f"🏖️ *Away Hub*\n\n⚙️ Auto-cancel on message: *{state}*"
        await q.message.edit_text(text, reply_markup=_home_kb(is_away), parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_away_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("aw_state")
    if not state:
        return False
    if update.effective_chat.type != "private":
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)

    async def _invalid(error_text: str, guide_text: str):
        try:
            await update.message.reply_text(f"❌ {error_text}", parse_mode="Markdown")
        except Exception:
            pass
        panel_chat = context.user_data.get("aw_panel_chat", uid)
        panel_msg  = context.user_data.get("aw_panel_msg")
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text=guide_text, reply_markup=_back_kb(), parse_mode="Markdown",
                )
            except Exception:
                pass

    # ── REASON ───────────────────────────────────────────────────────────────
    if state == "await_reason":
        if not text:
            return True
        cancel_text_input_timeout(context, uid, "aw_state")
        context.user_data["aw_reason"] = text
        context.user_data["aw_state"]  = "await_return_time"
        panel_chat = context.user_data.get("aw_panel_chat", uid)
        panel_msg  = context.user_data.get("aw_panel_msg")
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text="🏖️ *Set Away — Step 2 of 2*\n\n"
                         "Enter your *return date and time*:\n`MM/DD/YYYY HH:MM`\n\n"
                         "_e.g._ `06/30/2026 09:00`\n"
                         "⏰ _Times out in 120 seconds._",
                    reply_markup=_back_kb(), parse_mode="Markdown",
                )
            except Exception:
                pass
        await schedule_text_input_timeout(context, uid, "aw_state", "await_return_time", panel_chat or uid, panel_msg or 0)
        return True

    # ── RETURN TIME ───────────────────────────────────────────────────────────
    elif state == "await_return_time":
        try:
            end_time = WIB.localize(datetime.datetime.strptime(text, "%m/%d/%Y %H:%M"))
            if end_time < datetime.datetime.now(WIB):
                raise ValueError("past")
        except ValueError:
            await _invalid(
                "Invalid date/time or it's in the past.\nFormat: `MM/DD/YYYY HH:MM` (e.g. `06/30/2026 09:00`)",
                "🏖️ *Set Away — Step 2 of 2*\n\nEnter your *return date and time*:\n`MM/DD/YYYY HH:MM`\n\n"
                "_e.g._ `06/30/2026 09:00`\n⏰ _Times out in 120 seconds._",
            )
            return True
        cancel_text_input_timeout(context, uid, "aw_state")
        reason = context.user_data.pop("aw_reason", "Away")
        async with pool.acquire() as conn:
            existing = await conn.fetchrow("SELECT 1 FROM away_status WHERE username=$1", username)
            if existing:
                await update.message.reply_text("❌ You're already away. Use the panel to mark yourself back first.")
                context.user_data.pop("aw_state", None)
                return True
            await conn.execute(
                "INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3)",
                username, reason, end_time
            )

        for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
            j.schedule_removal()

        from cmd_admin import auto_return_away
        context.job_queue.run_once(
            auto_return_away,
            when=end_time,
            data={"username": username, "chat_id": uid},
            name=f"away_{username}"
        )
        context.user_data.pop("aw_state", None)
        await update.message.reply_text(
            f"✅ *Away status set!*\n\n"
            f"📝 Reason: _{reason}_\n"
            f"⏰ Until: {end_time.strftime('%b %d at %H:%M WIB')}\n\n"
            f"_Mentions will be queued and delivered when you return._",
            parse_mode="Markdown"
        )
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-CANCEL HOOK (called by global_text_router when user sends group message)
# ─────────────────────────────────────────────────────────────────────────────

async def check_auto_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    If user enabled auto-cancel and they send a group message while away,
    automatically clear their away status.
    """
    if not update.message or update.effective_chat.type == "private":
        return
    user     = update.effective_user
    username = user.username or str(user.id)
    key      = f"aw_autocancel_{username}"

    if not context.user_data.get(key):
        return

    pool = context.bot_data.get("db_pool")
    async with pool.acquire() as conn:
        is_away = await conn.fetchval("SELECT 1 FROM away_status WHERE username=$1", username)
    if not is_away:
        return

    import cmd_user
    msg = await cmd_user.process_return(username, pool, context.bot)
    for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
        j.schedule_removal()
    context.user_data.pop(key, None)
    # Reset away cache so global_tracker refreshes on next message
    if "away_cache" in context.bot_data:
        context.bot_data["away_cache"]["time"] = 0
    try:
        await context.bot.send_message(user.id, f"🟢 Auto-cancelled your away status.\n\n{msg}", parse_mode="Markdown")
    except Exception:
        pass
