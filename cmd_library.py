"""
cmd_library.py — /library  Inline Library Hub
──────────────────────────────────────────────
Runs entirely in DM. From a group, /library sends a DM nudge.
Owner-locked, 120-second auto-expiry.

Menu tree:
  /library  →  Home  ─┬─ 📂 Browse           → paginated list (page buttons)
                       ├─ 🔍 Get Asset        → type name in DM
                       ├─ ➕ Add Asset        → type "Name , Content [, private]"
                       ├─ ✏️ Edit Asset       → type "Name , New Content"
                       ├─ 🗑️ Delete Asset     → pick from your assets
                       └─ 📦 Batch Add        → multi-line "Name , Content" per line

Callback prefix: lib_
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import delete_cmd, is_bot_admin, schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership

logger = logging.getLogger(__name__)
PAGE_SIZE = 8   # assets per browse page


# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────

def _home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Browse",          callback_data="lib_browse_0"),
         InlineKeyboardButton("🔍 Get Asset",       callback_data="lib_get")],
        [InlineKeyboardButton("➕ Add",             callback_data="lib_add"),
         InlineKeyboardButton("📦 Batch Add",       callback_data="lib_batchadd")],
        [InlineKeyboardButton("✏️ Edit",            callback_data="lib_edit"),
         InlineKeyboardButton("🗑️ Delete",          callback_data="lib_delete_pick")],
        [InlineKeyboardButton("🗑️📦 Batch Delete",  callback_data="lib_batchdel")],
        [InlineKeyboardButton("🚪 Close",           callback_data="lib_close")],
    ])


def _back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",  callback_data="lib_home"),
        InlineKeyboardButton("🚪 Close", callback_data="lib_close"),
    ]])


async def _browse_kb(pool, username: str, page: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build paginated browse list, hiding other users' private assets."""
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            "SELECT name, is_private, added_by FROM library ORDER BY name ASC"
        )

    # Filter: show public + user's own private
    visible = [r for r in recs if not r["is_private"] or r["added_by"] == username]

    if not visible:
        return "📚 *Library*\n\n_The library is empty._", _back_kb()

    total   = len(visible)
    pages   = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page    = max(0, min(page, pages - 1))
    chunk   = visible[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]

    lines = [f"📚 *Library* — Page {page+1}/{pages}\n"]
    for r in chunk:
        icon = "🔒" if r["is_private"] else "📂"
        lines.append(f"{icon} `{r['name']}`")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"lib_browse_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"lib_browse_{page+1}"))

    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="lib_home"),
                 InlineKeyboardButton("🚪 Close", callback_data="lib_close")])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def library_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    user = update.effective_user
    uid  = user.id

    try:
        msg = await context.bot.send_message(
            uid,
            "📚 *Library Hub*\n\nBrowse and manage team assets.\n"
            "_(Panel closes after 120 s of inactivity.)_",
            reply_markup=_home_kb(),
            parse_mode="Markdown"
        )
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
        # Can't DM — nudge in group
        if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
            bot_uname = (await context.bot.get_me()).username
            url = f"https://t.me/{bot_uname}?start=open_library"
            kb  = InlineKeyboardMarkup([[InlineKeyboardButton("📚 Open Library in DM", url=url)]])
            await update.effective_chat.send_message(
                f"👋 {user.first_name} — tap below to open the Library in DM.",
                reply_markup=kb
            )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def library_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uid  = q.from_user.id
    username = q.from_user.username or str(uid)

    if not await check_kb_ownership(q, context):
        return await q.answer("This panel isn't yours.", show_alert=True)
    await q.answer()

    # ── Home ─────────────────────────────────────────────────────────────────
    if data == "lib_home":
        await q.message.edit_text(
            "📚 *Library Hub*\n\nBrowse and manage team assets.",
            reply_markup=_home_kb(), parse_mode="Markdown"
        )
        context.user_data.pop("lib_state", None)

    # ── Close ────────────────────────────────────────────────────────────────
    elif data == "lib_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("lib_state", None)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── Browse (paginated) ───────────────────────────────────────────────────
    elif data.startswith("lib_browse_"):
        page = int(data.split("_")[2])
        text, kb = await _browse_kb(pool, username, page)
        await q.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

    # ── Get Asset ────────────────────────────────────────────────────────────
    elif data == "lib_get":
        context.user_data["lib_state"] = "await_get_name"
        await q.message.edit_text(
            "🔍 *Get Asset*\n\nType the asset name:",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Add Asset ────────────────────────────────────────────────────────────
    elif data == "lib_add":
        context.user_data["lib_state"] = "await_add"
        await q.message.edit_text(
            "➕ *Add Asset*\n\n"
            "Send in this format:\n"
            "`Name , Content`\n\n"
            "To make it private, add `, private` at the end:\n"
            "`Name , Content , private`",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Batch Add ────────────────────────────────────────────────────────────
    elif data == "lib_batchadd":
        context.user_data["lib_state"] = "await_batchadd"
        await q.message.edit_text(
            "📦 *Batch Add*\n\n"
            "Send multiple assets — one per line:\n"
            "`Name1 , Content1`\n"
            "`Name2 , Content2 , private`\n"
            "`Name3 , Content3`\n\n"
            "_Each line becomes one asset._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Edit ─────────────────────────────────────────────────────────────────
    elif data == "lib_edit":
        context.user_data["lib_state"] = "await_edit"
        await q.message.edit_text(
            "✏️ *Edit Asset*\n\n"
            "Send in this format:\n"
            "`Name , New Content`\n\n"
            "_You can only edit assets you own._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Delete — pick list ───────────────────────────────────────────────────
    elif data == "lib_delete_pick":
        await _show_delete_pick(q, context, pool, username)

    elif data == "lib_batchdel":
        context.user_data["lib_state"] = "await_batchdel"
        await q.message.edit_text(
            "🗑️📦 *Batch Delete*\n\n"
            "Send asset names — one per line or comma-separated:\n"
            "`asset1\nasset2\nasset3`\n\n"
            "_You can only delete assets you own (admins can delete any)._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    elif data.startswith("lib_del_"):
        name = data[len("lib_del_"):]
        await _do_delete(q, context, pool, username, name)


# ─────────────────────────────────────────────────────────────────────────────
# DELETE PICK
# ─────────────────────────────────────────────────────────────────────────────

async def _show_delete_pick(q, context, pool, username: str):
    is_adm = await is_bot_admin(username, pool)
    async with pool.acquire() as conn:
        if is_adm:
            recs = await conn.fetch("SELECT name FROM library ORDER BY name ASC LIMIT 20")
        else:
            recs = await conn.fetch(
                "SELECT name FROM library WHERE added_by=$1 ORDER BY name ASC LIMIT 20", username
            )

    if not recs:
        return await q.answer("You have no assets to delete.", show_alert=True)

    rows = [[InlineKeyboardButton(f"🗑️ {r['name']}", callback_data=f"lib_del_{r['name']}")] for r in recs]
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="lib_home"),
                 InlineKeyboardButton("🚪 Close", callback_data="lib_close")])
    await q.message.edit_text(
        "🗑️ *Delete Asset*\n\nSelect an asset to delete:",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown"
    )


async def _do_delete(q, context, pool, username: str, name: str):
    is_adm = await is_bot_admin(username, pool)
    async with pool.acquire() as conn:
        asset = await conn.fetchrow("SELECT added_by FROM library WHERE LOWER(name)=$1", name.lower())
        if not asset:
            return await q.answer("Asset not found.", show_alert=True)
        if asset["added_by"] != username and not is_adm:
            return await q.answer("You can only delete your own assets.", show_alert=True)
        await conn.execute("DELETE FROM library WHERE LOWER(name)=$1", name.lower())

    await q.message.edit_text(
        f"✅ *Asset `{name}` deleted.*",
        reply_markup=_back_kb(), parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_library_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("lib_state")
    if not state:
        return False

    # Library always runs in DM
    if update.effective_chat.type != "private":
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)

    # ── GET ASSET ─────────────────────────────────────────────────────────
    if state == "await_get_name":
        name = text.lower()
        async with pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT name, content, is_private, added_by FROM library WHERE LOWER(name)=$1", name
            )
            if not r:
                r = await conn.fetchrow(
                    "SELECT name, content, is_private, added_by FROM library "
                    "WHERE LOWER(name) LIKE $1 LIMIT 1", f"%{name}%"
                )
        context.user_data.pop("lib_state", None)
        if not r:
            await update.message.reply_text("❌ Asset not found.")
        elif r["is_private"] and r["added_by"] != username:
            await update.message.reply_text("🔒 That asset is private and belongs to someone else.")
        else:
            icon = "🔒" if r["is_private"] else "📂"
            await update.message.reply_text(
                f"{icon} *{r['name'].title()}*\n\n{r['content']}",
                parse_mode="Markdown"
            )
        return True

    # ── ADD ASSET ─────────────────────────────────────────────────────────
    elif state == "await_add":
        is_private = False
        raw = text
        if raw.lower().endswith(", private"):
            is_private = True
            raw = raw[:-9].strip()
        try:
            name, content = [p.strip() for p in raw.split(",", 1)]
            if not name or not content:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Format: `Name , Content` (optionally `, private`)", parse_mode="Markdown")
            return True

        name = name.lower()
        async with pool.acquire() as conn:
            if await conn.fetchval("SELECT 1 FROM library WHERE LOWER(name)=$1", name):
                await update.message.reply_text(f"❌ An asset named `{name}` already exists.", parse_mode="Markdown")
                return True
            await conn.execute(
                "INSERT INTO library (name, content, added_by, is_private) VALUES ($1,$2,$3,$4)",
                name, content, username, is_private
            )
        context.user_data.pop("lib_state", None)
        await update.message.reply_text(
            f"✅ Asset *`{name}`* added! {'🔒 Private' if is_private else '📂 Public'}",
            parse_mode="Markdown"
        )
        return True

    # ── BATCH ADD ─────────────────────────────────────────────────────────
    elif state == "await_batchadd":
        lines   = [l.strip() for l in text.split("\n") if l.strip()]
        added   = []
        skipped = []
        async with pool.acquire() as conn:
            for line in lines:
                is_private = False
                raw = line
                if raw.lower().endswith(", private"):
                    is_private = True
                    raw = raw[:-9].strip()
                try:
                    name, content = [p.strip() for p in raw.split(",", 1)]
                    name = name.lower()
                    if not name or not content:
                        raise ValueError
                except ValueError:
                    skipped.append(f"`{line[:30]}`")
                    continue

                exists = await conn.fetchval("SELECT 1 FROM library WHERE LOWER(name)=$1", name)
                if exists:
                    skipped.append(f"`{name}` (duplicate)")
                    continue
                await conn.execute(
                    "INSERT INTO library (name, content, added_by, is_private) VALUES ($1,$2,$3,$4)",
                    name, content, username, is_private
                )
                added.append(f"`{name}`")

        context.user_data.pop("lib_state", None)
        msg = f"✅ *Batch Add Complete*\n\n"
        if added:
            msg += f"Added ({len(added)}): {', '.join(added)}\n"
        if skipped:
            msg += f"Skipped ({len(skipped)}): {', '.join(skipped)}"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return True

    # ── BATCH DELETE ──────────────────────────────────────────────────────────
    elif state == "await_batchdel":
        raw   = text.replace("\n", ",")
        names = [n.strip().lower() for n in raw.split(",") if n.strip()]
        is_adm = await is_bot_admin(username, pool)
        removed, not_found = [], []
        async with pool.acquire() as conn:
            for name in names:
                asset = await conn.fetchrow("SELECT added_by FROM library WHERE LOWER(name)=$1", name)
                if not asset:
                    not_found.append(f"`{name}`")
                    continue
                if asset["added_by"] != username and not is_adm:
                    not_found.append(f"`{name}` (not yours)")
                    continue
                await conn.execute("DELETE FROM library WHERE LOWER(name)=$1", name)
                removed.append(f"`{name}`")
        context.user_data.pop("lib_state", None)
        msg = "🗑️ *Batch Delete Result*\n\n"
        if removed:   msg += f"✅ Deleted ({len(removed)}): {', '.join(removed)}\n"
        if not_found: msg += f"⚠️ Skipped ({len(not_found)}): {', '.join(not_found)}"
        await update.message.reply_text(msg or "_Nothing processed._", parse_mode="Markdown")
        return True

    # ── EDIT ASSET ────────────────────────────────────────────────────────
    elif state == "await_edit":
        try:
            name, new_content = [p.strip() for p in text.split(",", 1)]
            name = name.lower()
            if not name or not new_content:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Format: `Name , New Content`", parse_mode="Markdown")
            return True

        is_adm = await is_bot_admin(username, pool)
        async with pool.acquire() as conn:
            asset = await conn.fetchrow("SELECT added_by FROM library WHERE LOWER(name)=$1", name)
            if not asset:
                await update.message.reply_text("❌ Asset not found.")
                context.user_data.pop("lib_state", None)
                return True
            if asset["added_by"] != username and not is_adm:
                await update.message.reply_text("❌ You can only edit your own assets.")
                context.user_data.pop("lib_state", None)
                return True
            await conn.execute("UPDATE library SET content=$1 WHERE LOWER(name)=$2", new_content, name)

        context.user_data.pop("lib_state", None)
        await update.message.reply_text(f"✅ Asset *`{name}`* updated.", parse_mode="Markdown")
        return True

    return False
