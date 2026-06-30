import datetime
import logging
import json
import re
import asyncio
from openai import OpenAI as GroqClient
from google import genai  # fallback only
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, GROQ_API_KEY, is_super, is_bot_admin, delete_cmd, log_action, schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership, CANCELLED_TEXT, schedule_text_input_timeout, cancel_text_input_timeout
from cmd_system import _generate_content_with_retry

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

async def send_md(context, chat_id, text):
    chunk = ""
    for line in text.split('\n'):
        if len(chunk) + len(line) + 1 > 3800:
            try:
                await context.bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Markdown parse failed, sending plain text: {e}")
                await context.bot.send_message(chat_id, chunk)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        try:
            await context.bot.send_message(chat_id, chunk, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Markdown parse failed, sending plain text: {e}")
            await context.bot.send_message(chat_id, chunk)


async def _ensure_version_table(pool):
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS bot_version (
                id SERIAL PRIMARY KEY,
                version VARCHAR(20),
                changelog TEXT,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        # Seed v1.2 entry if this is the first run at this version
        count = await conn.fetchval("SELECT COUNT(*) FROM bot_version WHERE version='1.2'")
        if not count:
            await conn.execute(
                "INSERT INTO bot_version (version, changelog, updated_at) VALUES ($1, $2, $3)",
                "1.2",
                "⭐ /mystar now shows your monthly and all-time RAWWY Stars in one place\n"
                "👋 Away mention alerts now include the reason and expected return time\n"
                "🤖 /ai is now faster and more responsive — ask it anything\n"
                "📖 /help is now a clean command list; use /command for full usage details\n"
                "📚 /library opens the full asset hub directly",
                __import__('pytz').timezone('Asia/Jakarta').localize(__import__('datetime').datetime(2026, 6, 23))
            )
        # Seed v1.3 entry
        count = await conn.fetchval("SELECT COUNT(*) FROM bot_version WHERE version='1.3'")
        if not count:
            await conn.execute(
                "INSERT INTO bot_version (version, changelog, updated_at) VALUES ($1, $2, $3)",
                "1.3",
                "⏰ All input steps now auto-cancel after 120 seconds — no more stuck panels\n"
                "🔄 Typing the wrong format shows an error and brings the guide back automatically\n"
                "✅ Inline menus now consistently close after 120 seconds of inactivity\n"
                "📋 /task step-by-step guide is now fully restored on any mistake\n"
                "📢 /broadcast schedule flow is now fully fixed — tag and confirm work reliably",
                __import__('pytz').timezone('Asia/Jakarta').localize(__import__('datetime').datetime(2026, 6, 26))
            )
        # Always refresh changelog text to latest wording (idempotent)
        await conn.execute(
            "UPDATE bot_version SET changelog=$1, updated_at=$2 WHERE version='1.2'",
            "⭐ /mystar now shows your monthly and all-time RAWWY Stars in one place\n"
            "👋 Away mention alerts now include the reason and expected return time\n"
            "🤖 /ai is now faster and more responsive — ask it anything\n"
            "📖 /help is now a clean command list; use /command for full usage details\n"
            "📚 /library opens the full asset hub directly",
            __import__('pytz').timezone('Asia/Jakarta').localize(__import__('datetime').datetime(2026, 6, 23))
        )
        await conn.execute(
            "UPDATE bot_version SET changelog=$1, updated_at=$2 WHERE version='1.3'",
            "⏰ All input steps now auto-cancel after 120 seconds — no more stuck panels\n"
            "🔄 Typing the wrong format shows an error and brings the guide back automatically\n"
            "✅ Inline menus now consistently close after 120 seconds of inactivity\n"
            "📋 /task step-by-step guide is now fully restored on any mistake\n"
            "📢 /broadcast schedule flow is now fully fixed — tag and confirm work reliably",
            __import__('pytz').timezone('Asia/Jakarta').localize(__import__('datetime').datetime(2026, 6, 26))
        )
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS bot_admins (
                username VARCHAR(100) PRIMARY KEY
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS graveyard (
                username VARCHAR(100) PRIMARY KEY,
                removed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_announcements (
                id           SERIAL PRIMARY KEY,
                chat_id      TEXT,
                frequency    VARCHAR(20) DEFAULT 'once',
                run_time     VARCHAR(5),
                mention      BOOLEAN DEFAULT FALSE,
                message      TEXT,
                created_by   VARCHAR(100),
                scheduled_at TIMESTAMP WITH TIME ZONE
            )
        ''')
        # Migration: guarantee every column this table has ever needed exists,
        # regardless of which CREATE TABLE ran first historically on this DB.
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITH TIME ZONE")
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN IF NOT EXISTS last_run TIMESTAMP WITH TIME ZONE")
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN IF NOT EXISTS scheduled_date TEXT")
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN IF NOT EXISTS mention BOOLEAN DEFAULT FALSE")
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN IF NOT EXISTS created_by VARCHAR(100)")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                text TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS announcement_messages (
                id SERIAL PRIMARY KEY,
                announcement_id INT,
                chat_id BIGINT,
                message_id BIGINT
            )
        ''')
        count = await conn.fetchval("SELECT COUNT(*) FROM bot_version")
        if count == 0:
            await conn.execute(
                "INSERT INTO bot_version (version, changelog) VALUES ($1, $2)",
                "1.0", "• Initial release of Nukhba Manager Bot."
            )


def _next_version(current: str) -> str:
    try:
        parts = current.strip().split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        if minor >= 9:
            return f"{major + 1}.0"
        return f"{major}.{minor + 1}"
    except Exception:
        return "1.1"


# ─────────────────────────────────────────────
# /botconfig — GLOBAL SETTINGS PANEL
# ─────────────────────────────────────────────

async def bot_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    async with pool.acquire() as conn:
        gl = await conn.fetchval("SELECT value FROM config WHERE key='gemini_weekly_limit'") or '20'
        sq = await conn.fetchval("SELECT value FROM config WHERE key='star_quota'") or '3'
        mt = await conn.fetchval("SELECT value FROM config WHERE key='max_tasks'") or '4'
        ma = await conn.fetchval("SELECT value FROM config WHERE key='max_away_days'") or '14'
        me = await conn.fetchval("SELECT value FROM config WHERE key='max_events'") or '5'

    context.user_data['cfg_owner'] = update.effective_user.id
    context.user_data['cfg_draft'] = {
        'gemini_weekly_limit': gl,
        'star_quota': sq,
        'max_tasks': mt,
        'max_away_days': ma,
        'max_events': me,
    }

    msg = await update.message.reply_text(
        _cfg_text(context.user_data['cfg_draft']),
        reply_markup=_cfg_kb(context.user_data['cfg_draft']),
        parse_mode="Markdown"
    )
    context.user_data['cfg_msg_id'] = msg.message_id
    await schedule_kb_timeout(context, update.effective_chat.id, msg.message_id, update.effective_user.id)


def _cfg_text(d):
    return (
        "⚙️ **NUKHBA GLOBAL CONFIGURATION**\n"
        "──────────────────────────────\n"
        f"🤖 AI Limit: `{d['gemini_weekly_limit']} queries/week`\n"
        f"⭐ Star Quota: `{d['star_quota']} stars/week`\n"
        f"⚡ Max Tasks: `{d['max_tasks']} pending/user`\n"
        f"📅 Max Events: `{d['max_events']} active/user`\n"
        f"🏖️ Max Away: `{d['max_away_days']} days`\n\n"
        "⚠️ *Press ✅ Save to apply changes.*"
    )


def _cfg_kb(d):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🤖 AI −", callback_data="cfg_gemini_sub"),
            InlineKeyboardButton(f"🤖 AI: {d['gemini_weekly_limit']}", callback_data="cfg_noop"),
            InlineKeyboardButton(f"🤖 AI +", callback_data="cfg_gemini_add"),
            InlineKeyboardButton("✏️", callback_data="cfg_gemini_cus"),
        ],
        [
            InlineKeyboardButton(f"⭐ Stars −", callback_data="cfg_stars_sub"),
            InlineKeyboardButton(f"⭐ Stars: {d['star_quota']}", callback_data="cfg_noop"),
            InlineKeyboardButton(f"⭐ Stars +", callback_data="cfg_stars_add"),
            InlineKeyboardButton("✏️", callback_data="cfg_stars_cus"),
        ],
        [
            InlineKeyboardButton(f"⚡ Tasks −", callback_data="cfg_tasks_sub"),
            InlineKeyboardButton(f"⚡ Tasks: {d['max_tasks']}", callback_data="cfg_noop"),
            InlineKeyboardButton(f"⚡ Tasks +", callback_data="cfg_tasks_add"),
            InlineKeyboardButton("✏️", callback_data="cfg_tasks_cus"),
        ],
        [
            InlineKeyboardButton(f"📅 Events −", callback_data="cfg_events_sub"),
            InlineKeyboardButton(f"📅 Events: {d['max_events']}", callback_data="cfg_noop"),
            InlineKeyboardButton(f"📅 Events +", callback_data="cfg_events_add"),
            InlineKeyboardButton("✏️", callback_data="cfg_events_cus"),
        ],
        [
            InlineKeyboardButton(f"🏖️ Away −", callback_data="cfg_away_sub"),
            InlineKeyboardButton(f"🏖️ Away: {d['max_away_days']}", callback_data="cfg_noop"),
            InlineKeyboardButton(f"🏖️ Away +", callback_data="cfg_away_add"),
            InlineKeyboardButton("✏️", callback_data="cfg_away_cus"),
        ],
        [
            InlineKeyboardButton("👥 Manage Users", callback_data="cfg_goto_users"),
            InlineKeyboardButton("🗓️ Sched Config", callback_data="cfg_goto_sched"),
        ],
        [
            InlineKeyboardButton("🆔 Group IDs", callback_data="cfg_show_groups"),
            InlineKeyboardButton("✅ Save", callback_data="cfg_save"),
            InlineKeyboardButton("❌ Cancel", callback_data="cfg_cancel"),
        ],
    ])


async def config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    pool = context.bot_data.get('db_pool')
    data = q.data

    if not await is_bot_admin(q.from_user.username, pool):
        return await q.answer("❌ Admins only.", show_alert=True)

    owner = context.user_data.get('cfg_owner')
    if owner and q.from_user.id != owner:
        return await q.answer("❌ This panel was opened by another admin.", show_alert=True)

    # ── Static actions (no draft needed) ─────────────────────────────────────
    if data == "cfg_noop":
        return await q.answer()

    if data == "cfg_cancel":
        cancel_kb_timeout(context, q.message.chat.id, q.message.message_id)
        context.user_data.pop('cfg_draft', None)
        context.user_data.pop('cfg_owner', None)
        await q.answer("Cancelled.")
        try:
            await q.edit_message_text("❌ Config cancelled. No changes saved.")
        except Exception as e:
            logger.debug(f"cfg_cancel edit failed: {e}")
        return

    if data == "cfg_save":
        d = context.user_data.get('cfg_draft')
        if not d:
            return await q.answer("Session expired.", show_alert=True)
        async with pool.acquire() as conn:
            for key, val in d.items():
                await conn.execute(
                    "INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2",
                    key, str(val)
                )
        cancel_kb_timeout(context, q.message.chat.id, q.message.message_id)
        context.user_data.pop('cfg_draft', None)
        context.user_data.pop('cfg_owner', None)
        await q.answer("✅ Saved!")
        try:
            await q.edit_message_text(
                "✅ **Configuration saved and applied!**\n\n" + _cfg_text(d),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.debug(f"cfg_save edit failed: {e}")
        return

    # ── Navigation buttons (open sub-panels) ─────────────────────────────────
    if data == "cfg_goto_users":
        await q.answer()
        context.user_data['mu_owner'] = q.from_user.id
        try:
            await q.edit_message_text(
                "👥 **USER MANAGER**\n\nChoose what you'd like to manage:",
                reply_markup=_mu_main_kb(),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.debug(f"cfg_goto_users nav failed: {e}")
        return

    if data == "cfg_goto_sched":
        await q.answer()
        async with pool.acquire() as conn:
            bday_time = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'")    or "10:00"
            bday_ch   = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'") or ""
            kp_time   = await conn.fetchval("SELECT value FROM config WHERE key='kp_lb_time'")   or "13:00"
            kp_ch     = await conn.fetchval("SELECT value FROM config WHERE key='kp_channel'")   or ""
            star_time = await conn.fetchval("SELECT value FROM config WHERE key='star_lb_time'") or "00:05"
            star_ch   = await conn.fetchval("SELECT value FROM config WHERE key='stars_channel'") or ""
        context.user_data['schcfg_owner']  = q.from_user.id
        context.user_data['schcfg_msg_id'] = q.message.message_id
        context.user_data['schcfg_draft']  = {
            'bday_time': bday_time, 'bday_ch': bday_ch,
            'kp_time':   kp_time,   'kp_ch':   kp_ch,
            'star_time': star_time, 'star_ch': star_ch,
        }
        for flag in ['awaiting_schcfg_bday_time', 'awaiting_schcfg_bday_ch',
                     'awaiting_schcfg_kp_time',   'awaiting_schcfg_kp_ch',
                     'awaiting_schcfg_star_time',  'awaiting_schcfg_star_ch']:
            context.user_data.pop(flag, None)
        try:
            await q.edit_message_text(
                _schcfg_text(context.user_data['schcfg_draft']),
                reply_markup=_schcfg_kb(),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.debug(f"cfg_goto_sched nav failed: {e}")
        return

    if data == "cfg_show_groups":
        await q.answer()
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title FROM active_groups ORDER BY title")
        if groups:
            lines = ["🆔 **Registered Group IDs**\n"]
            for g in groups:
                lines.append(f"• `{g['chat_id']}` — {g['title']}")
            body = "\n".join(lines)
        else:
            body = (
                "🆔 **Registered Group IDs**\n\n"
                "_No groups registered yet._\n\n"
                "Run `/registergroup` inside a group to add it."
            )
        try:
            await q.edit_message_text(
                body + "\n\n_Press Back to return to config._",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back to Config", callback_data="cfg_back")]
                ]),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.debug(f"cfg_show_groups failed: {e}")
        return

    if data == "cfg_back":
        d = context.user_data.get('cfg_draft')
        if not d:
            return await q.answer("Session expired. Run /botconfig again.", show_alert=True)
        await q.answer()
        try:
            await q.edit_message_text(_cfg_text(d), reply_markup=_cfg_kb(d), parse_mode="Markdown")
        except Exception as e:
            logger.debug(f"cfg_back failed: {e}")
        return

    # ── Field +/− /custom buttons (require draft) ────────────────────────────
    d = context.user_data.get('cfg_draft')
    if not d:
        return await q.answer("Session expired. Run /botconfig again.", show_alert=True)

    # callback_data format: cfg_<field>_<action>
    # field names: gemini, stars, tasks, events, away
    # actions: add, sub, cus
    field_key_map = {
        'gemini': 'gemini_weekly_limit',
        'stars':  'star_quota',
        'tasks':  'max_tasks',
        'events': 'max_events',
        'away':   'max_away_days',
    }
    field_labels = {
        'gemini_weekly_limit': 'AI Queries/Week',
        'star_quota':          'Star Quota/Week',
        'max_tasks':           'Max Pending Tasks',
        'max_events':          'Max Active Events',
        'max_away_days':       'Max Away Days',
    }

    # Strip prefix "cfg_" then split into field + action
    # e.g. "cfg_gemini_add" → "gemini_add" → field="ai", action="add"
    # e.g. "cfg_events_cus" → "events_cus" → field="events", action="cus"
    stripped = data[4:]  # remove "cfg_"
    # action is always the last segment; field is everything before
    segments = stripped.rsplit("_", 1)
    if len(segments) != 2:
        return await q.answer()
    field, action = segments[0], segments[1]
    db_key = field_key_map.get(field)
    if not db_key or action not in ('add', 'sub', 'cus'):
        return await q.answer()

    if action == 'add':
        d[db_key] = str(int(d[db_key]) + 1)
        await q.answer(f"→ {d[db_key]}")

    elif action == 'sub':
        d[db_key] = str(max(1, int(d[db_key]) - 1))
        await q.answer(f"→ {d[db_key]}")

    elif action == 'cus':
        context.user_data['awaiting_cfg_field'] = db_key
        context.user_data['cfg_msg_id'] = q.message.message_id
        label = field_labels.get(db_key, db_key)
        await q.answer()
        try:
            await q.edit_message_text(
                f"✏️ **Set Custom Value — {label}**\n\n"
                f"Current value: `{d[db_key]}`\n\n"
                f"Send a positive whole number.\n"
                f"_The config panel will restore automatically after your reply._",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.debug(f"cfg custom prompt edit failed: {e}")
        return  # Don't fall through to the refresh below

    # Refresh the panel for add/sub actions
    try:
        await q.edit_message_text(_cfg_text(d), reply_markup=_cfg_kb(d), parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"cfg_callback refresh error: {e}")


async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    owner = context.user_data.get('cfg_owner')
    if owner and update.effective_user.id != owner:
        return False

    field = context.user_data.get('awaiting_cfg_field')
    if not field:
        return False

    text = update.message.text.strip() if update.message and update.message.text else ""
    if not text:
        return False

    try:
        val = int(text)
        if val < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Must be a positive whole number.")
        return True

    context.user_data.pop('awaiting_cfg_field')
    d = context.user_data.get('cfg_draft')
    if d:
        d[field] = str(val)

    try:
        await update.message.delete()
    except Exception as e:
        logger.debug(f"Could not delete message: {e}")

    try:
        chat_id = update.effective_chat.id
        msg_id  = context.user_data.get('cfg_msg_id')
        if msg_id and d:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_cfg_text(d), reply_markup=_cfg_kb(d), parse_mode="Markdown"
            )
    except Exception as e:
        logger.warning(f"cfg text input refresh error: {e}")
    return True


# ─────────────────────────────────────────────
# /setchannel & /unsetchannel
# ─────────────────────────────────────────────

CHANNEL_MAP = {
    "bday":     "bday_channel",
    "stars":    "stars_channel",
    "feedback": "feedback_channel",
}

async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type == "private":
        return await update.message.reply_text(
            "❌ Run this command inside the group you want to bind."
        )

    target = context.args[0].lower() if context.args else ""
    if target == "trivia":
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO trivia_config (key, value) VALUES ('target_chat_id', $1) "
                "ON CONFLICT (key) DO UPDATE SET value=$1",
                str(update.effective_chat.id)
            )
        return await update.message.reply_text(
            f"✅ Trivia target bound to this chat (`{update.effective_chat.id}`).",
            parse_mode="Markdown"
        )

    if target not in CHANNEL_MAP:
        return await update.message.reply_text(
            "❌ **Usage:** `/setchannel <bday|trivia|stars|feedback>`\n\n"
            "Run this command inside the target group to bind the feature to it.",
            parse_mode="Markdown"
        )

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2",
            CHANNEL_MAP[target], str(update.effective_chat.id)
        )
    await update.message.reply_text(
        f"✅ `{target}` channel bound to this group (`{update.effective_chat.id}`).",
        parse_mode="Markdown"
    )


async def unset_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    target = context.args[0].lower() if context.args else ""
    if target == "trivia":
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM trivia_config WHERE key='target_chat_id'")
        return await update.message.reply_text("✅ Trivia target chat binding cleared.")

    if target not in CHANNEL_MAP:
        return await update.message.reply_text(
            "❌ **Usage:** `/unsetchannel <bday|trivia|stars|feedback>`",
            parse_mode="Markdown"
        )

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM config WHERE key=$1", CHANNEL_MAP[target])
    await update.message.reply_text(
        f"✅ `{target}` channel binding has been cleared.",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
# /schedconfig — SCHEDULE & CHANNEL CONFIG PANEL
# ─────────────────────────────────────────────

async def sched_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interactive panel for Birthday, KP Leaderboard, and Stars Leaderboard schedule + channel."""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type != "private":
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "🔒 Please run `/schedconfig` in my Direct Messages for security.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    async with pool.acquire() as conn:
        bday_time  = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'")   or "10:00"
        bday_ch    = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'") or ""
        kp_time    = await conn.fetchval("SELECT value FROM config WHERE key='kp_lb_time'")  or "13:00"
        kp_ch      = await conn.fetchval("SELECT value FROM config WHERE key='kp_channel'")  or ""
        star_time  = await conn.fetchval("SELECT value FROM config WHERE key='star_lb_time'") or "00:05"
        star_ch    = await conn.fetchval("SELECT value FROM config WHERE key='stars_channel'") or ""

    context.user_data['schcfg_owner'] = update.effective_user.id
    context.user_data['schcfg_draft'] = {
        'bday_time': bday_time, 'bday_ch': bday_ch,
        'kp_time':   kp_time,   'kp_ch':   kp_ch,
        'star_time': star_time, 'star_ch': star_ch,
    }
    for flag in ['awaiting_schcfg_bday_time','awaiting_schcfg_bday_ch',
                 'awaiting_schcfg_kp_time',  'awaiting_schcfg_kp_ch',
                 'awaiting_schcfg_star_time', 'awaiting_schcfg_star_ch']:
        context.user_data.pop(flag, None)

    msg = await context.bot.send_message(
        update.effective_chat.id,
        _schcfg_text(context.user_data['schcfg_draft']),
        reply_markup=_schcfg_kb(),
        parse_mode="Markdown"
    )
    context.user_data['schcfg_msg_id'] = msg.message_id


def _schcfg_text(d):
    def ch(val): return f"`{val}`" if val else "`Not Set`"
    return (
        "🗓️ *SCHEDULE & CHANNEL CONFIGURATION*\n"
        "──────────────────────────────\n"
        "🎂 *Birthday Announcements*\n"
        f"   ⏰ Time: `{d['bday_time']} WIB`\n"
        f"   📡 Channel: {ch(d['bday_ch'])}\n\n"
        "🏅 *Monthly KP Leaderboard*\n"
        f"   ⏰ Time: `{d['kp_time']} WIB` *(runs on 1st of month)*\n"
        f"   📡 Channel: {ch(d['kp_ch'])}\n\n"
        "⭐ *Monthly Stars Leaderboard*\n"
        f"   ⏰ Time: `{d['star_time']} WIB` *(runs on 1st of month)*\n"
        f"   📡 Channel: {ch(d['star_ch'])}\n\n"
        "⚠️ _Nothing saves until you press ✅ Save_"
    )


def _schcfg_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎂 Birthday Time  ─────────────────", callback_data="schcfg_noop")],
        [
            InlineKeyboardButton("−1h", callback_data="schcfg_bday_tsub"),
            InlineKeyboardButton("+1h", callback_data="schcfg_bday_tadd"),
            InlineKeyboardButton("✏️ Custom", callback_data="schcfg_bday_tcus"),
        ],
        [InlineKeyboardButton("📡 Set Birthday Channel", callback_data="schcfg_bday_ch")],
        [InlineKeyboardButton("🏅 KP Leaderboard  ─────────────", callback_data="schcfg_noop")],
        [
            InlineKeyboardButton("−1h", callback_data="schcfg_kp_tsub"),
            InlineKeyboardButton("+1h", callback_data="schcfg_kp_tadd"),
            InlineKeyboardButton("✏️ Custom", callback_data="schcfg_kp_tcus"),
        ],
        [InlineKeyboardButton("📡 Set KP Channel", callback_data="schcfg_kp_ch")],
        [InlineKeyboardButton("⭐ Stars Leaderboard  ──────────", callback_data="schcfg_noop")],
        [
            InlineKeyboardButton("−1h", callback_data="schcfg_star_tsub"),
            InlineKeyboardButton("+1h", callback_data="schcfg_star_tadd"),
            InlineKeyboardButton("✏️ Custom", callback_data="schcfg_star_tcus"),
        ],
        [InlineKeyboardButton("📡 Set Stars Channel", callback_data="schcfg_star_ch")],
        [
            InlineKeyboardButton("✅ Save", callback_data="schcfg_save"),
            InlineKeyboardButton("❌ Cancel", callback_data="schcfg_cancel"),
        ],
    ])


async def _schcfg_refresh(query, context):
    d = context.user_data.get('schcfg_draft')
    if not d:
        return
    try:
        await query.edit_message_text(_schcfg_text(d), reply_markup=_schcfg_kb(), parse_mode="Markdown")
    except Exception:
        pass


async def _schcfg_refresh_from_input(update, context, d):
    chat_id = update.effective_chat.id
    msg_id  = context.user_data.get('schcfg_msg_id')
    try:
        if msg_id:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_schcfg_text(d), reply_markup=_schcfg_kb(), parse_mode="Markdown"
            )
        else:
            msg = await context.bot.send_message(chat_id, _schcfg_text(d), reply_markup=_schcfg_kb(), parse_mode="Markdown")
            context.user_data['schcfg_msg_id'] = msg.message_id
    except Exception as e:
        logger.warning(f"schcfg input refresh error: {e}")


def _bump_time(t_str, delta_hours):
    h, m = map(int, t_str.split(":"))
    return f"{(h + delta_hours) % 24:02d}:{m:02d}"


async def sched_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all schcfg_ callbacks for the schedule config panel."""
    q    = update.callback_query
    pool = context.bot_data.get('db_pool')
    data = q.data

    if not await is_bot_admin(q.from_user.username, pool):
        return await q.answer("❌ Admins only.", show_alert=True)
    owner = context.user_data.get('schcfg_owner')
    if owner and q.from_user.id != owner:
        return await q.answer("❌ This config belongs to another admin.", show_alert=True)

    d   = context.user_data.get('schcfg_draft')
    act = data[7:]  # strip "schcfg_"

    if act == "noop":
        return await q.answer()

    if act == "cancel":
        context.user_data.pop('schcfg_draft', None)
        context.user_data.pop('schcfg_owner', None)
        await q.answer("Cancelled.")
        try:
            await q.edit_message_text("❌ *Schedule config cancelled. No changes saved.*", parse_mode="Markdown")
        except Exception:
            pass
        return

    if not d:
        return await q.answer("⚠️ Session expired. Run /schedconfig again.", show_alert=True)

    # ── Time adjustments ──────────────────────────────────────────────────────
    if act == "bday_tsub":
        d['bday_time'] = _bump_time(d['bday_time'], -1)
        await q.answer(f"Birthday time → {d['bday_time']}")
        return await _schcfg_refresh(q, context)

    if act == "bday_tadd":
        d['bday_time'] = _bump_time(d['bday_time'], +1)
        await q.answer(f"Birthday time → {d['bday_time']}")
        return await _schcfg_refresh(q, context)

    if act == "bday_tcus":
        context.user_data['awaiting_schcfg_bday_time'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "⏰ *Type Birthday announcement time* in `HH:MM` (24-hour WIB):\n\nExample: `09:30`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if act == "kp_tsub":
        d['kp_time'] = _bump_time(d['kp_time'], -1)
        await q.answer(f"KP time → {d['kp_time']}")
        return await _schcfg_refresh(q, context)

    if act == "kp_tadd":
        d['kp_time'] = _bump_time(d['kp_time'], +1)
        await q.answer(f"KP time → {d['kp_time']}")
        return await _schcfg_refresh(q, context)

    if act == "kp_tcus":
        context.user_data['awaiting_schcfg_kp_time'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "⏰ *Type KP Leaderboard reset time* in `HH:MM` (24-hour WIB):\n\nExample: `13:00`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if act == "star_tsub":
        d['star_time'] = _bump_time(d['star_time'], -1)
        await q.answer(f"Stars time → {d['star_time']}")
        return await _schcfg_refresh(q, context)

    if act == "star_tadd":
        d['star_time'] = _bump_time(d['star_time'], +1)
        await q.answer(f"Stars time → {d['star_time']}")
        return await _schcfg_refresh(q, context)

    if act == "star_tcus":
        context.user_data['awaiting_schcfg_star_time'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "⏰ *Type Stars Leaderboard reset time* in `HH:MM` (24-hour WIB):\n\nExample: `00:05`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # ── Channel input prompts ─────────────────────────────────────────────────
    if act == "bday_ch":
        context.user_data['awaiting_schcfg_bday_ch'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "📡 *Set Birthday Channel*\n\n"
                "Forward a message from the target channel/group, *or* type its chat ID directly.\n"
                "_Supergroups start with_ `-100`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if act == "kp_ch":
        context.user_data['awaiting_schcfg_kp_ch'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "📡 *Set KP Leaderboard Channel*\n\n"
                "Forward a message from the target channel/group, *or* type its chat ID directly.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if act == "star_ch":
        context.user_data['awaiting_schcfg_star_ch'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "📡 *Set Stars Leaderboard Channel*\n\n"
                "Forward a message from the target channel/group, *or* type its chat ID directly.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # ── Save ─────────────────────────────────────────────────────────────────
    if act == "save":
        async with pool.acquire() as conn:
            pairs = [
                ('bday_time',    d['bday_time']),
                ('bday_channel', d['bday_ch']),
                ('kp_lb_time',   d['kp_time']),
                ('kp_channel',   d['kp_ch']),
                ('star_lb_time', d['star_time']),
                ('stars_channel',d['star_ch']),
            ]
            for key, val in pairs:
                if val:
                    await conn.execute(
                        "INSERT INTO config (key, value) VALUES ($1, $2) "
                        "ON CONFLICT (key) DO UPDATE SET value=$2",
                        key, str(val)
                    )
                else:
                    await conn.execute("DELETE FROM config WHERE key=$1", key)

        # Reschedule live jobs
        from crons import schedule_bday_job, schedule_kp_job, schedule_star_job
        from telegram.ext import Application
        app = context.application
        await schedule_bday_job(app)
        await schedule_kp_job(app)
        await schedule_star_job(app)

        context.user_data.pop('schcfg_draft', None)
        context.user_data.pop('schcfg_owner', None)
        context.user_data.pop('schcfg_msg_id', None)
        await q.answer("✅ Saved & rescheduled!")
        try:
            def ch(val): return val if val else "Not Set"
            await q.edit_message_text(
                "✅ *Schedule Config Saved!*\n\n"
                f"🎂 Birthday: `{d['bday_time']} WIB` → `{ch(d['bday_ch'])}`\n"
                f"🏅 KP LB: `{d['kp_time']} WIB` → `{ch(d['kp_ch'])}`\n"
                f"⭐ Stars LB: `{d['star_time']} WIB` → `{ch(d['star_ch'])}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    await q.answer()


async def handle_schcfg_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Called from global_text_router. Returns True if we consumed the input."""
    d = context.user_data.get('schcfg_draft')
    if not d:
        return False

    text = (update.message.text or "").strip()

    def parse_time(t):
        parts = t.replace(".", ":").split(":")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h < 24 and 0 <= m < 60:
                return f"{h:02d}:{m:02d}"
        return None

    def parse_chat_id(msg):
        # Accept forwarded messages or raw typed IDs
        if msg.forward_origin:
            chat = getattr(msg.forward_origin, 'chat', None)
            if chat:
                return str(chat.id)
        t = msg.text.strip() if msg.text else ""
        if t.lstrip("-").isdigit():
            return t
        return None

    consumed = False

    if context.user_data.pop('awaiting_schcfg_bday_time', False):
        t = parse_time(text)
        if t:
            d['bday_time'] = t
            await update.message.reply_text(f"✅ Birthday time set to `{t} WIB`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Invalid format. Use `HH:MM` (e.g. `09:30`)", parse_mode="Markdown")
        consumed = True

    elif context.user_data.pop('awaiting_schcfg_kp_time', False):
        t = parse_time(text)
        if t:
            d['kp_time'] = t
            await update.message.reply_text(f"✅ KP Leaderboard time set to `{t} WIB`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Invalid format. Use `HH:MM` (e.g. `13:00`)", parse_mode="Markdown")
        consumed = True

    elif context.user_data.pop('awaiting_schcfg_star_time', False):
        t = parse_time(text)
        if t:
            d['star_time'] = t
            await update.message.reply_text(f"✅ Stars Leaderboard time set to `{t} WIB`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Invalid format. Use `HH:MM` (e.g. `00:05`)", parse_mode="Markdown")
        consumed = True

    elif context.user_data.pop('awaiting_schcfg_bday_ch', False):
        cid = parse_chat_id(update.message)
        if cid:
            d['bday_ch'] = cid
            await update.message.reply_text(f"✅ Birthday channel set to `{cid}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Could not read a chat ID. Forward a message or type the ID directly.")
        consumed = True

    elif context.user_data.pop('awaiting_schcfg_kp_ch', False):
        cid = parse_chat_id(update.message)
        if cid:
            d['kp_ch'] = cid
            await update.message.reply_text(f"✅ KP channel set to `{cid}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Could not read a chat ID. Forward a message or type the ID directly.")
        consumed = True

    elif context.user_data.pop('awaiting_schcfg_star_ch', False):
        cid = parse_chat_id(update.message)
        if cid:
            d['star_ch'] = cid
            await update.message.reply_text(f"✅ Stars channel set to `{cid}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Could not read a chat ID. Forward a message or type the ID directly.")
        consumed = True

    if consumed:
        await _schcfg_refresh_from_input(update, context, d)
    return consumed



# ─────────────────────────────────────────────
# /manageusers — INTERACTIVE USER MANAGER
# ─────────────────────────────────────────────

async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias — /manageusers is now merged into /botconfig. Kept for backward compat."""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    await update.message.reply_text(
        "ℹ️ `/manageusers` has been merged into `/botconfig`.\n\n"
        "Please use `/botconfig` and tap **👥 Manage Users** from the panel.",
        parse_mode="Markdown"
    )
    # Auto-open user manager directly for convenience
    # The full user manager logic is now accessed via /botconfig → Manage Users button
    return


def _mu_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 AI Limits",       callback_data="mu_section_ailimit")],
        [InlineKeyboardButton("⭐ RAWWY Stars",      callback_data="mu_section_stars")],
        [InlineKeyboardButton("🧠 Knowledge Points", callback_data="mu_section_kp")],
        [InlineKeyboardButton("❌ Close",            callback_data="mu_close")],
    ])


async def manage_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pool = context.bot_data.get('db_pool')

    if not await is_bot_admin(q.from_user.username, pool):
        return await q.answer("❌ Admins only.", show_alert=True)

    owner = context.user_data.get('mu_owner')
    if owner and q.from_user.id != owner:
        return await q.answer("❌ This panel was opened by another admin.", show_alert=True)

    data = q.data

    if data == "mu_close":
        cancel_kb_timeout(context, q.message.chat.id, q.message.message_id)
        context.user_data.pop('mu_owner', None)
        context.user_data.pop('mu_section', None)
        context.user_data.pop('awaiting_mu_input', None)
        await q.answer("Closed.")
        # If we came from /botconfig, restore the config panel
        cfg_draft = context.user_data.get('cfg_draft')
        if cfg_draft:
            try:
                await q.edit_message_text(
                    _cfg_text(cfg_draft),
                    reply_markup=_cfg_kb(cfg_draft),
                    parse_mode="Markdown"
                )
                return
            except Exception as e:
                logger.debug(f"mu_close restore cfg panel failed: {e}")
        try:
            await q.edit_message_text("👥 User Manager closed.")
        except Exception as e:
            logger.debug(f"Menu close failed: {e}")
        return

    if data == "mu_back":
        await q.answer()
        try:
            await q.edit_message_text(
                "👥 **USER MANAGER**\n\nChoose what you'd like to manage:",
                reply_markup=_mu_main_kb(),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.debug(f"Menu navigation failed: {e}")
        return

    if data == "mu_section_ailimit":
        await q.answer()
        context.user_data['mu_section'] = 'ailimit'
        try:
            await q.edit_message_text(
                "🤖 **AI Limit Manager**\n\n"
                "Type a username to look up or modify their AI query limit.\n\n"
                "Format: `@username , set|add|sub , amount`\n"
                "Or type `all` to view everyone's limits.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="mu_back")]
                ])
            )
        except Exception as e:
            logger.warning(f"AI Limit Manager UI failed: {e}")
        context.user_data['awaiting_mu_input'] = True
        return

    if data == "mu_section_stars":
        await q.answer()
        context.user_data['mu_section'] = 'stars'
        try:
            await q.edit_message_text(
                "⭐ **RAWWY Stars Manager**\n\n"
                "Type your adjustment in this format:\n\n"
                "`@username , quota|monthly|total , set|add|sub , amount`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="mu_back")]
                ])
            )
        except Exception as e:
            logger.warning(f"Stars Manager UI failed: {e}")
        context.user_data['awaiting_mu_input'] = True
        return

    if data == "mu_section_kp":
        await q.answer()
        context.user_data['mu_section'] = 'kp'
        try:
            await q.edit_message_text(
                "🧠 **Knowledge Points Manager**\n\n"
                "Type your adjustment in this format:\n\n"
                "`@username , set|add|sub , amount`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="mu_back")]
                ])
            )
        except Exception as e:
            logger.warning(f"KP Manager UI failed: {e}")
        context.user_data['awaiting_mu_input'] = True
        return

    await q.answer()


async def _handle_mu_text(update: Update, context: ContextTypes.DEFAULT_TYPE, pool) -> bool:
    if not context.user_data.get('awaiting_mu_input'):
        return False

    owner = context.user_data.get('mu_owner')
    if owner and update.effective_user.id != owner:
        return False

    section = context.user_data.get('mu_section')
    text    = update.message.text.strip() if update.message and update.message.text else ""
    if not text:
        return False

    context.user_data.pop('awaiting_mu_input', None)
    context.user_data.pop('mu_section', None)

    try:
        if section == 'ailimit':
            if text.lower() == 'all':
                async with pool.acquire() as conn:
                    recs = await conn.fetch('SELECT username, gemini_quota FROM users ORDER BY username')
                msg = "🤖 **AI Limits:**\n" + "\n".join(
                    [f"• @{r['username']}: {r['gemini_quota']}" for r in recs]
                ) if recs else "No users found."
            else:
                parts = [p.strip() for p in text.split(",", 2)]
                user  = parts[0].replace("@", "").lower()
                op    = parts[1].lower()
                amt   = int(parts[2])
                async with pool.acquire() as conn:
                    if op == 'set':
                        await conn.execute("UPDATE users SET gemini_quota=$1 WHERE username=$2", amt, user)
                    elif op == 'add':
                        await conn.execute("UPDATE users SET gemini_quota=gemini_quota+$1 WHERE username=$2", amt, user)
                    elif op == 'sub':
                        await conn.execute("UPDATE users SET gemini_quota=GREATEST(0,gemini_quota-$1) WHERE username=$2", amt, user)
                msg = f"✅ AI limit for @{user} updated (`{op}` {amt})."

        elif section == 'stars':
            parts = [p.strip() for p in text.split(",", 3)]
            user  = parts[0].replace("@", "").lower()
            field = parts[1].lower()
            op    = parts[2].lower()
            amt   = int(parts[3])
            col   = {'quota': 'quota', 'monthly': 'monthly_points', 'total': 'all_time_points'}.get(field, 'quota')
            async with pool.acquire() as conn:
                await conn.execute('INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', user)
                if op == 'set':
                    await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, user)
                elif op == 'add':
                    await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, user)
                elif op == 'sub':
                    await conn.execute(f'UPDATE kudos SET {col}=GREATEST(0,{col}-$1) WHERE username=$2', amt, user)
            msg = f"✅ Stars for @{user} updated (`{field}` `{op}` {amt})."

        elif section == 'kp':
            parts = [p.strip() for p in text.split(",", 2)]
            user  = parts[0].replace("@", "").lower()
            op    = parts[1].lower()
            amt   = int(parts[2])
            async with pool.acquire() as conn:
                if op == 'set':
                    await conn.execute(
                        "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1,$2,$2) "
                        "ON CONFLICT (username) DO UPDATE SET monthly_kp=$2, all_time_kp=$2", user, amt
                    )
                elif op == 'add':
                    await conn.execute(
                        "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1,$2,$2) "
                        "ON CONFLICT (username) DO UPDATE SET "
                        "monthly_kp=trivia_scores.monthly_kp+$2, all_time_kp=trivia_scores.all_time_kp+$2",
                        user, amt
                    )
                elif op == 'sub':
                    await conn.execute(
                        "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1,0,0) "
                        "ON CONFLICT (username) DO UPDATE SET "
                        "monthly_kp=GREATEST(0,trivia_scores.monthly_kp-$2), "
                        "all_time_kp=GREATEST(0,trivia_scores.all_time_kp-$2)",
                        user, amt
                    )
            msg = f"✅ Knowledge Points for @{user} updated (`{op}` {amt} KP)."
        else:
            return False

    except Exception as e:
        msg = f"❌ Error: {e}\n\nPlease check the format and try again."

    try:
        await update.message.delete()
    except Exception as e:
        logger.debug(f"Failed to delete message: {e}")
    await update.message.reply_text(msg, parse_mode="Markdown")
    return True


# ─────────────────────────────────────────────
# VERSION SYSTEM: /pushupdate, /updatechange, /updateinfo
# ─────────────────────────────────────────────

async def update_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    await _ensure_version_table(pool)

    is_admin_user  = await is_bot_admin(update.effective_user.username, pool)
    is_super_owner = await is_super(update.effective_user.username)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT version, changelog, updated_at FROM bot_version ORDER BY id ASC"
        )

    # Show all versions up to and including 1.3
    MAX_VERSION = (1, 3)
    def _ver_tuple(v):
        try:
            parts = str(v).split('.')
            return tuple(int(x) for x in parts)
        except Exception:
            return (0, 0)

    rows = [r for r in rows if _ver_tuple(r['version']) <= MAX_VERSION]

    if not rows:
        return await update.message.reply_text("ℹ️ No version info available yet.")

    latest = rows[-1]
    header = (
        f"🤖 Nukhba Manager Bot\n"
        f"📦 Current Version: {latest['version']}\n"
        f"📅 Last Updated: {latest['updated_at'].astimezone(WIB).strftime('%d %b %Y')}, WIB\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 Changelog:\n"
    )
    changelog_lines = []
    for r in rows:
        ts  = r['updated_at'].astimezone(WIB).strftime('%d %b %Y')
        log = r['changelog']
        # For non-admins, strip out lines that mention admin/super commands
        if not is_admin_user and not is_super_owner:
            filtered = []
            skip_keywords = [
                'admin', 'super owner', '/botconfig', '/manageuser',
                '/addadmin', '/deladmin', '/graveyard', '/schedconfig',
                '/newsched', '/analyze', 'super_reset', 'botstatus',
                '/userconfig', '/birthdayconfig', '/broadcastconfig',
                '/awayconfig', '/eventpoll',
            ]
            for line in log.split('\n'):
                if not any(kw.lower() in line.lower() for kw in skip_keywords):
                    filtered.append(line)
            log = '\n'.join(filtered).strip()
        if log:
            changelog_lines.append(f"\n🔖 v{r['version']} — {ts}\n{log}")

    await send_md(context, update.effective_chat.id, header + "\n".join(changelog_lines))


async def push_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_super(update.effective_user.username):
        return await update.message.reply_text("❌ Super Owner only.")

    changelog = " ".join(context.args).strip()
    if not changelog:
        return await update.message.reply_text(
            "❌ **Usage:** `/pushupdate [changelog text]`\n\n"
            "Example: `/pushupdate Fixed trivia timer, added /about command`",
            parse_mode="Markdown"
        )

    await _ensure_version_table(pool)

    async with pool.acquire() as conn:
        latest = await conn.fetchrow("SELECT version FROM bot_version ORDER BY id DESC LIMIT 1")
        current_ver = latest['version'] if latest else "1.0"
        new_ver     = _next_version(current_ver)
        await conn.execute(
            "INSERT INTO bot_version (version, changelog) VALUES ($1, $2)",
            new_ver, changelog
        )
        dm_users = await conn.fetch(
            "SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL"
        )

    now_str = datetime.datetime.now(WIB).strftime('%d %b %Y')
    broadcast_text = (
        f"🤖 Nukhba Manager Bot\n"
        f"📦 Current Version: {new_ver}\n"
        f"📅 Last Updated: {now_str}, WIB\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 New update released!\n\n"
        f"📝 What's New:\n{changelog}\n\n"
        f"Type /update to see the full changelog."
    )

    sent_count = 0
    for user in dm_users:
        try:
            await context.bot.send_message(user['user_id'], broadcast_text, parse_mode="Markdown")
            sent_count += 1
            await asyncio.sleep(0.05) 
        except Exception as e:
            logger.warning(f"Failed to push update broadcast to {user['user_id']}: {e}")

    await update.message.reply_text(
        f"✅ **Version `{new_ver}` pushed!**\n"
        f"📢 Update broadcasted to {sent_count} users.",
        parse_mode="Markdown"
    )


async def update_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /updatechange — open inline panel pre-filled with current version + changelog for easy edit.
    Super Owner only.
    """
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    uid  = update.effective_user.id
    if not await is_super(update.effective_user.username):
        return

    await _ensure_version_table(pool)
    async with pool.acquire() as conn:
        latest = await conn.fetchrow(
            "SELECT version, changelog FROM bot_version ORDER BY id DESC LIMIT 1"
        )

    cur_ver = latest['version'] if latest else "1.2"
    cur_log = latest['changelog'] if latest else ""

    # Show current version info with inline Edit button
    text = (
        f"🔄 *Changelog Editor*\n\n"
        f"📦 Current version: `{cur_ver}`\n\n"
        f"📝 Current changelog:\n_{cur_log[:500]}_\n\n"
        f"Send the updated entry in this format:\n"
        f"`VERSION , CHANGELOG`\n\n"
        f"Example:\n"
        f"`1.3 , Added /eventpoll, fixed library hub, improved /mytask`"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data="uc_cancel")
    ]])

    try:
        msg = await context.bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
        context.user_data['uc_state']     = 'await_updatechange'
        context.user_data['uc_panel_chat'] = uid
        context.user_data['uc_panel_msg']  = msg.message_id
        await schedule_text_input_timeout(context, uid, "uc_state", "await_updatechange", uid, msg.message_id)
    except Exception:
        if update.message:
            await update.message.reply_text("❌ Please start a DM with me first (/start).")

    context.user_data.pop('uc_state', None)
    await update.message.reply_text(
        f"✅ *Version `{new_ver}` saved!*\n\n"
        f"📝 Changelog:\n_{changelog}_\n\n"
        f"Use `/pushupdate` to broadcast this to all groups.",
        parse_mode="Markdown"
    )
    return True


# ─────────────────────────────────────────────
# /newsched — INTERACTIVE BROADCAST SCHEDULER
# ─────────────────────────────────────────────

async def new_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    context.user_data['nsched_owner'] = update.effective_user.id
    context.user_data['nsched_draft'] = {
        'chat_id': 'all',
        'frequency': 'daily',
        'run_time': '09:00',
        'mention': False,
        'message': '',
    }

    msg = await update.message.reply_text(
        _nsched_text(context.user_data['nsched_draft']),
        reply_markup=_nsched_kb(context.user_data['nsched_draft']),
        parse_mode="Markdown"
    )
    context.user_data['nsched_msg_id']  = msg.message_id
    context.user_data['nsched_chat_id'] = update.effective_chat.id
    await schedule_kb_timeout(context, update.effective_chat.id, msg.message_id, update.effective_user.id)


def _nsched_text(d):
    mention_label = "Yes 🔔" if d['mention'] else "No 🔕"
    msg_preview   = (d['message'][:40] + "…") if len(d['message']) > 40 else (d['message'] or "_Not set_")
    return (
        "📢 **BROADCAST SCHEDULER**\n"
        "──────────────────────────────\n"
        f"📡 Target: `{d['chat_id']}`\n"
        f"🔁 Frequency: `{d['frequency']}`\n"
        f"⏰ Time: `{d['run_time']} WIB`\n"
        f"🔔 Tag All: `{mention_label}`\n"
        f"📝 Message: {msg_preview}\n\n"
        "⚠️ *Press ✅ Schedule to save.*"
    )


def _nsched_kb(d):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Set Target (all / chat ID)", callback_data="nsched_target")],
        [
            InlineKeyboardButton("🔁 Once",   callback_data="nsched_freq_once"),
            InlineKeyboardButton("🔁 Daily",  callback_data="nsched_freq_daily"),
            InlineKeyboardButton("🔁 Weekly", callback_data="nsched_freq_weekly"),
        ],
        [
            InlineKeyboardButton("⏰ −1h", callback_data="nsched_time_sub"),
            InlineKeyboardButton("⏰ +1h", callback_data="nsched_time_add"),
            InlineKeyboardButton("✏️ Custom Time", callback_data="nsched_time_cus"),
        ],
        [InlineKeyboardButton(
            f"🔔 Tag All: {'Yes' if d['mention'] else 'No'} (Toggle)",
            callback_data="nsched_mention"
        )],
        [InlineKeyboardButton("📝 Set Message", callback_data="nsched_message")],
        [
            InlineKeyboardButton("✅ Schedule", callback_data="nsched_save"),
            InlineKeyboardButton("❌ Cancel",   callback_data="nsched_cancel"),
        ],
    ])


async def newsched_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    pool = context.bot_data.get('db_pool')

    if not await is_bot_admin(q.from_user.username, pool):
        return await q.answer("❌ Admins only.", show_alert=True)

    owner = context.user_data.get('nsched_owner')
    if owner and q.from_user.id != owner:
        return await q.answer("❌ Panel opened by another admin.", show_alert=True)

    d    = context.user_data.get('nsched_draft')
    data = q.data

    if data == "nsched_cancel":
        cancel_kb_timeout(context, q.message.chat.id, q.message.message_id)
        context.user_data.pop('nsched_draft', None)
        context.user_data.pop('nsched_owner', None)
        await q.answer("Cancelled.")
        try:
            await q.edit_message_text("❌ Schedule cancelled. No changes saved.")
        except Exception as e:
            logger.debug(f"Failed to clear scheduler UI: {e}")
        return

    if not d:
        return await q.answer("Session expired. Run /newsched again.", show_alert=True)

    if data == "nsched_save":
        if not d['message']:
            return await q.answer("❌ Message is required before saving.", show_alert=True)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO scheduled_announcements (chat_id, frequency, run_time, mention, message, created_by) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                d['chat_id'], d['frequency'], d['run_time'], d['mention'],
                d['message'], q.from_user.username
            )
        cancel_kb_timeout(context, q.message.chat.id, q.message.message_id)
        context.user_data.pop('nsched_draft', None)
        context.user_data.pop('nsched_owner', None)
        await q.answer("✅ Scheduled!")
        try:
            await q.edit_message_text(
                f"✅ **Broadcast Scheduled!**\n\n{_nsched_text(d)}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Failed to update schedule message: {e}")
        return

    if data == "nsched_target":
        context.user_data['awaiting_nsched_target'] = True
        # Store chat_id + msg_id so we can restore the panel after user replies
        context.user_data['nsched_msg_id']  = q.message.message_id
        context.user_data['nsched_chat_id'] = q.message.chat.id
        await q.answer()
        try:
            await q.edit_message_text(
                "📡 **Set Target Chat**\n\n"
                "Type `all` to broadcast to all groups,\n"
                "or type a specific Group ID (e.g. `-1001234567890`).\n\n"
                "_Run /groupid or /registergroup inside the target group to get its ID._",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Failed to update target chat prompt: {e}")
        return

    if data.startswith("nsched_freq_"):
        d['frequency'] = data.replace("nsched_freq_", "")
        await q.answer(f"Frequency → {d['frequency']}")

    elif data == "nsched_time_add":
        h, m = map(int, d['run_time'].split(":"))
        d['run_time'] = f"{(h + 1) % 24:02d}:{m:02d}"
        await q.answer(f"Time → {d['run_time']}")

    elif data == "nsched_time_sub":
        h, m = map(int, d['run_time'].split(":"))
        d['run_time'] = f"{(h - 1) % 24:02d}:{m:02d}"
        await q.answer(f"Time → {d['run_time']}")

    elif data == "nsched_time_cus":
        context.user_data['awaiting_nsched_time'] = True
        context.user_data['nsched_msg_id']  = q.message.message_id
        context.user_data['nsched_chat_id'] = q.message.chat.id
        await q.answer()
        try:
            await q.edit_message_text(
                "⏰ **Type exact time in HH:MM (24-hour WIB):**\n\nExample: `14:30`",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Failed to update time prompt: {e}")
        return

    elif data == "nsched_mention":
        d['mention'] = not d['mention']
        await q.answer(f"Tag All → {'Yes' if d['mention'] else 'No'}")

    elif data == "nsched_message":
        context.user_data['awaiting_nsched_message'] = True
        context.user_data['nsched_msg_id']  = q.message.message_id
        context.user_data['nsched_chat_id'] = q.message.chat.id
        await q.answer()
        try:
            await q.edit_message_text(
                "📝 **Type the broadcast message now:**\n\n"
                "_Your next message will be used as the announcement text._"
            )
        except Exception as e:
            logger.warning(f"Failed to update message prompt: {e}")
        return

    try:
        await q.edit_message_text(
            _nsched_text(d), reply_markup=_nsched_kb(d), parse_mode="Markdown"
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"nsched_callback edit error: {e}")


async def _handle_nsched_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    owner = context.user_data.get('nsched_owner')
    if owner and update.effective_user.id != owner:
        return False

    d = context.user_data.get('nsched_draft')
    if not d:
        return False

    text = update.message.text.strip() if update.message and update.message.text else ""
    if not text:
        return False

    consumed = False

    if context.user_data.get('awaiting_nsched_target'):
        context.user_data.pop('awaiting_nsched_target')
        normalized = text.strip()
        if normalized.lower() == 'all':
            d['chat_id'] = 'all'
            consumed = True
        elif normalized.lstrip('-').isdigit():
            d['chat_id'] = normalized
            consumed = True
        else:
            await update.message.reply_text(
                "❌ **Invalid target.**\n\n"
                "Type `all` to broadcast to all groups, or a numeric Group ID (e.g. `-1001234567890`).\n\n"
                "_Run /groupid inside the target group to get its ID._",
                parse_mode="Markdown"
            )
            context.user_data['awaiting_nsched_target'] = True  # keep waiting
            return True

    elif context.user_data.get('awaiting_nsched_time'):
        context.user_data.pop('awaiting_nsched_time')
        if re.match(r'^\d{1,2}:\d{2}$', text):
            h, m = map(int, text.split(":"))
            if 0 <= h <= 23 and 0 <= m <= 59:
                d['run_time'] = f"{h:02d}:{m:02d}"
                consumed = True
            else:
                await update.message.reply_text("❌ Invalid time.")
                context.user_data['awaiting_nsched_time'] = True
                return True
        else:
            await update.message.reply_text("❌ Format must be HH:MM")
            context.user_data['awaiting_nsched_time'] = True
            return True

    elif context.user_data.get('awaiting_nsched_message'):
        context.user_data.pop('awaiting_nsched_message')
        d['message'] = text
        consumed = True

    if consumed:
        try:
            await update.message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete user message: {e}")

        # Try to edit the original panel message back; fall back to new message
        msg_id  = context.user_data.get('nsched_msg_id')
        chat_id = context.user_data.get('nsched_chat_id') or update.effective_chat.id
        if msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=_nsched_text(d), reply_markup=_nsched_kb(d), parse_mode="Markdown"
                )
                return True
            except Exception as e:
                logger.debug(f"nsched restore edit failed: {e}")
        # Fallback: send a new panel and update stored msg_id
        m = await context.bot.send_message(
            chat_id, _nsched_text(d), reply_markup=_nsched_kb(d), parse_mode="Markdown"
        )
        context.user_data['nsched_msg_id'] = m.message_id
        return True

    return False


# ─────────────────────────────────────────────
# /allcommandtest — REAL COMMAND HEALTH CHECK
# ─────────────────────────────────────────────

async def all_command_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return await update.message.reply_text("❌ Super Owner only.")

    status_msg = await update.message.reply_text("🔍 Running dynamic command health check…")

    import cmd_system, cmd_user, cmd_trivia, cmd_admin as _self_module
    import cmd_command_nav, cmd_events, cmd_away, cmd_broadcast
    import cmd_manual, cmd_library, cmd_task, cmd_adminconfig, cmd_birthday, cmd_standup
    try:
        import cmd_system_help
    except ImportError:
        cmd_system_help = None

    module_registry = {
        "start":                   cmd_system,
        "about_command":           cmd_system,
        "what_did_i_miss":         cmd_system,
        "submit_feedback":         cmd_system,
        "ask_bot":                 cmd_system,
        "ask_ai":                  cmd_system,
        "global_tracker":          cmd_system,
        "unknown_command":         cmd_system,
        "help_command":            cmd_system_help,
        "command_nav":             cmd_command_nav,
        "eventpoll_command":       cmd_events,
        "listevent_command":       cmd_events,
        "away_command":            cmd_away,
        "broadcast_command":       cmd_broadcast,
        "manual_command":          cmd_manual,
        "library_command":         cmd_library,
        "task_command":            cmd_task,
        "mytask_command":          cmd_task,
        "standup_command":         cmd_standup,
        "admin_command":           cmd_adminconfig,
        "userconfig_command":      cmd_adminconfig,
        "birthday_config_command": cmd_birthday,
        "set_back":                cmd_user,
        "give_thanks":             cmd_user,
        "my_quota":                cmd_user,
        "my_star":                 cmd_user,
        "leaderboard_star":        cmd_user,
        "my_point":                cmd_trivia,
        "leaderboard_kp":          cmd_trivia,
        "trivia_config":           cmd_trivia,
        "force_trivia":            cmd_trivia,
        "force_super_trivia":      cmd_trivia,
        "cancel_trivia":           cmd_trivia,
        "end_trivia":              cmd_trivia,
        "admin_kp":                cmd_trivia,
        "update_info":             _self_module,
        "push_update":             _self_module,
        "update_change":           _self_module,
        "bot_config":              _self_module,
        "sched_config":            _self_module,
        "set_channel":             _self_module,
        "unset_channel":           _self_module,
        "check_group_id":          _self_module,
        "register_group":          _self_module,
        "attendance":              _self_module,
        "force_back":              _self_module,
        "group_tasks":             _self_module,
        "cancel_task":             _self_module,
        "feedback_list":           _self_module,
        "analyze_feedback":        _self_module,
        "all_command_test":        _self_module,
        "bot_status":              _self_module,
        "pause_bot":               _self_module,
        "restart_bot":             _self_module,
        "super_reset_req":         _self_module,
    }

    CATEGORIES = {
        "💬 General": [
            ("start",            "start"),
            ("help",             "help_command"),
            ("command",          "command_nav"),
            ("about",            "about_command"),
            ("update",           "update_info"),
            ("feedback",         "submit_feedback"),
            ("manual",           "manual_command"),
        ],
        "⭐ RAWWY Stars": [
            ("thanks",           "give_thanks"),
            ("mystar",           "my_star"),
            ("myquota",          "my_quota"),
            ("leaderboard_star", "leaderboard_star"),
        ],
        "🎮 Trivia & KP": [
            ("mypoint",          "my_point"),
            ("leaderboard_kp",   "leaderboard_kp"),
            ("triviaconfig",     "trivia_config"),
            ("forcetrivia",      "force_trivia"),
            ("forcesupertrivia", "force_super_trivia"),
            ("canceltrivia",     "cancel_trivia"),
            ("endtrivia",        "end_trivia"),
            ("triviaend",        "end_trivia"),
            ("admin_kp",         "admin_kp"),
        ],
        "📅 Events & Polls": [
            ("eventpoll",        "eventpoll_command"),
            ("listevent",        "listevent_command"),
        ],
        "📚 Library": [
            ("library",          "library_command"),
        ],
        "📋 Tasks": [
            ("task",             "task_command"),
            ("mytask",           "mytask_command"),
            ("standup",          "standup_command"),
            ("grouptasks",       "group_tasks"),
            ("canceltask",       "cancel_task"),
        ],
        "🏖️ Away Status": [
            ("away",             "away_command"),
            ("back",             "set_back"),
        ],
        "🤖 AI Assistant": [
            ("ai",               "ask_ai"),
            ("ask",              "ask_bot"),
            ("wdim",             "what_did_i_miss"),
        ],
        "📢 Broadcast": [
            ("broadcast",        "broadcast_command"),
        ],
        "⚙️ Admin Config": [
            ("botconfig",        "bot_config"),
            ("schedconfig",      "sched_config"),
            ("triviaconfig",     "trivia_config"),
            ("setchannel",       "set_channel"),
            ("unsetchannel",     "unset_channel"),
            ("groupid",          "check_group_id"),
            ("registergroup",    "register_group"),
            ("userconfig",       "userconfig_command"),
            ("birthdayconfig",   "birthday_config_command"),
            ("admin",            "admin_command"),
            ("attendance",       "attendance"),
            ("forceback",        "force_back"),
            ("grouptasks",       "group_tasks"),
            ("canceltask",       "cancel_task"),
            ("feedbacklist",     "feedback_list"),
            ("analyze_feedback", "analyze_feedback"),
        ],
        "👑 Super Owner": [
            ("updatechange",     "update_change"),
            ("pushupdate",       "push_update"),
            ("botstatus",        "bot_status"),
            ("pause",            "pause_bot"),
            ("restart",          "restart_bot"),
            ("super_reset",      "super_reset_req"),
            ("allcommandtest",   "all_command_test"),
        ],
    }

    lines = []
    total_ok = total_fail = 0

    for cat, cmds in CATEGORIES.items():
        cat_lines = []
        for cmd, func_name in cmds:
            module = module_registry.get(func_name)
            if module is None:
                cat_lines.append(f"  🚫 /{cmd} — `{func_name}` not in registry")
                total_fail += 1
            elif not hasattr(module, func_name):
                cat_lines.append(f"  ❌ /{cmd} — `{func_name}` missing from `{module.__name__}`")
                total_fail += 1
            elif not callable(getattr(module, func_name)):
                cat_lines.append(f"  ❌ /{cmd} — `{func_name}` not callable")
                total_fail += 1
            else:
                cat_lines.append(f"  ✅ /{cmd}")
                total_ok += 1
        lines.append(f"\n*{cat}*")
        lines.extend(cat_lines)

    header = (
        f"🧪 **DYNAMIC COMMAND HEALTH REPORT**\n"
        f"──────────────────────────────────────\n"
        f"✅ OK: {total_ok}  |  ❌ Failed: {total_fail}  |  🗂️ Total: {total_ok + total_fail}\n"
    )

    try:
        await status_msg.delete()
    except Exception as e:
        logger.debug(f"Failed to delete status message: {e}")

    await send_md(context, update.effective_user.id, header + "\n".join(lines))


# ─────────────────────────────────────────────
# RESTORED MISSING COMMANDS (WITH ASYNC RETRY FOR AI)
# ─────────────────────────────────────────────

async def _generate_content_with_retry(client, model_name, contents, max_retries=3, base_delay=5):
    """
    Groq-primary AI call with Gemini fallback.
    `client` and `model_name` params kept for API compatibility but are unused;
    providers and models are selected internally.
    """
    from cmd_system import _generate_content_with_retry as _sys_retry
    return await _sys_retry(None, contents, max_retries=max_retries, base_delay=base_delay)

async def analyze_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        return await update.message.reply_text("❌ No AI API key configured. Set GROQ_API_KEY in environment variables.")

    arg = " ".join(context.args).strip() if context.args else ""
    try:
        async with pool.acquire() as conn:
            if "to" in arg.lower():
                st, en = [p.strip() for p in arg.lower().split("to", 1)]
                s_dt   = datetime.datetime.strptime(st, "%m/%d/%Y").date()
                e_dt   = datetime.datetime.strptime(en, "%m/%d/%Y").date()
                reports = await conn.fetch(
                    "SELECT username, report, created_at FROM bug_reports "
                    "WHERE created_at::date >= $1 AND created_at::date <= $2 ORDER BY created_at ASC",
                    s_dt, e_dt
                )
                range_desc = f"from {st} to {en}"
            else:
                reports = await conn.fetch(
                    "SELECT username, report, created_at FROM bug_reports "
                    "WHERE created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at ASC"
                )
                range_desc = "last 7 days"
    except Exception:
        return await update.message.reply_text("❌ Date error. Use: `MM/DD/YYYY to MM/DD/YYYY`")

    if not reports:
        return await update.message.reply_text(f"✅ No feedback in the {range_desc}.")

    temp     = await update.message.reply_text("⏳ Generating AI feedback analysis…")
    raw_data = "\n".join([f"• @{r['username']}: {r['report']}" for r in reports])
    ai_prompt = (
        f"Analyze this team feedback ({range_desc}).\n"
        "Output strictly this format. Be concise and strategic.\n\n"
        "### 🚨 Summary\n[Summary]\n\n"
        "### 💡 Suggestion\n[Enhancements]\n\n"
        "### 🚀 Next Step\n[Actionable steps]\n\n"
        f"Data:\n{raw_data}"
    )
    try:
        response = await _generate_content_with_retry(None, None, ai_prompt)
        await temp.delete()
        await send_md(
            context, update.effective_user.id,
            f"✅ 🤖 **AI Feedback Analysis ({range_desc})**\n\n{response.text}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Analysis failed: {e}")


async def unpin_event(context):
    try:
        await context.bot.unpin_chat_message(
            chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id']
        )
    except Exception as e:
        logger.warning(f"Failed to unpin event message: {e}")


async def event_reminder(context):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetch(
            'SELECT username FROM rsvps WHERE event_id=$1 AND status=$2',
            context.job.data['id'], 'Going'
        )
    if r:
        await context.bot.send_message(
            context.job.chat_id,
            f"⏰ Event **{context.job.data['title']}** starting soon!\n" +
            " ".join([f"@{x['username']}" for x in r]),
            parse_mode="Markdown"
        )


async def task_reminder(context):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if status != 'Completed':
        await context.bot.send_message(
            context.job.chat_id,
            "⚠️ **Task Reminder:** Deadline approaching in 10 minutes!",
            parse_mode="Markdown"
        )


async def auto_return_away(context):
    pool     = context.bot_data.get('db_pool')
    username = context.job.data['username']
    async with pool.acquire() as conn:
        uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
    import cmd_user
    msg = await cmd_user.process_return(username, pool, context.bot)
    await log_action(pool, uid or 0, context.job.data['chat_id'], "Away Status", "Auto-Returned", f"@{username}")
    if uid:
        try:
            await context.bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception as e:
            logger.debug(f"Failed to notify user of auto-return: {e}")


async def poll_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(
            context.job.data['chat_id'],
            f"⏳ **Poll Reminder:** *{context.job.data['q']}* ends in 15 minutes!",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Failed to send poll reminder: {e}")


async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        e_id = int(context.args[0])
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/cancelevent [ID]`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
        if not ev:
            return await context.bot.send_message(update.effective_user.id, "❌ Event not found.")
        await conn.execute('DELETE FROM events WHERE id=$1', e_id)
    for j in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"):
        j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"):
        j.schedule_removal()
    try:
        await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
    except Exception as e:
        logger.warning(f"Failed to unpin cancelled event: {e}")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Cancelled", "Success", f"#{e_id} by @{update.effective_user.username}")
    await context.bot.send_message(update.effective_user.id, "✅ Event cancelled and unpinned.")


async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool     = context.bot_data.get('db_pool')
    is_adm   = await is_bot_admin(username, pool)
    try:
        t_id = int(context.args[0])
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/canceltask [ID]`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task:
            return await context.bot.send_message(update.effective_user.id, "❌ Task not found.")
        if task['assigned_by'] != username and not is_adm:
            return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await context.bot.send_message(update.effective_user.id, "✅ Task deleted.")


async def cancel_poll_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.poll:
        return await context.bot.send_message(
            update.effective_user.id,
            "❌ Reply to a live poll message with `/cancelpoll`.",
            parse_mode="Markdown"
        )
    try:
        await context.bot.stop_poll(update.effective_chat.id, update.message.reply_to_message.message_id)
        await context.bot.send_message(update.effective_user.id, "✅ Poll stopped.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")


async def check_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool   = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    target = context.args[0].lower().replace("@", "") if context.args else 'all'
    async with pool.acquire() as conn:
        if target == 'all':
            recs = await conn.fetch('SELECT username, gemini_quota FROM users ORDER BY gemini_quota ASC')
            msg  = "🤖 **AI Limits**\n" + "\n".join([f"• @{r['username']}: {r['gemini_quota']}" for r in recs])
        else:
            r   = await conn.fetchval('SELECT gemini_quota FROM users WHERE username=$1', target)
            msg = f"✅ @{target} — AI queries left: `{r}`" if r is not None else "❌ User not found."
    await context.bot.send_message(update.effective_user.id, msg[:4000], parse_mode="Markdown")


async def admin_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 2)]
        t     = parts[0].replace("@", "").lower()
        act   = parts[1].lower()
        amt   = int(parts[2])
    except Exception:
        return await context.bot.send_message(
            update.effective_user.id,
            "❌ Format: `/admin_limit @user , set|add|sub , amount`",
            parse_mode="Markdown"
        )
    async with pool.acquire() as conn:
        if act == "set":
            await conn.execute("UPDATE users SET gemini_quota=$1 WHERE username=$2", amt, t)
        elif act == "add":
            await conn.execute("UPDATE users SET gemini_quota=gemini_quota+$1 WHERE username=$2", amt, t)
        elif act == "sub":
            await conn.execute("UPDATE users SET gemini_quota=GREATEST(0,gemini_quota-$1) WHERE username=$2", amt, t)
    await context.bot.send_message(update.effective_user.id, f"✅ AI limit for @{t} updated.")


async def check_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool   = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    target = context.args[0].lower().replace("@", "") if context.args else 'all'
    async with pool.acquire() as conn:
        if target == 'all':
            recs = await conn.fetch('SELECT username, quota FROM kudos ORDER BY quota DESC')
            msg  = "⭐ **Star Quotas**\n" + "\n".join([f"• @{r['username']}: {r['quota']}" for r in recs])
        else:
            r   = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', target)
            msg = f"✅ @{target} — Stars quota left: `{r}`" if r is not None else "❌ User not found."
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 3)]
        t     = parts[0].replace("@", "").lower()
        field = parts[1].lower()
        act   = parts[2].lower()
        amt   = int(parts[3])
        col   = {'monthly': 'monthly_points', 'total': 'all_time_points', 'quota': 'quota'}.get(field, 'quota')
    except Exception:
        return await context.bot.send_message(
            update.effective_user.id,
            "❌ Format: `/admin_stars @user , quota|monthly|total , set|add|sub , amount`",
            parse_mode="Markdown"
        )
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
        if act == "add":
            await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, t)
        elif act == "sub":
            await conn.execute(f'UPDATE kudos SET {col}=GREATEST(0,{col}-$1) WHERE username=$2', amt, t)
        else:
            await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, t)
    await context.bot.send_message(update.effective_user.id, f"✅ Stars for @{t} updated.")


async def _validate_bday(b: str) -> bool:
    """Validate MM/DD format."""
    import re as _re
    if not _re.match(r'^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])$', b):
        return False
    return True


async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u = parts[0].replace("@", "").lower()
        b = parts[1]
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/addbday @user , MM/DD`", parse_mode="Markdown")
    if not await _validate_bday(b):
        return await context.bot.send_message(update.effective_user.id, f"❌ Invalid date format `{b}`. Use MM/DD (e.g. `06/22`).", parse_mode="Markdown")
    async with pool.acquire() as conn:
        exist = await conn.fetchval('SELECT bday FROM birthdays WHERE lower(username)=$1', u)
        if exist:
            return await context.bot.send_message(update.effective_user.id, f"❌ @{u} already registered as `{exist}`. Use `/editbday` to change it.", parse_mode="Markdown")
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
    await context.bot.send_message(update.effective_user.id, f"✅ Birthday for @{u} logged as `{b}`.", parse_mode="Markdown")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Birthday", "Added", f"@{u} → {b}")


async def edit_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u = parts[0].replace("@", "").lower()
        b = parts[1]
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/editbday @user , MM/DD`", parse_mode="Markdown")
    if not await _validate_bday(b):
        return await context.bot.send_message(update.effective_user.id, f"❌ Invalid date format `{b}`. Use MM/DD (e.g. `06/22`).", parse_mode="Markdown")
    async with pool.acquire() as conn:
        res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE lower(username)=$2', b, u)
    if res == "UPDATE 0":
        return await context.bot.send_message(update.effective_user.id, f"❌ @{u} not found in birthday registry. Use `/addbday` first.", parse_mode="Markdown")
    await context.bot.send_message(update.effective_user.id, f"✅ Birthday updated: @{u} → `{b}`.", parse_mode="Markdown")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Birthday", "Updated", f"@{u} → {b}")


async def del_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        u = context.args[0].replace("@", "").lower()
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/delbday @user`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", u)
    await context.bot.send_message(update.effective_user.id, f"✅ Birthday for @{u} removed.")


async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    async with pool.acquire() as conn:
        b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    if not b:
        return await context.bot.send_message(update.effective_user.id, "🎂 No birthdays registered yet.")
    msg = "🎂 **Birthday Registry**\n\n" + "\n".join([f"• @{x['username']}: `{x['bday']}`" for x in b])
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


async def bulk_add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bulk-add birthdays. Format: /bulkaddbday @user1 MM/DD , @user2 MM/DD , @user3 MM/DD"""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    if not context.args:
        return await context.bot.send_message(
            update.effective_user.id,
            "❌ **Usage:** `/bulkaddbday @user1 MM/DD , @user2 MM/DD , @user3 MM/DD`\n\n"
            "Each entry is `@username MM/DD`, separated by commas.\n"
            "Example: `/bulkaddbday @alice 06/15 , @bob 12/01 , @charlie 03/22`",
            parse_mode="Markdown"
        )

    raw = " ".join(context.args)
    entries = [e.strip() for e in raw.split(",") if e.strip()]

    added, skipped, errors = [], [], []

    async with pool.acquire() as conn:
        for entry in entries:
            parts = entry.split()
            if len(parts) < 2:
                errors.append(f"`{entry}` — bad format")
                continue
            u = parts[0].replace("@", "").lower()
            b = parts[1]
            if not await _validate_bday(b):
                errors.append(f"@{u} — invalid date `{b}`")
                continue
            exist = await conn.fetchval("SELECT bday FROM birthdays WHERE lower(username)=$1", u)
            if exist:
                skipped.append(f"@{u} (already `{exist}`)")
                continue
            await conn.execute("INSERT INTO birthdays (username, bday) VALUES ($1, $2)", u, b)
            added.append(f"@{u} → `{b}`")
            await log_action(pool, update.effective_user.id, update.effective_chat.id, "Birthday", "Bulk Added", f"@{u} → {b}")

    report = f"🎂 **Bulk Birthday Import**\n\n"
    if added:
        report += f"✅ **Added ({len(added)}):**\n" + "\n".join(f"  • {x}" for x in added) + "\n\n"
    if skipped:
        report += f"⚠️ **Skipped — already exist ({len(skipped)}):**\n" + "\n".join(f"  • {x}" for x in skipped) + "\n\n"
    if errors:
        report += f"❌ **Errors ({len(errors)}):**\n" + "\n".join(f"  • {x}" for x in errors) + "\n\n"
    if not added and not skipped and not errors:
        report += "_Nothing to process._"

    await context.bot.send_message(update.effective_user.id, report, parse_mode="Markdown")


async def bulk_del_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bulk-delete birthdays. Format: /bulkdelbday @user1 , @user2 , @user3"""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    if not context.args:
        return await context.bot.send_message(
            update.effective_user.id,
            "❌ **Usage:** `/bulkdelbday @user1 , @user2 , @user3`\n\n"
            "Separate usernames with commas.\n"
            "Example: `/bulkdelbday @alice , @bob , @charlie`",
            parse_mode="Markdown"
        )

    raw = " ".join(context.args)
    usernames = [u.strip().replace("@", "").lower() for u in raw.split(",") if u.strip()]

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
            await log_action(pool, update.effective_user.id, update.effective_chat.id, "Birthday", "Bulk Deleted", f"@{u}")

    report = f"🗑️ **Bulk Birthday Delete**\n\n"
    if removed:
        report += f"✅ **Removed ({len(removed)}):**\n" + "\n".join(f"  • {x}" for x in removed) + "\n\n"
    if not_found:
        report += f"⚠️ **Not found ({len(not_found)}):**\n" + "\n".join(f"  • {x}" for x in not_found) + "\n\n"
    if not removed and not not_found:
        report += "_Nothing to process._"

    await context.bot.send_message(update.effective_user.id, report, parse_mode="Markdown")


async def feedback_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            "SELECT username, report, created_at FROM bug_reports "
            "WHERE created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at ASC"
        )
    if not recs:
        return await context.bot.send_message(update.effective_user.id, "🪹 No feedback in the last 7 days.")
    msg = "📋 **Feedback — Last 7 Days**\n\n"
    for r in recs:
        ts   = r['created_at'].astimezone(WIB).strftime('%m/%d %H:%M')
        msg += f"• `[{ts}]` @{r['username']}: {r['report']}\n"
    await send_md(context, update.effective_user.id, msg)


async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        target_raw = parts[0]
        message    = parts[1]
    except Exception:
        return await context.bot.send_message(
            update.effective_user.id,
            "❌ Format: `/announce all , Your message here`",
            parse_mode="Markdown"
        )
    async with pool.acquire() as conn:
        a_id    = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", message)
        targets = await conn.fetch("SELECT chat_id FROM active_groups") if target_raw.lower() == "all" else [{"chat_id": int(target_raw)}]
        for t in targets:
            try:
                m = await context.bot.send_message(
                    t['chat_id'],
                    f"📢 **[RAWWY] NUKHBA BROADCAST**\n\n{message}",
                    parse_mode="Markdown"
                )
                await conn.execute(
                    "INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1,$2,$3)",
                    a_id, t['chat_id'], m.message_id
                )
            except Exception as e:
                logger.warning(f"Broadcast failed to {t['chat_id']}: {e}")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Success", f"ID#{a_id} by @{update.effective_user.username} → {target_raw}")
    await context.bot.send_message(update.effective_user.id, "✅ Broadcast sent.")


async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        a_id  = int(parts[0])
        text  = parts[1]
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/editannounce [ID] , New text`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try:
                await context.bot.edit_message_text(
                    f"📢 **[RAWWY] NUKHBA BROADCAST**\n\n{text}",
                    chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"Edit broadcast failed for {m['chat_id']}: {e}")
        await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", text, a_id)
    await context.bot.send_message(update.effective_user.id, "✅ Announcement updated.")


async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        a_id = int(context.args[0])
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/delannounce [ID]`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try:
                await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
            except Exception as e:
                logger.warning(f"Delete broadcast failed for {m['chat_id']}: {e}")
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, "✅ Announcement deleted.")


async def register_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually register the current group into active_groups. Run this if the bot was
    added before the tracking fix or after a database wipe."""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return await context.bot.send_message(
            update.effective_user.id,
            "❌ Run this command **inside the group** you want to register.",
            parse_mode="Markdown"
        )
    async with pool.acquire() as conn:
        await conn.execute(
            'INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2',
            chat.id, chat.title
        )
    # Also clear seen_groups cache so global_tracker re-evaluates
    context.bot_data.get('seen_groups', set()).discard(chat.id)
    await context.bot.send_message(
        update.effective_user.id,
        f"✅ **Group Registered!**\n\n🏠 `{chat.title}`\n🆔 `{chat.id}`",
        parse_mode="Markdown"
    )
    await log_action(pool, update.effective_user.id, chat.id, "System", "Group Registered", f"Manual register by @{update.effective_user.username}")


async def check_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        await context.bot.send_message(
            update.effective_chat.id,
            f"📌 **Group Info**\nTitle: `{update.effective_chat.title}`\nID: `{update.effective_chat.id}`",
            parse_mode="Markdown"
        )
    else:
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
        msg = ("📈 **Tracked Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` — {g['title']}" for g in groups])) if groups else "❌ No active groups tracked yet."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_super(update.effective_user.username):
        return
    async with pool.acquire() as conn:
        g = await conn.fetch("SELECT chat_id, title FROM active_groups")
        u = await conn.fetchval("SELECT COUNT(*) FROM users")
        t = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Pending'")
        l = await conn.fetchval("SELECT COUNT(*) FROM library")
        b = await conn.fetchval("SELECT COUNT(*) FROM birthdays")
        ver = await conn.fetchval("SELECT version FROM bot_version ORDER BY id DESC LIMIT 1") or "1.0"
    await context.bot.send_message(
        update.effective_user.id,
        f"📊 **NUKHBA BOT STATUS**\n"
        f"──────────────────────────────\n"
        f"📦 Version: `{ver}`\n"
        f"👥 Users tracked: `{u}`\n"
        f"📋 Pending tasks: `{t}`\n"
        f"📚 Library assets: `{l}`\n"
        f"🎂 Birthdays: `{b}`\n"
        f"🏠 Active groups: `{len(g)}`",
        parse_mode="Markdown"
    )


async def force_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        target = context.args[0].replace("@", "").lower()
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Usage: `/forceback @user`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', target)
        if not status:
            return await context.bot.send_message(update.effective_user.id, f"❌ @{target} is not away.")
    for j in context.job_queue.get_jobs_by_name(f"away_{target}"):
        j.schedule_removal()
    import cmd_user
    msg = await cmd_user.process_return(target, pool, context.bot)
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Force Removed", f"@{update.effective_user.username} forced @{target} back")
    async with pool.acquire() as conn:
        uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", target)
    if uid:
        try:
            await context.bot.send_message(uid, f"⚠️ An admin removed your Away status.\n\n{msg}", parse_mode="Markdown")
        except Exception as e:
            logger.debug(f"Could not notify user of forced return: {e}")
    await context.bot.send_message(update.effective_user.id, f"✅ @{target} forced back to Available.")


async def attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        aways = await conn.fetch('SELECT username, end_time FROM away_status')
    msg = "📊 **Team Attendance**\n\n"
    if aways:
        msg += "🔴 **Currently Away:**\n"
        for a in aways:
            rem = a['end_time'].astimezone(WIB) - now
            d   = rem.days
            h   = rem.seconds // 3600
            m   = (rem.seconds % 3600) // 60
            msg += f"• @{a['username']} — returns in {f'{d}d {h}h {m}m' if d > 0 else f'{h}h {m}m'}\n"
        msg += "\n🟢 *Everyone else is Available.*"
    else:
        msg += "🟢 Everyone is currently Available!"
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


async def group_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool     = context.bot_data.get('db_pool')
    username = update.effective_user.username or str(update.effective_user.id)
    is_adm   = await is_bot_admin(username, pool)
    if not is_adm:
        return
    now      = datetime.datetime.now(WIB)
    chat_id  = update.effective_chat.id
    in_group = update.effective_chat.type in ('group', 'supergroup')

    async with pool.acquire() as conn:
        if in_group and not is_adm:
            # Non-admin in group: only their assigned tasks
            pending = await conn.fetch(
                "SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks "
                "WHERE status='Pending' AND (assignee=$1 OR assigned_by=$1) ORDER BY deadline",
                username
            )
            completed = await conn.fetch(
                "SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks "
                "WHERE status='Completed' AND (assignee=$1 OR assigned_by=$1) "
                "ORDER BY deadline DESC LIMIT 7", username
            )
        else:
            # Admin (any context) or DM: see all tasks
            pending = await conn.fetch(
                "SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks "
                "WHERE status='Pending' ORDER BY deadline"
            )
            completed = await conn.fetch(
                "SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks "
                "WHERE status='Completed' ORDER BY deadline DESC LIMIT 7"
            )

    lines = ["📋 **Active Tasks**\n"]
    if not pending:
        lines.append("✅ No pending tasks — all clear!\n")
    else:
        for t in pending:
            dl = t['deadline']
            if dl.tzinfo is None:
                dl = WIB.localize(dl)
            secs = (dl - now).total_seconds()
            if secs <= 0:
                status = "⚠️ **OVERDUE**"
            elif secs < 3600:
                status = f"⏳ {int(secs/60)}m left"
            elif secs < 86400:
                h, m = divmod(int(secs/60), 60)
                status = f"⏳ {h}h {m}m left"
            else:
                status = f"⏳ {int(secs/86400)}d left"
            lines.append(
                f"🔹 `#{t['id']}` **{t['task_desc'][:40]}**\n"
                f"   👤 @{t['assignee']} ← @{t['assigned_by']} | {status}"
            )

    if completed:
        lines.append("\n📂 **Last 7 Completed Tasks**\n")
        for t in completed:
            lines.append(
                f"✅ `#{t['id']}` {t['task_desc'][:40]}\n"
                f"   👤 @{t['assignee']} ← @{t['assigned_by']}"
            )

    msg = "\n".join(lines)
    dest = update.effective_user.id
    await context.bot.send_message(dest, msg, parse_mode="Markdown")


def _super_reset_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☢️ WIPE ALL DATA ☢️", callback_data="sup_reset_all")],
        [
            InlineKeyboardButton("⭐ Stars", callback_data="sup_reset_stars"),
            InlineKeyboardButton("🎂 Birthdays", callback_data="sup_reset_birthdays"),
            InlineKeyboardButton("📅 Events", callback_data="sup_reset_events")
        ],
        [
            InlineKeyboardButton("📊 Polls", callback_data="sup_reset_polls"),
            InlineKeyboardButton("📚 Library", callback_data="sup_reset_library"),
            InlineKeyboardButton("⚡ Tasks", callback_data="sup_reset_tasks")
        ],
        [
            InlineKeyboardButton("🏖️ Away", callback_data="sup_reset_away"),
            InlineKeyboardButton("📍 Channels", callback_data="sup_reset_channels"),
            InlineKeyboardButton("🗓️ Schedules", callback_data="sup_reset_schedules")
        ],
        [
            InlineKeyboardButton("💡 Feedback", callback_data="sup_reset_feedback"),
            InlineKeyboardButton("📈 Stats", callback_data="sup_reset_stats"),
            InlineKeyboardButton("🧠 Trivia", callback_data="sup_reset_trivia")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="sup_cancel")]
    ])


async def super_reset_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    await context.bot.send_message(
        update.effective_user.id,
        "☢️ **FACTORY WIPE MENU**\n\nSelect a database section to wipe. *This action is destructive and permanent.*",
        reply_markup=_super_reset_kb(),
        parse_mode="Markdown"
    )


async def request_super_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, label: str):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    try:
        t = context.args[0].replace("@", "").lower()
    except Exception:
        return await context.bot.send_message(update.effective_user.id, f"❌ Usage: `/{action} @username`", parse_mode="Markdown")
    await context.bot.send_message(
        update.effective_user.id,
        f"⚠️ **Confirm:** {label} for @{t}?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm", callback_data=f"sup_{action}_{t}"),
            InlineKeyboardButton("❌ Cancel",  callback_data="sup_cancel")
        ]])
    )


async def add_admin_req(u, c):
    await request_super_action(u, c, "addadmin", "Promote to Admin")


async def del_admin_req(u, c):
    await request_super_action(u, c, "deladmin", "Demote from Admin")


async def remove_member_req(u, c):
    await request_super_action(u, c, "removemember", "Offboard Member")


async def super_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    pool = context.bot_data.get('db_pool')
    if not await is_super(q.from_user.username):
        return await q.answer("❌ Super Owner only.", show_alert=True)
    if q.data == "sup_cancel":
        await q.answer("Cancelled.")
        return await q.edit_message_text("❌ Action cancelled.")
    parts = q.data.split("_")
    act   = parts[1]
    t     = parts[2] if len(parts) > 2 else ""
    async with pool.acquire() as conn:
        if act == "addadmin":
            await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
            await q.edit_message_text(f"✅ @{t} promoted to Admin.")
        elif act == "deladmin":
            await conn.execute('DELETE FROM bot_admins WHERE username=$1', t)
            await q.edit_message_text(f"✅ @{t} demoted from Admin.")
        elif act == "removemember":
            await conn.execute('DELETE FROM kudos WHERE username=$1', t)
            await conn.execute('DELETE FROM birthdays WHERE username=$1', t)
            await conn.execute('INSERT INTO graveyard (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
            await q.edit_message_text(f"✅ @{t} offboarded and moved to Graveyard.")
        elif act == "reset":
            try:
                if t in ["stars", "all"]: await conn.execute("TRUNCATE kudos CASCADE")
                if t in ["birthdays", "all"]: await conn.execute("TRUNCATE birthdays CASCADE")
                if t in ["events", "all"]: await conn.execute("TRUNCATE events, rsvps CASCADE")
                if t in ["polls", "all"]: await conn.execute("TRUNCATE poll_drafts, active_polls CASCADE")
                if t in ["library", "all"]: await conn.execute("TRUNCATE library CASCADE")
                if t in ["tasks", "all"]: await conn.execute("TRUNCATE tasks CASCADE")
                if t in ["away", "all"]: await conn.execute("TRUNCATE away_status, away_mentions CASCADE")
                if t in ["channels", "all"]:
                    await conn.execute("DELETE FROM config WHERE key IN ('bday_channel', 'stars_channel', 'feedback_channel')")
                    await conn.execute("DELETE FROM trivia_config WHERE key='target_chat_id'")
                if t in ["schedules", "all"]: await conn.execute("TRUNCATE scheduled_announcements CASCADE")
                if t in ["feedback", "all"]: await conn.execute("TRUNCATE bug_reports, feedback_drafts CASCADE")
                # ⚠️ SAFE STATS WIPE: preserve active_groups so the bot still knows its registered
                # chats — wiping active_groups would silently break all group-targeted features
                # (birthday cron, trivia posts, announcements) until /registergroup is re-run.
                if t in ["stats", "all"]: await conn.execute("TRUNCATE bot_stats, chat_history CASCADE")
                if t in ["trivia", "all"]:
                    await conn.execute("TRUNCATE active_trivia, trivia_scores CASCADE")
                    # Reset trivia_config to sane defaults rather than calling a non-existent helper
                    await conn.execute("""
                        UPDATE trivia_config SET value = CASE
                            WHEN key = 'enabled'        THEN 'true'
                            WHEN key = 'interval_hours' THEN '24'
                            WHEN key = 'duration_secs'  THEN '30'
                            WHEN key = 'points_normal'  THEN '5'
                            WHEN key = 'points_super'   THEN '10'
                            WHEN key = 'reset_day'      THEN '1'
                            ELSE value
                        END
                    """)
                # ✅ bot_admins, config (non-channel keys), users, graveyard are intentionally
                # NOT wiped — admin accounts and core config must survive a data reset.
                await q.edit_message_text(f"✅ Wiped `{t}` data. Admin accounts and core config preserved.")
            except Exception as e:
                await q.edit_message_text(f"❌ Error wiping `{t}`: {e}")


async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT username FROM bot_admins ORDER BY username')
    msg = "👑 **Admin List**\n\n" + ("\n".join([f"• @{r['username']}" for r in recs]) if recs else "_No admins registered._")
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


async def graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            # Ensure table exists with removed_at column (idempotent)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS graveyard (
                    username VARCHAR(100) PRIMARY KEY,
                    removed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            # Migrate: add removed_at if it doesn't exist (fixes legacy tables)
            await conn.execute("""
                ALTER TABLE graveyard ADD COLUMN IF NOT EXISTS
                removed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            """)
            recs = await conn.fetch('SELECT username, removed_at FROM graveyard ORDER BY removed_at DESC')

        if not recs:
            msg = "🪦 **Graveyard — Offboarded Members**\n\n_No members have been offboarded yet. The graveyard is empty._"
        else:
            lines = []
            for r in recs:
                try:
                    date_str = r['removed_at'].astimezone(WIB).strftime('%d %b %Y')
                except Exception:
                    date_str = "Unknown date"
                lines.append(f"• @{r['username']} — removed {date_str}")
            count = len(lines)
            msg = f"🪦 **Graveyard — Offboarded Members** ({count})\n\n" + "\n".join(lines)

        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Graveyard error: {e}")
        await context.bot.send_message(update.effective_user.id, "❌ Something went wrong loading the graveyard. Please try again.")


async def pause_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config (key, value) VALUES ('status', 'paused') ON CONFLICT (key) DO UPDATE SET value='paused'"
        )
    await context.bot.send_message(update.effective_user.id, "⏸️ **Bot paused.** Trivia and scheduled posts will not fire.", parse_mode="Markdown")


async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config (key, value) VALUES ('status', 'active') ON CONFLICT (key) DO UPDATE SET value='active'"
        )
    await context.bot.send_message(update.effective_user.id, "▶️ **Bot resumed and active.**", parse_mode="Markdown")


async def process_schedules(context: ContextTypes.DEFAULT_TYPE):
    """
    Cron: check and fire any scheduled announcements (runs every 30s).
    Frequencies: once | daily | weekday | weekly
    run_time format:
      once/daily/weekday/weekly → 'HH:MM'
      scheduled_date (for once) → 'MM/DD/YYYY'
    """
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    now     = datetime.datetime.now(WIB)
    weekday = now.weekday()  # 0=Mon … 6=Sun

    # Ensure last_run column exists (migration)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "ALTER TABLE scheduled_announcements ADD COLUMN IF NOT EXISTS last_run "
                "TIMESTAMP WITH TIME ZONE"
            )
    except Exception:
        pass

    async with pool.acquire() as conn:
        schedules = await conn.fetch("SELECT * FROM scheduled_announcements")

    for s in schedules:
        should_run = False
        freq  = s['frequency']
        t_str = (s['run_time'] or '').strip()

        try:
            # All recurring types store run_time as 'HH:MM'
            h, m = map(int, t_str.split(':'))
            time_match = (now.hour == h and now.minute == m)
            try:
                last_run = s['last_run']
            except (KeyError, IndexError):
                last_run = None
            ran_today  = (last_run and last_run.astimezone(WIB).date() == now.date())

            if freq == 'once':
                # For once: fire at the scheduled_at datetime
                try:
                    sched_at = s['scheduled_at']
                except (KeyError, IndexError):
                    sched_at = None
                if sched_at and not last_run:
                    sched_wib = sched_at.astimezone(WIB)
                    if now >= sched_wib:
                        should_run = True

            elif freq == 'daily':
                if time_match and not ran_today:
                    should_run = True

            elif freq == 'weekday':
                # Mon–Fri only (weekday 0–4)
                if weekday <= 4 and time_match and not ran_today:
                    should_run = True

            elif freq == 'weekly':
                # Fire every Monday at the set time
                if weekday == 0 and time_match and not ran_today:
                    should_run = True

        except Exception as e:
            logger.warning(f"Schedule #{s['id']} parse error: {e}")
            continue

        if not should_run:
            continue

        # Build message and targets
        async with pool.acquire() as conn:
            if s['chat_id'] == 'all':
                groups = await conn.fetch(
                    "SELECT chat_id FROM group_settings UNION "
                    "SELECT chat_id FROM active_groups"
                )
                targets = list({g['chat_id'] for g in groups})
            else:
                try:
                    targets = [int(s['chat_id'])]
                except (ValueError, TypeError):
                    continue

            mention_line = ""
            if s['mention']:
                users = await conn.fetch(
                    "SELECT username FROM users WHERE username IS NOT NULL"
                )
                mention_line = " ".join(f"@{u['username']}" for u in users)

        raw_msg = s['message'] or ""
        full_msg = (mention_line + "\n\n" + raw_msg) if mention_line else raw_msg

        for t in targets:
            try:
                await context.bot.send_message(t, full_msg, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Broadcast #{s['id']} to {t} failed: {e}")

        # Mark as run
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scheduled_announcements SET last_run=$1 WHERE id=$2",
                now, s['id']
            )
            # Delete once-schedules after firing
            if freq == 'once':
                await conn.execute(
                    "DELETE FROM scheduled_announcements WHERE id=$1", s['id']
                )
        logger.info(f"Broadcast schedule #{s['id']} fired ({freq})")


async def list_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    async with pool.acquire() as conn:
        recs = await conn.fetch("SELECT * FROM scheduled_announcements ORDER BY id ASC")
    if not recs:
        return await context.bot.send_message(update.effective_user.id, "❌ No active schedules.")
    out = "🗓️ **Active Schedules**\n\n"
    for r in recs:
        out += (
            f"🔹 `ID: {r['id']}` | **{r['frequency'].upper()}** | ⏰ {r['run_time']}\n"
            f"   Target: {r['chat_id']} | Tag All: {r['mention']}\n"
            f"   📝 {r['message'][:50]}{'…' if len(r['message']) > 50 else ''}\n\n"
        )
    await send_md(context, update.effective_user.id, out)


async def del_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        s_id = int(context.args[0])
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/delschedule [ID]`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM scheduled_announcements WHERE id=$1", s_id)
        if res == "DELETE 0":
            return await context.bot.send_message(update.effective_user.id, "❌ Schedule ID not found.")
    await context.bot.send_message(update.effective_user.id, f"✅ Schedule `{s_id}` deleted.", parse_mode="Markdown")
