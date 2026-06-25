"""
cmd_library.py — /library  Inline Library Hub
──────────────────────────────────────────────
Runs entirely in DM. From a group, /library sends a DM nudge.
Owner-locked, 120-second auto-expiry.

Menu:
  /library → Home ─┬─ 📂 Browse         → paginated tappable list (tap = view content)
                    ├─ 🔍 Get Asset      → type name
                    ├─ ➕ Add            → Name , Content [, private]
                    ├─ 📦 Batch Add      → one per line
                    ├─ ✏️ Edit           → Name , New Content
                    ├─ ✏️📦 Batch Edit   → one per line
                    ├─ 🗑️ Delete         → pick from your assets
                    └─ 🗑️📦 Batch Delete → names comma/newline separated

Callback prefix: lib_
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import delete_cmd, is_bot_admin, schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership

logger    = logging.getLogger(__name__)
PAGE_SIZE = 8


# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────

def _home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Browse",         callback_data="lib_browse_0"),
         InlineKeyboardButton("🔍 Get Asset",      callback_data="lib_get")],
        [InlineKeyboardButton("➕ Add",            callback_data="lib_add"),
         InlineKeyboardButton("📦 Batch Add",      callback_data="lib_batchadd")],
        [InlineKeyboardButton("✏️ Edit",           callback_data="lib_edit"),
         InlineKeyboardButton("✏️📦 Batch Edit",   callback_data="lib_batchedit")],
        [InlineKeyboardButton("🗑️ Delete",         callback_data="lib_delete_pick"),
         InlineKeyboardButton("🗑️📦 Batch Delete", callback_data="lib_batchdel")],
        [InlineKeyboardButton("🚪 Close",          callback_data="lib_close")],
    ])


def _back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",  callback_data="lib_home"),
        InlineKeyboardButton("🚪 Close", callback_data="lib_close"),
    ]])


def _browse_back_kb(page: int = 0):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Back to List", callback_data=f"lib_browse_{page}"),
        InlineKeyboardButton("🏠 Home",         callback_data="lib_home"),
    ]])


async def _build_browse(pool, username: str, page: int):
    """Paginated list — each asset is a tappable button that shows its content."""
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            "SELECT name, is_private, added_by FROM library ORDER BY name ASC"
        )

    visible = [r for r in recs if not r["is_private"] or r["added_by"] == username]

    if not visible:
        return ("📚 *Library*\n\n_The library is empty._\nUse ➕ Add to create an asset.",
                _back_kb())

    total = len(visible)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page  = max(0, min(page, pages - 1))
    chunk = visible[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    header = f"📚 *Library* — Page {page+1}/{pages} ({total} total)\n_Tap an asset to view it._\n"

    rows = []
    for r in chunk:
        icon  = "🔒" if r["is_private"] else "📂"
        mine  = " ✎" if r["added_by"] == username else ""
        label = f"{icon} {r['name']}{mine}"
        # Store page so back button returns to same page
        rows.append([InlineKeyboardButton(label[:48], callback_data=f"lib_view_{page}_{r['name']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"lib_browse_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"lib_browse_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="lib_home"),
                 InlineKeyboardButton("🚪 Close", callback_data="lib_close")])

    return header, InlineKeyboardMarkup(rows)


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
            reply_markup=_home_kb(), parse_mode="Markdown"
        )
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
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
        context.user_data.pop("lib_state", None)
        await q.message.edit_text(
            "📚 *Library Hub*\n\nBrowse and manage team assets.",
            reply_markup=_home_kb(), parse_mode="Markdown"
        )

    # ── Close ─────────────────────────────────────────────────────────────────
    elif data == "lib_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("lib_state", None)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── Browse ────────────────────────────────────────────────────────────────
    elif data.startswith("lib_browse_"):
        page = int(data.split("_")[2])
        text, kb = await _build_browse(pool, username, page)
        await q.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

    # ── View asset (tapped from browse list) ──────────────────────────────────
    elif data.startswith("lib_view_"):
        # format: lib_view_{page}_{name}
        parts = data[len("lib_view_"):].split("_", 1)
        try:
            back_page = int(parts[0])
            name      = parts[1]
        except (IndexError, ValueError):
            name      = data[len("lib_view_"):]
            back_page = 0

        async with pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT name, content, is_private, added_by FROM library WHERE LOWER(name)=$1",
                name.lower()
            )
        if not r:
            return await q.answer("Asset not found.", show_alert=True)
        if r["is_private"] and r["added_by"] != username:
            return await q.answer("🔒 This asset is private.", show_alert=True)

        icon    = "🔒" if r["is_private"] else "📂"
        content = r["content"][:3800]
        await q.message.edit_text(
            f"{icon} *{r['name'].title()}*\n\n{content}",
            reply_markup=_browse_back_kb(back_page),
            parse_mode="Markdown"
        )

    # ── Get Asset ─────────────────────────────────────────────────────────────
    elif data == "lib_get":
        context.user_data["lib_state"] = "await_get_name"
        await q.message.edit_text(
            "🔍 *Get Asset*\n\nType the asset name:",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Add ───────────────────────────────────────────────────────────────────
    elif data == "lib_add":
        context.user_data["lib_state"] = "await_add"
        await q.message.edit_text(
            "➕ *Add Asset*\n\n"
            "Format: `Name , Content`\n"
            "Private: `Name , Content , private`",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Batch Add ─────────────────────────────────────────────────────────────
    elif data == "lib_batchadd":
        context.user_data["lib_state"] = "await_batchadd"
        await q.message.edit_text(
            "📦 *Batch Add*\n\nOne entry per line:\n"
            "`Name1 , Content1`\n"
            "`Name2 , Content2 , private`",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Edit ──────────────────────────────────────────────────────────────────
    elif data == "lib_edit":
        context.user_data["lib_state"] = "await_edit"
        await q.message.edit_text(
            "✏️ *Edit Asset*\n\n"
            "Format: `Name , New Content`\n"
            "_You can only edit assets you own._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Batch Edit ────────────────────────────────────────────────────────────
    elif data == "lib_batchedit":
        context.user_data["lib_state"] = "await_batchedit"
        await q.message.edit_text(
            "✏️📦 *Batch Edit*\n\nOne per line:\n"
            "`Name1 , New Content1`\n"
            "`Name2 , New Content2`\n\n"
            "_You can only edit assets you own._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Delete pick ───────────────────────────────────────────────────────────
    elif data == "lib_delete_pick":
        await _show_delete_pick(q, pool, username)

    elif data.startswith("lib_del_"):
        name = data[len("lib_del_"):]
        await _do_delete(q, pool, username, name)

    # ── Batch Delete ──────────────────────────────────────────────────────────
    elif data == "lib_batchdel":
        context.user_data["lib_state"] = "await_batchdel"
        await q.message.edit_text(
            "🗑️📦 *Batch Delete*\n\n"
            "Names comma-separated or one per line:\n"
            "`name1, name2, name3`\n\n"
            "_Admins can delete any asset. Others: yours only._",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )


# ─────────────────────────────────────────────────────────────────────────────
# DELETE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _show_delete_pick(q, pool, username: str):
    is_adm = await is_bot_admin(username, pool)
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            "SELECT name FROM library ORDER BY name ASC LIMIT 20"
        ) if is_adm else await conn.fetch(
            "SELECT name FROM library WHERE added_by=$1 ORDER BY name ASC LIMIT 20", username
        )

    if not recs:
        return await q.answer("You have no assets to delete.", show_alert=True)

    rows = [[InlineKeyboardButton(f"🗑️ {r['name']}", callback_data=f"lib_del_{r['name']}")] for r in recs]
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="lib_home"),
                 InlineKeyboardButton("🚪 Close", callback_data="lib_close")])
    await q.message.edit_text(
        "🗑️ *Delete Asset*\n\nSelect an asset:",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown"
    )


async def _do_delete(q, pool, username: str, name: str):
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
    if not state or update.effective_chat.type != "private":
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)

    # ── GET ───────────────────────────────────────────────────────────────────
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
            await update.message.reply_text("🔒 That asset is private.")
        else:
            icon = "🔒" if r["is_private"] else "📂"
            await update.message.reply_text(
                f"{icon} *{r['name'].title()}*\n\n{r['content']}",
                parse_mode="Markdown"
            )
        return True

    # ── ADD ───────────────────────────────────────────────────────────────────
    elif state == "await_add":
        is_private = text.lower().endswith(", private")
        raw = text[:-9].strip() if is_private else text
        try:
            name, content = [p.strip() for p in raw.split(",", 1)]
            if not name or not content: raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Format: `Name , Content` (or `Name , Content , private`)",
                parse_mode="Markdown"
            )
            return True
        name = name.lower()
        async with pool.acquire() as conn:
            if await conn.fetchval("SELECT 1 FROM library WHERE LOWER(name)=$1", name):
                await update.message.reply_text(f"❌ `{name}` already exists.", parse_mode="Markdown")
                return True
            await conn.execute(
                "INSERT INTO library (name, content, added_by, is_private) VALUES ($1,$2,$3,$4)",
                name, content, username, is_private
            )
        context.user_data.pop("lib_state", None)
        await update.message.reply_text(
            f"✅ Added *`{name}`* {'🔒 Private' if is_private else '📂 Public'}",
            parse_mode="Markdown"
        )
        return True

    # ── BATCH ADD ─────────────────────────────────────────────────────────────
    elif state == "await_batchadd":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        added = []
        skipped = []
        async with pool.acquire() as conn:
            for line in lines:
                is_private = line.lower().endswith(", private")
                raw = line[:-9].strip() if is_private else line
                try:
                    name, content = [p.strip() for p in raw.split(",", 1)]
                    name = name.lower()
                    if not name or not content: raise ValueError
                except ValueError:
                    skipped.append(f"`{line[:25]}` — bad format")
                    continue
                if await conn.fetchval("SELECT 1 FROM library WHERE LOWER(name)=$1", name):
                    skipped.append(f"`{name}` — duplicate")
                    continue
                await conn.execute(
                    "INSERT INTO library (name, content, added_by, is_private) VALUES ($1,$2,$3,$4)",
                    name, content, username, is_private
                )
                added.append(f"`{name}`")
        context.user_data.pop("lib_state", None)
        msg = "📦 *Batch Add Result*\n\n"
        if added:   msg += f"✅ Added ({len(added)}): {', '.join(added)}\n"
        if skipped: msg += f"⚠️ Skipped ({len(skipped)}):\n" + "\n".join(f"  • {x}" for x in skipped)
        await update.message.reply_text(msg, parse_mode="Markdown")
        return True

    # ── EDIT ──────────────────────────────────────────────────────────────────
    elif state == "await_edit":
        try:
            name, new_content = [p.strip() for p in text.split(",", 1)]
            name = name.lower()
            if not name or not new_content: raise ValueError
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
        await update.message.reply_text(f"✅ *`{name}`* updated.", parse_mode="Markdown")
        return True

    # ── BATCH EDIT ────────────────────────────────────────────────────────────
    elif state == "await_batchedit":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        updated = []
        failed  = []
        is_adm  = await is_bot_admin(username, pool)
        async with pool.acquire() as conn:
            for line in lines:
                try:
                    name, new_content = [p.strip() for p in line.split(",", 1)]
                    name = name.lower()
                    if not name or not new_content: raise ValueError
                except ValueError:
                    failed.append(f"`{line[:25]}` — bad format")
                    continue
                asset = await conn.fetchrow("SELECT added_by FROM library WHERE LOWER(name)=$1", name)
                if not asset:
                    failed.append(f"`{name}` — not found")
                    continue
                if asset["added_by"] != username and not is_adm:
                    failed.append(f"`{name}` — not yours")
                    continue
                await conn.execute("UPDATE library SET content=$1 WHERE LOWER(name)=$2", new_content, name)
                updated.append(f"`{name}`")
        context.user_data.pop("lib_state", None)
        msg = "✏️ *Batch Edit Result*\n\n"
        if updated: msg += f"✅ Updated ({len(updated)}): {', '.join(updated)}\n"
        if failed:  msg += f"❌ Failed ({len(failed)}):\n" + "\n".join(f"  • {x}" for x in failed)
        await update.message.reply_text(msg or "_Nothing processed._", parse_mode="Markdown")
        return True

    # ── BATCH DELETE ──────────────────────────────────────────────────────────
    elif state == "await_batchdel":
        raw   = text.replace("\n", ",")
        names = [n.strip().lower() for n in raw.split(",") if n.strip()]
        is_adm = await is_bot_admin(username, pool)
        removed = []
        skipped = []
        async with pool.acquire() as conn:
            for name in names:
                asset = await conn.fetchrow("SELECT added_by FROM library WHERE LOWER(name)=$1", name)
                if not asset:
                    skipped.append(f"`{name}` — not found")
                    continue
                if asset["added_by"] != username and not is_adm:
                    skipped.append(f"`{name}` — not yours")
                    continue
                await conn.execute("DELETE FROM library WHERE LOWER(name)=$1", name)
                removed.append(f"`{name}`")
        context.user_data.pop("lib_state", None)
        msg = "🗑️ *Batch Delete Result*\n\n"
        if removed: msg += f"✅ Deleted ({len(removed)}): {', '.join(removed)}\n"
        if skipped: msg += f"⚠️ Skipped ({len(skipped)}):\n" + "\n".join(f"  • {x}" for x in skipped)
        await update.message.reply_text(msg or "_Nothing processed._", parse_mode="Markdown")
        return True

    return False
