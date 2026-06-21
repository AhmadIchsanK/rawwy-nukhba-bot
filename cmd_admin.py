import datetime
import logging
import json
import re
import asyncio
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, delete_cmd, log_action

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

async def send_md(context, chat_id, text):
    """Send long markdown text in safe chunks."""
    chunk = ""
    for line in text.split('\n'):
        if len(chunk) + len(line) + 1 > 3800:
            try:
                await context.bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(chat_id, chunk)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        try:
            await context.bot.send_message(chat_id, chunk, parse_mode="Markdown")
        except Exception:
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
                id SERIAL PRIMARY KEY,
                chat_id TEXT,
                frequency TEXT,
                run_time TEXT,
                mention BOOLEAN DEFAULT FALSE,
                message TEXT,
                created_by VARCHAR(100),
                last_run TIMESTAMP WITH TIME ZONE
            )
        ''')
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
        # Seed version 1.0 if table is empty
        count = await conn.fetchval("SELECT COUNT(*) FROM bot_version")
        if count == 0:
            await conn.execute(
                "INSERT INTO bot_version (version, changelog) VALUES ($1, $2)",
                "1.0", "• Initial release of Nukhba Manager Bot."
            )


def _next_version(current: str) -> str:
    """Auto-increment version: 1.0→1.1, 1.9→2.0, 1.15→1.2 (always one decimal step)."""
    try:
        parts = current.strip().split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        # If minor >= 9, roll over
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

    # Store owner so only they interact
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
            InlineKeyboardButton("✅ Save", callback_data="cfg_save"),
            InlineKeyboardButton("❌ Cancel", callback_data="cfg_cancel"),
        ],
    ])


async def config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pool = context.bot_data.get('db_pool')

    if not await is_bot_admin(q.from_user.username, pool):
        return await q.answer("❌ Admins only.", show_alert=True)

    owner = context.user_data.get('cfg_owner')
    if owner and q.from_user.id != owner:
        return await q.answer("❌ This panel was opened by another admin.", show_alert=True)

    data = q.data  # e.g. "cfg_gemini_add"

    if data == "cfg_noop":
        return await q.answer()

    if data == "cfg_cancel":
        context.user_data.pop('cfg_draft', None)
        context.user_data.pop('cfg_owner', None)
        await q.answer("Cancelled.")
        try:
            await q.edit_message_text("❌ Config cancelled. No changes saved.")
        except Exception:
            pass
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
        context.user_data.pop('cfg_draft', None)
        context.user_data.pop('cfg_owner', None)
        await q.answer("✅ Saved!")
        try:
            await q.edit_message_text(
                "✅ **Configuration saved and applied!**\n\n" + _cfg_text(d),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    d = context.user_data.get('cfg_draft')
    if not d:
        return await q.answer("Session expired. Run /botconfig again.", show_alert=True)

    # Parse "cfg_<field>_<action>"
    parts = data.split("_")  # ['cfg', 'gemini', 'add'] or ['cfg', 'away', 'cus']
    if len(parts) < 3:
        return await q.answer()

    field_key_map = {
        'gemini': 'gemini_weekly_limit',
        'stars':  'star_quota',
        'tasks':  'max_tasks',
        'events': 'max_events',
        'away':   'max_away_days',
    }
    field  = parts[1]
    action = parts[2]
    db_key = field_key_map.get(field)

    if not db_key:
        return await q.answer()

    if action == 'add':
        d[db_key] = str(int(d[db_key]) + 1)
        await q.answer(f"→ {d[db_key]}")
    elif action == 'sub':
        new_val = max(1, int(d[db_key]) - 1)
        d[db_key] = str(new_val)
        await q.answer(f"→ {d[db_key]}")
    elif action == 'cus':
        context.user_data['awaiting_cfg_field'] = db_key
        await q.answer()
        try:
            await q.edit_message_text(
                f"✏️ **Type a new value for `{field}`:**\n\nCurrent: `{d[db_key]}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # Refresh panel
    try:
        await q.edit_message_text(
            _cfg_text(d),
            reply_markup=_cfg_kb(d),
            parse_mode="Markdown"
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"cfg_callback edit error: {e}")


async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle pending custom text input for /botconfig.
    Returns True if message was consumed, False otherwise.
    Called from global_text_router in main.py.
    """
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
    except Exception:
        pass

    # Re-send the config panel
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
            "❌ **Usage:** `/setchannel bday|trivia|stars|feedback`\n\n"
            "Run this command inside the target group.",
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
            "❌ **Usage:** `/unsetchannel bday|trivia|stars|feedback`",
            parse_mode="Markdown"
        )

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM config WHERE key=$1", CHANNEL_MAP[target])
    await update.message.reply_text(
        f"✅ `{target}` channel binding has been cleared.",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
# /auditlog — PULL DIAGNOSTIC LOGS
# ─────────────────────────────────────────────

async def get_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    # Optional arg: number of entries to show (default 20)
    try:
        limit = int(context.args[0]) if context.args else 20
        limit = max(1, min(limit, 100))
    except ValueError:
        limit = 20

    async with pool.acquire() as conn:
        # Ensure table exists
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                user_id BIGINT,
                chat_id BIGINT,
                category VARCHAR(50),
                status VARCHAR(50),
                detail TEXT
            )
        ''')
        rows = await conn.fetch(
            "SELECT timestamp, category, status, detail FROM audit_logs "
            "ORDER BY timestamp DESC LIMIT $1",
            limit
        )

    if not rows:
        return await context.bot.send_message(
            update.effective_user.id,
            "📋 **Audit Log**\n\nNo entries found. The log is empty.",
            parse_mode="Markdown"
        )

    lines = [f"📋 **Audit Log (Last {limit} entries)**\n"]
    for r in rows:
        ts = r['timestamp'].astimezone(WIB).strftime('%m/%d %H:%M')
        lines.append(f"`[{ts}]` **{r['category']}** — {r['status']}\n  _{r['detail']}_")

    await send_md(context, update.effective_user.id, "\n".join(lines))


# ─────────────────────────────────────────────
# /audittime — SET DAILY AUDIT DIGEST TIME
# ─────────────────────────────────────────────

async def set_audit_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    time_str = context.args[0] if context.args else ""
    if not re.match(r'^\d{1,2}:\d{2}$', time_str):
        return await update.message.reply_text(
            "❌ **Usage:** `/audittime HH:MM`\n\nExample: `/audittime 23:50`",
            parse_mode="Markdown"
        )

    try:
        h, m = map(int, time_str.split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        return await update.message.reply_text("❌ Invalid time. Use HH:MM (24-hour).")

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config (key, value) VALUES ('audit_digest_time', $1) "
            "ON CONFLICT (key) DO UPDATE SET value=$1",
            f"{h:02d}:{m:02d}"
        )

    await update.message.reply_text(
        f"✅ Daily audit digest will be sent at `{h:02d}:{m:02d} WIB`.",
        parse_mode="Markdown"
    )


async def send_daily_audit_digest(context: ContextTypes.DEFAULT_TYPE):
    """Cron job: sends AI-digested audit report at configured time."""
    pool = context.bot_data.get('db_pool')
    if not pool:
        return

    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        audit_time = await conn.fetchval("SELECT value FROM config WHERE key='audit_digest_time'") or "23:50"
        super_uid  = await conn.fetchval("SELECT user_id FROM users WHERE LOWER(username)=$1", SUPER_OWNER.lower())

    h, m = map(int, audit_time.split(":"))
    if now.hour != h or now.minute != m:
        return
    if not super_uid:
        return

    try:
        from crons import generate_audit_report
        msg = await generate_audit_report(pool, now.date())
    except Exception:
        msg = f"📋 **Daily Audit Digest** — {now.strftime('%m/%d/%Y')}\n\nNo audit report generator found."

    try:
        await context.bot.send_message(super_uid, msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Audit digest send failed: {e}")


# ─────────────────────────────────────────────
# /manageusers — INTERACTIVE USER MANAGER
# ─────────────────────────────────────────────

async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return

    context.user_data['mu_owner'] = update.effective_user.id
    await update.message.reply_text(
        "👥 **USER MANAGER**\n\n"
        "Choose what you'd like to manage:",
        reply_markup=_mu_main_kb(),
        parse_mode="Markdown"
    )


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
        await q.answer("Closed.")
        try:
            await q.edit_message_text("👥 User Manager closed.")
        except Exception:
            pass
        return

    if data == "mu_back":
        await q.answer()
        try:
            await q.edit_message_text(
                "👥 **USER MANAGER**\n\nChoose what you'd like to manage:",
                reply_markup=_mu_main_kb(),
                parse_mode="Markdown"
            )
        except Exception:
            pass
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
        except Exception:
            pass
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
        except Exception:
            pass
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
        except Exception:
            pass
        context.user_data['awaiting_mu_input'] = True
        return

    await q.answer()


async def _handle_mu_text(update: Update, context: ContextTypes.DEFAULT_TYPE, pool) -> bool:
    """Process text input for the manage users panel."""
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
    except Exception:
        pass
    await update.message.reply_text(msg, parse_mode="Markdown")
    return True


# ─────────────────────────────────────────────
# VERSION SYSTEM: /pushupdate, /updatechange, /updateinfo
# ─────────────────────────────────────────────

async def update_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current bot version and changelog. Available to all users."""
    pool = context.bot_data.get('db_pool')
    await _ensure_version_table(pool)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT version, changelog, updated_at FROM bot_version ORDER BY id DESC LIMIT 10"
        )

    if not rows:
        return await update.message.reply_text("ℹ️ No version info available yet.")

    latest = rows[0]
    lines  = [
        f"🤖 **Nukhba Manager Bot**\n"
        f"📦 Current Version: `{latest['version']}`\n"
        f"📅 Last Updated: `{latest['updated_at'].astimezone(WIB).strftime('%d %b %Y, %H:%M WIB')}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 **Changelog:**\n"
    ]
    for r in rows:
        ts = r['updated_at'].astimezone(WIB).strftime('%d %b %Y')
        lines.append(f"\n🔖 **v{r['version']}** — _{ts}_\n{r['changelog']}")

    await send_md(context, update.effective_chat.id, "\n".join(lines))


async def push_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Auto-increment version and log a changelog entry.
    Broadcasts update DM to all users who have ever DM'd the bot.
    Super Owner only.
    Usage: /pushupdate Fixed trivia timer, added /about command
    """
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
        # Get all users who have ever DM'd the bot
        dm_users = await conn.fetch(
            "SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL"
        )

    broadcast_text = (
        f"🤖 **Nukhba Manager Bot — Update Released!**\n\n"
        f"📦 **Version:** `{new_ver}`\n"
        f"📅 **Date:** {datetime.datetime.now(WIB).strftime('%d %b %Y, %H:%M WIB')}\n\n"
        f"📝 **What's New:**\n{changelog}\n\n"
        f"Type /updateinfo to see the full changelog."
    )

    sent_count = 0
    for user in dm_users:
        try:
            await context.bot.send_message(user['user_id'], broadcast_text, parse_mode="Markdown")
            sent_count += 1
            await asyncio.sleep(0.05)  # Avoid hitting rate limits
        except Exception:
            pass

    await update.message.reply_text(
        f"✅ **Version `{new_ver}` pushed!**\n"
        f"📢 Update broadcasted to {sent_count} users.",
        parse_mode="Markdown"
    )


async def update_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Manually set a version number and log an entry.
    Super Owner only.
    Usage: /updatechange 2.0 , Complete system overhaul
    """
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_super(update.effective_user.username):
        return await update.message.reply_text("❌ Super Owner only.")

    raw = " ".join(context.args).strip()
    if "," not in raw:
        return await update.message.reply_text(
            "❌ **Usage:** `/updatechange [version] , [changelog]`\n\n"
            "Example: `/updatechange 2.0 , Complete system overhaul`",
            parse_mode="Markdown"
        )

    parts     = raw.split(",", 1)
    new_ver   = parts[0].strip()
    changelog = parts[1].strip()

    if not re.match(r'^\d+\.\d+$', new_ver):
        return await update.message.reply_text(
            "❌ Version must be in format `X.Y` (e.g. `2.0`, `1.5`)",
            parse_mode="Markdown"
        )

    await _ensure_version_table(pool)

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_version (version, changelog) VALUES ($1, $2)",
            new_ver, changelog
        )

    await update.message.reply_text(
        f"✅ Version manually set to `{new_ver}`.\n"
        f"Next `/pushupdate` will auto-increment from this version.",
        parse_mode="Markdown"
    )


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

    await update.message.reply_text(
        _nsched_text(context.user_data['nsched_draft']),
        reply_markup=_nsched_kb(context.user_data['nsched_draft']),
        parse_mode="Markdown"
    )


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
        context.user_data.pop('nsched_draft', None)
        context.user_data.pop('nsched_owner', None)
        await q.answer("Cancelled.")
        try:
            await q.edit_message_text("❌ Schedule cancelled. No changes saved.")
        except Exception:
            pass
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
        context.user_data.pop('nsched_draft', None)
        context.user_data.pop('nsched_owner', None)
        await q.answer("✅ Scheduled!")
        try:
            await q.edit_message_text(
                f"✅ **Broadcast Scheduled!**\n\n{_nsched_text(d)}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data == "nsched_target":
        context.user_data['awaiting_nsched_target'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "📡 **Set Target Chat**\n\n"
                "Type `all` to broadcast to all groups,\n"
                "or type a specific chat ID (e.g. `-1001234567890`):",
                parse_mode="Markdown"
            )
        except Exception:
            pass
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
        await q.answer()
        try:
            await q.edit_message_text(
                "⏰ **Type exact time in HH:MM (24-hour WIB):**\n\nExample: `14:30`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    elif data == "nsched_mention":
        d['mention'] = not d['mention']
        await q.answer(f"Tag All → {'Yes' if d['mention'] else 'No'}")

    elif data == "nsched_message":
        context.user_data['awaiting_nsched_message'] = True
        await q.answer()
        try:
            await q.edit_message_text(
                "📝 **Type the broadcast message now:**\n\n"
                "_Your next message will be used as the announcement text._"
            )
        except Exception:
            pass
        return

    # Refresh panel
    try:
        await q.edit_message_text(
            _nsched_text(d), reply_markup=_nsched_kb(d), parse_mode="Markdown"
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"nsched_callback edit error: {e}")


async def _handle_nsched_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Process text inputs for /newsched panel."""
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
        d['chat_id'] = text
        consumed = True

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
        except Exception:
            pass
        await update.message.reply_text(
            _nsched_text(d), reply_markup=_nsched_kb(d), parse_mode="Markdown"
        )
        return True

    return False


# ─────────────────────────────────────────────
# /allcommandtest — REAL COMMAND HEALTH CHECK
# ─────────────────────────────────────────────

async def all_command_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return await update.message.reply_text("❌ Super Owner only.")

    status_msg = await update.message.reply_text("🔍 Running command health check…")

    # All registered command → function mappings to test
    import cmd_system
    import cmd_user
    import cmd_trivia
    try:
        import cmd_cheer
    except ImportError:
        cmd_cheer = None
    try:
        import cmd_system_help
    except ImportError:
        cmd_system_help = None

    checks = [
        # (command_name, module, function_name)
        ("start",           cmd_system,      "start"),
        ("help",            cmd_system_help, "help_command"),
        ("about",           cmd_system,      "about_command"),
        ("wdim",            cmd_system,      "what_did_i_miss"),
        ("feedback",        cmd_system,      "submit_feedback"),
        ("ask",             cmd_system,      "ask_bot"),
        ("gemini",          cmd_system,      "ask_gemini"),
        ("updateinfo",      None,            None),  # this file
        ("pushupdate",      None,            None),
        ("updatechange",    None,            None),
        ("newevent",        cmd_user,        "create_event"),
        ("editevent",       cmd_user,        "edit_event"),
        ("events",          cmd_user,        "list_events"),
        ("poll",            cmd_user,        "create_poll"),
        ("thanks",          cmd_user,        "give_thanks"),
        ("myquota",         cmd_user,        "my_quota"),
        ("mystar",          cmd_user,        "my_star"),
        ("totalstar",       cmd_user,        "total_star"),
        ("leaderboard",     cmd_user,        "leaderboard"),
        ("addlib",          cmd_user,        "add_lib"),
        ("editlib",         cmd_user,        "edit_lib"),
        ("dellib",          cmd_user,        "del_lib"),
        ("getlib",          cmd_user,        "get_lib"),
        ("library",         cmd_user,        "list_lib"),
        ("assign",          cmd_user,        "assign_task"),
        ("complete",        cmd_user,        "complete_task"),
        ("mytasks",         cmd_user,        "my_tasks"),
        ("away",            cmd_user,        "set_away"),
        ("back",            cmd_user,        "set_back"),
        ("cheerme",         cmd_cheer,       "cheer_me"),
        ("setcheer",        cmd_cheer,       "set_cheer"),
        ("mypoint",         cmd_trivia,      "my_point"),
        ("triviaconfig",    cmd_trivia,      "trivia_config"),
        ("forcetrivia",     cmd_trivia,      "force_trivia"),
        ("forcesupertrivia",cmd_trivia,      "force_super_trivia"),
        ("canceltrivia",    cmd_trivia,      "cancel_trivia"),
        ("endtrivia",       cmd_trivia,      "end_trivia"),
        ("admin_kp",        cmd_trivia,      "admin_kp"),
        ("botconfig",       None,            None),  # this file
        ("setchannel",      None,            None),
        ("unsetchannel",    None,            None),
        ("groupid",         None,            None),
        ("auditlog",        None,            None),
        ("audittime",       None,            None),
        ("manageusers",     None,            None),
        ("checkquota",      None,            None),
        ("admin_stars",     None,            None),
        ("checklimit",      None,            None),
        ("admin_limit",     None,            None),
        ("addbday",         None,            None),
        ("editbday",        None,            None),
        ("delbday",         None,            None),
        ("listbdays",       None,            None),
        ("attendance",      None,            None),
        ("forceback",       None,            None),
        ("grouptasks",      None,            None),
        ("cancelevent",     None,            None),
        ("canceltask",      None,            None),
        ("cancelpoll",      None,            None),
        ("newsched",        None,            None),
        ("listschedules",   None,            None),
        ("delschedule",     None,            None),
        ("announce",        None,            None),
        ("editannounce",    None,            None),
        ("delannounce",     None,            None),
        ("feedbacklist",    None,            None),
        ("analyze_feedback",None,            None),
        ("allcommandtest",  None,            None),
        ("addadmin",        None,            None),
        ("deladmin",        None,            None),
        ("listadmins",      None,            None),
        ("removemember",    None,            None),
        ("graveyard",       None,            None),
        ("botstatus",       None,            None),
        ("pause",           None,            None),
        ("restart",         None,            None),
        ("super_reset",     None,            None),
    ]

    # Self-check for this module
    self_funcs = {
        "updateinfo": update_info, "pushupdate": push_update,
        "updatechange": update_change, "botconfig": bot_config,
        "setchannel": set_channel, "unsetchannel": unset_channel,
        "groupid": check_group_id, "auditlog": get_audit_log,
        "audittime": set_audit_time, "manageusers": manage_users,
        "checkquota": check_quota, "admin_stars": admin_stars,
        "checklimit": check_limit, "admin_limit": admin_limit,
        "addbday": add_bday, "editbday": edit_bday,
        "delbday": del_bday, "listbdays": list_bdays,
        "attendance": attendance, "forceback": force_back,
        "grouptasks": group_tasks, "cancelevent": cancel_event,
        "canceltask": cancel_task, "cancelpoll": cancel_poll_admin,
        "newsched": new_schedule, "listschedules": list_schedules,
        "delschedule": del_schedule, "announce": announce,
        "editannounce": edit_announce, "delannounce": del_announce,
        "feedbacklist": feedback_list, "analyze_feedback": analyze_feedback,
        "allcommandtest": all_command_test, "addadmin": add_admin_req,
        "deladmin": del_admin_req, "listadmins": list_admins,
        "removemember": remove_member_req, "graveyard": graveyard,
        "botstatus": bot_status, "pause": pause_bot,
        "restart": restart_bot, "super_reset": super_reset_req,
    }

    results = []
    ok = 0
    fail = 0

    for cmd, module, func_name in checks:
        if module is None:
            # Check in self_funcs
            fn = self_funcs.get(cmd)
            if fn and callable(fn):
                results.append(f"/{cmd} ✅")
                ok += 1
            else:
                results.append(f"/{cmd} ❌ Not implemented")
                fail += 1
        else:
            if module is None:
                results.append(f"/{cmd} ❌ Module not loaded")
                fail += 1
            elif not hasattr(module, func_name):
                results.append(f"/{cmd} ❌ `{func_name}` missing from {module.__name__}")
                fail += 1
            elif not callable(getattr(module, func_name)):
                results.append(f"/{cmd} ❌ `{func_name}` not callable")
                fail += 1
            else:
                results.append(f"/{cmd} ✅")
                ok += 1

    report = (
        f"🧪 **COMMAND HEALTH REPORT**\n"
        f"──────────────────────────────\n"
        f"✅ OK: {ok}  |  ❌ Failed: {fail}\n\n"
        + "\n".join(results)
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    await send_md(context, update.effective_user.id, report)


# ─────────────────────────────────────────────
# GLOBAL TEXT INPUT ROUTER FOR ADMIN PANELS
# (called from main.py global_text_router)
# ─────────────────────────────────────────────

async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Routes text input to whichever admin panel is currently awaiting input.
    Returns True if consumed, False otherwise.
    """
    pool = context.bot_data.get('db_pool')

    # /botconfig custom input
    if context.user_data.get('awaiting_cfg_field'):
        owner = context.user_data.get('cfg_owner')
        if not owner or update.effective_user.id == owner:
            return await handle_admin_text_input(update, context)

    # /manageusers text input
    if context.user_data.get('awaiting_mu_input'):
        return await _handle_mu_text(update, context, pool)

    # /newsched text input
    if any(context.user_data.get(k) for k in [
        'awaiting_nsched_target', 'awaiting_nsched_time', 'awaiting_nsched_message'
    ]):
        return await _handle_nsched_text(update, context)

    # /botconfig custom number input
    if context.user_data.get('awaiting_cfg_field'):
        field = context.user_data.get('awaiting_cfg_field')
        text  = update.message.text.strip() if update.message and update.message.text else ""
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
        except Exception:
            pass
        try:
            chat_id = update.effective_chat.id
            msg_id  = context.user_data.get('cfg_msg_id')
            if msg_id and d:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=_cfg_text(d), reply_markup=_cfg_kb(d), parse_mode="Markdown"
                )
        except Exception:
            pass
        return True

    return False


# ─────────────────────────────────────────────
# REMAINING ADMIN COMMANDS (unchanged / kept)
# ─────────────────────────────────────────────

async def analyze_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if not GEMINI_API_KEY:
        return await update.message.reply_text("❌ Gemini API Key missing.")

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
        client   = genai.Client(api_key=GEMINI_API_KEY)
        response = await asyncio.to_thread(
            client.models.generate_content, model='gemini-2.5-flash', contents=ai_prompt
        )
        await temp.delete()
        await send_md(
            context, update.effective_user.id,
            f"✅ 🤖 **Gemini Feedback Analysis ({range_desc})**\n\n{response.text}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Analysis failed: {e}")


async def unpin_event(context):
    try:
        await context.bot.unpin_chat_message(
            chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id']
        )
    except Exception:
        pass


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
        except Exception:
            pass


async def poll_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(
            context.job.data['chat_id'],
            f"⏳ **Poll Reminder:** *{context.job.data['q']}* ends in 15 minutes!",
            parse_mode="Markdown"
        )
    except Exception:
        pass


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
    except Exception:
        pass
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
    async with pool.acquire() as conn:
        exist = await conn.fetchval('SELECT bday FROM birthdays WHERE lower(username)=$1', u)
        if exist:
            return await context.bot.send_message(update.effective_user.id, f"❌ Already registered: {exist}")
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
    await context.bot.send_message(update.effective_user.id, f"✅ Birthday for @{u} logged as `{b}`.", parse_mode="Markdown")


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
    async with pool.acquire() as conn:
        res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE lower(username)=$2', b, u)
    if res == "UPDATE 0":
        return await context.bot.send_message(update.effective_user.id, "❌ User not found.")
    await context.bot.send_message(update.effective_user.id, f"✅ Birthday updated for @{u}.")


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
                    f"📢 **[RW] NUKHBA BROADCAST**\n\n{message}",
                    parse_mode="Markdown"
                )
                await conn.execute(
                    "INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1,$2,$3)",
                    a_id, t['chat_id'], m.message_id
                )
            except Exception:
                pass
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
                    f"📢 **[RW] NUKHBA BROADCAST**\n\n{text}",
                    chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown"
                )
            except Exception:
                pass
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
            except Exception:
                pass
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, "✅ Announcement deleted.")


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
        except Exception:
            pass
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
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        tasks = await conn.fetch(
            "SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks WHERE status='Pending' ORDER BY deadline"
        )
    if not tasks:
        return await context.bot.send_message(update.effective_user.id, "✅ 🎉 No pending tasks.")
    msg = "📋 **Global Pending Tasks**\n\n"
    for t in tasks:
        rem  = int((t['deadline'] - now).total_seconds() / 60)
        msg += f"🔹 `{t['id']}` | **{t['task_desc']}**\nTo: @{t['assignee']} | By: @{t['assigned_by']} | ⏳ {'OVERDUE' if rem <= 0 else f'{rem}m left'}\n\n"
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


async def super_reset_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    target = context.args[0].lower() if context.args else 'all'
    await context.bot.send_message(
        update.effective_user.id,
        f"⚠️ **Factory Wipe Confirmation**\n\nAre you sure you want to wipe `{target}`?\n\n**This cannot be undone.**",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚠️ Confirm Wipe", callback_data=f"sup_reset_{target}"),
            InlineKeyboardButton("❌ Cancel",        callback_data="sup_cancel")
        ]]),
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
    t     = parts[2]
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
            if t in ["stars", "all"]:
                await conn.execute("TRUNCATE kudos CASCADE")
            if t in ["birthdays", "all"]:
                await conn.execute("TRUNCATE birthdays CASCADE")
            await q.edit_message_text(f"✅ Wiped `{t}` database.")


async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT username FROM bot_admins ORDER BY username')
    msg = "👑 **Admin List**\n\n" + ("\n".join([f"• @{r['username']}" for r in recs]) if recs else "_No admins registered._")
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


async def graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT username, removed_at FROM graveyard ORDER BY removed_at DESC')
    msg = "🪦 **Graveyard — Offboarded Members**\n\n" + (
        "\n".join([f"• @{r['username']} — {r['removed_at'].astimezone(WIB).strftime('%d %b %Y')}" for r in recs])
        if recs else "_Graveyard is empty._"
    )
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")


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
    """Cron: check and fire any scheduled announcements."""
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        schedules = await conn.fetch("SELECT * FROM scheduled_announcements")
        for s in schedules:
            should_run = False
            f     = s['frequency']
            t_str = s['run_time']
            try:
                if f == 'once':
                    run_dt = WIB.localize(datetime.datetime.strptime(t_str, "%m/%d/%Y %H:%M"))
                    if now >= run_dt and not s['last_run']:
                        should_run = True
                elif f == 'daily':
                    h, m = map(int, t_str.split(':'))
                    if now.hour == h and now.minute == m and (not s['last_run'] or s['last_run'].date() < now.date()):
                        should_run = True
                elif f == 'weekly':
                    day, tm = t_str.split(' ')
                    h, m = map(int, tm.split(':'))
                    if (now.weekday() == int(day) and now.hour == h and now.minute == m and
                            (not s['last_run'] or (now - s['last_run'].astimezone(WIB)).days >= 6)):
                        should_run = True
            except Exception:
                continue

            if should_run:
                msg     = f"📢 **Scheduled Announcement**\n\n{s['message']}"
                targets = [g['chat_id'] for g in await conn.fetch("SELECT chat_id FROM active_groups")] \
                    if s['chat_id'] == 'all' else [int(s['chat_id'])]
                if s['mention']:
                    users = await conn.fetch("SELECT username FROM users WHERE username IS NOT NULL")
                    msg  += "\n\n👥 " + " ".join([f"@{u['username']}" for u in users])
                for t in targets:
                    try:
                        await send_md(context, t, msg)
                    except Exception:
                        pass
                await conn.execute(
                    "UPDATE scheduled_announcements SET last_run=$1 WHERE id=$2", now, s['id']
                )


async def schedule_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy text command. /newsched is the preferred inline keyboard version."""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    await update.message.reply_text(
        "ℹ️ Please use `/newsched` for the interactive broadcast scheduler.",
        parse_mode="Markdown"
    )


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
