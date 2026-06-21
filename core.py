import os, datetime, logging, json, sys, asyncio
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
SUPER_OWNER = os.getenv("SUPER_OWNER", "superadmin")

# --- CENTRALIZED DATABASE CONNECTIVITY INITIALIZER ---
async def init_db(app: Application):
    if not DATABASE_URL:
        logger.critical("❌ CRITICAL: DATABASE_URL variable is missing!")
        return

    try:
        app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
        logger.info("✅ PostgreSQL global database connection pool created successfully.")
        
        async with app.bot_data['db_pool'].acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS config (key VARCHAR(100) PRIMARY KEY, value TEXT)
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_stats (date DATE PRIMARY KEY, uses INT DEFAULT 0, errors INT DEFAULT 0)
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT)
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bug_reports (
                    id SERIAL PRIMARY KEY, username VARCHAR(100), report TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY, chat_id BIGINT, username VARCHAR(100), message TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS poll_drafts (
                    pid BIGINT PRIMARY KEY, owner BIGINT, q TEXT, opts TEXT, anon BOOLEAN, multi BOOLEAN, quiz_idx INT, hours INT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS feedback_drafts (
                    user_id BIGINT PRIMARY KEY, text TEXT
                )
            ''')
            
        import cmd_trivia
        await cmd_trivia.ensure_trivia_database(app.bot_data['db_pool'])
        
    except Exception as e:
        logger.critical(f"❌ CRITICAL FAILURE: Could not establish initial database structures: {e}")
        sys.exit(1)

async def is_bot_admin(username: str, pool) -> bool:
    if not username: return False
    if username.lower() == SUPER_OWNER.lower(): return True
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT username FROM bot_admins WHERE LOWER(username) = $1", username.lower())
        return record is not None

async def is_super(username: str) -> bool:
    if not username: return False
    return username.lower() == SUPER_OWNER.lower()

async def delete_cmd(update: Update):
    try:
        if update.message: await update.message.delete()
    except Exception: pass

async def log_action(pool, user_id: int, chat_id: int, category: str, status: str, detail: str):
    if not pool: return
    try:
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY, timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    user_id BIGINT, chat_id BIGINT, category VARCHAR(50), status VARCHAR(50), detail TEXT
                )
            ''')
            await conn.execute('''
                INSERT INTO audit_logs (user_id, chat_id, category, status, detail)
                VALUES ($1, $2, $3, $4, $5)
            ''', user_id, chat_id, category, status, detail)
    except Exception as e:
        logger.error(f"Failed to record diagnostic log: {e}")

async def update_user_menu(user_id: int, username: str, pool, bot): pass
