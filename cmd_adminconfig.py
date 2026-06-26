"""
cmd_adminconfig.py
──────────────────
/admin      — Inline hub: add admin, remove admin, list admins (Super Owner only)
/userconfig — Inline hub: remove member, graveyard, check quota, admin stars,
              check limit, admin limit, registered user list (Admin+)

Callback prefixes: adm_  /  uc_
Owner-locked, 120-second auto-expiry.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import (
    delete_cmd, is_bot_admin, is_super,
    schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership, log_action,
    schedule_text_input_timeout, cancel_text_input_timeout,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# /admin — Add / Remove / List Admins  (Super Owner only)
# ─────────────────────────────────────────────────────────────────────────────

def _admin_home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Admin",    callback_data="adm_add"),
         InlineKeyboardButton("➖ Remove Admin", callback_data="adm_remove")],
        [InlineKeyboardButton("📋 List Admins",  callback_data="adm_list")],
        [InlineKeyboardButton("🚪 Close",        callback_data="adm_close")],
    ])


def _back_adm_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",  callback_data="adm_home"),
        InlineKeyboardButton("🚪 Close", callback_data="adm_close"),
    ]])


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uid = update.effective_user.id
    if not await is_super(update.effective_user.username):
        return

    try:
        msg = await context.bot.send_message(
            uid,
            "👑 *Admin Management*\n\nAdd, remove, or list bot admins.\n"
            "_(Panel closes after 120 s.)_",
            reply_markup=_admin_home_kb(), parse_mode="Markdown"
        )
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
        if update.message:
            await update.message.reply_text("❌ Start a DM with me first (/start).")


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uid  = q.from_user.id

    if not await check_kb_ownership(q, context):
        return await q.answer("This panel isn't yours.", show_alert=True)
    if not await is_super(q.from_user.username):
        return await q.answer("Super Owner only.", show_alert=True)
    await q.answer()

    if data == "adm_uc_cancel":
        context.user_data.pop("uc_state", None)
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    if data == "adm_home":
        context.user_data.pop("adm_state", None)
        await q.message.edit_text(
            "👑 *Admin Management*\n\nAdd, remove, or list bot admins.",
            reply_markup=_admin_home_kb(), parse_mode="Markdown"
        )

    elif data == "adm_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("adm_state", None)
        try: await q.message.delete()
        except Exception: pass

    elif data == "adm_list":
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT username FROM bot_admins ORDER BY username")
        if not rows:
            return await q.message.edit_text(
                "📋 *Admin List*\n\n_No admins configured yet._",
                reply_markup=_back_adm_kb(), parse_mode="Markdown"
            )
        lines = "\n".join(f"• @{r['username']}" for r in rows)
        await q.message.edit_text(
            f"📋 *Admin List* ({len(rows)} admins)\n\n{lines}",
            reply_markup=_back_adm_kb(), parse_mode="Markdown"
        )

    elif data == "adm_add":
        context.user_data["adm_state"]     = "await_add_admin"
        context.user_data["adm_panel_chat"] = q.message.chat_id
        context.user_data["adm_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "➕ *Add Admin*\n\nType the username to promote:\n`@username`\n⏰ _Times out in 120 seconds._",
            reply_markup=_back_adm_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "adm_state", "await_add_admin", q.message.chat_id, q.message.message_id)

    elif data == "adm_remove":
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT username FROM bot_admins ORDER BY username LIMIT 20")
        if not rows:
            return await q.answer("No admins to remove.", show_alert=True)
        btns = [[InlineKeyboardButton(f"➖ @{r['username']}", callback_data=f"adm_del_{r['username']}")] for r in rows]
        btns.append([InlineKeyboardButton("🏠 Home", callback_data="adm_home"),
                     InlineKeyboardButton("🚪 Close", callback_data="adm_close")])
        await q.message.edit_text(
            "➖ *Remove Admin*\n\nTap to demote:",
            reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown"
        )

    elif data.startswith("adm_del_"):
        target = data[8:]
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bot_admins WHERE LOWER(username)=$1", target.lower())
        await log_action(pool, uid, uid, "Admin", "Removed", f"@{target}")
        await q.message.edit_text(
            f"✅ @{target} removed from admins.",
            reply_markup=_back_adm_kb(), parse_mode="Markdown"
        )


async def handle_admin_inline_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("adm_state")
    if not state or update.effective_chat.type != "private":
        return False
    if not await is_super(update.effective_user.username):
        return False

    text = (update.message.text or "").strip().lstrip("@").lower()
    pool = context.bot_data.get("db_pool")
    uid  = update.effective_user.id

    if state == "await_add_admin":
        if not text:
            return True
        async with pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM bot_admins WHERE LOWER(username)=$1", text)
            if exists:
                await update.message.reply_text(f"⚠️ @{text} is already an admin.")
                cancel_text_input_timeout(context, uid, "adm_state")
                context.user_data.pop("adm_state", None)
                return True
            await conn.execute("INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING", text)
        await log_action(pool, uid, uid, "Admin", "Added", f"@{text}")
        cancel_text_input_timeout(context, uid, "adm_state")
        context.user_data.pop("adm_state", None)
        await update.message.reply_text(f"✅ @{text} promoted to admin.", parse_mode="Markdown")
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# /userconfig — User Management Hub  (Admin+)
# ─────────────────────────────────────────────────────────────────────────────

def _uc_home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Registered Users",  callback_data="uc_list_0"),
         InlineKeyboardButton("🪦 Graveyard",         callback_data="uc_graveyard")],
        [InlineKeyboardButton("🔍 Check Quota",       callback_data="uc_checkquota"),
         InlineKeyboardButton("⭐ Admin Stars",        callback_data="uc_adminstars")],
        [InlineKeyboardButton("🤖 Check AI Limit",    callback_data="uc_checklimit"),
         InlineKeyboardButton("🔧 Set AI Limit",      callback_data="uc_adminlimit")],
        [InlineKeyboardButton("☠️ Remove Member",     callback_data="uc_remove")],
        [InlineKeyboardButton("🚪 Close",             callback_data="uc_close")],
    ])


def _back_uc_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",  callback_data="uc_home"),
        InlineKeyboardButton("🚪 Close", callback_data="uc_close"),
    ]])


async def userconfig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)
    pool     = context.bot_data.get("db_pool")

    if not await is_bot_admin(username, pool):
        return

    try:
        msg = await context.bot.send_message(
            uid,
            "👥 *User Config*\n\nManage registered members.\n"
            "_(Panel closes after 120 s.)_",
            reply_markup=_uc_home_kb(), parse_mode="Markdown"
        )
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
        if update.message:
            await update.message.reply_text("❌ Start a DM with me first (/start).")


async def userconfig_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if data == "uc_home":
        context.user_data.pop("uc_state", None)
        await q.message.edit_text(
            "👥 *User Config*\n\nManage registered members.",
            reply_markup=_uc_home_kb(), parse_mode="Markdown"
        )

    # ── Close ─────────────────────────────────────────────────────────────────
    elif data == "uc_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("uc_state", None)
        try: await q.message.delete()
        except Exception: pass

    # ── Registered Users (paginated) ──────────────────────────────────────────
    elif data.startswith("uc_list_"):
        page = int(data[8:])
        await _show_user_list(q, pool, page)

    # ── Graveyard ─────────────────────────────────────────────────────────────
    elif data == "uc_graveyard":
        async with pool.acquire() as conn:
            recs = await conn.fetch(
                "SELECT username, removed_at FROM graveyard ORDER BY removed_at DESC"
            )
        if not recs:
            text = "🪦 *Graveyard*\n\n_Empty — no members have been offboarded yet._"
        else:
            lines = [f"• @{r['username']} — removed {r['removed_at'].strftime('%d %b %Y')}" for r in recs]
            text  = f"🪦 *Graveyard* ({len(recs)} members)\n\n" + "\n".join(lines)
        await q.message.edit_text(text, reply_markup=_back_uc_kb(), parse_mode="Markdown")

    # ── Check Quota ───────────────────────────────────────────────────────────
    elif data == "uc_checkquota":
        context.user_data["uc_state"]     = "await_checkquota"
        context.user_data["uc_panel_chat"] = q.message.chat_id
        context.user_data["uc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "🔍 *Check Star Quota*\n\nType `@username` or `all`:\n⏰ _Times out in 120 seconds._",
            reply_markup=_back_uc_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "uc_state", "await_checkquota", q.message.chat_id, q.message.message_id)

    # ── Admin Stars ───────────────────────────────────────────────────────────
    elif data == "uc_adminstars":
        context.user_data["uc_state"]     = "await_adminstars"
        context.user_data["uc_panel_chat"] = q.message.chat_id
        context.user_data["uc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "⭐ *Admin Stars*\n\nFormat:\n"
            "`@user , quota|monthly|total , set|add|sub , amount`\n\n"
            "Example: `@alice , monthly , add , 5`\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_uc_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "uc_state", "await_adminstars", q.message.chat_id, q.message.message_id)

    # ── Check AI Limit ────────────────────────────────────────────────────────
    elif data == "uc_checklimit":
        context.user_data["uc_state"]     = "await_checklimit"
        context.user_data["uc_panel_chat"] = q.message.chat_id
        context.user_data["uc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "🤖 *Check AI Limit*\n\nType `@username` or `all`:\n⏰ _Times out in 120 seconds._",
            reply_markup=_back_uc_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "uc_state", "await_checklimit", q.message.chat_id, q.message.message_id)

    # ── Admin Limit ───────────────────────────────────────────────────────────
    elif data == "uc_adminlimit":
        context.user_data["uc_state"]     = "await_adminlimit"
        context.user_data["uc_panel_chat"] = q.message.chat_id
        context.user_data["uc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "🔧 *Set AI Limit*\n\nFormat:\n"
            "`@user , set|add|sub , amount`\n\n"
            "Example: `@bob , set , 20`\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_uc_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "uc_state", "await_adminlimit", q.message.chat_id, q.message.message_id)

    # ── Remove Member ─────────────────────────────────────────────────────────
    elif data == "uc_remove":
        if not await is_super(username):
            return await q.answer("Super Owner only.", show_alert=True)
        context.user_data["uc_state"]     = "await_remove"
        context.user_data["uc_panel_chat"] = q.message.chat_id
        context.user_data["uc_panel_msg"]  = q.message.message_id
        await q.message.edit_text(
            "☠️ *Remove Member*\n\nType `@username` to offboard permanently.\n"
            "_This removes them from all data tables and adds them to the graveyard._\n"
            "⏰ _Times out in 120 seconds._",
            reply_markup=_back_uc_kb(), parse_mode="Markdown"
        )
        await schedule_text_input_timeout(context, q.from_user.id, "uc_state", "await_remove", q.message.chat_id, q.message.message_id)


async def _show_user_list(q, pool, page: int):
    PAGE = 10
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT username, user_id FROM users WHERE username IS NOT NULL ORDER BY username"
        )
    total = len(rows)
    pages = max(1, (total + PAGE - 1) // PAGE)
    page  = max(0, min(page, pages - 1))
    chunk = rows[page * PAGE: (page + 1) * PAGE]

    lines = [f"👥 *Registered Users* ({total}) — Page {page+1}/{pages}\n"]
    for r in chunk:
        uid_str = f" (`{r['user_id']}`)" if r['user_id'] else ""
        lines.append(f"• @{r['username']}{uid_str}")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"uc_list_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"uc_list_{page+1}"))

    rows_kb = [nav] if nav else []
    rows_kb.append([InlineKeyboardButton("🏠 Home", callback_data="uc_home"),
                    InlineKeyboardButton("🚪 Close", callback_data="uc_close")])

    await q.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows_kb),
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER (routes from global_text_router)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_adminconfig_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("uc_state")
    if not state or update.effective_chat.type != "private":
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)

    if not await is_bot_admin(username, pool):
        return False

    async def _invalid(error_text: str, guide_text: str, kb=None):
        back_kb = kb or _back_uc_kb()
        try:
            await update.message.reply_text(f"❌ {error_text}", parse_mode="Markdown")
        except Exception:
            pass
        panel_chat = context.user_data.get("uc_panel_chat", uid)
        panel_msg  = context.user_data.get("uc_panel_msg")
        if panel_msg:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel_chat, message_id=panel_msg,
                    text=guide_text, reply_markup=back_kb, parse_mode="Markdown",
                )
            except Exception:
                pass

    # ── updatechange flow (from cmd_admin.update_change) ─────────────────────
    if state == "await_updatechange":
        import re as _re
        if "," not in text:
            await _invalid("Format: `VERSION , CHANGELOG`",
                "🔖 *Update Version*\n\nFormat: `VERSION , CHANGELOG`\n_e.g._ `1.4 , Added new feature`\n⏰ _Times out in 120 seconds._")
            return True
        parts     = text.split(",", 1)
        new_ver   = parts[0].strip()
        changelog = parts[1].strip()
        if not _re.match(r'^\d+\.\d+$', new_ver):
            await _invalid("Version must be `X.Y` format.",
                "🔖 *Update Version*\n\nFormat: `VERSION , CHANGELOG`\n_e.g._ `1.4 , Added new feature`\n⏰ _Times out in 120 seconds._")
            return True
        from cmd_admin import _ensure_version_table
        await _ensure_version_table(pool)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO bot_version (version, changelog) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                new_ver, changelog
            )
        cancel_text_input_timeout(context, uid, "uc_state")
        context.user_data.pop("uc_state", None)
        await update.message.reply_text(
            f"✅ Version `{new_ver}` saved!\n📝 _{changelog}_",
            parse_mode="Markdown"
        )
        return True

    # ── Check Quota ───────────────────────────────────────────────────────────
    if state == "await_checkquota":
        from cmd_admin import check_quota
        cancel_text_input_timeout(context, uid, "uc_state")
        context.user_data.pop("uc_state", None)
        context.args = [text.lstrip("@")]
        await check_quota(update, context)
        return True

    # ── Admin Stars ───────────────────────────────────────────────────────────
    if state == "await_adminstars":
        from cmd_admin import admin_stars
        cancel_text_input_timeout(context, uid, "uc_state")
        context.user_data.pop("uc_state", None)
        context.args = text.replace("@", "").split(",")
        await admin_stars(update, context)
        return True

    # ── Check Limit ───────────────────────────────────────────────────────────
    if state == "await_checklimit":
        from cmd_admin import check_limit
        cancel_text_input_timeout(context, uid, "uc_state")
        context.user_data.pop("uc_state", None)
        context.args = [text.lstrip("@")]
        await check_limit(update, context)
        return True

    # ── Admin Limit ───────────────────────────────────────────────────────────
    if state == "await_adminlimit":
        from cmd_admin import admin_limit
        cancel_text_input_timeout(context, uid, "uc_state")
        context.user_data.pop("uc_state", None)
        context.args = text.replace("@", "").split(",")
        await admin_limit(update, context)
        return True

    # ── Remove Member ─────────────────────────────────────────────────────────
    if state == "await_remove":
        if not await is_super(username):
            cancel_text_input_timeout(context, uid, "uc_state")
            context.user_data.pop("uc_state", None)
            return False
        target = text.lstrip("@").lower()
        from cmd_admin import remove_member_req
        cancel_text_input_timeout(context, uid, "uc_state")
        context.user_data.pop("uc_state", None)
        context.args = [target]
        await remove_member_req(update, context)
        return True

    return False
