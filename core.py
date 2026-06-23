import os
import datetime
import logging
import json
import sys
import asyncio
import asyncpg
from pytz import timezone
from telegram import Update
from telegram.ext import Application

logger = logging.getLogger(__name__)

# --- SYSTEM TIMING REGIONS & TIMEZONES ---
WIB = timezone('Asia/Jakarta')

# --- ENVIRONMENT CREDENTIAL EXTRACTIONS ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
SUPER_OWNER = os.getenv("SUPER_OWNER", "superadmin")

async def init_db(app: Application):
    if not DATABASE_URL:
        logger.critical("❌ CRITICAL: DATABASE_URL variable is missing from environment variables setup!")
        return

    try:
        app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
        logger.info("✅ PostgreSQL global database connection pool created successfully.")
        
        async with app.bot_data['db_pool'].acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_stats (
                    date DATE PRIMARY KEY,
                    uses INT DEFAULT 0,
                    errors INT DEFAULT 0
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS active_groups (
                    chat_id BIGINT PRIMARY KEY,
                    title TEXT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bug_reports (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100),
                    report TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT,
                    username VARCHAR(100),
                    message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS poll_drafts (
                    pid BIGINT PRIMARY KEY,
                    owner BIGINT,
                    q TEXT,
                    opts TEXT,
                    anon BOOLEAN,
                    multi BOOLEAN,
                    quiz_idx INT,
                    hours INT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS feedback_drafts (
                    user_id BIGINT PRIMARY KEY,
                    text TEXT
                )
            ''')
            # ── USERS (core identity + AI quota) ──────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    username    VARCHAR(100) PRIMARY KEY,
                    user_id     BIGINT,
                    gemini_quota INT DEFAULT 10,
                    last_about  TIMESTAMP WITH TIME ZONE,
                    can_dm      BOOLEAN DEFAULT FALSE
                )
            ''')
            # Migration: add can_dm if upgrading from an older schema
            await conn.execute('''
                ALTER TABLE users ADD COLUMN IF NOT EXISTS can_dm BOOLEAN DEFAULT FALSE
            ''')
            # ── KUDOS / RAWWY STARS ───────────────────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS kudos (
                    username        VARCHAR(100) PRIMARY KEY,
                    quota           INT DEFAULT 3,
                    monthly_points  INT DEFAULT 0,
                    all_time_points INT DEFAULT 0
                )
            ''')
            # ── EVENTS ────────────────────────────────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id          SERIAL PRIMARY KEY,
                    title       TEXT NOT NULL,
                    event_time  TIMESTAMP WITH TIME ZONE,
                    created_by  VARCHAR(100),
                    chat_id     BIGINT,
                    msg_id      BIGINT,
                    reminder_mins INT DEFAULT 30
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rsvps (
                    event_id    INT REFERENCES events(id) ON DELETE CASCADE,
                    username    VARCHAR(100),
                    status      VARCHAR(20),
                    PRIMARY KEY (event_id, username)
                )
            ''')
            # ── TASKS ─────────────────────────────────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id          SERIAL PRIMARY KEY,
                    assignee    VARCHAR(100),
                    task_desc   TEXT,
                    deadline    TIMESTAMP WITH TIME ZONE,
                    assigned_by VARCHAR(100),
                    status      VARCHAR(20) DEFAULT 'Pending',
                    chat_id     BIGINT
                )
            ''')
            # ── LIBRARY ───────────────────────────────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS library (
                    name        VARCHAR(200) PRIMARY KEY,
                    content     TEXT,
                    added_by    VARCHAR(100),
                    is_private  BOOLEAN DEFAULT FALSE
                )
            ''')
            # ── AWAY STATUS ───────────────────────────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS away_status (
                    username        VARCHAR(100) PRIMARY KEY,
                    reason          TEXT,
                    end_time        TIMESTAMP WITH TIME ZONE,
                    last_notified   TIMESTAMP WITH TIME ZONE
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS away_mentions (
                    id              SERIAL PRIMARY KEY,
                    away_username   VARCHAR(100),
                    mentioner       VARCHAR(100),
                    message         TEXT,
                    chat_title      TEXT,
                    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            # ── BIRTHDAYS ─────────────────────────────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS birthdays (
                    username    VARCHAR(100) PRIMARY KEY,
                    bday        VARCHAR(5)
                )
            ''')
            # ── ACTIVE POLLS ──────────────────────────────────────────────────
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS active_polls (
                    chat_id     BIGINT,
                    user_id     BIGINT,
                    end_time    TIMESTAMP WITH TIME ZONE,
                    PRIMARY KEY (chat_id, user_id)
                )
            ''')

        import cmd_trivia
        import cmd_cheer
        await cmd_trivia.ensure_trivia_database(app.bot_data['db_pool'])
        await cmd_cheer.ensure_cheer_profile_column(app.bot_data['db_pool'])
        
    except Exception as e:
        logger.critical(f"❌ CRITICAL FAILURE: Could not establish initial database structures: {e}")
        sys.exit(1)

async def is_bot_admin(username: str, pool) -> bool:
    if not username:
        return False
    if username.lower() == SUPER_OWNER.lower():
        return True
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT username FROM bot_admins WHERE LOWER(username) = $1", username.lower())
        return record is not None

async def is_super(username: str) -> bool:
    if not username:
        return False
    return username.lower() == SUPER_OWNER.lower()

async def delete_cmd(update: Update):
    try:
        # Ensures that commands typed in Private DMs are NEVER deleted
        if update.message and update.effective_chat.type != 'private':
            await update.message.delete()
    except Exception:
        pass

async def log_action(pool, user_id: int, chat_id: int, category: str, status: str, detail: str):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
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
            await conn.execute('''
                INSERT INTO audit_logs (user_id, chat_id, category, status, detail)
                VALUES ($1, $2, $3, $4, $5)
            ''', user_id, chat_id, category, status, detail)
    except Exception as e:
        logger.error(f"Failed to record diagnostic audit log event entry: {e}")

async def update_user_menu(user_id: int, username: str, pool, bot):
    pass

# ─────────────────────────────────────────────────────────────────
# ⏱️ INLINE KEYBOARD TIMEOUT & OWNERSHIP UTILITIES
# ─────────────────────────────────────────────────────────────────
KEYBOARD_TIMEOUT = 120  # seconds

def kb_key(chat_id: int, msg_id: int) -> str:
    return f"kb_owner_{chat_id}_{msg_id}"

def register_kb_owner(context, chat_id: int, msg_id: int, user_id: int, prompt_msg_id: int = None):
    """Register who owns an inline keyboard and schedule its auto-expiry."""
    context.bot_data.setdefault('kb_owners', {})[kb_key(chat_id, msg_id)] = {
        'user_id': user_id,
        'prompt_msg_id': prompt_msg_id,
    }

def get_kb_owner(context, chat_id: int, msg_id: int) -> int:
    """Return the user_id who owns a keyboard, or None."""
    entry = context.bot_data.get('kb_owners', {}).get(kb_key(chat_id, msg_id))
    return entry['user_id'] if entry else None

def pop_kb_owner(context, chat_id: int, msg_id: int):
    """Remove and return the kb owner entry."""
    return context.bot_data.get('kb_owners', {}).pop(kb_key(chat_id, msg_id), None)

CANCELLED_TEXT = "⏰ This panel was closed due to 120 seconds of inactivity."

async def keyboard_timeout_callback(context):
    """Job callback: expire an inline keyboard after KEYBOARD_TIMEOUT seconds."""
    job = context.job
    chat_id = job.data['chat_id']
    msg_id  = job.data['msg_id']
    bot     = context.bot

    entry = pop_kb_owner(context, chat_id, msg_id)
    if entry is None:
        return  # already dismissed

    # 1. Remove the keyboard from the original message
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg_id, reply_markup=None)
    except Exception:
        pass

    # 2. Send the cancellation notice
    try:
        await bot.send_message(chat_id, CANCELLED_TEXT)
    except Exception:
        pass

    # 3. Delete any pending "awaiting input" prompt message
    prompt_msg_id = entry.get('prompt_msg_id')
    if prompt_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prompt_msg_id)
        except Exception:
            pass

async def schedule_kb_timeout(context, chat_id: int, msg_id: int, user_id: int, prompt_msg_id: int = None):
    """Register ownership + schedule auto-expiry. Call after sending any personal inline keyboard."""
    register_kb_owner(context, chat_id, msg_id, user_id, prompt_msg_id)
    job_name = f"kb_timeout_{chat_id}_{msg_id}"
    for j in context.job_queue.get_jobs_by_name(job_name):
        j.schedule_removal()
    context.job_queue.run_once(
        keyboard_timeout_callback,
        when=KEYBOARD_TIMEOUT,
        data={'chat_id': chat_id, 'msg_id': msg_id},
        name=job_name
    )

def cancel_kb_timeout(context, chat_id: int, msg_id: int):
    """Cancel the timeout job when a keyboard is dismissed normally."""
    pop_kb_owner(context, chat_id, msg_id)
    job_name = f"kb_timeout_{chat_id}_{msg_id}"
    for j in context.job_queue.get_jobs_by_name(job_name):
        j.schedule_removal()

async def check_kb_ownership(query, context) -> bool:
    """
    Call at the top of any personal callback handler.
    Returns True (allowed) or False (blocked + answered).
    Public keyboards (trivia answers, polls, rsvp) should NOT call this.
    """
    chat_id = query.message.chat.id
    msg_id  = query.message.message_id
    owner   = get_kb_owner(context, chat_id, msg_id)
    if owner is None:
        # No owner registered (e.g. public kb) — allow
        return True
    if query.from_user.id != owner:
        await query.answer("❌ This panel belongs to someone else.", show_alert=True)
        return False
    return True

async def dismiss_kb_timeout_on_action(context, chat_id: int, msg_id: int):
    """Call when user successfully dismisses/saves a panel — cancels the timeout cleanly."""
    cancel_kb_timeout(context, chat_id, msg_id)
