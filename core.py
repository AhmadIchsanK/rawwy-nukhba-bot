import os, datetime, logging, json, sys, asyncio
import asyncpg
from pytz import timezone
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
    """
    Spawns the central connection pool for PostgreSQL and runs immediate structural
    migrations to establish necessary modules like system configs, cheers, and trivia.
    """
    if not DATABASE_URL:
        logger.critical("❌ CRITICAL: DATABASE_URL variable is missing from environment variables setup!")
        return

    try:
        # Build global asyncpg connection manager pool
        app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
        logger.info("✅ PostgreSQL global database connection pool created successfully.")
        
        # -----------------------------------------------------------------
        # AUTOMATED SYSTEM MIGRATION HOOKS
        # -----------------------------------------------------------------
        # 1. Core Config and Stats baseline setup
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
            
        # 2. Daily/Weekly Super Trivia Feature Migrations
        import cmd_trivia
        await cmd_trivia.ensure_trivia_database(app.bot_data['db_pool'])
        logger.info("✅ Trivia database verification checks successfully completed.")
        
    except Exception as e:
        logger.critical(f"❌ CRITICAL FAILURE: Could not establish initial database structures: {e}")
        sys.exit(1)

# --- GLOBAL UTILITY SECURITY MATRIX ASSESSORS ---
async def is_bot_admin(username: str, pool) -> bool:
    """Verifies if the specified username possesses explicit admin execution tokens."""
    if not username: return False
    if username.lower() == SUPER_OWNER.lower(): return True
    
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT username FROM bot_admins WHERE LOWER(username) = $1", username.lower())
        return record is not None

async def is_super(username: str) -> bool:
    """Checks if a user is the primary programmatic system anchor."""
    if not username: return False
    return username.lower() == SUPER_OWNER.lower()

# --- SYSTEM DIAGNOSTIC ACTIVITY RECORDER ---
async def log_action(pool, user_id: int, chat_id: int, category: str, status: str, detail: str):
    """Logs internal system operations, user interactions, or structural faults."""
    if not pool: return
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

# --- WEB APP SYNC INTERFACES ---
async def update_user_menu(user_id: int, username: str, pool, bot):
    """Maintains alignment across interactive dashboard variables when required."""
    pass