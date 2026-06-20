import logging, datetime, pytz, os, asyncpg
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat, BotCommandScopeDefault, BotCommandScopeChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters, ContextTypes

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

async def delete_cmd(update: Update):
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
    from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeDefault())
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeAllPrivateChats())
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeAllGroupChats())
    
    await schedule_bday_job(app)
    logger.info("✅ Enterprise Database & Scoped Menus Configured!")

# --- CORE INTERFACE ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
    await update.message.reply_text("✅ **Hello! [RW] Nukhba Manager is fully operational.** Type `/help` to see the command manual.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
        
    help_text = (
        "🚀 *[RW] Nukhba Manager Guide*\n\n"
        "📅 *1/ Events*\n`/newevent Title , MM/DD/YYYY HH.MM , RemMins` - Schedules a pinned event.\n`/events` - View upcoming events.\n\n"
        "📊 *2/ Polls*\n`/poll Question , Opt1 , Opt2` - Launches interactive poll builder.\n\n"
        "🌟 *3/ RAWWY Stars*\n`/thanks` (Reply) - Give 1 Star.\n`/myquota` - Check remaining sends.\n`/mystar` - Stars earned this month.\n`/totalstar` - Stars earned all-time.\n\n"
        "📚 *4/ Library*\n`/addlib Name , Content` - Save an asset.\n`/editlib Name , Content` - Edit your asset.\n`/dellib Name` - Delete your asset.\n`/getlib Name` - Pull an asset.\n`/library` - Browse everything.\n\n"
        "⚡ *5/ Tasks*\n`/assign @user , 60 , Task description` - Deadline in 60-480m.\n`/complete ID` - Close task.\n`/mytasks` - View your active tasks.\n\n"
        "🏖️ *6/ Away Mode*\n`/away Reason , MM/DD/YYYY HH.MM` - Set away status.\n`/back` - Return early and receive missed mentions.\n\n"
        "🐛 *Extras*\n`/bugreport Your issue here`"
    )

    is_adm = await is_bot_admin(username, pool)
    if is_adm:
        help_text += (
            "\n\n🔐 *[RW] NUKHBA ADMIN SUITE*\n\n"
            "🎂 *Birthdays*\n`/addbday @user , MM/DD`\n`/editbday @user , MM/DD`\n`/delbday @user`\n`/setbdaychannel` (Run in target group)\n`/setbdaytime HH:MM`\n`/bdayconfig` | `/listbdays`\n`/addbday_batch` | `/delbday_batch`\n\n"
            "🌟 *Stars & Quotas*\n`/checkquota all` or `@user`\n`/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`\n\n"
            "⚙️ *Management*\n`/attendance` - See who is Away in this group.\n`/forceback @user` - Force stop user away status.\n`/grouptasks` - See pending tasks in the database.\n`/cancelevent ID` | `/canceltask ID` | `/cancelpoll` (Reply)\n`/addlib_batch` | `/dellib_batch`\n\n"
            "📢 *System*\n`/announce [ChatID/All] , Message`\n`/editannounce ID , New Msg` | `/delannounce ID`\n`/groupid` - Check current group or all groups.\n`/auditlog` - Pull diagnostics log now."
        )
        if await is_super(username):
            help_text += (
                "\n\n👑 *SUPER OWNER EXCLUSIVES*\n"
                "🛡️ *Access:* `/addadmin @user` | `/deladmin @user` | `/listadmins`\n"
                "🛑 *Offboarding:* `/removemember @user` (Archives to graveyard)\n"
                "🪦 *Graveyard:* `/graveyard`\n"
                "📈 *System:* `/botstatus`\n"
                "☢️ *Wipe:* `/super_reset [stars/tasks/library/events/away/birthdays/all]`"
            )

    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("✅ I have securely sent the manual to your Direct Messages!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("❌ I cannot send you a DM yet. Please start a private chat with me first!")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ **Unknown Command.** Please type `/help` to see valid commands or check with your admin.", parse_mode="Markdown")

# --- CRONS & LOGS ---
async def generate_audit_report(pool, target_date: datetime.date) -> str:
    now = datetime.datetime.now(WIB)
    start_dt = WIB.localize(datetime.datetime.combine(target_date, datetime.time.min))
    end_dt = WIB.localize(datetime.datetime.combine(target_date, datetime.time.max))
    
    async with pool.acquire() as conn:
        active_groups = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
        away_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Away Status' AND status='Set' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        back_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Away Status' AND status='Removed' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        
        events_created = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Event Created' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        events_updated = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Event Updated' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        rsvp_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='RSVP' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        
        ann_sent = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Announcement' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        ann_failed = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Announcement' AND status='Failed' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        
        sys_errors = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE status='Error' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        sys_warns = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE status='Warning' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        
    msg = f"✅ 🌅 **Daily Diagnostic Audit Report**\nDate: {target_date.strftime('%d/%m/%Y')} | Time: {now.strftime('%H:%M')} WIB\n\n"
    msg += f"**Groups:**\n• Total Active Groups: {active_groups}\n\n"
    msg += f"**Users:**\n• Away Count: {away_count}\n• Back Count: {back_count}\n\n"
    msg += f"**Events:**\n• Created: {events_created}\n• Updated: {events_updated}\n• RSVP Count: {rsvp_count}\n\n"
    msg += f"**Announcements:**\n• Sent: {ann_sent}\n• Failed: {ann_failed}\n\n"
    msg += f"**System:**\n• Errors: {sys_errors}\n• Warnings: {sys_warns}"
    return msg

async def daily_morning_log(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    target_date = datetime.datetime.now(WIB).date()
    try:
        msg = await generate_audit_report(pool, target_date)
        async with pool.acquire() as conn:
            admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
            super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
        
        admin_ids = {a['user_id'] for a in admins}
        if super_id: admin_ids.add(super_id)
        
        for uid in admin_ids:
            try: await context.bot.send_message(uid, msg, parse_mode="Markdown")
            except: pass
    except Exception as e:
        logger.error(f"Failed to run daily morning log: {e}")

async def monthly_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    if now.day != 1: return 
    
    month_name = (now - datetime.timedelta(days=1)).strftime("%B")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        top_earner = await conn.fetchrow('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 1')
        groups = await conn.fetch('SELECT chat_id FROM active_groups')
        
        if top_earner:
            msg = f"🏆 **Best star earner this month ({month_name}) is @{top_earner['username']}!** 🏆\n\nTotal **{top_earner['monthly_points']} RAWWY Stars** earned. Absolutely incredible work! 🌟 Keep up the amazing momentum, team!"
            for g in groups:
                try: await context.bot.send_message(g['chat_id'], msg, parse_mode="Markdown")
                except: pass
        await conn.execute("UPDATE kudos SET monthly_points = 0")

async def weekly_quota_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute("UPDATE kudos SET quota = 3")

async def schedule_bday_job(app: Application):
    pool = app.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            t_val = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'")
        
        hour, minute = 10, 0
        if t_val:
            try: hour, minute = map(int, t_val.split(':'))
            except: pass
            
        for job in app.job_queue.get_jobs_by_name('bday_cron'):
            job.schedule_removal()
            
        app.job_queue.run_daily(daily_bday_announcement, datetime.time(hour=hour, minute=minute, tzinfo=WIB), name='bday_cron')
        logger.info(f"✅ Birthday alerts actively scheduled for {hour:02d}:{minute:02d} WIB.")
    except Exception as e:
        logger.error(f"Failed to schedule birthday job: {e}")

async def daily_bday_announcement(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    today_str = now.strftime("%m/%d")
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        bday_users = await conn.fetch("SELECT username FROM birthdays WHERE bday=$1", today_str)
        target_group = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'")
        
    if not bday_users or not target_group: return
    
    msg = "🎉🎂 **HAPPY BIRTHDAY!** 🎂🎉\n\n"
    msg += "Please join me in sending the warmest wishes to our amazing team member(s):\n"
    for u in bday_users: msg += f"🎈 @{u['username']}\n"
    msg += "\nWe hope you have an incredible day filled with joy, and a fantastic year ahead!"
    
    try: await context.bot.send_message(int(target_group), msg, parse_mode="Markdown")
    except: pass

async def poll_cleanup(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_polls WHERE end_time < NOW()")

# --- FORTRESS SECURITY & GLOBAL TRACKER ---
async def security_track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result: return
    chat = result.chat
    status = result.new_chat_member.status
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
        super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
    admin_ids = {a['user_id'] for a in admins}
    if super_id: admin_ids.add(super_id)
    
    now_str = datetime.datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S WIB')
    
    if status in ['member', 'administrator']:
        inviter = result.from_user.username or str(result.from_user.id)
        if not await is_bot_admin(inviter, pool):
            try:
                await context.bot.send_message(chat.id, "❌ **Access Denied.** I am a private enterprise system. You are not authorized to deploy me here. Leaving chat.")
                await context.bot.leave_chat(chat.id)
                await log_action(pool, update.effective_user.id, chat.id, "Security", "Warning", f"Unauthorized invite by @{inviter}")
            except: pass
            return
            
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
        
        try: await context.bot.send_message(chat.id, "✅ **Authorization confirmed.** [RW] Nukhba Manager is locked in and syncing data.")
        except: pass
        
        member_count = await chat.get_member_count()
        adm_msg = f"✅ **Bot Joined Group**\n\nGroup Name: {chat.title}\nGroup ID: `{chat.id}`\nMember Count: {member_count}\nTime: {now_str}"
        for uid in admin_ids:
            try: await context.bot.send_message(uid, adm_msg, parse_mode="Markdown")
            except: pass
            
        await log_action(pool, update.effective_user.id, chat.id, "System", "Success", "Bot joined group successfully.")
        
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)
            
        adm_msg = f"⚠️ **Bot Left Group**\n\nGroup Name: {chat.title}\nGroup ID: `{chat.id}`\nTime: {now_str}"
        for uid in admin_ids:
            try: await context.bot.send_message(uid, adm_msg, parse_mode="Markdown")
            except: pass
            
        await log_action(pool, update.effective_user.id, chat.id, "System", "Warning", "Bot left or was removed from group.")

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    pool = context.bot_data.get('db_pool')
    now = datetime.datetime.now(WIB)
    username = update.effective_user.username or str(update.effective_user.id)
    
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET user_id=$2", username, update.effective_user.id)
            await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, 1, 0) ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + 1")
            
            chat = update.effective_chat
            if chat.type in ['group', 'supergroup']:
                await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
                
            text = update.message.text
            
            is_away = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username)
            if is_away:
                for j in context.job_queue.get_jobs_by_name(f"away_{username}"): j.schedule_removal()
                recap_msg = await process_return(username, pool, context.bot)
                await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Removed", f"@{username} auto-returned via chat")
                
                try:
                    uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
                    if uid: await context.bot.send_message(uid, f"✅ {recap_msg}", parse_mode="Markdown")
                except: pass
            
            aways = await conn.fetch('SELECT username, reason, end_time, last_notified FROM away_status')
            for a in aways:
                if f"@{a['username']}" in text:
                    await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], username, text, update.effective_chat.title or "DM")
                    if not a['last_notified'] or (now - a['last_notified']).total_seconds() > 3600:
                        rem = a['end_time'].astimezone(WIB) - now
                        if rem.total_seconds() > 0:
                            d = rem.days; h = rem.seconds // 3600; m = (rem.seconds % 3600) // 60
                            if d > 0: t_str = f"{d} days, {h} hours, and {m} minutes"
                            elif h > 0: t_str = f"{h} hours and {m} minutes"
                            else: t_str = f"{m} minutes"
                            await update.message.reply_text(f"Just a polite heads up, @{a['username']} is currently away for another {t_str}.\n(Reason: {a['reason']})")
                            await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "System", "Error", f"Global tracker exception: {e}")

async def report_bug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: return await update.message.reply_text("❌ Please type: `/bugreport [explain issue here]`", parse_mode="Markdown")
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", username, text)
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Bug Report", "Success", f"Bug reported by @{username}")
        await update.message.reply_text("✅ 🐛 Bug securely filed for review.")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception handled:", exc_info=context.error)
    pool = context.bot_data.get('db_pool')
    if pool:
        uid = update.effective_user.id if update and hasattr(update, 'effective_user') and update.effective_user else 0
        cid = update.effective_chat.id if update and hasattr(update, 'effective_chat') and update.effective_chat else 0
        await log_action(pool, uid, cid, "System Exception", "Error", str(context.error))
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO bot_stats (date, errors) VALUES (CURRENT_DATE, 1) ON CONFLICT (date) DO UPDATE SET errors = bot_stats.errors + 1")

# --- 1/ EVENTS ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 2) if p.strip()]
        if len(parts) < 3: raise ValueError
        title = parts[0]
        e_time = WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H.%M"))
        rem = int(parts[2])
        if e_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ I cannot schedule events in the past. Please select a future date and time.")
    except ValueError:
        return await update.message.reply_text("❌ Time format error. Please strictly use `MM/DD/YYYY HH.MM`.")
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Created", "Error", str(e))
        return await update.message.reply_text("❌ Incorrect format. Please use: `/newevent Title , MM/DD/YYYY HH.MM , RemMins`")
    
    kb = [[InlineKeyboardButton("✅ Going", callback_data="rsvp_temp_Going"), InlineKeyboardButton("❌ Not Going", callback_data="rsvp_temp_Not Going")]]
    msg = await update.message.reply_text(f"✅ 📅 **{title} has been scheduled!**\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\nNo RSVPs yet.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    
    try: await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except: pass 
    
    async with pool.acquire() as conn: 
        e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by, chat_id, msg_id) VALUES ($1, $2, $3, $4, $5) RETURNING id', title, e_time, username, update.effective_chat.id, msg.message_id)
    
    new_kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not Going")]]
    await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
    
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
    context.job_queue.run_once(unpin_event, when=e_time, data={"chat_id": update.effective_chat.id, "msg_id": msg.message_id}, name=f"event_unpin_{e_id}")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Created", "Success", f"Event '{title}' created")

async def unpin_event(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.unpin_chat_message(chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id'])
    except: pass

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        raw_args = " ".join(context.args)
        id_part, rest = raw_args.split(",", 1)
        title_part, time_str, rem_str = [p.strip() for p in rest.rsplit(",", 2)]
        e_id = int(id_part.strip()); title = title_part; e_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M")); rem = int(rem_str)
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Updated", "Error", str(e))
        return await update.message.reply_text("❌ Please use: `/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`")
    
    try:
        async with pool.acquire() as conn: 
            ev = await conn.fetchrow('SELECT created_by FROM events WHERE id=$1', e_id)
            if not ev: return await update.message.reply_text("❌ Event not found.")
            if ev['created_by'] != username and not await is_bot_admin(username, pool):
                return await update.message.reply_text("❌ Only the event creator or an admin can edit this event.")
                
            await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, e_id)
            
        for job in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"): job.schedule_removal()
        
        context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Updated", "Success", f"Event ID {e_id} updated")
        await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
        if not events: return await update.message.reply_text("❌ No upcoming events scheduled.")
        await update.message.reply_text("✅ 📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data.startswith("rsvp_temp"): return await q.answer("Initializing, please wait a second...")
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
    await log_action(pool, q.from_user.id, update.effective_chat.id, "RSVP", "Success", f"User {username} RSVP {status} to event {e_id}")

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    if not r: return
    await context.bot.send_message(context.job.chat_id, f"⏰ Hey everyone! The event **{context.job.data['title']}** is starting very soon.\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: e_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/cancelevent ID`")
    
    try:
        async with pool.acquire() as conn: 
            ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
            if not ev: return await context.bot.send_message(update.effective_user.id, "❌ Event not found.")
            await conn.execute('DELETE FROM events WHERE id=$1', e_id)
            
        for j in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"): j.schedule_removal()
        for j in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"): j.schedule_removal()
        try: await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
        except: pass
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Cancelled", "Success", f"Event ID {e_id} cancelled by admin")
        await context.bot.send_message(update.effective_user.id, "✅ 🗑️ Event cancelled and removed.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

# --- 2/ POLLS ---
def get_poll_kb(draft, pid):
    anon_str = "👻 Anonymous: ON" if draft['anon'] else "👻 Anonymous: OFF"
    multi_str = "☑️ Multiple Options" if draft['multi'] else "☑️ Single Option"
    quiz_str = f"🧠 Quiz (Ans: {draft['quiz_idx']+1})" if draft['quiz_idx'] >= 0 else "🧠 Quiz Mode: OFF"
    hrs_str = f"⏳ Duration: {draft['hours']}h"

    kb = [
        [InlineKeyboardButton(anon_str, callback_data=f"pollst_{pid}_anon"),
         InlineKeyboardButton(multi_str, callback_data=f"pollst_{pid}_multi")],
        [InlineKeyboardButton(quiz_str, callback_data=f"pollst_{pid}_quiz"),
         InlineKeyboardButton(hrs_str, callback_data=f"pollst_{pid}_hrs")],
        [InlineKeyboardButton("🚀 Finish Now", callback_data=f"pollst_{pid}_send")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"pollst_{pid}_cancel")]
    ]
    return InlineKeyboardMarkup(kb)

async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private": return await update.message.reply_text("❌ Polls must be created in a group.")
    pool = context.bot_data.get('db_pool')
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        if len(parts) < 3: raise ValueError
        question = parts[0]
        options = parts[1:11] 
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Poll Create", "Error", str(e))
        return await update.message.reply_text("❌ Format error. Use: `/poll Question , Option 1 , Option 2 , ...`")

    pid = update.message.message_id
    context.chat_data[f"poll_{pid}"] = {
        'owner': update.effective_user.id,
        'q': question,
        'opts': options,
        'anon': False,
        'multi': False,
        'quiz_idx': -1,
        'hours': 24
    }

    opts_str = "\n".join([f"{i+1}. {o}" for i, o in enumerate(options)])
    text = f"📊 **Interactive Poll Setup**\n\n**Question:** {question}\n\n**Options:**\n{opts_str}\n\n_Configure settings below and click Finish Now._"

    await update.message.reply_text(text, reply_markup=get_poll_kb(context.chat_data[f"poll_{pid}"], pid), parse_mode="Markdown")

async def poll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")
    pid = int(parts[1])
    action = parts[2]

    draft = context.chat_data.get(f"poll_{pid}")
    if not draft:
        await q.message.delete()
        return await q.answer("❌ Poll session expired.", show_alert=True)

    if update.effective_user.id != draft['owner']:
        return await q.answer("❌ Only the creator can configure this poll.", show_alert=True)

    if action == "anon":
        draft['anon'] = not draft['anon']
    elif action == "multi":
        if draft['quiz_idx'] >= 0: return await q.answer("❌ Multiple answers are disabled in Quiz mode!", show_alert=True)
        draft['multi'] = not draft['multi']
    elif action == "quiz":
        draft['quiz_idx'] += 1
        if draft['quiz_idx'] >= len(draft['opts']): draft['quiz_idx'] = -1
        if draft['quiz_idx'] >= 0: draft['multi'] = False
    elif action == "hrs":
        cycles = [1, 6, 12, 24, 48, 72]
        idx = cycles.index(draft['hours']) if draft['hours'] in cycles else 0
        draft['hours'] = cycles[(idx + 1) % len(cycles)]
    elif action == "cancel":
        del context.chat_data[f"poll_{pid}"]
        await q.message.delete()
        return await q.answer("✅ Poll setup cancelled.")
    elif action == "send":
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn:
            active = await conn.fetchval("SELECT end_time FROM active_polls WHERE chat_id=$1 AND user_id=$2 AND end_time > NOW()", update.effective_chat.id, draft['owner'])
            if active:
                return await q.answer(f"❌ You already have an active poll running here until {active.astimezone(WIB).strftime('%H:%M WIB')}!", show_alert=True)

        dur = draft['hours'] * 3600
        try:
            msg = await context.bot.send_poll(
                chat_id=update.effective_chat.id,
                question=draft['q'],
                options=draft['opts'],
                is_anonymous=draft['anon'],
                allows_multiple_answers=draft['multi'],
                type='quiz' if draft['quiz_idx'] >= 0 else 'regular',
                correct_option_id=draft['quiz_idx'] if draft['quiz_idx'] >= 0 else None,
                open_period=dur
            )
            end_time = datetime.datetime.now(WIB) + datetime.timedelta(seconds=dur)
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO active_polls (chat_id, user_id, end_time) VALUES ($1, $2, $3) ON CONFLICT (chat_id, user_id) DO UPDATE SET end_time=$3", update.effective_chat.id, draft['owner'], end_time)

            rem_time = end_time - datetime.timedelta(minutes=15)
            if dur > 900:
                context.job_queue.run_once(poll_reminder, when=rem_time, data={"chat_id": update.effective_chat.id, "q": draft['q'], "msg_id": msg.message_id})

            del context.chat_data[f"poll_{pid}"]
            await q.message.delete()
            return await q.answer("✅ Poll launched successfully!")
        except Exception as e:
            return await q.answer(f"❌ Failed to launch poll: {str(e)}", show_alert=True)

    await q.edit_message_reply_markup(reply_markup=get_poll_kb(draft, pid))
    await q.answer()

async def cancel_poll_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.poll:
        return await context.bot.send_message(update.effective_user.id, "❌ Please reply to a live poll message with `/cancelpoll`.")
    
    try:
        await context.bot.stop_poll(update.effective_chat.id, update.message.reply_to_message.message_id)
        await context.bot.send_message(update.effective_user.id, "✅ Poll successfully stopped.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ Failed to stop poll: {e}")

async def poll_reminder(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.send_message(context.job.data['chat_id'], f"⏳ **Attention team!** The poll '{context.job.data['q']}' is ending in 15 minutes! Please get your votes in.", reply_to_message_id=context.job.data['msg_id'], parse_mode="Markdown")
    except: pass

# --- 3/ STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Please reply to a specific user's message to give them a Star!")
    giver = update.effective_user.username or str(update.effective_user.id)
    receiver_user = update.message.reply_to_message.from_user
    receiver = receiver_user.username or str(receiver_user.id)
    pool = context.bot_data.get('db_pool')
    
    if receiver_user.is_bot: return await update.message.reply_text("❌ Oops! I appreciate the thought, but bots cannot receive RAWWY Stars.")
    if giver == receiver: return await update.message.reply_text("❌ Nice try! You cannot convert your Star Quota to yourself. Please share the love with the team.")
    
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
            q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
            if q <= 0: 
                return await update.message.reply_text("❌ You have completely depleted your Star Quota for this week! Please wait for the Monday reset.")
            
            await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
            await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
            score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Star Given", "Success", f"@{giver} gave star to @{receiver}")
        await update.message.reply_text(f"✅ 🌟 **Star Sent!**\n@{receiver} received a RAWWY Star from @{giver}!\nThey now have {score} total Stars.", parse_mode="Markdown")
        try: await context.bot.send_message(update.effective_user.id, f"✅ 🌟 You sent a star! You have **{q - 1} Star Quota** remaining this week.")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def my_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
            q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
        await update.message.reply_text(f"✅ 🌟 Hello @{user}, you currently have **{q} Star Quota** left to give to others this week.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def my_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: pts = await conn.fetchval('SELECT monthly_points FROM kudos WHERE username=$1', user)
        if not pts or pts == 0: await update.message.reply_text("❌ You haven't received any RAWWY Stars this month yet. Keep helping others!")
        else: await update.message.reply_text(f"✅ 🌟 Awesome! You have received **{pts} RAWWY Stars** this month.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def total_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: pts = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', user)
        if not pts or pts == 0: await update.message.reply_text("❌ You haven't collected any RAWWY Stars historically.")
        else: await update.message.reply_text(f"✅ 🌟 Impressive! You have collected a total of **{pts} RAWWY Stars** all-time.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def check_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: target = " ".join(context.args).replace("@", "").strip()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Please use: `/checkquota all` OR `/checkquota @user`")
    if not target: return await context.bot.send_message(update.effective_user.id, "❌ Please provide a user or 'all'.")
    
    try:
        async with pool.acquire() as conn:
            if target.lower() == 'all':
                recs = await conn.fetch('SELECT username, quota, monthly_points, all_time_points FROM kudos')
                msg = "✅ 🌟 **Team Stars Audit**\n" + "\n".join([f"@{r['username']} - Quota: {r['quota']} | Month: {r['monthly_points']} | Total: {r['all_time_points']}" for r in recs]) if recs else "❌ No records found."
            else:
                r = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
                msg = f"✅ 🌟 **@{target} Audit**\nQuota left: {r['quota']}\nMonthly: {r['monthly_points']}\nTotal: {r['all_time_points']}" if r else "❌ User not found in database."
        await context.bot.send_message(update.effective_user.id, msg)
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 3) if p.strip()]
        if len(parts) != 4: raise ValueError
        t = parts[0].replace("@", ""); field = parts[1].lower(); act = parts[2].lower(); amt = int(parts[3])
        if field not in ['quota', 'monthly', 'total'] or act not in ['add', 'sub', 'set']: raise ValueError
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Admin Stars", "Error", str(e))
        return await context.bot.send_message(update.effective_user.id, "❌ Incorrect format. Please strictly use: `/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn:
            col = 'monthly_points' if field == 'monthly' else 'all_time_points' if field == 'total' else 'quota'
            await conn.execute(f'INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
            
            if act == "set": await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, t)
            elif act == "add": await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, t)
            elif act == "sub": await conn.execute(f'UPDATE kudos SET {col}={col}-$1 WHERE username=$2', amt, t)
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Admin Stars", "Success", f"@{username} used '{act}' on @{t}'s {field} by {amt}.")
        await context.bot.send_message(update.effective_user.id, f"✅ The {field} stars for @{t} have been successfully updated.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

# --- 4/ LIBRARY ---
async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_args = " ".join(context.args)
    if not raw_args: return await update.message.reply_text("❌ Looks like you missed something! Format: `/addlib Name , Link/Content , [private]`", parse_mode="Markdown")
    pool = context.bot_data.get('db_pool')
    try:
        is_private = False
        if raw_args.lower().endswith(", private"):
            is_private = True
            raw_args = raw_args[:-9].strip()
            await delete_cmd(update)
        parts = [p.strip() for p in raw_args.split(",", 1)]
        if len(parts) < 2: raise ValueError
        name = parts[0].lower(); content = parts[1]
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Add", "Error", str(e))
        return await update.message.reply_text("❌ Oops! The format seems a bit off. Please use: `/addlib Name , Content`")
    
    try:
        username = update.effective_user.username or str(update.effective_user.id)
        async with pool.acquire() as conn:
            exist = await conn.fetchval('SELECT name FROM library WHERE name=$1', name)
            if exist: return await update.message.reply_text(f"❌ That name ('{name}') is already taken! Please pick a unique name or use `/editlib` to update it.", parse_mode="Markdown")
            await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4)', name, content, username, is_private)
        
        target_chat = update.effective_user.id if is_private else update.effective_chat.id
        try: await context.bot.send_message(target_chat, f"✅ Asset **'{name}'** added by {update.effective_user.first_name}! {'🔒 (Private)' if is_private else ''}", parse_mode="Markdown")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def edit_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        if len(parts) < 2: raise ValueError
        name = parts[0].lower(); content = parts[1]
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Edit", "Error", str(e))
        return await update.message.reply_text("❌ Format error: `/editlib Name , New Content`")
    
    try:
        async with pool.acquire() as conn:
            asset = await conn.fetchrow('SELECT added_by FROM library WHERE name=$1', name)
            if not asset: return await update.message.reply_text("❌ I couldn't find that asset.")
            if asset['added_by'] != username and not await is_bot_admin(username, pool):
                return await update.message.reply_text("❌ Only the original author or an Admin can edit this file.")
            
            await conn.execute('UPDATE library SET content=$1 WHERE name=$2', content, name)
        await update.message.reply_text(f"✅ Asset **'{name}'** has been successfully updated.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: name = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await update.message.reply_text("❌ What asset are you looking for? Try: `/getlib Name`")
    
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            r = await conn.fetchrow('SELECT content, is_private, added_by FROM library WHERE name=$1', name)
            
        if not r: return await update.message.reply_text("❌ Hmm, I couldn't find that asset in the library.")
        if r['is_private']:
            await delete_cmd(update)
            if r['added_by'] != username:
                return await context.bot.send_message(update.effective_user.id, "❌ Sorry, you don't have permission to view this private file.")
            try: await context.bot.send_message(update.effective_user.id, f"✅ 🔒 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
            except: await update.message.reply_text("❌ Please start a DM with me so I can send your private files securely.")
        else:
            await update.message.reply_text(f"✅ 📂 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    is_adm = await is_bot_admin(username, pool)
    
    try: name = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Please provide an asset to delete: `/dellib Name`")
    
    try:
        async with pool.acquire() as conn:
            asset = await conn.fetchrow('SELECT added_by FROM library WHERE name=$1', name)
            if not asset: 
                return await context.bot.send_message(update.effective_user.id, "❌ That asset doesn't exist.")
            
            if asset['added_by'] != username and not is_adm:
                return await context.bot.send_message(update.effective_user.id, "❌ You can only delete assets that you personally added.")
            
            await conn.execute('DELETE FROM library WHERE name=$1', name)
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Delete", "Success", f"Asset '{name}' deleted")
        await context.bot.send_message(update.effective_user.id, f"✅ 🗑️ The asset '{name}' was successfully removed.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
        if not recs: return await update.message.reply_text("❌ 📚 Library is empty.")
        
        msg = "✅ 📚 **RAWWY Library**\n"
        for r in recs:
            if r['is_private']:
                if r['added_by'] == username:
                    msg += f"• 🔒 `{r['name']}` (Private)\n"
            else:
                msg += f"• 📂 `{r['name']}`\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

# --- ADMIN BATCH COMMANDS ---
async def addlib_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return

    text = update.message.text
    lines = text.split('\n')
    first_line = lines[0].split(' ', 1)
    items = []
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])

    if not items: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/addlib_batch Name,Content,[private] \n Name2,Content2`")

    success, failed = 0, 0
    fail_reasons = []

    async with pool.acquire() as conn:
        for item in items:
            try:
                is_private = False
                raw_args = item
                if raw_args.lower().endswith(", private"):
                    is_private = True
                    raw_args = raw_args[:-9].strip()
                parts = [p.strip() for p in raw_args.split(",", 1)]
                if len(parts) < 2: raise ValueError("Missing content")
                name = parts[0].lower(); content = parts[1]

                exist = await conn.fetchval('SELECT name FROM library WHERE name=$1', name)
                if exist:
                    failed += 1
                    fail_reasons.append(f"{name}: Already exists")
                    continue

                await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4)', name, content, username, is_private)
                success += 1
            except Exception as e:
                failed += 1
                fail_reasons.append(f"{item.split(',')[0][:15]}: Format/DB error")

    msg = f"✅ **Batch Add Library Complete**\nSuccess: {success}\nFailed: {failed}"
    if failed > 0: msg += "\n\n**Errors:**\n" + "\n".join(fail_reasons[:10]) + ("\n..." if len(fail_reasons)>10 else "")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Add Batch", "Success", f"Added {success}, failed {failed}")
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def dellib_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return

    text = update.message.text
    lines = text.split('\n')
    first_line = lines[0].split(' ', 1)
    items = []
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])

    if not items: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/dellib_batch Name1 \n Name2`")

    success, failed = 0, 0
    fail_reasons = []

    async with pool.acquire() as conn:
        for item in items:
            name = item.lower()
            res = await conn.execute('DELETE FROM library WHERE name=$1', name)
            if res == "DELETE 0":
                failed += 1
                fail_reasons.append(f"{name}: Not found")
            else:
                success += 1

    msg = f"✅ **Batch Delete Library Complete**\nSuccess: {success}\nFailed: {failed}"
    if failed > 0: msg += "\n\n**Errors:**\n" + "\n".join(fail_reasons[:10]) + ("\n..." if len(fail_reasons)>10 else "")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Delete Batch", "Success", f"Deleted {success}, failed {failed}")
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def addbday_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return

    text = update.message.text
    lines = text.split('\n')
    first_line = lines[0].split(' ', 1)
    items = []
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])

    if not items: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/addbday_batch @user,MM/DD \n @user2,MM/DD`")

    success, failed = 0, 0
    fail_reasons = []

    async with pool.acquire() as conn:
        for item in items:
            try:
                parts = [p.strip() for p in item.split(",")]
                if len(parts) < 2: raise ValueError("Missing date")
                u = parts[0].replace("@", "").lower(); b = parts[1]
                datetime.datetime.strptime(b, "%m/%d")

                exist = await conn.fetchval('SELECT bday FROM birthdays WHERE lower(username)=$1', u)
                if exist:
                    failed += 1
                    fail_reasons.append(f"@{u}: Already exists ({exist})")
                    continue

                await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
                success += 1
            except Exception as e:
                failed += 1
                fail_reasons.append(f"{item.split(',')[0][:15]}: Invalid format")

    msg = f"✅ **Batch Add Birthdays Complete**\nSuccess: {success}\nFailed: {failed}"
    if failed > 0: msg += "\n\n**Errors:**\n" + "\n".join(fail_reasons[:10]) + ("\n..." if len(fail_reasons)>10 else "")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Birthday Add Batch", "Success", f"Added {success}, failed {failed}")
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def delbday_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return

    text = update.message.text
    lines = text.split('\n')
    first_line = lines[0].split(' ', 1)
    items = []
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])

    if not items: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/delbday_batch @user1 \n @user2`")

    success, failed = 0, 0
    fail_reasons = []

    async with pool.acquire() as conn:
        for item in items:
            u = item.replace("@", "").strip().lower()
            res = await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", u)
            if res == "DELETE 0":
                failed += 1
                fail_reasons.append(f"@{u}: Not found")
            else:
                success += 1

    msg = f"✅ **Batch Delete Birthdays Complete**\nSuccess: {success}\nFailed: {failed}"
    if failed > 0: msg += "\n\n**Errors:**\n" + "\n".join(fail_reasons[:10]) + ("\n..." if len(fail_reasons)>10 else "")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Birthday Delete Batch", "Success", f"Deleted {success}, failed {failed}")
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

# --- ADMINISTRATION ---
async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",", 1) if p.strip()]
        if len(parts) < 2: raise ValueError
        target, msg = parts[0], parts[1]
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Error", str(e))
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/announce [ChatID or All] , Message`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn:
            a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", msg)
            targets = await conn.fetch("SELECT chat_id FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target)}]
            
            if not targets:
                await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Failed", "No target groups configured.")
                return await context.bot.send_message(update.effective_user.id, "❌ Failed to send announcement.\nReason: No target groups configured.")
            
            sent = 0
            failed = 0
            for t in targets:
                try:
                    formatted_msg = f"📢 **[RW] NUKHBA BROADCAST**\n\nHello Nukhba,\n\n{msg}\n\nYalla Yalla"
                    m = await context.bot.send_message(t['chat_id'], formatted_msg, parse_mode="Markdown")
                    await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
                    sent += 1
                except Exception as e: 
                    failed += 1
                    await log_action(pool, update.effective_user.id, t['chat_id'], "Announcement", "Error", f"Failed in group {t['chat_id']}: {str(e)}")

        if sent > 0:
            await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Success", f"Broadcast {a_id} sent to {sent} groups.")
            await context.bot.send_message(update.effective_user.id, f"✅ Announcement sent successfully to {sent} group(s).", parse_mode="Markdown")
        
        if failed > 0:
            await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Failed", f"Broadcast {a_id} failed in {failed} groups.")
            await context.bot.send_message(update.effective_user.id, f"❌ Failed to send announcement to {failed} group(s).\nReason: Bot lacks permission or group not found.", parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",", 1) if p.strip()]
        a_id = int(parts[0]); new_msg = parts[1]
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/editannounce ID , New Msg`")
    
    try:
        async with pool.acquire() as conn:
            msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
            for m in msgs:
                try: await context.bot.edit_message_text(f"📢 **[RW] NUKHBA BROADCAST**\n\nHello Nukhba,\n\n{new_msg}\n\nYalla Yalla", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
                except: pass
            await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", new_msg, a_id)
        await context.bot.send_message(update.effective_user.id, f"✅ Updated Announcement {a_id}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: a_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/delannounce ID`")
    
    try:
        async with pool.acquire() as conn:
            msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
            for m in msgs:
                try: await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
                except: pass
            await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
            await conn.execute("DELETE FROM announcement_messages WHERE announcement_id=$1", a_id)
        await context.bot.send_message(update.effective_user.id, f"✅ Deleted Announcement {a_id}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def check_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        if update.effective_chat.type in ['group', 'supergroup']:
            msg = f"✅ 📌 **Current Group Info**\nTitle: `{update.effective_chat.title}`\nID: `{update.effective_chat.id}`"
            try: await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
            except: pass
        else:
            async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
            if not groups: msg = "❌ I have not detected any active groups yet."
            else: msg = "✅ 📈 **Tracked Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups])
            try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
            except: pass
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def get_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        target_date = datetime.datetime.now(WIB).date()
        msg = await generate_audit_report(pool, target_date)
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: `{e}`", parse_mode="Markdown")

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
            u_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            t_count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Pending'")
            l_count = await conn.fetchval("SELECT COUNT(*) FROM library")
            b_count = await conn.fetchval("SELECT COUNT(*) FROM birthdays")
        
        msg = "✅ 📈 **Enterprise System Status**\n\n"
        msg += f"👥 Users Tracked: `{u_count}`\n📋 Pending Tasks: `{t_count}`\n📚 Library Assets: `{l_count}`\n🎂 Birthdays Saved: `{b_count}`\n\n"
        msg += f"🏠 **Active Groups ({len(groups)}):**\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups])
        try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
        except: pass
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def set_bday_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    if update.effective_chat.type == "private": return await context.bot.send_message(update.effective_user.id, "❌ Run this command inside the group you want to set.")
    
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO config (key, value) VALUES ('bday_channel', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(update.effective_chat.id))
        await context.bot.send_message(update.effective_user.id, f"✅ Birthday announcements will now be sent to {update.effective_chat.title}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def set_bday_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        time_str = context.args[0]
        h, m = map(int, time_str.split(':'))
        if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
    except:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/setbdaytime HH:MM` (24-hour format, e.g., 09:00)", parse_mode="Markdown")
    
    try:
        formatted_time = f"{h:02d}:{m:02d}"
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO config (key, value) VALUES ('bday_time', $1) ON CONFLICT (key) DO UPDATE SET value=$1", formatted_time)
        
        await schedule_bday_job(context.application)
        await context.bot.send_message(update.effective_user.id, f"✅ Birthday alerts will now be triggered daily at {formatted_time} WIB.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def bday_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        async with pool.acquire() as conn:
            channel = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'")
            time_val = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'") or "10:00"
        
        msg = "✅ 🎂 **Birthday System Configuration**\n\n"
        if channel:
            msg += f"📢 Target Chat ID: `{channel}`\n"
        else:
            msg += f"📢 Target Chat ID: ❌ Not Set (Use `/setbdaychannel` in target group)\n"
        msg += f"⏰ Alert Time: `{time_val} WIB` (Use `/setbdaytime HH:MM` to change)\n"
        
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        if len(parts) < 2: raise ValueError
        u = parts[0].replace("@", "").lower(); b = parts[1]
        datetime.datetime.strptime(b, "%m/%d")
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error. Try: `/addbday @user , MM/DD`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn:
            exist = await conn.fetchval('SELECT bday FROM birthdays WHERE lower(username)=$1', u)
            if exist: 
                return await context.bot.send_message(update.effective_user.id, f"❌ @{u} already has a birthday registered (Date: {exist}). Use `/editbday` to update it.", parse_mode="Markdown")
            await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
        await context.bot.send_message(update.effective_user.id, f"✅ 🎂 Birthday securely logged for @{u}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def edit_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        u = parts[0].replace("@", "").lower(); b = parts[1]
        datetime.datetime.strptime(b, "%m/%d")
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error: `/editbday @user , MM/DD`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn: 
            res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE lower(username)=$2', b, u)
            if res == "UPDATE 0": return await context.bot.send_message(update.effective_user.id, "❌ User not found. Use `/addbday`.")
        await context.bot.send_message(update.effective_user.id, f"✅ 🎂 Birthday updated for @{u}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def del_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try: u = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/delbday @user`")
    
    try:
        async with pool.acquire() as conn:
            res = await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", u)
            if res == "DELETE 0":
                return await context.bot.send_message(update.effective_user.id, f"❌ @{u} not found in birthday database.")
        await context.bot.send_message(update.effective_user.id, f"✅ Removed @{u} from birthday database.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        async with pool.acquire() as conn: b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
        await context.bot.send_message(update.effective_user.id, "✅ 🎂 **Birthdays**\n" + "\n".join([f"• @{x['username']}: {x['bday']}" for x in b]) if b else "❌ None saved.", parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

# --- SUPER ACTIONS ---

async def super_reset_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error: `/super_reset [stars/tasks/library/events/away/birthdays/all]`", parse_mode="Markdown")
    
    cb_data = f"sup_reset_{target}"
    kb = [[InlineKeyboardButton("⚠️ Yes, Wipe Data", callback_data=cb_data), InlineKeyboardButton("No, Cancel", callback_data="sup_cancel")]]
    await context.bot.send_message(update.effective_user.id, f"⚠️ **FACTORY WIPE MODULE**\nAre you absolutely sure you want to wipe data for `{target}`?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def request_super_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, label: str):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, f"❌ Format error: `/{action} @user`")
    
    cb_data = f"sup_{action}_{target}"
    kb = [[InlineKeyboardButton("Yes, Do it", callback_data=cb_data), InlineKeyboardButton("No, Cancel", callback_data="sup_cancel")]]
    await context.bot.send_message(update.effective_user.id, f"⚠️ Are you sure you want to execute **{label}** on `{target}`?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_admin_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await request_super_action(update, context, "addadmin", "Promote Admin")

async def del_admin_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await request_super_action(update, context, "deladmin", "Demote Admin")

async def remove_member_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await request_super_action(update, context, "removemember", "Offboard User")

async def super_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    username = q.from_user.username or str(q.from_user.id)
    if not await is_super(username): return await q.answer("Unauthorized.")
    if q.data == "sup_cancel":
        await q.edit_message_text("❌ Action cancelled.")
        return await q.answer()
        
    parts = q.data.split("_")
    action = parts[1]; target = parts[2]
    pool = context.bot_data.get('db_pool')
    
    try:
        if action == "addadmin":
            async with pool.acquire() as conn: 
                await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
                uid = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', target)
            if uid:
                try:
                    await update_user_menu(uid, target, pool, context.bot)
                    await context.bot.send_message(uid, "🎉 **Congratulations!** You have been promoted to Global Bot Admin. Type `/help`.", parse_mode="Markdown")
                except: pass
            await q.edit_message_text(f"✅ @{target} is now a Bot Admin.")
            
        elif action == "deladmin":
            async with pool.acquire() as conn: await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
            await q.edit_message_text(f"✅ 🗑️ @{target} removed from Admins.")
            
        elif action == "removemember":
            async with pool.acquire() as conn:
                k = await conn.fetchrow("SELECT * FROM kudos WHERE username=$1", target)
                b = await conn.fetchval("SELECT bday FROM birthdays WHERE username=$1", target)
                c = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Completed' AND assignee=$1", target)
                data_dump = f"Stars: {k['all_time_points'] if k else 0} | Bday: {b} | Tasks Done: {c}"
                await conn.execute("INSERT INTO graveyard (username, data_dump) VALUES ($1, $2)", target, data_dump)
                
                await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
                await conn.execute('DELETE FROM kudos WHERE username=$1', target)
                await conn.execute('DELETE FROM birthdays WHERE username=$1', target)
                await conn.execute('DELETE FROM away_status WHERE username=$1', target)
                await conn.execute("UPDATE tasks SET assignee='Unassigned' WHERE assignee=$1", target)
            await q.edit_message_text(f"✅ 🪦 @{target} offboarded to graveyard.")

        elif action == "reset":
            async with pool.acquire() as conn:
                if target in ["stars", "all"]: await conn.execute("TRUNCATE kudos CASCADE")
                if target in ["tasks", "all"]: await conn.execute("TRUNCATE tasks RESTART IDENTITY CASCADE")
                if target in ["library", "all"]: await conn.execute("TRUNCATE library CASCADE")
                if target in ["events", "all"]: await conn.execute("TRUNCATE events, rsvps RESTART IDENTITY CASCADE")
                if target in ["birthdays", "all"]: await conn.execute("TRUNCATE birthdays CASCADE")
                if target in ["away", "all"]: await conn.execute("TRUNCATE away_status, away_mentions CASCADE")
            await q.edit_message_text(f"✅ ☢️ Data Wipe for `{target}` successfully executed.", parse_mode="Markdown")
            
    except Exception as e:
        await q.edit_message_text(f"❌ System Error: {e}")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: admins = await conn.fetch('SELECT username FROM bot_admins')
        msg = "✅ 👑 **Bot Admins**\n" + "\n".join([f"• @{a['username']}" for a in admins]) if admins else "✅ 👑 **Bot Admins**\nNone (Only Super Owner exists)."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: gy = await conn.fetch('SELECT * FROM graveyard')
        if not gy: return await context.bot.send_message(update.effective_user.id, "❌ 🪦 The graveyard is empty.")
        msg = "✅ 🪦 **Employee Graveyard**\n\n"
        for g in gy: msg += f"• @{g['username']} (Left: {g['offboarded_at'].strftime('%m/%d/%Y')})\n  _{g['data_dump']}_\n\n"
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

# --- RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db
    app.add_error_handler(error_handler)

    app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(monthly_leaderboard, datetime.time(hour=13, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(weekly_quota_reset, datetime.time(hour=0, minute=0, tzinfo=WIB), days=(0,))
    app.job_queue.run_repeating(poll_cleanup, interval=3600)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("bugreport", report_bug))
    
    app.add_handler(CommandHandler("addadmin", add_admin_req))
    app.add_handler(CommandHandler("deladmin", del_admin_req))
    app.add_handler(CommandHandler("listadmins", list_admins))
    app.add_handler(CommandHandler("removemember", remove_member_req))
    app.add_handler(CommandHandler("graveyard", graveyard))
    app.add_handler(CommandHandler("super_reset", super_reset_req))
    
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("editannounce", edit_announce))
    app.add_handler(CommandHandler("delannounce", del_announce))
    app.add_handler(CommandHandler("admin_stars", admin_stars))
    app.add_handler(CommandHandler("checkquota", check_quota))
    
    app.add_handler(CommandHandler("addbday", add_bday))
    app.add_handler(CommandHandler("editbday", edit_bday))
    app.add_handler(CommandHandler("delbday", del_bday))
    app.add_handler(CommandHandler("listbdays", list_bdays))
    app.add_handler(CommandHandler("setbdaychannel", set_bday_channel))
    app.add_handler(CommandHandler("setbdaytime", set_bday_time))
    app.add_handler(CommandHandler("bdayconfig", bday_config))
    app.add_handler(CommandHandler("addbday_batch", addbday_batch))
    app.add_handler(CommandHandler("delbday_batch", delbday_batch))
    
    app.add_handler(CommandHandler("cancelevent", cancel_event))
    app.add_handler(CommandHandler("canceltask", cancel_task))
    app.add_handler(CommandHandler("dellib", del_lib))
    app.add_handler(CommandHandler("addlib_batch", addlib_batch))
    app.add_handler(CommandHandler("dellib_batch", dellib_batch))
    
    app.add_handler(CommandHandler("attendance", attendance))
    app.add_handler(CommandHandler("grouptasks", group_tasks))
    app.add_handler(CommandHandler("groupid", check_group_id))
    app.add_handler(CommandHandler("listgroups", check_group_id))
    app.add_handler(CommandHandler("botstatus", bot_status))
    app.add_handler(CommandHandler("auditlog", get_audit_log))
    app.add_handler(CommandHandler("forceback", force_back))
    
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("myquota", my_quota))
    app.add_handler(CommandHandler("mystar", my_star))
    app.add_handler(CommandHandler("totalstar", total_star))
    
    app.add_handler(CommandHandler("newevent", create_event))
    app.add_handler(CommandHandler("editevent", edit_event))
    app.add_handler(CommandHandler("events", list_events))
    
    app.add_handler(CommandHandler("assign", assign_task))
    app.add_handler(CommandHandler("complete", complete_task))
    app.add_handler(CommandHandler("mytasks", my_tasks))
    
    app.add_handler(CommandHandler("poll", create_poll))
    app.add_handler(CommandHandler("cancelpoll", cancel_poll_admin))
    app.add_handler(CommandHandler("addlib", add_lib))
    app.add_handler(CommandHandler("editlib", edit_lib))
    app.add_handler(CommandHandler("getlib", get_lib))
    app.add_handler(CommandHandler("library", list_lib))

    app.add_handler(CallbackQueryHandler(poll_callback, pattern="^pollst_"))
    app.add_handler(CallbackQueryHandler(super_callback, pattern="^sup_"))
    app.add_handler(CallbackQueryHandler(rsvp_callback, pattern="^rsvp_"))
    app.add_handler(ChatMemberHandler(security_track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_tracker))

    logger.info("Starting Enterprise bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
