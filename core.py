import os, logging, pytz, asyncpg
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, BotCommandScopeChatMember, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
from telegram.ext import Application

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL")
SUPER_OWNER = os.getenv("SUPER_OWNER", "AdminUsername").replace("@", "").lower()
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- HELPERS & AUTH ---
async def is_super(username: str) -> bool:
    if not username: return False
    return username.lower() == SUPER_OWNER

async def is_bot_admin(username: str, pool) -> bool:
    if await is_super(username): return True
    if not username: return False
    async with pool.acquire() as conn:
        res = await conn.fetchrow('SELECT username FROM bot_admins WHERE username=$1', username.lower())
        return bool(res)

async def delete_cmd(update):
    if update.effective_chat.type != "private":
        try: await update.message.delete()
        except: pass

async def log_action(pool, user_id: int, chat_id: int, action_type: str, status: str, text: str):
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_logs (user_id, chat_id, action_type, status, log_text) VALUES ($1, $2, $3, $4, $5)",
                user_id, chat_id, action_type, status, text
            )
    except Exception as e:
        logger.error(f"Failed to log action: {e}")

# --- DYNAMIC MENU BUILDER ---
async def update_user_menu(user_id: int, username: str, pool, bot):
    is_adm = await is_bot_admin(username, pool)
    is_sup = await is_super(username)
    
    base_cmds = [
        BotCommand("help", "📖 View Nukhba Manual"),
        BotCommand("newevent", "📅 Schedule an event"),
        BotCommand("events", "📅 View upcoming events"),
        BotCommand("poll", "📊 Interactive Team Poll"),
        BotCommand("thanks", "🌟 Give a Star (Reply)"),
        BotCommand("myquota", "🌟 Check Star Quota left"),
        BotCommand("mystar", "🌟 Monthly Stars earned"),
        BotCommand("totalstar", "🌟 All-time Stars earned"),
        BotCommand("addlib", "📚 Save a library asset"),
        BotCommand("editlib", "📚 Edit your asset"),
        BotCommand("dellib", "📚 Delete your asset"),
        BotCommand("getlib", "📚 Retrieve an asset"),
        BotCommand("library", "📚 Browse the Library"),
        BotCommand("assign", "⚡ Assign a task"),
        BotCommand("complete", "⚡ Mark task complete"),
        BotCommand("mytasks", "⚡ View your active tasks"),
        BotCommand("away", "🏖️ Set away status"),
        BotCommand("back", "🏖️ Return to available"),
        BotCommand("bugreport", "🐛 Report an issue")
    ]
    
    if is_adm:
        base_cmds.extend([
            BotCommand("addbday", "🎂 Add user birthday"),
            BotCommand("editbday", "🎂 Edit user birthday"),
            BotCommand("delbday", "🎂 Remove a birthday"),
            BotCommand("addbday_batch", "🎂 Batch Add Birthdays"),
            BotCommand("delbday_batch", "🎂 Batch Delete Birthdays"),
            BotCommand("listbdays", "🎂 View all birthdays"),
            BotCommand("setbdaychannel", "⚙️ Set Group for Bdays"),
            BotCommand("setbdaytime", "⚙️ Set Alert Time (HH:MM)"),
            BotCommand("bdayconfig", "⚙️ Check Bday Setup"),
            BotCommand("attendance", "⚙️ View Away vs Available"),
            BotCommand("forceback", "⚙️ Force stop user away status"),
            BotCommand("checkquota", "⚙️ Audit user quotas"),
            BotCommand("admin_stars", "⚙️ Modify user stars"),
            BotCommand("grouptasks", "⚙️ View group tasks"),
            BotCommand("cancelevent", "⚙️ Cancel Event"),
            BotCommand("canceltask", "⚙️ Cancel Task"),
            BotCommand("cancelpoll", "⚙️ Stop Poll (Reply)"),
            BotCommand("addlib_batch", "⚙️ Batch Add Assets"),
            BotCommand("dellib_batch", "⚙️ Batch Delete Assets"),
            BotCommand("announce", "📢 Send Broadcast"),
            BotCommand("editannounce", "📢 Edit Broadcast"),
            BotCommand("delannounce", "📢 Delete Broadcast"),
            BotCommand("groupid", "📢 Check Chat IDs"),
            BotCommand("auditlog", "📢 Pull diagnostics log")
        ])
    if is_sup:
        base_cmds.extend([
            BotCommand("addadmin", "👑 Promote Admin"),
            BotCommand("deladmin", "👑 Demote Admin"),
            BotCommand("listadmins", "👑 View Admins"),
            BotCommand("removemember", "🛑 Offboard User"),
            BotCommand("graveyard", "🪦 View Graveyard"),
            BotCommand("botstatus", "📈 Global DB Status"),
            BotCommand("super_reset", "☢️ Factory Wipe Module")
        ])
        
    try: 
        await bot.set_my_commands(base_cmds, scope=BotCommandScopeChat(chat_id=user_id))
        if is_adm:
            async with pool.acquire() as conn:
                groups = await conn.fetch("SELECT chat_id FROM active_groups")
                for g in groups:
                    try: await bot.set_my_commands(base_cmds, scope=BotCommandScopeChatMember(chat_id=g['chat_id'], user_id=user_id))
                    except: pass
    except: pass

# --- DATABASE SETUP ---
async def init_db(app: Application):
    if not DATABASE_URL: return logger.error("DATABASE_URL missing!")
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, user_id BIGINT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_admins (username TEXT PRIMARY KEY);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS kudos (username TEXT PRIMARY KEY, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0, quota INT DEFAULT 3);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT, is_private BOOLEAN DEFAULT FALSE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT, chat_id BIGINT, msg_id BIGINT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE, assigned_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_polls (chat_id BIGINT, user_id BIGINT, end_time TIMESTAMP WITH TIME ZONE, PRIMARY KEY(chat_id, user_id));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (username TEXT PRIMARY KEY, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (username TEXT PRIMARY KEY, bday TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_stats (date DATE PRIMARY KEY, uses INT DEFAULT 0, errors INT DEFAULT 0);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bug_reports (id SERIAL PRIMARY KEY, username TEXT, report TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS graveyard (username TEXT PRIMARY KEY, offboarded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), data_dump TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS audit_logs (id SERIAL PRIMARY KEY, log_text TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcements (id SERIAL PRIMARY KEY, text TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcement_messages (announcement_id INTEGER, chat_id BIGINT, message_id BIGINT);''')
        
        try:
            await conn.execute('''ALTER TABLE audit_logs ADD COLUMN user_id BIGINT, ADD COLUMN chat_id BIGINT, ADD COLUMN action_type TEXT, ADD COLUMN status TEXT;''')
        except Exception:
            pass

    default_cmds = [
        BotCommand("help", "📖 View Nukhba Manual"),
        BotCommand("newevent", "📅 Schedule an event"),
        BotCommand("events", "📅 View upcoming events"),
        BotCommand("poll", "📊 Interactive Team Poll"),
        BotCommand("thanks", "🌟 Give a Star (Reply)"),
        BotCommand("myquota", "🌟 Check Star Quota left"),
        BotCommand("mystar", "🌟 Monthly Stars earned"),
        BotCommand("totalstar", "🌟 All-time Stars earned"),
        BotCommand("addlib", "📚 Save a library asset"),
        BotCommand("editlib", "📚 Edit your asset"),
        BotCommand("dellib", "📚 Delete your asset"),
        BotCommand("getlib", "📚 Retrieve an asset"),
        BotCommand("library", "📚 Browse the Library"),
        BotCommand("assign", "⚡ Assign a task"),
        BotCommand("complete", "⚡ Mark task complete"),
        BotCommand("mytasks", "⚡ View your active tasks"),
        BotCommand("away", "🏖️ Set away status"),
        BotCommand("back", "🏖️ Return to available")
    ]
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeDefault())
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeAllPrivateChats())
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeAllGroupChats())
    
    logger.info("✅ Enterprise Database & Scoped Menus Configured!")
