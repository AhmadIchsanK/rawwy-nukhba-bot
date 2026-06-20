import logging, datetime, pytz, os, asyncpg, random
from telegram import Update, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters, ContextTypes
from telegram.error import TelegramError

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL")
SUPER_OWNER = os.getenv("SUPER_OWNER", "AdminUsername").replace("@", "").lower()
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- AUTHENTICATION & AUDIT LOGGING ---
async def is_super(username: str) -> bool:
    return username.lower() == SUPER_OWNER if username else False

async def is_bot_admin(username: str, pool) -> bool:
    if await is_super(username): return True
    if not username: return False
    async with pool.acquire() as conn:
        res = await conn.fetchrow('SELECT username FROM bot_admins WHERE username=$1', username.lower())
        return bool(res)

async def notify_admins(bot, pool, message_text: str):
    async with pool.acquire() as conn:
        admins = await conn.fetch("SELECT username FROM bot_admins")
        admin_unames = {SUPER_OWNER} | {a['username'] for a in admins}
        for uname in admin_unames:
            uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", uname)
            if uid:
                try: await bot.send_message(uid, message_text, parse_mode="Markdown")
                except: pass

async def log_audit(pool, user_id: int, username: str, chat_id: int, action_type: str, detail: str, status: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO audit_logs (user_id, username, chat_id, action_type, detail, status) VALUES ($1, $2, $3, $4, $5, $6)",
            user_id, username, chat_id, action_type, detail, status
        )

# --- UNIFIED COMMAND MENUS ---
def get_user_menu():
    return [
        BotCommand("event_create", "📅 Create an event"),
        BotCommand("event_list", "📅 View upcoming events"),
        BotCommand("clockin", "👥 Start attendance"),
        BotCommand("clockout", "👥 Submit attendance report"),
        BotCommand("birthday_list", "🎂 View birthday list"),
        BotCommand("poll", "🎲 Create a poll"),
        BotCommand("raffle", "🎲 Pick random winners"),
        BotCommand("mystar", "🌟 Stars earned this month"),
        BotCommand("myquota", "🌟 Star Quota left to give"),
        BotCommand("thanks", "🌟 (Reply) Send a Star"),
        BotCommand("library", "📚 Browse Library"),
        BotCommand("mytasks", "⚡ View your tasks"),
        BotCommand("away", "⚙️ Set away status"),
        BotCommand("back", "⚙️ Return to available status"),
        BotCommand("bugreport", "🐛 Report an issue")
    ]

def get_admin_menu():
    return get_user_menu() + [
        BotCommand("admin_groups", "🛠️ Manage active groups"),
        BotCommand("admin_broadcast", "🛠️ Broadcast announcement"),
        BotCommand("announcement_create", "🛠️ Draft announcement"),
        BotCommand("announcement_send", "🛠️ Push announcement"),
        BotCommand("birthday_add", "🛠️ Add a user birthday"),
        BotCommand("birthday_edit", "🛠️ Edit a user birthday"),
        BotCommand("auditlog", "🛠️ Manual diagnostic report"),
        BotCommand("systemstatus", "🛠️ Live system metrics"),
        BotCommand("admin_stars", "🛠️ Edit Stars"),
        BotCommand("checkquota", "🛠️ Audit Quotas"),
        BotCommand("grouptasks", "🛠️ View all tasks")
    ]

async def sync_menus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        if await is_bot_admin(username, pool):
            await context.bot.set_my_commands(get_admin_menu(), scope=BotCommandScopeChat(chat_id=update.effective_chat.id))
        else:
            await context.bot.set_my_commands(get_user_menu(), scope=BotCommandScopeChat(chat_id=update.effective_chat.id))

# --- DATABASE SETUP ---
async def init_db(app: Application):
    if not DATABASE_URL: return logger.error("DATABASE_URL missing!")
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_admins (username TEXT PRIMARY KEY);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT, member_count INT, added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (username TEXT PRIMARY KEY, bday TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (user_id BIGINT PRIMARY KEY, username TEXT, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS attendance (user_id BIGINT PRIMARY KEY, status TEXT, updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS kudos (username TEXT PRIMARY KEY, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0, quota INT DEFAULT 3);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT, is_private BOOLEAN DEFAULT FALSE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT, chat_id BIGINT, msg_id BIGINT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE, assigned_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_polls (chat_id BIGINT, user_id BIGINT, end_time TIMESTAMP WITH TIME ZONE, PRIMARY KEY(chat_id, user_id));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_stats (date DATE PRIMARY KEY, uses INT DEFAULT 0, errors INT DEFAULT 0);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bug_reports (id SERIAL PRIMARY KEY, username TEXT, report TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS graveyard (username TEXT PRIMARY KEY, offboarded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), data_dump TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS audit_logs (id SERIAL PRIMARY KEY, user_id BIGINT, username TEXT, chat_id BIGINT, action_type TEXT, detail TEXT, status TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
    await app.bot.set_my_commands(get_user_menu(), scope=BotCommandScopeDefault())
    logger.info("✅ Enterprise Database Configured.")

# --- CORE CRONS ---
async def cron_daily_audit(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    yesterday = (now - datetime.timedelta(days=1)).date()
    start_dt = WIB.localize(datetime.datetime.combine(yesterday, datetime.time.min))
    end_dt = WIB.localize(datetime.datetime.combine(yesterday, datetime.time.max))
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        groups_cnt = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(CASE WHEN action_type = 'Clock In' THEN 1 END) as clock_in_cnt,
                COUNT(CASE WHEN action_type = 'Clock Out' THEN 1 END) as clock_out_cnt,
                COUNT(CASE WHEN action_type = 'Away' THEN 1 END) as away_cnt,
                COUNT(CASE WHEN action_type = 'Back' THEN 1 END) as back_cnt,
                COUNT(CASE WHEN action_type = 'Event Create' THEN 1 END) as evt_create_cnt,
                COUNT(CASE WHEN action_type = 'RSVP' THEN 1 END) as rsvp_cnt,
                COUNT(CASE WHEN action_type = 'Announcement' AND status = 'Success' THEN 1 END) as ann_sent,
                COUNT(CASE WHEN action_type = 'Announcement' AND status = 'Failed' THEN 1 END) as ann_fail,
                COUNT(CASE WHEN status = 'Failed' THEN 1 END) as err_cnt
            FROM audit_logs WHERE created_at >= $1 AND created_at <= $2
        """, start_dt, end_dt)
        top_users = await conn.fetch("SELECT username, COUNT(*) as activity FROM audit_logs WHERE created_at >= $1 AND created_at <= $2 AND username IS NOT NULL GROUP BY username ORDER BY activity DESC LIMIT 3", start_dt, end_dt)

    msg = f"🌅 **Daily Diagnostic Audit Report**\nDate: {yesterday.strftime('%d/%m/%Y')}\n\n**Groups:**\n• Total Active Groups: {groups_cnt}\n\n**Users:**\n• Clock In Count: {stats['clock_in_cnt']}\n• Clock Out Count: {stats['clock_out_cnt']}\n• Away Count: {stats['away_cnt']}\n• Back Count: {stats['back_cnt']}\n\n**Events:**\n• Created: {stats['evt_create_cnt']}\n• RSVP Count: {stats['rsvp_cnt']}\n\n**Announcements:**\n• Sent: {stats['ann_sent']}\n• Failed: {stats['ann_fail']}\n\n**System:**\n• Errors/Warnings: {stats['err_cnt']}\n\n**Top Active Users:**\n"
    for i, u in enumerate(top_users, 1): msg += f"{i}. @{u['username']} ({u['activity']} actions)\n"
    if not top_users: msg += "No activity recorded."
    await notify_admins(context.bot, pool, msg)

async def monthly_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    if now.day != 1: return 
    month_name = (now - datetime.timedelta(days=1)).strftime("%B")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        top_earner = await conn.fetchrow('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 1')
        groups = await conn.fetch('SELECT chat_id FROM active_groups')
        if top_earner:
            msg = f"🏆 **Best star earner this month ({month_name}) is @{top_earner['username']}!** 🏆\nTotal **{top_earner['monthly_points']} RAWWY Stars** earned. Incredible work! 🌟"
            for g in groups:
                try: await context.bot.send_message(g['chat_id'], msg, parse_mode="Markdown")
                except: pass
        await conn.execute("UPDATE kudos SET monthly_points = 0")

async def weekly_quota_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute("UPDATE kudos SET quota = 3")

async def daily_bday_announcement(context: ContextTypes.DEFAULT_TYPE):
    today_str = datetime.datetime.now(WIB).strftime("%m/%d")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        bday_users = await conn.fetch("SELECT username FROM birthdays WHERE bday=$1", today_str)
        target_group = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'")
    if not bday_users or not target_group: return
    msg = "🎉🎂 **HAPPY BIRTHDAY!** 🎂🎉\nPlease join me in sending the warmest wishes to:\n"
    for u in bday_users: msg += f"🎈 @{u['username']}\n"
    try: await context.bot.send_message(int(target_group), msg, parse_mode="Markdown")
    except: pass

async def poll_cleanup(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute("DELETE FROM active_polls WHERE end_time < NOW()")

# --- BASE COMMANDS ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_menus(update, context)
    await update.message.reply_text("🤖 **System Online.** Welcome to the Workspace. Use the menu to navigate features.", parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_menus(update, context)
    text = "🚀 **Workspace Guide**\n\nUse the dynamic `/` menu to browse all available tools based on your access level."
    await update.message.reply_text(text, parse_mode="Markdown")

# --- ATTENDANCE & PRESENCE ---
async def cmd_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    reason = " ".join(context.args) or "Not specified"
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO away_status (user_id, username, reason) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET reason=$3', user_id, username, reason)
        await update.message.reply_text(f"⚙️ You are now marked as Away. Reason: {reason}")
        await log_audit(pool, user_id, username, chat_id, "Away", reason, "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed to set away status.")
        await log_audit(pool, user_id, username, chat_id, "Away", str(e), "Failed")

async def cmd_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    try:
        async with pool.acquire() as conn:
            mentions = await conn.fetch('SELECT mentioner, message, chat_title, created_at FROM away_mentions WHERE away_username=$1 ORDER BY created_at ASC', username)
            res = await conn.execute('DELETE FROM away_status WHERE user_id=$1', user_id)
            await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
            if res == "DELETE 0":
                await update.message.reply_text("You are already marked as Available.")
                return await log_audit(pool, user_id, username, chat_id, "Back", "Already available", "Success")
        
        msg = "✅ You are now marked as Available.\n\n"
        if mentions:
            msg += "Here are the mentions you missed:\n"
            for m in mentions: msg += f"🔹 [{m['created_at'].astimezone(WIB).strftime('%m/%d %H:%M')}] in {m['chat_title']}\n**@{m['mentioner']}**: {m['message']}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
        await log_audit(pool, user_id, username, chat_id, "Back", "Returned", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Error updating status.")
        await log_audit(pool, user_id, username, chat_id, "Back", str(e), "Failed")

async def cmd_clockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: await conn.execute('INSERT INTO attendance (user_id, status, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET status=$2, updated_at=NOW()', user_id, 'Clocked In')
        await update.message.reply_text("✅ Clock In successful.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock In", "User clocked in", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed to clock in.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock In", str(e), "Failed")

async def cmd_clockout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: await conn.execute('INSERT INTO attendance (user_id, status, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET status=$2, updated_at=NOW()', user_id, 'Clocked Out')
        await update.message.reply_text("✅ Clock Out report submitted.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock Out", "User clocked out", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed to clock out.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock Out", str(e), "Failed")

# --- BIRTHDAYS ---
async def cmd_birthday_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    if not await is_bot_admin(username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        if len(parts) < 2: raise ValueError("Missing parameters.")
        t_uname = parts[0].replace("@", "")
        bday_str = parts[1]
        datetime.datetime.strptime(bday_str, "%d/%m")
        async with pool.acquire() as conn:
            exists = await conn.fetchval('SELECT 1 FROM birthdays WHERE username=$1', t_uname)
            if exists:
                await update.message.reply_text("❌ Birthday already exists.\nUse `/birthday_edit` to edit the input", parse_mode="Markdown")
                return await log_audit(pool, user_id, username, chat_id, "Birthday Add", "Duplicate", "Failed")
            await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', t_uname, bday_str)
        await update.message.reply_text(f"✅ Birthday added for @{t_uname}.")
        await log_audit(pool, user_id, username, chat_id, "Birthday Add", f"Added {t_uname}", "Success")
    except ValueError:
        await update.message.reply_text("❌ Failed. Use `/birthday_add @user, DD/MM`", parse_mode="Markdown")
        await log_audit(pool, user_id, username, chat_id, "Birthday Add", "Format error", "Failed")
    except Exception as e:
        await update.message.reply_text("❌ Database error.")
        await log_audit(pool, user_id, username, chat_id, "Birthday Add", str(e), "Failed")

async def cmd_birthday_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        t_uname = parts[0].replace("@", "")
        bday_str = parts[1]
        datetime.datetime.strptime(bday_str, "%d/%m")
        async with pool.acquire() as conn:
            res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE username=$2', bday_str, t_uname)
            if res == "UPDATE 0":
                await update.message.reply_text("❌ User not found.")
                return await log_audit(pool, user_id, username, update.effective_chat.id, "Birthday Edit", "Not found", "Failed")
        await update.message.reply_text(f"✅ Birthday updated for @{t_uname}.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Birthday Edit", f"Edited {t_uname}", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed. Use `/birthday_edit @user, DD/MM`", parse_mode="Markdown")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Birthday Edit", str(e), "Failed")

async def cmd_birthday_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: bdays = await conn.fetch("SELECT username, bday FROM birthdays ORDER BY bday ASC")
        if not bdays: await update.message.reply_text("📅 No birthdays recorded.")
        else: await update.message.reply_text("🎂 **Birthdays:**\n" + "\n".join([f"• @{b['username']}: {b['bday']}" for b in bdays]), parse_mode="Markdown")
    except: pass

async def cmd_setbdaychannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private": return await update.message.reply_text("❌ Run this in the target group.")
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username or str(update.effective_user.id), pool): return
    async with pool.acquire() as conn: await conn.execute("INSERT INTO config (key, value) VALUES ('bday_channel', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(update.effective_chat.id))
    await update.message.reply_text("✅ This group is now the default Birthday channel.")

# --- ANNOUNCEMENTS ---
async def cmd_announcement_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        payload = " ".join(context.args)
        if not payload: raise ValueError("Payload is empty.")
        context.bot_data['draft_announcement'] = payload
        await update.message.reply_text("✅ Announcement drafted. Use `/announcement_send` to broadcast.", parse_mode="Markdown")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Announcement", "Draft stored", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed to draft announcement. Provide text.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Announcement", str(e), "Failed")

async def cmd_announcement_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    draft = context.bot_data.get('draft_announcement')
    if not draft:
        await update.message.reply_text("❌ Failed to send announcement.\nReason: No draft found.")
        return await log_audit(pool, user_id, username, update.effective_chat.id, "Announcement", "No draft", "Failed")
    try:
        async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
        if not groups:
            await update.message.reply_text("❌ Failed to send announcement.\nReason: No target groups configured.")
            return await log_audit(pool, user_id, username, update.effective_chat.id, "Announcement", "No groups", "Failed")
        success = 0
        for g in groups:
            try:
                await context.bot.send_message(g['chat_id'], f"📢 **Announcement**\n\n{draft}", parse_mode="Markdown")
                success += 1
                await log_audit(pool, user_id, username, g['chat_id'], "Announcement", f"Sent to {g['title']}", "Success")
            except TelegramError as e:
                await log_audit(pool, user_id, username, g['chat_id'], "Announcement", f"Failed to send: {str(e)}", "Failed")
        if success > 0:
            await update.message.reply_text(f"✅ Announcement sent successfully to {success} groups.")
            context.bot_data['draft_announcement'] = None
        else:
            await update.message.reply_text("❌ Failed to send announcement.\nReason: Bot lacks permission in the targeted groups.")
    except Exception as e:
        await update.message.reply_text("❌ Failed to process announcement.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Announcement", str(e), "Failed")

async def cmd_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        args_text = " ".join(context.args)
        if "," not in args_text: raise ValueError("Format: `/admin_broadcast [ChatID|All], Message`")
        target, msg = [p.strip() for p in args_text.split(",", 1)]
        if not msg: raise ValueError("Empty message.")
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target), "title": "Target"}]
        if not groups:
            await update.message.reply_text("❌ Failed to send announcement.\nReason: No target groups.")
            return await log_audit(pool, user_id, username, update.effective_chat.id, "Broadcast", "No targets", "Failed")
        success = 0
        for g in groups:
            try:
                await context.bot.send_message(g['chat_id'], f"📢 **Broadcast**\n\n{msg}", parse_mode="Markdown")
                success += 1
                await log_audit(pool, user_id, username, g['chat_id'], "Announcement", f"Sent to {g['title']}", "Success")
            except TelegramError as e:
                await log_audit(pool, user_id, username, g['chat_id'], "Announcement", f"Failed: {str(e)}", "Failed")
        if success > 0: await update.message.reply_text(f"✅ Announcement sent successfully.")
        else: await update.message.reply_text("❌ Failed to send announcement.\nReason: Bot lacks permission.")
    except Exception as e:
        await update.message.reply_text("❌ Failed to broadcast.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Broadcast", str(e), "Failed")

# --- STARS ---
async def cmd_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Please reply to a message to give a Star!")
    giver = update.effective_user.username or str(update.effective_user.id)
    receiver = update.message.reply_to_message.from_user.username or str(update.message.reply_to_message.from_user.id)
    if update.message.reply_to_message.from_user.is_bot: return await update.message.reply_text("❌ Bots cannot receive Stars.")
    if giver == receiver: return await update.message.reply_text("❌ You cannot send Stars to yourself.")
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
            q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
            if q <= 0: return await update.message.reply_text("❌ You have depleted your Star Quota for this week.")
            await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
            await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
            score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
        await update.message.reply_text(f"🌟 **Star Sent!**\n@{receiver} received a Star from @{giver}!\nTotal Stars: {score}")
        await log_audit(pool, update.effective_user.id, giver, update.effective_chat.id, "Star Sent", f"To {receiver}", "Success")
        try: await context.bot.send_message(update.effective_user.id, f"🌟 You sent a star! Quota left: **{q - 1}**")
        except: pass
    except Exception as e:
        await update.message.reply_text("❌ Error processing Star.")
        await log_audit(pool, update.effective_user.id, giver, update.effective_chat.id, "Star Sent", str(e), "Failed")

async def cmd_myquota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 You have **{q} Star Quota** left this week.")

async def cmd_mystar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: pts = await conn.fetchval('SELECT monthly_points FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 You have **{pts or 0} RAWWY Stars** this month.")

async def cmd_totalstar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: pts = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 You have collected **{pts or 0} RAWWY Stars** all-time.")

async def cmd_checkquota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: target = " ".join(context.args).replace("@", "").strip()
    except: target = ""
    if not target: return await context.bot.send_message(update.effective_user.id, "❌ Usage: `/checkquota all` or `@user`")
    async with pool.acquire() as conn:
        if target.lower() == 'all':
            recs = await conn.fetch('SELECT username, quota, monthly_points, all_time_points FROM kudos')
            msg = "🌟 **Team Stars Audit**\n" + "\n".join([f"@{r['username']} - Q: {r['quota']} | M: {r['monthly_points']} | T: {r['all_time_points']}" for r in recs]) if recs else "No records."
        else:
            r = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
            msg = f"🌟 **@{target} Audit**\nQuota left: {r['quota']}\nMonthly: {r['monthly_points']}\nTotal: {r['all_time_points']}" if r else "User not found."
    await context.bot.send_message(update.effective_user.id, msg)

async def cmd_admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 3)]
        if len(parts) != 4: raise ValueError
        t, field, act, amt = parts[0].replace("@", ""), parts[1].lower(), parts[2].lower(), int(parts[3])
        col = 'monthly_points' if field == 'monthly' else 'all_time_points' if field == 'total' else 'quota'
        async with pool.acquire() as conn:
            await conn.execute(f'INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
            if act == "set": await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, t)
            elif act == "add": await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, t)
            elif act == "sub": await conn.execute(f'UPDATE kudos SET {col}={col}-$1 WHERE username=$2', amt, t)
        await log_audit(pool, update.effective_user.id, username, update.effective_chat.id, "Admin Star", f"Modified {t}", "Success")
        await context.bot.send_message(update.effective_user.id, f"✅ Updated stars for @{t}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, "❌ Usage: `/admin_stars @user, quota/monthly/total, set/add/sub, Amt`", parse_mode="Markdown")

# --- EVENTS ---
async def cmd_event_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 2)]
        if len(parts) < 3: raise ValueError
        title, e_time_str, rem_str = parts[0], parts[1], parts[2]
        e_time = WIB.localize(datetime.datetime.strptime(e_time_str, "%m/%d/%Y %H.%M"))
        if e_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ Cannot schedule in the past.")
        
        kb = [[InlineKeyboardButton("✅ Going", callback_data="rsvp_temp_Going"), InlineKeyboardButton("❌ Not Going", callback_data="rsvp_temp_Not Going")]]
        msg = await update.message.reply_text(f"📅 **{title} scheduled!**\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\nNo RSVPs yet.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        try: await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
        except: pass
        
        async with pool.acquire() as conn:
            e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by, chat_id, msg_id) VALUES ($1, $2, $3, $4, $5) RETURNING id', title, e_time, username, update.effective_chat.id, msg.message_id)
        
        new_kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not Going")]]
        await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
        
        await log_audit(pool, update.effective_user.id, username, update.effective_chat.id, "Event Create", f"Created {title}", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Format: `/event_create Title, MM/DD/YYYY HH.MM, RemMins`", parse_mode="Markdown")
        await log_audit(pool, update.effective_user.id, username, update.effective_chat.id, "Event Create", str(e), "Failed")

async def cmd_event_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if not events: return await update.message.reply_text("📅 No upcoming events.")
    await update.message.reply_text("📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")

async def cmd_cancelevent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        e_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
        async with pool.acquire() as conn:
            ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
            if not ev: return await context.bot.send_message(update.effective_user.id, "❌ Event not found.")
            await conn.execute('DELETE FROM events WHERE id=$1', e_id)
        try: await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
        except: pass
        await context.bot.send_message(update.effective_user.id, "✅ Event cancelled.")
        await log_audit(pool, update.effective_user.id, username, update.effective_chat.id, "Event Cancel", f"Cancelled {e_id}", "Success")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, "❌ Usage: `/cancelevent ID`")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if "temp" in q.data: return await q.answer("Initializing...")
    _, e_id, status = q.data.split("_")
    username = q.from_user.username or str(q.from_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status=$3', int(e_id), username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title, event_time FROM events WHERE id=$1', int(e_id))
    if not event: return await q.answer("Event deleted.")
    text = f"📅 **{event['title']}**\n🕒 {event['event_time'].astimezone(WIB).strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\n"
    for r in all_rsvps: text += f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n"
    await q.edit_message_text(text, reply_markup=q.message.reply_markup, parse_mode="Markdown")
    await q.answer(status)
    await log_audit(pool, q.from_user.id, username, q.message.chat.id, "RSVP", f"RSVP {status} for {e_id}", "Success")

# --- POLLS & UTILS ---
async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    username = update.effective_user.username or str(update.effective_user.id)
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        if len(parts) < 4: raise ValueError
        hours = int(parts[1])
        dur = hours * 3600
        msg = await context.bot.send_poll(update.effective_chat.id, parts[0], parts[2:], is_anonymous=False, allows_multiple_answers=True, open_period=dur)
        async with pool.acquire() as conn: await conn.execute("INSERT INTO active_polls (chat_id, user_id, end_time) VALUES ($1, $2, NOW() + INTERVAL '1 sec' * $3) ON CONFLICT DO NOTHING", update.effective_chat.id, update.effective_user.id, dur)
        await log_audit(pool, update.effective_user.id, username, update.effective_chat.id, "Poll Create", f"Created poll", "Success")
    except Exception as e: 
        await update.message.reply_text("❌ Format: `/poll Question, Hours, Opt1, Opt2`")
        await log_audit(pool, update.effective_user.id, username, update.effective_chat.id, "Poll Create", str(e), "Failed")

async def cmd_raffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: users = await conn.fetch("SELECT username FROM users WHERE username IS NOT NULL")
    if not users: return await update.message.reply_text("❌ No users available.")
    winner = random.choice(users)['username']
    await update.message.reply_text(f"🎲 Raffle Winner: @{winner}!")
    await log_audit(pool, update.effective_user.id, update.effective_user.username or str(update.effective_user.id), update.effective_chat.id, "Raffle", f"Winner: {winner}", "Success")

# --- LIBRARY ---
async def cmd_addlib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    raw_args = " ".join(context.args)
    try:
        is_private = False
        if raw_args.lower().endswith(", private"):
            is_private = True
            raw_args = raw_args[:-9].strip()
            await delete_cmd(update)
        parts = [p.strip() for p in raw_args.split(",", 1)]
        if len(parts) < 2: raise ValueError
        name, content = parts[0].lower(), parts[1]
        async with pool.acquire() as conn:
            if await conn.fetchval('SELECT name FROM library WHERE name=$1', name): return await update.message.reply_text("❌ Name exists.")
            await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4)', name, content, username, is_private)
        await context.bot.send_message(update.effective_user.id if is_private else update.effective_chat.id, f"✅ Asset **'{name}'** added! {'🔒' if is_private else ''}", parse_mode="Markdown")
        await log_audit(pool, update.effective_user.id, username, update.effective_chat.id, "Library Add", f"Added {name}", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Format: `/addlib Name, Content, [private]`")

async def cmd_editlib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        name, content = parts[0].lower(), parts[1]
        async with pool.acquire() as conn:
            asset = await conn.fetchrow('SELECT added_by FROM library WHERE name=$1', name)
            if not asset: return await update.message.reply_text("❌ Not found.")
            if asset['added_by'] != username and not await is_bot_admin(username, pool): return await update.message.reply_text("❌ Permission denied.")
            await conn.execute('UPDATE library SET content=$1 WHERE name=$2', content, name)
        await update.message.reply_text(f"✅ Asset **'{name}'** updated.", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Format: `/editlib Name, Content`")

async def cmd_getlib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        name = [p.strip() for p in " ".join(context.args).split(",")][0].lower()
        async with pool.acquire() as conn: r = await conn.fetchrow('SELECT content, is_private, added_by FROM library WHERE name=$1', name)
        if not r: return await update.message.reply_text("❌ Not found.")
        if r['is_private']:
            await delete_cmd(update)
            if r['added_by'] != username: return await context.bot.send_message(update.effective_user.id, "❌ Private file.")
            await context.bot.send_message(update.effective_user.id, f"🔒 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
        else: await update.message.reply_text(f"📂 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Usage: `/getlib Name`")

async def cmd_dellib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        name = [p.strip() for p in " ".join(context.args).split(",")][0].lower()
        async with pool.acquire() as conn:
            if await conn.execute('DELETE FROM library WHERE name=$1', name) == "DELETE 0": return await context.bot.send_message(update.effective_user.id, "❌ Not found.")
        await context.bot.send_message(update.effective_user.id, f"✅ Asset '{name}' deleted.")
    except: pass

async def cmd_library(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
    if not recs: return await update.message.reply_text("📚 Library is empty.")
    msg = "📚 **Library**\n" + "\n".join([f"• {'🔒' if r['is_private'] else '📂'} `{r['name']}`" for r in recs if not r['is_private'] or r['added_by'] == username])
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- TASKS ---
async def cmd_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assigner = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try: 
        parts = [p.strip() for p in " ".join(context.args).rsplit(",", 2)]
        a, m, d = parts[0].replace("@", ""), int(parts[1]), parts[2]
        dl = datetime.datetime.now(WIB) + datetime.timedelta(minutes=m)
        async with pool.acquire() as conn: 
            t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', a, d, dl, assigner)
        await update.message.reply_text(f"📋 **Task Assigned!**\nTo: @{a}\n📝 {d}\n⏳ Deadline: {dl.strftime('%H:%M WIB')}", parse_mode="Markdown")
        await log_audit(pool, update.effective_user.id, assigner, update.effective_chat.id, "Task Assign", f"Assigned to {a}", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Format: `/assign @user, Minutes, Task description`")
        await log_audit(pool, update.effective_user.id, assigner, update.effective_chat.id, "Task Assign", str(e), "Failed")

async def cmd_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        t_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
        async with pool.acquire() as conn:
            task = await conn.fetchrow('SELECT assignee, status FROM tasks WHERE id=$1', t_id)
            if not task: return await update.message.reply_text("❌ Task not found.")
            if task['assignee'] != username: return await update.message.reply_text("❌ Only the assignee can complete this.")
            await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
        await update.message.reply_text(f"✅ Task `{t_id}` completed.", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Format: `/complete ID`")

async def cmd_canceltask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        t_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
        async with pool.acquire() as conn: await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
        await context.bot.send_message(update.effective_user.id, "🗑️ Task cancelled.")
    except: pass

async def cmd_mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: tasks = await conn.fetch("SELECT id, task_desc FROM tasks WHERE status='Pending' AND assignee=$1", username)
    if not tasks: return await update.message.reply_text("🎉 No pending tasks!")
    await update.message.reply_text("📋 **Your Tasks**\n" + "\n".join([f"🔹 `{t['id']}` | {t['task_desc']}" for t in tasks]), parse_mode="Markdown")

async def cmd_grouptasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username or str(update.effective_user.id), pool): return
    async with pool.acquire() as conn: tasks = await conn.fetch("SELECT id, assignee, task_desc FROM tasks WHERE status='Pending'")
    if not tasks: msg = "🎉 Zero pending tasks globally."
    else: msg = "📋 **Global Tasks**\n" + "\n".join([f"🔹 `{t['id']}` | @{t['assignee']} | {t['task_desc']}" for t in tasks])
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: pass

# --- SYSTEM & ADMIN ---
async def cmd_admin_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username or str(update.effective_user.id), pool): return
    async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title, member_count FROM active_groups")
    msg = "📊 **Active Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` | {g['title']} ({g['member_count'] or 0} members)" for g in groups]) if groups else "No groups."
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: pass

async def cmd_groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username or str(update.effective_user.id), pool): return
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text(f"📌 **Group Info**\nTitle: `{update.effective_chat.title}`\nID: `{update.effective_chat.id}`", parse_mode="Markdown")
    else:
        async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
        msg = "📈 **Tracked Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups]) if groups else "No groups."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def cmd_systemstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username or str(update.effective_user.id), pool): return
    async with pool.acquire() as conn:
        g_cnt = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
        u_cnt = await conn.fetchval("SELECT COUNT(*) FROM users")
        a_cnt = await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
    await update.message.reply_text(f"⚙️ **Live System Metrics:**\n• Tracked Groups: {g_cnt}\n• Tracked Users: {u_cnt}\n• Logged Actions: {a_cnt}", parse_mode="Markdown")

async def cmd_auditlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    now = datetime.datetime.now(WIB)
    start_dt = WIB.localize(datetime.datetime.combine(now.date(), datetime.time.min))
    report = await compile_audit_report(pool, start_dt, now, now.strftime("%d/%m/%Y (Up to now)"))
    try:
        await context.bot.send_message(user_id, report, parse_mode="Markdown")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Audit Pull", "Pulled manual report", "Success")
    except Exception as e:
        await log_audit(pool, user_id, username, update.effective_chat.id, "Audit Pull", str(e), "Failed")

# --- SUPER ADMIN ---
async def super_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    try:
        target = context.args[0].replace("@", "").lower()
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn: await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
        await update.message.reply_text(f"✅ @{target} promoted.")
    except: await update.message.reply_text("❌ `/addadmin @user`")

async def super_deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    try:
        target = context.args[0].replace("@", "").lower()
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn: await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
        await update.message.reply_text(f"🗑️ @{target} demoted.")
    except: await update.message.reply_text("❌ `/deladmin @user`")

async def super_listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: admins = await conn.fetch('SELECT username FROM bot_admins')
    await update.message.reply_text("👑 **Admins:**\n" + "\n".join([f"• @{a['username']}" for a in admins]))

async def super_removemember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    try:
        target = context.args[0].replace("@", "")
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn:
            k = await conn.fetchrow("SELECT all_time_points FROM kudos WHERE username=$1", target)
            c = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Completed' AND assignee=$1", target)
            data_dump = f"Stars: {k['all_time_points'] if k else 0} | Tasks Done: {c}"
            await conn.execute("INSERT INTO graveyard (username, data_dump) VALUES ($1, $2)", target, data_dump)
            await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
            await conn.execute('DELETE FROM kudos WHERE username=$1', target)
            await conn.execute('DELETE FROM birthdays WHERE username=$1', target)
            await conn.execute('DELETE FROM away_status WHERE username=$1', target)
        await update.message.reply_text(f"🪦 @{target} offboarded.")
    except: await update.message.reply_text("❌ `/removemember @user`")

async def super_graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: gy = await conn.fetch('SELECT * FROM graveyard')
    msg = "🪦 **Graveyard**\n" + "\n".join([f"• @{g['username']} (Left: {g['offboarded_at'].strftime('%m/%d/%Y')})" for g in gy]) if gy else "Empty."
    await update.message.reply_text(msg)

async def super_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE kudos, tasks, library, events, rsvps, away_status, away_mentions CASCADE")
    await update.message.reply_text("☢️ Factory wipe complete.")

# --- TRACKERS ---
async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result: return
    chat = result.chat
    status = result.new_chat_member.status
    pool = context.bot_data.get('db_pool')
    
    if status in ['member', 'administrator']:
        inviter = result.from_user.username or str(result.from_user.id)
        try: member_count = await chat.get_member_count()
        except: member_count = 0
            
        if not await is_bot_admin(inviter, pool):
            try:
                await context.bot.send_message(chat.id, "❌ **Access Denied.** Unauthorized deploy.")
                await context.bot.leave_chat(chat.id)
                await log_audit(pool, result.from_user.id, inviter, chat.id, "Group Join", "Unauthorized", "Failed")
            except: pass
            return
            
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO active_groups (chat_id, title, member_count) VALUES ($1, $2, $3) ON CONFLICT (chat_id) DO UPDATE SET title=$2, member_count=$3', chat.id, chat.title, member_count)
        
        await notify_admins(context.bot, pool, f"✅ **Bot Joined Group**\nName: `{chat.title}`\nID: `{chat.id}`\nMembers: {member_count}")
        await log_audit(pool, result.from_user.id, inviter, chat.id, "Group Join", f"Joined {chat.title}", "Success")
        
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)
        await notify_admins(context.bot, pool, f"⚠️ **Bot Left Group**\nName: `{chat.title}`\nID: `{chat.id}`")
        await log_audit(pool, context.bot.id, context.bot.username, chat.id, "Group Leave", f"Left {chat.title}", "Success")

async def global_message_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    pool = context.bot_data.get('db_pool')
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username=$2", user_id, username)
        
        # Passive group tracking
        chat = update.effective_chat
        if chat.type in ['group', 'supergroup']:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO NOTHING', chat.id, chat.title)

async def cmd_bugreport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: return await update.message.reply_text("Please type: `/bugreport [issue]`")
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", username, text)
    await update.message.reply_text("🐛 Bug securely filed.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception handled:", exc_info=context.error)
    pool = context.bot_data.get('db_pool')
    if pool: await log_audit(pool, 0, "System", 0, "Error", str(context.error), "Failed")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command.")

# --- RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db
    app.add_error_handler(error_handler)

    # CRONS
    app.job_queue.run_daily(cron_daily_audit, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(monthly_leaderboard, datetime.time(hour=13, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(weekly_quota_reset, datetime.time(hour=0, minute=0, tzinfo=WIB), days=(0,))
    app.job_queue.run_daily(daily_bday_announcement, datetime.time(hour=10, minute=0, tzinfo=WIB))
    app.job_queue.run_repeating(poll_cleanup, interval=3600)

    # CORE COMMANDS
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clockin", cmd_clockin))
    app.add_handler(CommandHandler("clockout", cmd_clockout))
    app.add_handler(CommandHandler("away", cmd_away))
    app.add_handler(CommandHandler("back", cmd_back))
    
    # BIRTHDAYS
    app.add_handler(CommandHandler("birthday_add", cmd_birthday_add))
    app.add_handler(CommandHandler("birthday_edit", cmd_birthday_edit))
    app.add_handler(CommandHandler("birthday_list", cmd_birthday_list))
    app.add_handler(CommandHandler("setbdaychannel", cmd_setbdaychannel))
    app.add_handler(CommandHandler("addbday", cmd_birthday_add)) # Alias
    app.add_handler(CommandHandler("editbday", cmd_birthday_edit)) # Alias
    
    # STARS
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("myquota", my_quota))
    app.add_handler(CommandHandler("mystar", my_star))
    app.add_handler(CommandHandler("totalstar", total_star))
    app.add_handler(CommandHandler("checkquota", check_quota))
    app.add_handler(CommandHandler("admin_stars", admin_stars))
    
    # EVENTS
    app.add_handler(CommandHandler("event_create", cmd_event_create))
    app.add_handler(CommandHandler("newevent", cmd_event_create)) # Alias
    app.add_handler(CommandHandler("event_list", cmd_event_list))
    app.add_handler(CommandHandler("events", cmd_event_list)) # Alias
    app.add_handler(CommandHandler("cancelevent", cmd_cancelevent))
    
    # POLLS & RAFFLES
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("raffle", cmd_raffle))
    
    # LIBRARY
    app.add_handler(CommandHandler("addlib", cmd_addlib))
    app.add_handler(CommandHandler("editlib", cmd_editlib))
    app.add_handler(CommandHandler("getlib", cmd_getlib))
    app.add_handler(CommandHandler("dellib", cmd_dellib))
    app.add_handler(CommandHandler("library", cmd_library))
    
    # TASKS
    app.add_handler(CommandHandler("assign", cmd_assign))
    app.add_handler(CommandHandler("complete", cmd_complete))
    app.add_handler(CommandHandler("mytasks", cmd_mytasks))
    app.add_handler(CommandHandler("canceltask", cmd_canceltask))
    app.add_handler(CommandHandler("grouptasks", cmd_grouptasks))
    
    # ANNOUNCEMENTS & ADMIN
    app.add_handler(CommandHandler("announcement_create", cmd_announcement_create))
    app.add_handler(CommandHandler("announcement_send", cmd_announcement_send))
    app.add_handler(CommandHandler("admin_broadcast", cmd_admin_broadcast))
    app.add_handler(CommandHandler("announce", cmd_admin_broadcast)) # Alias
    app.add_handler(CommandHandler("admin_groups", cmd_admin_groups))
    app.add_handler(CommandHandler("groupid", cmd_groupid))
    app.add_handler(CommandHandler("systemstatus", cmd_systemstatus))
    app.add_handler(CommandHandler("auditlog", cmd_auditlog))
    app.add_handler(CommandHandler("getlog", cmd_auditlog)) # Alias
    app.add_handler(CommandHandler("attendance", attendance))
    
    # SUPER ADMIN
    app.add_handler(CommandHandler("addadmin", super_addadmin))
    app.add_handler(CommandHandler("deladmin", super_deladmin))
    app.add_handler(CommandHandler("listadmins", super_listadmins))
    app.add_handler(CommandHandler("removemember", super_removemember))
    app.add_handler(CommandHandler("graveyard", super_graveyard))
    app.add_handler(CommandHandler("super_reset", super_reset))
    
    app.add_handler(CommandHandler("bugreport", cmd_bugreport))

    # TRACKERS
    app.add_handler(CallbackQueryHandler(rsvp_callback, pattern="^rsvp_"))
    app.add_handler(ChatMemberHandler(security_track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_message_tracker))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logger.info("Starting Enterprise Audit System...")
    app.run_polling()

if __name__ == "__main__":
    main()
