"""
cmd_command_nav.py  —  /command  Inline Command Navigator
──────────────────────────────────────────────────────────
Always runs in DM only. In a group, the /command message is silently
deleted and the navigator is sent straight to the user's DM.

If the bot can't DM the user yet (first time), an ephemeral personal nudge
is posted in the group with a deep-link button, then auto-deleted in 30 s.

Navigation flow (all in DM):
  /command  →  Home screen (role-aware category tiles)
            →  Category screen (command buttons)
            →  Command detail card (desc + usage + copy tip)

Callback prefix: cmenu_
  cmenu_home        — re-render home
  cmenu_cat_N       — open category index N
  cmenu_cmd_NAME    — open command detail for /NAME
  cmenu_close       — delete the navigator message
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import is_bot_admin, is_super, delete_cmd
from commands_manifest import COMMANDS
from cmd_system_help import _check_can_dm, _reset_can_dm, _send_nudge

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ROLE / CATEGORY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _all_categories() -> dict:
    seen = {}
    for c in COMMANDS:
        seen.setdefault(c["category"], []).append(c)
    return seen


def _role_for_cmd(cmd: dict) -> str:
    if cmd.get("super"):  return "super"
    if cmd.get("admin"):  return "admin"
    return "user"


def _visible_categories(is_admin: bool, is_superowner: bool) -> dict:
    result = {}
    for cat, cmds in _all_categories().items():
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
    cats = _visible_categories(is_admin, is_superowner)
    return cats, list(cats.keys())


def _section_badge(cat_name: str) -> str:
    cmds  = _all_categories().get(cat_name, [])
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
    items = list(enumerate(index_list))
    for i in range(0, len(items), 2):
        row = []
        for idx, name in items[i:i+2]:
            badge = _section_badge(name)
            label = f"{badge} {name}".strip() if badge else name
            row.append(InlineKeyboardButton(label, callback_data=f"cmenu_cat_{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Close", callback_data="cmenu_close")])
    return InlineKeyboardMarkup(rows)


def _category_keyboard(cat_idx: int, is_admin: bool, is_superowner: bool):
    cats, index_list = _cat_index_map(is_admin, is_superowner)
    if cat_idx >= len(index_list):
        return "", None
    cat_name = index_list[cat_idx]
    cmds = cats[cat_name]
    rows = []
    for i in range(0, len(cmds), 2):
        row = []
        for c in cmds[i:i+2]:
            label = f"{c.get('emoji','🔹')} /{c['name']}"
            row.append(InlineKeyboardButton(label, callback_data=f"cmenu_cmd_{c['name']}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ Back", callback_data="cmenu_home"),
        InlineKeyboardButton("❌ Close", callback_data="cmenu_close"),
    ])
    return cat_name, InlineKeyboardMarkup(rows)


def _detail_keyboard(cmd_name: str, cat_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Back to Category", callback_data=f"cmenu_cat_{cat_idx}"),
        InlineKeyboardButton("🏠 Home", callback_data="cmenu_home"),
    ], [
        InlineKeyboardButton("❌ Close", callback_data="cmenu_close"),
    ]])


def _find_cat_idx(cmd_name: str, is_admin: bool, is_superowner: bool) -> int:
    _, index_list = _cat_index_map(is_admin, is_superowner)
    for i, cat_name in enumerate(index_list):
        if any(c["name"] == cmd_name for c in _all_categories().get(cat_name, [])):
            return i
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# TEXT BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _home_text(is_admin: bool, is_superowner: bool) -> str:
    cats, _ = _cat_index_map(is_admin, is_superowner)
    total   = sum(len(v) for v in cats.values())
    role    = "👑 Super Owner" if is_superowner else ("🔐 Admin" if is_admin else "🟢 Member")
    return (
        f"🗂 *Command Navigator*\n"
        f"Role: {role}  •  {total} commands available\n\n"
        f"Select a category to browse, or type any command directly.\n\n"
        f"💡 _This menu is for discovery only — type commands normally in the group._"
    )


def _category_text(cat_name: str, cmds: list) -> str:
    lines = [f"*{cat_name}*\n_{len(cmds)} command(s)_\n"]
    for c in cmds:
        lines.append(f"{c.get('emoji','🔹')} `/{c['name']}` — {c['desc']}")
    lines.append("\n_Tap a command to see full usage details._")
    return "\n".join(lines)


def _detail_text(cmd: dict) -> str:
    lines = [
        f"{cmd.get('emoji','🔹')} */{cmd['name']}*",
        f"_{cmd['desc']}_",
        "",
    ]
    if cmd.get("experimental"):
        lines.append("⚠️ _Experimental — don't abuse it yet_\n")
    fmt = cmd.get("format")
    if fmt:
        lines.append(f"📝 *Usage:*\n`{fmt.replace('`','')}`\n")
    else:
        lines.append(f"📝 *Usage:*\n`/{cmd['name']}`\n")
    lines += [
        "─────────────────",
        "💡 *How to use:*",
        "Type the command directly in the group chat,",
        "or long-press the usage line above to copy it.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: send the navigator to user's DM
# ─────────────────────────────────────────────────────────────────────────────

async def _deliver_navigator(bot, user_id: int, is_admin: bool, is_superowner: bool) -> None:
    """Send the navigator home screen to the user's DM."""
    await bot.send_message(
        user_id,
        _home_text(is_admin, is_superowner),
        reply_markup=_home_keyboard(is_admin, is_superowner),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT — /command
# ─────────────────────────────────────────────────────────────────────────────

async def command_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Always delete the /command message from chat first.
    Then either:
      - DM already open → silently deliver navigator to DM (zero group noise)
      - DM not open yet → post ephemeral nudge in group (auto-deleted in 30 s)
    """
    # Step 1: delete the /command message from group immediately
    await delete_cmd(update)

    user    = update.effective_user
    pool    = context.bot_data.get("db_pool")
    uname   = user.username or str(user.id)

    is_superowner = await is_super(uname)
    is_admin_user = await is_bot_admin(uname, pool)

    # ── Already in DM — deliver directly ──────────────────────────────────
    if update.effective_chat.type == "private":
        await _deliver_navigator(context.bot, user.id, is_admin_user, is_superowner)
        return

    # ── In a group ────────────────────────────────────────────────────────
    can_dm = await _check_can_dm(user.id, pool)

    if can_dm:
        try:
            await _deliver_navigator(context.bot, user.id, is_admin_user, is_superowner)
            # No group confirmation message — completely silent ✅
        except Exception:
            # Bot was blocked since last time — reset and nudge
            await _reset_can_dm(user.id, pool)
            await _send_nudge(update, context, "open_command", "Command Navigator")
    else:
        # First time — show ephemeral nudge, auto-deleted in 30 s
        await _send_nudge(update, context, "open_command", "Command Navigator")


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER — all cmenu_ patterns
# ─────────────────────────────────────────────────────────────────────────────

async def command_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    data  = q.data
    pool  = context.bot_data.get("db_pool")
    uname = q.from_user.username or str(q.from_user.id)

    is_superowner = await is_super(uname)
    is_admin_user = await is_bot_admin(uname, pool)

    await q.answer()

    # ── CLOSE ────────────────────────────────────────────────────────────────
    if data == "cmenu_close":
        try:
            await q.message.delete()
        except Exception:
            await q.edit_message_text("_Navigator closed._", parse_mode="Markdown")
        return

    # ── HOME ─────────────────────────────────────────────────────────────────
    if data == "cmenu_home":
        try:
            await q.edit_message_text(
                _home_text(is_admin_user, is_superowner),
                reply_markup=_home_keyboard(is_admin_user, is_superowner),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    # ── CATEGORY ─────────────────────────────────────────────────────────────
    if data.startswith("cmenu_cat_"):
        try:
            idx = int(data.removeprefix("cmenu_cat_"))
        except ValueError:
            return
        cat_name, kb = _category_keyboard(idx, is_admin_user, is_superowner)
        if not kb:
            await q.answer("Category not found.", show_alert=True)
            return
        cats, _ = _cat_index_map(is_admin_user, is_superowner)
        try:
            await q.edit_message_text(
                _category_text(cat_name, cats.get(cat_name, [])),
                reply_markup=kb,
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    # ── COMMAND DETAIL ────────────────────────────────────────────────────────
    if data.startswith("cmenu_cmd_"):
        cmd_name = data.removeprefix("cmenu_cmd_")
        cmd_obj  = next((c for c in COMMANDS if c["name"] == cmd_name), None)
        if not cmd_obj:
            await q.answer("Command not found.", show_alert=True)
            return

        # Permission guard — block upward navigation by non-privileged users
        role = _role_for_cmd(cmd_obj)
        if role == "super" and not is_superowner:
            await q.answer("⛔ Super Owner only.", show_alert=True)
            return
        if role == "admin" and not (is_admin_user or is_superowner):
            await q.answer("⛔ Admins only.", show_alert=True)
            return

        cat_idx = _find_cat_idx(cmd_name, is_admin_user, is_superowner)
        try:
            await q.edit_message_text(
                _detail_text(cmd_obj),
                reply_markup=_detail_keyboard(cmd_name, cat_idx),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return
