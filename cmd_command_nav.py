"""
cmd_command_nav.py  —  /command  Inline Command Navigator
──────────────────────────────────────────────────────────
Gives every user a role-aware interactive command browser.
No text is sent in the group — the navigator opens in DM.

Navigation flow:
  /command  →  Home screen (category tiles)
            →  Category screen (command list)
            →  Command detail card (desc + format + copy tip)

Callback prefix:  cmenu_
  cmenu_home           — re-render home
  cmenu_cat_N          — open category index N
  cmenu_cmd_NAME       — open command detail for /NAME
  cmenu_close          — delete the message
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import is_bot_admin, is_super, delete_cmd
from commands_manifest import COMMANDS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _all_categories():
    """Return ordered list of unique categories from manifest."""
    seen = {}
    for c in COMMANDS:
        cat = c["category"]
        if cat not in seen:
            seen[cat] = []
        seen[cat].append(c)
    return seen  # {category_name: [cmd_dict, ...]}


def _role_for_cmd(cmd: dict) -> str:
    if cmd.get("super"):
        return "super"
    if cmd.get("admin"):
        return "admin"
    return "user"


def _visible_categories(is_admin: bool, is_superowner: bool) -> dict:
    """Filter categories to only those the caller is allowed to see."""
    all_cats = _all_categories()
    result = {}
    for cat, cmds in all_cats.items():
        visible = []
        for c in cmds:
            role = _role_for_cmd(c)
            if role == "user":
                visible.append(c)
            elif role == "admin" and (is_admin or is_superowner):
                visible.append(c)
            elif role == "super" and is_superowner:
                visible.append(c)
        if visible:
            result[cat] = visible
    return result


def _cat_index_map(is_admin: bool, is_superowner: bool):
    """Return (cats_dict, index_to_name_list) for stable N-indexed callbacks."""
    cats = _visible_categories(is_admin, is_superowner)
    index_list = list(cats.keys())  # stable order
    return cats, index_list


def _section_label(cat_name: str, is_admin: bool, is_superowner: bool) -> str:
    """Return a short section badge for the home screen."""
    # Check if this category is admin-only or super-only
    cmds = _all_categories().get(cat_name, [])
    roles = {_role_for_cmd(c) for c in cmds}
    if "super" in roles and not ("user" in roles or "admin" in roles):
        return "👑"
    if "admin" in roles and "user" not in roles:
        return "🔐"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARD BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _home_keyboard(is_admin: bool, is_superowner: bool) -> InlineKeyboardMarkup:
    cats, index_list = _cat_index_map(is_admin, is_superowner)
    rows = []
    # Two categories per row for compact layout
    cat_items = [(i, name) for i, name in enumerate(index_list)]
    for i in range(0, len(cat_items), 2):
        row = []
        for idx, name in cat_items[i:i+2]:
            badge = _section_label(name, is_admin, is_superowner)
            label = f"{badge} {name}".strip() if badge else name
            row.append(InlineKeyboardButton(label, callback_data=f"cmenu_cat_{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Close", callback_data="cmenu_close")])
    return InlineKeyboardMarkup(rows)


def _category_keyboard(cat_idx: int, is_admin: bool, is_superowner: bool) -> tuple[str, InlineKeyboardMarkup]:
    cats, index_list = _cat_index_map(is_admin, is_superowner)
    if cat_idx >= len(index_list):
        return "", None
    cat_name = index_list[cat_idx]
    cmds = cats[cat_name]

    rows = []
    # Two commands per row
    for i in range(0, len(cmds), 2):
        row = []
        for c in cmds[i:i+2]:
            emoji = c.get("emoji", "🔹")
            label = f"{emoji} /{c['name']}"
            row.append(InlineKeyboardButton(label, callback_data=f"cmenu_cmd_{c['name']}"))
        rows.append(row)

    rows.append([
        InlineKeyboardButton("◀️ Back", callback_data="cmenu_home"),
        InlineKeyboardButton("❌ Close", callback_data="cmenu_close"),
    ])
    return cat_name, InlineKeyboardMarkup(rows)


def _command_detail_keyboard(cmd_name: str, cat_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Back to Category", callback_data=f"cmenu_cat_{cat_idx}"),
        InlineKeyboardButton("🏠 Home", callback_data="cmenu_home"),
    ], [
        InlineKeyboardButton("❌ Close", callback_data="cmenu_close"),
    ]])


def _find_cat_idx_for_cmd(cmd_name: str, is_admin: bool, is_superowner: bool) -> int:
    """Return the index of the category containing cmd_name, for back-nav."""
    _, index_list = _cat_index_map(is_admin, is_superowner)
    cats = _all_categories()
    for i, cat_name in enumerate(index_list):
        if any(c["name"] == cmd_name for c in cats.get(cat_name, [])):
            return i
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# TEXT BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _home_text(is_admin: bool, is_superowner: bool) -> str:
    cats, _ = _cat_index_map(is_admin, is_superowner)
    total = sum(len(v) for v in cats.values())
    role_line = "👑 Super Owner" if is_superowner else ("🔐 Admin" if is_admin else "🟢 Member")
    return (
        f"🗂 *Command Navigator*\n"
        f"Role: {role_line}  •  {total} commands available\n\n"
        f"Select a category to browse, or type a command directly.\n\n"
        f"💡 _Tip: You can always type any command manually — "
        f"this menu is just for easy discovery._"
    )


def _category_text(cat_name: str, cmds: list) -> str:
    lines = [f"*{cat_name}*\n_{len(cmds)} command(s)_\n"]
    for c in cmds:
        lines.append(f"{c.get('emoji','🔹')} `/{c['name']}` — {c['desc']}")
    lines.append("\n_Tap a command to see its full usage details._")
    return "\n".join(lines)


def _command_detail_text(cmd: dict) -> str:
    emoji  = cmd.get("emoji", "🔹")
    name   = cmd["name"]
    desc   = cmd["desc"]
    fmt    = cmd.get("format")
    exp    = cmd.get("experimental", False)

    lines = [
        f"{emoji} */{name}*",
        f"_{desc}_",
        "",
    ]

    if exp:
        lines.append("⚠️ _Experimental — don't abuse it yet_\n")

    if fmt:
        # Strip backtick wrappers for cleaner display, show as plain text
        clean_fmt = fmt.replace("`", "")
        lines.append(f"📝 *Usage:*\n`{clean_fmt}`\n")
    else:
        lines.append(f"📝 *Usage:*\n`/{name}`\n")

    lines += [
        "─────────────────",
        "💡 *How to use:*",
        f"Just type the command above directly in the chat,",
        f"or long-press the usage line to copy it.",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT  —  /command
# ─────────────────────────────────────────────────────────────────────────────

async def command_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /command — opens the navigator in DM."""
    await delete_cmd(update)
    user    = update.effective_user
    pool    = context.bot_data.get("db_pool")
    uname   = user.username or str(user.id)

    is_superowner = await is_super(uname)
    is_admin_user = await is_bot_admin(uname, pool)

    text = _home_text(is_admin_user, is_superowner)
    kb   = _home_keyboard(is_admin_user, is_superowner)

    try:
        await context.bot.send_message(
            user.id, text,
            reply_markup=kb,
            parse_mode="Markdown"
        )
        # If called from a group, confirm in the group briefly
        if update.effective_chat.type != "private":
            await update.message.reply_text(
                "✅ Command Navigator sent to your DMs!",
            )
    except Exception:
        # Can't DM — send inline in the chat itself (graceful fallback)
        if update.message:
            await update.message.reply_text(
                text,
                reply_markup=kb,
                parse_mode="Markdown"
            )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER  —  all cmenu_ patterns
# ─────────────────────────────────────────────────────────────────────────────

async def command_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uname = q.from_user.username or str(q.from_user.id)

    is_superowner = await is_super(uname)
    is_admin_user = await is_bot_admin(uname, pool)

    await q.answer()  # dismiss the loading spinner

    # ── CLOSE ────────────────────────────────────────────────────────────────
    if data == "cmenu_close":
        try:
            await q.message.delete()
        except Exception:
            await q.edit_message_text("_Navigator closed._", parse_mode="Markdown")
        return

    # ── HOME ─────────────────────────────────────────────────────────────────
    if data == "cmenu_home":
        text = _home_text(is_admin_user, is_superowner)
        kb   = _home_keyboard(is_admin_user, is_superowner)
        try:
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
        return

    # ── CATEGORY ─────────────────────────────────────────────────────────────
    if data.startswith("cmenu_cat_"):
        try:
            idx = int(data.split("cmenu_cat_")[1])
        except ValueError:
            return
        cat_name, kb = _category_keyboard(idx, is_admin_user, is_superowner)
        if not kb:
            await q.answer("Category not found.", show_alert=True)
            return
        cats, _ = _cat_index_map(is_admin_user, is_superowner)
        cmds    = cats.get(cat_name, [])
        text    = _category_text(cat_name, cmds)
        try:
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
        return

    # ── COMMAND DETAIL ────────────────────────────────────────────────────────
    if data.startswith("cmenu_cmd_"):
        cmd_name = data.split("cmenu_cmd_")[1]
        # Find the command in manifest
        cmd_obj = next((c for c in COMMANDS if c["name"] == cmd_name), None)
        if not cmd_obj:
            await q.answer("Command not found.", show_alert=True)
            return
        # Permission guard — prevent URL-guessing into higher-privilege commands
        role = _role_for_cmd(cmd_obj)
        if role == "super" and not is_superowner:
            await q.answer("⛔ Super Owner only.", show_alert=True)
            return
        if role == "admin" and not (is_admin_user or is_superowner):
            await q.answer("⛔ Admins only.", show_alert=True)
            return

        cat_idx = _find_cat_idx_for_cmd(cmd_name, is_admin_user, is_superowner)
        text    = _command_detail_text(cmd_obj)
        kb      = _command_detail_keyboard(cmd_name, cat_idx)
        try:
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
        return
