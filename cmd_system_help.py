"""
cmd_system_help.py — /help command + shared DM-gate utilities
──────────────────────────────────────────────────────────────
DM-gate flow (group context):
  1. /help or /command typed in group
  2. Command message is auto-deleted immediately
  3. If user has can_dm=TRUE  → content sent directly to DM, no group noise
  4. If user has can_dm=FALSE → personal nudge posted in group (ephemeral,
     auto-deleted after 30 s), with a deep-link button to the bot DM
  5. User taps button → /start open_help or /start open_command fires in DM
     → can_dm set TRUE → content delivered → done forever

After the first time, zero group noise.
"""

import asyncio
import datetime
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from commands_manifest import COMMANDS
from core import delete_cmd, is_bot_admin, is_super

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SHARED UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

async def send_md_chunks(bot, chat_id: int, text: str):
    """Split long Markdown messages and send in safe-size chunks."""
    limit = 3800
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current)
    for chunk in chunks:
        if chunk.strip():
            try:
                await bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except Exception:
                await bot.send_message(chat_id, chunk)


async def _check_can_dm(user_id: int, pool) -> bool:
    """Return True only if this user has previously /start-ed the bot in DM."""
    if not pool:
        return False
    try:
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT can_dm FROM users WHERE user_id=$1", user_id
            )
        return bool(val)
    except Exception:
        return False


async def _reset_can_dm(user_id: int, pool) -> None:
    """Mark can_dm=FALSE when a send attempt reveals the user blocked the bot."""
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET can_dm=FALSE WHERE user_id=$1", user_id
            )
    except Exception:
        pass


async def _auto_delete_job(context) -> None:
    """PTB job callback — deletes a message by (chat_id, message_id)."""
    chat_id, message_id = context.job.data
    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception:
        pass  # already gone, fine


async def _send_nudge(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
    feature: str,
) -> None:
    """
    Post a personal, ephemeral nudge in the group telling the user to open DM.
    The nudge auto-deletes from the group after 30 seconds so it doesn't linger.
    The /command message itself is already deleted by the caller before this runs.
    """
    bot_username = context.bot.username
    url = f"https://t.me/{bot_username}?start={payload}"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"💬 Tap to open DM & get your {feature}", url=url)
    ]])

    user = update.effective_user
    first_name = user.first_name or "there"

    sent = await context.bot.send_message(
        update.effective_chat.id,
        f"👋 Hey {first_name}! The *{feature}* is sent privately.\n"
        f"Tap the button below to open a DM with the bot — you only need to do this *once*.\n"
        f"_This message will disappear in 30 seconds._",
        reply_markup=kb,
        parse_mode="Markdown",
    )

    # Schedule auto-delete of the nudge in 30 s
    if context.job_queue:
        context.job_queue.run_once(
            _auto_delete_job,
            when=30,
            data=(sent.chat_id, sent.message_id),
            name=f"nudge_del_{sent.chat_id}_{sent.message_id}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# HELP CONTENT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

async def _build_help_text(uname: str, pool) -> str:
    """Build the full /help text, role-filtered for the calling user."""
    is_superowner = await is_super(uname)
    is_admin_user = await is_bot_admin(uname, pool)

    public = [c for c in COMMANDS if c.get("public")]
    admin  = [c for c in COMMANDS if c.get("admin") and not c.get("super")]
    superc = [c for c in COMMANDS if c.get("super")]

    text  = "📖 **[RAWWY] Nukhba Manager Manual**\n\n"
    text += "_(If your `/` menu looks outdated, log out of Telegram and log back in.)_\n\n"

    text += "🟢 **USER COMMANDS**\n"
    current_cat = ""
    exp_shown = False
    for c in public:
        cat = c.get("category", "")
        if cat != current_cat:
            current_cat = cat
            text += f"\n*{current_cat}*\n"
            if c.get("experimental") and not exp_shown:
                text += "⚠️ _(Experimental — don't abuse it yet)_\n"
                exp_shown = True
        text += f"{c.get('emoji','🔹')} `/{c['name']}` — {c['desc']}\n"
        if "format" in c:
            text += f"   └ {c['format']}\n"

    if admin and is_admin_user:
        text += "\n🔐 **ADMINISTRATOR SUITE**\n"
        current_cat = ""
        for c in admin:
            cat = c.get("category", "")
            if cat != current_cat:
                current_cat = cat
                text += f"\n*{current_cat}*\n"
            text += f"{c.get('emoji','🔹')} `/{c['name']}` — {c['desc']}\n"
            if "format" in c:
                text += f"   └ {c['format']}\n"

    if superc and is_superowner:
        text += "\n👑 **SUPER OWNER EXCLUSIVES**\n"
        for c in superc:
            text += f"{c.get('emoji','🔹')} `/{c['name']}` — {c['desc']}\n"
            if "format" in c:
                text += f"   └ {c['format']}\n"

    return text


# ─────────────────────────────────────────────────────────────────────────────
# /help HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Always delete the /help command from the chat immediately
    await delete_cmd(update)

    pool    = context.bot_data.get("db_pool")
    user    = update.effective_user
    user_id = user.id
    uname   = user.username or str(user_id)

    # Build the help text upfront (role-aware)
    text = await _build_help_text(uname, pool)

    # ── Already in DM ─────────────────────────────────────────────────────
    if update.effective_chat.type == "private":
        await send_md_chunks(context.bot, user_id, text)
        return

    # ── In a group ────────────────────────────────────────────────────────
    can_dm = await _check_can_dm(user_id, pool)

    if can_dm:
        try:
            await send_md_chunks(context.bot, user_id, text)
            # Silent success — no group message, no noise
        except Exception:
            # User blocked the bot since last time — reset flag and nudge
            await _reset_can_dm(user_id, pool)
            await _send_nudge(update, context, "open_help", "Manual")
    else:
        await _send_nudge(update, context, "open_help", "Manual")
