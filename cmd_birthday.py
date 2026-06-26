"""
cmd_birthday.py — /birthdayconfig  Inline Birthday Management Hub
──────────────────────────────────────────────────────────────────
Admin-only. Runs entirely in DM.
Replaces: /addbday /editbday /delbday /listbdays /bulkaddbday /bulkdelbday /listbirthday

Menu:
  /birthdayconfig →  Home  ─┬─ 📋 List Birthdays   (paginated)
                             ├─ ➕ Add Birthday      (custom input)
                             ├─ ✏️ Edit Birthday     (pick → input)
                             ├─ 🗑️ Delete Birthday   (pick from list)
                             ├─ 📥 Batch Add         (multi-line input)
                             └─ 🗑️📥 Batch Delete    (multi-line input)

Callback prefix: bd_
Owner-locked, 120-second auto-expiry.
"""

import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import (
    delete_cmd, is_bot_admin,
    schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership, log_action,
    schedule_text_input_timeout, cancel_text_input_timeout,
)

logger   = logging.getLogger(__name__)
PAGE_SZ  = 10   # birthdays per list page


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _valid_bday(b: str) -> bool:
    return bool(re.match(r'^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$', b))


# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────

def _home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Birthdays",  callback_data="bd_list_0"),
         InlineKeyboardButton("➕ Add",             callback_data="bd_add")],
        [InlineKeyboardButton("✏️ Edit",            callback_data="bd_edit_pick"),
         InlineKeyboardButton("🗑️ Delete",          callback_data="bd_del_pick")],
        [InlineKeyboardButton("📥 Batch Add",       callback_data="bd_batchadd"),
         InlineKeyboardButton("🗑️📥 Batch Delete",  callback_data="bd_batchdel")],
        [InlineKeyboardButton("🚪 Close",           callback_data="bd_close")],
    ])


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",  callback_data="bd_home"),
        InlineKeyboardButton("🚪 Close", callback_data="bd_close"),
    ]])


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def birthday_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool     = context.bot_data.get("db_pool")
    username = update.effective_user.username or str(update.effective_user.id)
    uid      = update.effective_user.id

    if not await is_bot_admin(username, pool):
        return

    try:
        msg = await context.bot.send_message(
            uid,
            "🎂 *Birthday Config*\n\nManage team birthday registrations.\n"
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

async def birthday_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if data == "bd_home":
        context.user_data.pop("bd_state", None)
        context.user_data.pop("bd_edit_user", None)
        await q.message.edit_text(
            "🎂 *Birthday Config*\n\nManage team birthday registrations.",
            reply_markup=_home_kb(), parse_mode="Markdown"
        )

    # ── Close ─────────────────────────────────────────────────────────────────
    elif data == "bd_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("bd_state", None)
        context.user_data.pop("bd_edit_user", None)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── List (paginated) ──────────────────────────────────────────────────────
    elif data.startswith("bd_list_"):
        page = int(data.split("_")[2])
        await _show_list(q, pool, page)

    # ── Add ───────────────────────────────────────────────────────────────────
    elif data == "bd_add":
        context.user_data["bd_state"]     = "await_add"
        context.user_data["bd_panel_chat"] = q.message.chat_id
        context.user_data["bd_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "➕ *Add Birthday*\n\n"
            "Send in this format:\n"
            "`@username , MM/DD`\n\n"
            "_e.g._ `@alice , 06/15`\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, uid, "bd_state", "await_add", q.message.chat_id, q.message.message_id)

    # ── Edit — pick user ──────────────────────────────────────────────────────
    elif data == "bd_edit_pick":
        await _show_pick(q, pool, prefix="bd_editsel_", title="✏️ *Edit Birthday*\n\nSelect a member to edit:")

    elif data.startswith("bd_editsel_"):
        target = data[len("bd_editsel_"):]
        context.user_data["bd_state"]      = "await_edit_date"
        context.user_data["bd_edit_user"]  = target
        context.user_data["bd_panel_chat"] = q.message.chat_id
        context.user_data["bd_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            f"✏️ *Edit Birthday — @{target}*\n\n"
            "Send the new date:\n`MM/DD`\n\n"
            "_e.g._ `07/04`\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, uid, "bd_state", "await_edit_date", q.message.chat_id, q.message.message_id)

    # ── Delete — pick user ────────────────────────────────────────────────────
    elif data == "bd_del_pick":
        await _show_pick(q, pool, prefix="bd_delsel_", title="🗑️ *Delete Birthday*\n\nSelect a member to remove:")

    elif data.startswith("bd_delsel_"):
        target = data[len("bd_delsel_"):]
        async with pool.acquire() as conn:
            bday = await conn.fetchval("SELECT bday FROM birthdays WHERE lower(username)=$1", target.lower())
            await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", target.lower())
        await log_action(pool, uid, uid, "Birthday", "Deleted", f"@{target}")
        await q.message.edit_text(
            f"✅ *Birthday for @{target}* (`{bday or 'unknown'}`) removed.",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Batch Add ─────────────────────────────────────────────────────────────
    elif data == "bd_batchadd":
        context.user_data["bd_state"]     = "await_batchadd"
        context.user_data["bd_panel_chat"] = q.message.chat_id
        context.user_data["bd_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "📥 *Batch Add Birthdays*\n\n"
            "Send multiple entries — one per line:\n"
            "`@user1 , MM/DD`\n"
            "`@user2 , MM/DD`\n"
            "`@user3 , MM/DD`\n\n"
            "_Existing entries will be skipped (use Edit to change them)._\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, uid, "bd_state", "await_batchadd", q.message.chat_id, q.message.message_id)

    # ── Batch Delete ──────────────────────────────────────────────────────────
    elif data == "bd_batchdel":
        context.user_data["bd_state"]     = "await_batchdel"
        context.user_data["bd_panel_chat"] = q.message.chat_id
        context.user_data["bd_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "🗑️📥 *Batch Delete Birthdays*\n\n"
            "Send usernames — one per line or comma-separated:\n"
            "`@user1`\n"
            "`@user2`\n"
            "`@user3`\n\n"
            "or: `@user1 , @user2 , @user3`\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, uid, "bd_state", "await_batchdel", q.message.chat_id, q.message.message_id)


# ─────────────────────────────────────────────────────────────────────────────
# LIST
# ─────────────────────────────────────────────────────────────────────────────

async def _show_list(q, pool, page: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT username, bday FROM birthdays ORDER BY bday, username")

    if not rows:
        return await q.message.edit_text(
            "🎂 *Birthday Registry*\n\n_No birthdays registered yet._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    total  = len(rows)
    pages  = max(1, (total + PAGE_SZ - 1) // PAGE_SZ)
    page   = max(0, min(page, pages - 1))
    chunk  = rows[page * PAGE_SZ: (page + 1) * PAGE_SZ]

    lines  = [f"🎂 *Birthday Registry* — Page {page+1}/{pages} ({total} total)\n"]
    for r in chunk:
        lines.append(f"• @{r['username']}: `{r['bday']}`")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"bd_list_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"bd_list_{page+1}"))

    rows_kb = [nav] if nav else []
    rows_kb.append([InlineKeyboardButton("🏠 Home", callback_data="bd_home"),
                    InlineKeyboardButton("🚪 Close", callback_data="bd_close")])

    await q.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows_kb),
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────────────────────────
# PICK LIST (shared for edit and delete)
# ─────────────────────────────────────────────────────────────────────────────

async def _show_pick(q, pool, prefix: str, title: str):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT username, bday FROM birthdays ORDER BY username ASC LIMIT 25")

    if not rows:
        return await q.answer("No birthdays registered yet.", show_alert=True)

    btn_rows = []
    for r in rows:
        label = f"@{r['username']} — {r['bday']}"
        btn_rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}{r['username']}")])

    btn_rows.append([InlineKeyboardButton("🏠 Home", callback_data="bd_home"),
                     InlineKeyboardButton("🚪 Close", callback_data="bd_close")])

    await q.message.edit_text(title, reply_markup=InlineKeyboardMarkup(btn_rows), parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_birthday_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("bd_state")
    if not state:
        return False
    if update.effective_chat.type != "private":
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)

    if not await is_bot_admin(username, pool):
        context.user_data.pop("bd_state", None)
        return False

    async def _invalid(error_text: str, guide_text: str):
        try:
            await update.message.reply_text(f"❌ {error_text}", parse_mode="Markdown")
        except Exception:
            pass
        panel_chat = context.user_data.get("bd_panel_chat", uid)
        panel_msg  = context.user_data.get("bd_panel_msg")
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text=guide_text, reply_markup=_back_kb(), parse_mode="Markdown",
                )
            except Exception:
                pass

    # ── ADD ───────────────────────────────────────────────────────────────────
    if state == "await_add":
        try:
            parts = [p.strip() for p in text.split(",", 1)]
            u     = parts[0].lstrip("@").lower()
            b     = parts[1]
        except Exception:
            await _invalid("Format: `@username , MM/DD`",
                "➕ *Add Birthday*\n\nSend in this format:\n`@username , MM/DD`\n\n_e.g._ `@alice , 06/15`\n⏰ _Times out in 120 seconds._")
            return True

        if not _valid_bday(b):
            await _invalid(f"Invalid date `{b}`. Use MM/DD (e.g. `06/15`).",
                "➕ *Add Birthday*\n\nSend in this format:\n`@username , MM/DD`\n\n_e.g._ `@alice , 06/15`\n⏰ _Times out in 120 seconds._")
            return True

        async with pool.acquire() as conn:
            exist = await conn.fetchval("SELECT bday FROM birthdays WHERE lower(username)=$1", u)
            if exist:
                await update.message.reply_text(
                    f"❌ @{u} already registered as `{exist}`.\nUse ✏️ Edit to change it.", parse_mode="Markdown"
                )
                cancel_text_input_timeout(context, uid, "bd_state")
                context.user_data.pop("bd_state", None)
                return True
            await conn.execute("INSERT INTO birthdays (username, bday) VALUES ($1, $2)", u, b)

        await log_action(pool, uid, uid, "Birthday", "Added", f"@{u} → {b}")
        cancel_text_input_timeout(context, uid, "bd_state")
        context.user_data.pop("bd_state", None)
        await update.message.reply_text(f"✅ Birthday for @{u} set to `{b}`.", parse_mode="Markdown")
        return True

    # ── EDIT (date input after user was picked from inline kb) ────────────────
    elif state == "await_edit_date":
        b      = text.strip()
        target = context.user_data.pop("bd_edit_user", None)

        if not target:
            cancel_text_input_timeout(context, uid, "bd_state")
            context.user_data.pop("bd_state", None)
            await update.message.reply_text("❌ Session expired. Please restart /birthdayconfig.")
            return True
        if not _valid_bday(b):
            await _invalid(f"Invalid date `{b}`. Use MM/DD.",
                f"✏️ *Edit Birthday — @{target}*\n\nSend the new date:\n`MM/DD`\n\n_e.g._ `07/04`\n⏰ _Times out in 120 seconds._")
            context.user_data["bd_edit_user"] = target  # put back for retry
            return True
        cancel_text_input_timeout(context, uid, "bd_state")
        context.user_data.pop("bd_state", None)

        async with pool.acquire() as conn:
            res = await conn.execute("UPDATE birthdays SET bday=$1 WHERE lower(username)=$2", b, target.lower())

        if res == "UPDATE 0":
            await update.message.reply_text(f"❌ @{target} not found. Add them first with ➕ Add.")
        else:
            await log_action(pool, uid, uid, "Birthday", "Updated", f"@{target} → {b}")
            await update.message.reply_text(f"✅ @{target}'s birthday updated to `{b}`.", parse_mode="Markdown")
        return True

    # ── BATCH ADD ─────────────────────────────────────────────────────────────
    elif state == "await_batchadd":
        lines   = [l.strip() for l in text.split("\n") if l.strip()]
        added, skipped, errors = [], [], []

        async with pool.acquire() as conn:
            for line in lines:
                try:
                    parts = [p.strip() for p in line.split(",", 1)]
                    u     = parts[0].lstrip("@").lower()
                    b     = parts[1]
                except Exception:
                    errors.append(f"`{line[:30]}` — bad format")
                    continue
                if not _valid_bday(b):
                    errors.append(f"@{u} — invalid date `{b}`")
                    continue
                exist = await conn.fetchval("SELECT bday FROM birthdays WHERE lower(username)=$1", u)
                if exist:
                    skipped.append(f"@{u} (already `{exist}`)")
                    continue
                await conn.execute("INSERT INTO birthdays (username, bday) VALUES ($1, $2)", u, b)
                added.append(f"@{u} → `{b}`")
                await log_action(pool, uid, uid, "Birthday", "Batch Added", f"@{u} → {b}")

        cancel_text_input_timeout(context, uid, "bd_state")
        context.user_data.pop("bd_state", None)
        report = "🎂 *Batch Add Result*\n\n"
        if added:
            report += f"✅ Added ({len(added)}):\n" + "\n".join(f"  • {x}" for x in added) + "\n\n"
        if skipped:
            report += f"⚠️ Skipped ({len(skipped)}):\n" + "\n".join(f"  • {x}" for x in skipped) + "\n\n"
        if errors:
            report += f"❌ Errors ({len(errors)}):\n" + "\n".join(f"  • {x}" for x in errors)
        if not added and not skipped and not errors:
            report += "_Nothing to process._"
        await update.message.reply_text(report, parse_mode="Markdown")
        return True

    # ── BATCH DELETE ──────────────────────────────────────────────────────────
    elif state == "await_batchdel":
        # Accept either newlines or commas as separators
        raw       = text.replace("\n", ",")
        usernames = [u.strip().lstrip("@").lower() for u in raw.split(",") if u.strip()]
        removed, not_found = [], []

        async with pool.acquire() as conn:
            for u in usernames:
                if not u:
                    continue
                exist = await conn.fetchval("SELECT bday FROM birthdays WHERE lower(username)=$1", u)
                if not exist:
                    not_found.append(f"@{u}")
                    continue
                await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", u)
                removed.append(f"@{u} (was `{exist}`)")
                await log_action(pool, uid, uid, "Birthday", "Batch Deleted", f"@{u}")

        cancel_text_input_timeout(context, uid, "bd_state")
        context.user_data.pop("bd_state", None)
        report = "🗑️ *Batch Delete Result*\n\n"
        if removed:
            report += f"✅ Removed ({len(removed)}):\n" + "\n".join(f"  • {x}" for x in removed) + "\n\n"
        if not_found:
            report += f"⚠️ Not found ({len(not_found)}):\n" + "\n".join(f"  • {x}" for x in not_found)
        if not removed and not not_found:
            report += "_Nothing to process._"
        await update.message.reply_text(report, parse_mode="Markdown")
        return True

    return False
