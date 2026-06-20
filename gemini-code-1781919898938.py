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

async def log_action(pool, text: str):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO audit_logs (log_text) VALUES ($1)", text)

# --- DYNAMIC MENU BUILDER ---
async def update_user_menu(user_id: int, username: str, pool, bot):
    is_adm = await is_bot_admin(username, pool)
    is_sup = await is_super(username)
    
    base_cmds = [
        BotCommand("help", "View User Manual"),
        BotCommand("newevent", "[1] Schedule an event"),
        BotCommand("events", "[1] View upcoming events"),
        BotCommand("poll", "[2] Create a team poll"),
        BotCommand("mystar", "[3] RAWWY Stars earned this month"),
        BotCommand("totalstar", "[3] RAWWY Stars earned all-time"),
        BotCommand("myquota", "[3] Star Quota left to give"),
        BotCommand("thanks", "[3] (Reply) Send a Star"),
        BotCommand("addlib", "[4] Save to Library"),
        BotCommand("editlib", "[4] Edit Library File"),
        BotCommand("getlib", "[4] Retrieve an asset"),
        BotCommand("library", "[4] Browse Library"),
        BotCommand("assign", "[5] Assign a task"),
        BotCommand("complete", "[5] Mark task complete"),
        BotCommand("mytasks", "[5] View your tasks"),
        BotCommand("away", "[6] Set Away status"),
        BotCommand("back", "[6] Return from Away"),
        BotCommand("bugreport", "Report issue to Admin")
    ]
    
    if is_adm:
        base_cmds.extend([
            BotCommand("help_admin", "[Admin] View Suite"),
            BotCommand("addbday", "[Admin - HR] Add Bday"),
            BotCommand("editbday", "[Admin - HR] Edit Bday"),
            BotCommand("listbdays", "[Admin - HR] View Bdays"),
            BotCommand("setbdaychannel", "[Admin - HR] Set Group"),
            BotCommand("attendance", "[Admin - HR] View Away List"),
            BotCommand("checkquota", "[Admin - Stars] Audit Quotas"),
            BotCommand("admin_stars", "[Admin - Stars] Edit Stars"),
            BotCommand("grouptasks", "[Admin - Ops] View Tasks"),
            BotCommand("cancelevent", "[Admin - Ops] Cancel Event"),
            BotCommand("canceltask", "[Admin - Ops] Cancel Task"),
            BotCommand("dellib", "[Admin - Ops] Delete Asset"),
            BotCommand("announce", "[Admin - Sys] Broadcast"),
            BotCommand("groupid", "[Admin - Sys] Check Chat IDs"),
            BotCommand("getlog", "[Admin - Sys] Diagnostics Log")
        ])
    if is_sup:
        base_cmds.extend([
            BotCommand("addadmin", "[Super] Promote Admin"),
            BotCommand("deladmin", "[Super] Demote Admin"),
            BotCommand("listadmins", "[Super] View Admins"),
            BotCommand("removemember", "[Super] Offboard User"),
            BotCommand("graveyard", "[Super] View Graveyard"),
            BotCommand("super_reset", "[Super] Factory Wipe")
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
    if not DATABASE_URL:
        logger.error("DATABASE_URL missing!")
        return
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
        await conn.execute('''CREATE TABLE IF NOT EXISTS bug_reports (id SERIAL PRIMARY KEY, username TEXT, report TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS audit_logs (id SERIAL PRIMARY KEY, log_text TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS graveyard (username TEXT PRIMARY KEY, offboarded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), data_dump TEXT);''')

    default_cmds = [
        BotCommand("help", "View Manager Guide"),
        BotCommand("newevent", "[1] Schedule Event"),
        BotCommand("events", "[1] View Schedule"),
        BotCommand("poll", "[2] Create Poll"),
        BotCommand("mystar", "[3] Monthly Stars"),
        BotCommand("totalstar", "[3] All-Time Stars"),
        BotCommand("myquota", "[3] Check Star Quota"),
        BotCommand("thanks", "[3] (Reply) Send Star"),
        BotCommand("addlib", "[4] Add to Library"),
        BotCommand("editlib", "[4] Edit Library File"),
        BotCommand("getlib", "[4] Get Library Asset"),
        BotCommand("library", "[4] Browse Library"),
        BotCommand("assign", "[5] Assign Task"),
        BotCommand("complete", "[5] Complete Task"),
        BotCommand("mytasks", "[5] My To-Do List"),
        BotCommand("away", "[6] Go Away"),
        BotCommand("back", "[6] Return")
    ]
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeDefault())
    logger.info("✅ Enterprise Database, Graveyard & Scoped Menus Configured!")

# --- CORE INTERFACE ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
    await update.message.reply_text("🤖 Hello! **[RW] Nukhba Manager is fully operational.** Type `/help` to see the command manual.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
        
    help_text = (
        "🚀 *[RW] Nukhba Manager Guide*\n\n"
        "📅 *1/ Events*\n`/newevent Title , MM/DD/YYYY HH.MM , RemMins` - Schedules a pinned event.\n`/events` - View upcoming events.\n\n"
        "📊 *2/ Polls*\n`/poll Question , Hours (1-72) , Opt1 , Opt2` - Max 1 poll per user.\n\n"
        "🌟 *3/ RAWWY Stars*\n`/thanks` (Reply) - Give 1 Star.\n`/myquota` - Check remaining sends.\n`/mystar` - Stars earned this month.\n`/totalstar` - Stars earned all-time.\n\n"
        "📚 *4/ Library*\n`/addlib Name , Content` - Save an asset (Add ', private' to lock it).\n`/editlib Name , Content` - Edit your asset.\n`/getlib Name` - Pull an asset.\n`/library` - Browse everything.\n\n"
        "⚡ *5/ Tasks*\n`/assign @user , 60 , Task description` - Deadline in 60-480m.\n`/complete ID` - Close task.\n`/mytasks` - View your active tasks.\n\n"
        "🏖️ *6/ Away Mode*\n`/away Reason , MM/DD/YYYY HH.MM` - Set away status.\n`/back` - Return early and receive missed mentions.\n\n"
        "🐛 *Extras*\n`/bugreport Your issue here`"
    )
    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("📬 I have securely sent the manual to your Direct Messages!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("I cannot send you a DM yet. Please start a private chat with me first!")

async def help_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    if not await is_bot_admin(username, pool): return
    is_owner = await is_super(username)
    
    help_text = (
        "🔐 *[RW] NUKHBA ADMIN SUITE*\n\n"
        "🎂 *Birthdays*\n`/addbday @user , MM/DD`\n`/editbday @user , MM/DD`\n`/setbdaychannel` (Run in target group)\n`/listbdays`\n\n"
        "🌟 *Stars & Quotas*\n`/checkquota all` or `@user`\n`/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`\n\n"
        "⚙️ *Management*\n`/attendance` - See who is Away in this group.\n`/grouptasks` - See pending tasks in the database.\n`/cancelevent ID` | `/canceltask ID` | `/dellib Name`\n\n"
        "📢 *System*\n`/announce [ChatID/All] , Message`\n`/groupid` - Check current group or all groups.\n`/getlog` - Force pull the daily diagnostics log."
    )
    if is_owner:
        help_text += (
            "\n\n👑 *SUPER OWNER EXCLUSIVES*\n"
            "🛡️ *Access:* `/addadmin @user` | `/deladmin @user` | `/listadmins`\n"
            "🛑 *Offboarding:* `/removemember @user` (Archives to graveyard)\n"
            "🪦 *Graveyard:* `/graveyard`\n"
            "☢️ *Wipe:* `/super_reset [stars/tasks/library/events/away/all]`"
        )
    await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Nothing happens on this command. Please check with the admin.")

# --- CRONS ---
async def generate_log_text(pool):
    async with pool.acquire() as conn:
        stats = await conn.fetchrow('SELECT uses, errors FROM bot_stats WHERE date=CURRENT_DATE - INTERVAL \'1 day\'')
        bugs = await conn.fetch('SELECT username, report FROM bug_reports')
        audit = await conn.fetch('SELECT log_text FROM audit_logs ORDER BY created_at ASC')
        
        msg = "🌅 **Diagnostic Audit Log:**\n\n"
        msg += f"📈 **Usage Yesterday:** {stats['uses'] if stats else 0} interactions\n"
        msg += f"⚠️ **Errors Caught:** {stats['errors'] if stats else 0} errors\n\n"
        msg += "🐛 **Bug Reports:**\n" + ("\n".join([f"- @{b['username']}: {b['report']}" for b in bugs]) if bugs else "No bugs reported! 🎉")
        msg += "\n\n🌟 **System Audit Log:**\n" + ("\n".join([f"- {s['log_text']}" for s in audit]) if audit else "No administrative modifications recorded.")
        
        await conn.execute("TRUNCATE bug_reports")
        await conn.execute("TRUNCATE audit_logs")
    return msg

async def daily_morning_log(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        owner_id = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', SUPER_OWNER)
    if not owner_id: return
    msg = await generate_log_text(pool)
    try: await context.bot.send_message(owner_id, msg, parse_mode="Markdown")
    except: pass

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
    
    if status in ['member', 'administrator']:
        inviter = result.from_user.username or str(result.from_user.id)
        if not await is_bot_admin(inviter, pool):
            try:
                await context.bot.send_message(chat.id, "❌ **Access Denied.** I am a private enterprise system. You are not authorized to deploy me here. Leaving chat.")
                await context.bot.leave_chat(chat.id)
            except: pass
            return
            
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
        try: await context.bot.send_message(chat.id, "✅ **Authorization confirmed.** [RW] Nukhba Manager is locked in and syncing data.")
        except: pass
        
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    pool = context.bot_data.get('db_pool')
    now = datetime.datetime.now(WIB)
    username = update.effective_user.username or str(update.effective_user.id)
    
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET user_id=$2", username, update.effective_user.id)
        await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, 1, 0) ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + 1")
        
        chat = update.effective_chat
        if chat.type in ['group', 'supergroup']:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
            
        text = update.message.text
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

async def report_bug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: return await update.message.reply_text("Please type: `/bugreport [explain issue here]`", parse_mode="Markdown")
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", username, text)
    await update.message.reply_text("🐛 Bug securely filed for review.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception handled:", exc_info=context.error)
    pool = context.bot_data.get('db_pool')
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO bot_stats (date, errors) VALUES (CURRENT_DATE, 1) ON CONFLICT (date) DO UPDATE SET errors = bot_stats.errors + 1")

# --- SUPER ACTIONS WITH CONFIRMATIONS ---
async def request_super_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, label: str):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, f"❌ Format error: `/{action} @user` (or `all` for reset).")
    
    cb_data = f"sup_{action}_{target}"
    kb = [[InlineKeyboardButton("Yes, Do it", callback_data=cb_data), InlineKeyboardButton("No, Cancel", callback_data="sup_cancel")]]
    await context.bot.send_message(update.effective_user.id, f"⚠️ Are you sure you want to execute **{label}** on `{target}`?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_admin_req(u, c): await request_super_action(u, c, "addadmin", "Promote Admin")
async def del_admin_req(u, c): await request_super_action(u, c, "deladmin", "Demote Admin")
async def remove_member_req(u, c): await request_super_action(u, c, "removemember", "Offboard User")
async def super_reset_req(u, c): await request_super_action(u, c, "reset", "Factory Wipe")

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
    
    if action == "addadmin":
        async with pool.acquire() as conn: 
            await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
            uid = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', target)
        if uid:
            try:
                await update_user_menu(uid, target, pool, context.bot)
                await context.bot.send_message(uid, "🎉 **Congratulations!** You have been promoted to Global Bot Admin. Type `/help_admin`.", parse_mode="Markdown")
            except: pass
        await q.edit_message_text(f"✅ @{target} is now a Bot Admin.")
        
    elif action == "deladmin":
        async with pool.acquire() as conn: await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
        await q.edit_message_text(f"🗑️ @{target} removed from Admins.")
        
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
        await q.edit_message_text(f"🪦 @{target} offboarded to graveyard.")
        
    elif action == "reset":
        if target == "all" and "confirm" not in q.data:
            kb = [[InlineKeyboardButton("Yes, I am absolutely sure", callback_data="sup_reset_all_confirm"), InlineKeyboardButton("No, Cancel", callback_data="sup_cancel")]]
            return await q.edit_message_text("⚠️ **WARNING:** You selected 'all'. This will wipe EVERYTHING. Are you sure?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            
        async with pool.acquire() as conn:
            if target == "stars" or "all" in target: await conn.execute("TRUNCATE kudos")
            if target == "tasks" or "all" in target: await conn.execute("TRUNCATE tasks RESTART IDENTITY")
            if target == "library" or "all" in target: await conn.execute("TRUNCATE library")
            if target == "events" or "all" in target: await conn.execute("TRUNCATE events, rsvps CASCADE RESTART IDENTITY")
            if target == "away" or "all" in target: await conn.execute("TRUNCATE away_status, away_mentions CASCADE")
        await q.edit_message_text(f"☢️ Data Wipe for `{target}` complete.", parse_mode="Markdown")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: admins = await conn.fetch('SELECT username FROM bot_admins')
    msg = "👑 **Bot Admins**\n" + "\n".join([f"• @{a['username']}" for a in admins]) if admins else "👑 **Bot Admins**\nNone (Only Super Owner exists)."
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: gy = await conn.fetch('SELECT * FROM graveyard')
    if not gy: return await context.bot.send_message(update.effective_user.id, "🪦 The graveyard is empty.")
    msg = "🪦 **Employee Graveyard**\n\n"
    for g in gy: msg += f"• @{g['username']} (Left: {g['offboarded_at'].strftime('%m/%d/%Y')})\n  _{g['data_dump']}_\n\n"
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

# --- 1/ EVENTS ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 2) if p.strip()]
        if len(parts) < 3: raise ValueError
        title = parts[0]
        e_time = WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H.%M"))
        rem = int(parts[2])
        if e_time < datetime.datetime.now(WIB): return await update.message.reply_text("I cannot schedule events in the past. Please select a future date and time.")
    except ValueError:
        return await update.message.reply_text("Time format error. Please strictly use `MM/DD/YYYY HH.MM`.")
    except: return await update.message.reply_text("Incorrect format. Please use: `/newevent Title , MM/DD/YYYY HH.MM , RemMins`")
    
    pool = context.bot_data.get('db_pool')
    kb = [[InlineKeyboardButton("✅ Going", callback_data="rsvp_temp_Going"), InlineKeyboardButton("❌ Not Going", callback_data="rsvp_temp_Not Going")]]
    msg = await update.message.reply_text(f"📅 **{title} has been scheduled!**\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\nNo RSVPs yet.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    
    try: await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except: pass 
    
    async with pool.acquire() as conn: 
        e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by, chat_id, msg_id) VALUES ($1, $2, $3, $4, $5) RETURNING id', title, e_time, username, update.effective_chat.id, msg.message_id)
    
    new_kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not Going")]]
    await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
    
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
    context.job_queue.run_once(unpin_event, when=e_time, data={"chat_id": update.effective_chat.id, "msg_id": msg.message_id}, name=f"event_unpin_{e_id}")

async def unpin_event(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.unpin_chat_message(chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id'])
    except: pass

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    try:
        raw_args = " ".join(context.args)
        id_part, rest = raw_args.split(",", 1)
        title_part, time_str, rem_str = [p.strip() for p in rest.rsplit(",", 2)]
        e_id = int(id_part.strip()); title = title_part; e_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M")); rem = int(rem_str)
    except: return await update.message.reply_text("Please use: `/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        ev = await conn.fetchrow('SELECT created_by FROM events WHERE id=$1', e_id)
        if not ev: return await update.message.reply_text("Event not found.")
        if ev['created_by'] != username and not await is_bot_admin(username, pool):
            return await update.message.reply_text("Only the event creator or an admin can edit this event.")
            
        await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, e_id)
        
    for job in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"): job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"): job.schedule_removal()
    
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
    await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if not events: return await update.message.reply_text("No upcoming events scheduled.")
    await update.message.reply_text("📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")

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

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.job_queue.application.bot_data.get('db_pool')
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
    
    async with pool.acquire() as conn: 
        ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
        if not ev: return await context.bot.send_message(update.effective_user.id, "Event not found.")
        await conn.execute('DELETE FROM events WHERE id=$1', e_id)
        
    for j in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"): j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"): j.schedule_removal()
    try: await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
    except: pass
    await context.bot.send_message(update.effective_user.id, "🗑️ Event cancelled and removed.")

# --- 2/ POLLS ---
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private": return await update.message.reply_text("Polls must be created in a group.")
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        if len(parts) < 4: raise ValueError
        hours = int(parts[1])
        if hours < 1 or hours > 72: return await update.message.reply_text("Poll duration must be between 1 and 72 hours.")
    except ValueError: return await update.message.reply_text("Make sure Hours is a number and avoid using commas inside the question itself!")
    except: return await update.message.reply_text("Poll format error. Use: `/poll Question , Hours , Opt1 , Opt2`")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        active = await conn.fetchval("SELECT end_time FROM active_polls WHERE chat_id=$1 AND user_id=$2 AND end_time > NOW()", update.effective_chat.id, update.effective_user.id)
        if active:
            return await update.message.reply_text(f"You already have an active poll running in this group! Please wait for it to expire at {active.astimezone(WIB).strftime('%H:%M WIB')} before creating another.")

    dur = hours * 3600
    msg = await context.bot.send_poll(update.effective_chat.id, parts[0], parts[2:], is_anonymous=False, allows_multiple_answers=True, open_period=dur)
    
    end_time = datetime.datetime.now(WIB) + datetime.timedelta(seconds=dur)
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO active_polls (chat_id, user_id, end_time) VALUES ($1, $2, $3) ON CONFLICT (chat_id, user_id) DO UPDATE SET end_time=$3", update.effective_chat.id, update.effective_user.id, end_time)

    rem_time = end_time - datetime.timedelta(minutes=15)
    if dur > 900:
        context.job_queue.run_once(poll_reminder, when=rem_time, data={"chat_id": update.effective_chat.id, "q": parts[0], "msg_id": msg.message_id})

async def poll_reminder(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.send_message(context.job.data['chat_id'], f"⏳ **Attention team!** The poll '{context.job.data['q']}' is ending in 15 minutes! Please get your votes in.", reply_to_message_id=context.job.data['msg_id'], parse_mode="Markdown")
    except: pass

# --- 3/ STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("Please reply to a specific user's message to give them a Star!")
    giver = update.effective_user.username or str(update.effective_user.id)
    receiver_user = update.message.reply_to_message.from_user
    receiver = receiver_user.username or str(receiver_user.id)
    
    if receiver_user.is_bot: return await update.message.reply_text("Oops! I appreciate the thought, but bots cannot receive RAWWY Stars.")
    if giver == receiver: return await update.message.reply_text("Nice try! You cannot convert your Star Quota to yourself. Please share the love with the team.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
        if q <= 0: 
            return await update.message.reply_text("You have completely depleted your Star Quota for this week! Please wait for the Monday reset.")
        
        await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
        await log_action(pool, f"@{giver} awarded 1 Star to @{receiver}.")
        
    await update.message.reply_text(f"🌟 **Star Sent!**\n@{receiver} received a RAWWY Star from @{giver}!\nThey now have {score} total Stars.", parse_mode="Markdown")
    try: await context.bot.send_message(update.effective_user.id, f"🌟 You sent a star! You have **{q - 1} Star Quota** remaining this week.")
    except: pass

async def my_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 Hello @{user}, you currently have **{q} Star Quota** left to give to others this week.", parse_mode="Markdown")

async def my_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: pts = await conn.fetchval('SELECT monthly_points FROM kudos WHERE username=$1', user)
    if not pts or pts == 0: await update.message.reply_text("You haven't received any RAWWY Stars this month yet. Keep helping others!")
    else: await update.message.reply_text(f"🌟 Awesome! You have received **{pts} RAWWY Stars** this month.", parse_mode="Markdown")

async def total_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: pts = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', user)
    if not pts or pts == 0: await update.message.reply_text("You haven't collected any RAWWY Stars historically.")
    else: await update.message.reply_text(f"🌟 Impressive! You have collected a total of **{pts} RAWWY Stars** all-time.", parse_mode="Markdown")

async def check_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: target = " ".join(context.args).replace("@", "").strip()
    except: return await context.bot.send_message(update.effective_user.id, "Please use: `/checkquota all` OR `/checkquota @user`")
    if not target: return await context.bot.send_message(update.effective_user.id, "Please provide a user or 'all'.")
    
    async with pool.acquire() as conn:
        if target.lower() == 'all':
            recs = await conn.fetch('SELECT username, quota, monthly_points, all_time_points FROM kudos')
            msg = "🌟 **Team Stars Audit**\n" + "\n".join([f"@{r['username']} - Quota: {r['quota']} | Month: {r['monthly_points']} | Total: {r['all_time_points']}" for r in recs]) if recs else "No records found."
        else:
            r = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
            msg = f"🌟 **@{target} Audit**\nQuota left: {r['quota']}\nMonthly: {r['monthly_points']}\nTotal: {r['all_time_points']}" if r else "User not found in database."
    try: await context.bot.send_message(update.effective_user.id, msg)
    except: pass

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
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ Incorrect format. Please strictly use: `/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`\n*Example:* `/admin_stars Justin , quota , set , 5`", parse_mode="Markdown")
    
    async with pool.acquire() as conn:
        col = 'monthly_points' if field == 'monthly' else 'all_time_points' if field == 'total' else 'quota'
        await conn.execute(f'INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
        
        if act == "set": await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, t)
        elif act == "add": await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, t)
        elif act == "sub": await conn.execute(f'UPDATE kudos SET {col}={col}-$1 WHERE username=$2', amt, t)
        
        await log_action(pool, f"Admin @{username} executed '{act}' to modify @{t}'s {field} by {amt}.")
    await context.bot.send_message(update.effective_user.id, f"✅ The {field} stars for @{t} have been successfully updated.")

# --- 4/ LIBRARY ---
async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_args = " ".join(context.args)
    if not raw_args: return await update.message.reply_text("Looks like you missed something! Format: `/addlib Name , Link/Content , [private]`", parse_mode="Markdown")
    try:
        is_private = False
        if raw_args.lower().endswith(", private"):
            is_private = True
            raw_args = raw_args[:-9].strip()
            await delete_cmd(update)
        parts = [p.strip() for p in raw_args.split(",", 1)]
        if len(parts) < 2: raise ValueError
        name = parts[0].lower(); content = parts[1]
    except: return await update.message.reply_text("Oops! The format seems a bit off. Please use: `/addlib Name , Content`")
    
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        exist = await conn.fetchval('SELECT name FROM library WHERE name=$1', name)
        if exist: return await update.message.reply_text(f"That name ('{name}') is already taken! Please pick a unique name or use `/editlib` to update it.", parse_mode="Markdown")
        await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4)', name, content, username, is_private)
    
    target_chat = update.effective_user.id if is_private else update.effective_chat.id
    try: await context.bot.send_message(target_chat, f"✅ Asset **'{name}'** added by {update.effective_user.first_name}! {'🔒 (Private)' if is_private else ''}", parse_mode="Markdown")
    except: pass

async def edit_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        if len(parts) < 2: raise ValueError
        name = parts[0].lower(); content = parts[1]
    except: return await update.message.reply_text("Format error: `/editlib Name , New Content`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        asset = await conn.fetchrow('SELECT added_by FROM library WHERE name=$1', name)
        if not asset: return await update.message.reply_text("I couldn't find that asset.")
        if asset['added_by'] != username and not await is_bot_admin(username, pool):
            return await update.message.reply_text("Only the original author or an Admin can edit this file.")
        
        await conn.execute('UPDATE library SET content=$1 WHERE name=$2', content, name)
    await update.message.reply_text(f"✅ Asset **'{name}'** has been successfully updated.", parse_mode="Markdown")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: name = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await update.message.reply_text("What asset are you looking for? Try: `/getlib Name`")
    
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT content, is_private, added_by FROM library WHERE name=$1', name)
        
    if not r: return await update.message.reply_text("Hmm, I couldn't find that asset in the library.")
    if r['is_private']:
        await delete_cmd(update)
        if r['added_by'] != username:
            return await context.bot.send_message(update.effective_user.id, "Sorry, you don't have permission to view this private file.")
        try: await context.bot.send_message(update.effective_user.id, f"🔒 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
        except: await update.message.reply_text("Please start a DM with me so I can send your private files securely.")
    else:
        await update.message.reply_text(f"📂 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: name = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await context.bot.send_message(update.effective_user.id, "Please provide an asset to delete: `/dellib Name`")
    
    async with pool.acquire() as conn:
        if await conn.execute('DELETE FROM library WHERE name=$1', name) == "DELETE 0": 
            return await context.bot.send_message(update.effective_user.id, "That asset doesn't exist.")
    await context.bot.send_message(update.effective_user.id, f"🗑️ The asset '{name}' was successfully removed.")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
    if not recs: return await update.message.reply_text("📚 Library is empty.")
    
    msg = "📚 **RAWWY Library**\n"
    for r in recs:
        if r['is_private']:
            if r['added_by'] == username:
                msg += f"• 🔒 `{r['name']}` (Private)\n"
        else:
            msg += f"• 📂 `{r['name']}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- 5/ TASKS ---
async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 2)]
        if len(parts) < 3 or not all(parts): raise ValueError
        a = parts[0].replace("@", ""); m = int(parts[1]); d = parts[2]
    except: 
        return await update.message.reply_text("You missed some details! Format: `/assign @user , Minutes , Task description`", parse_mode="Markdown")
        
    assigner = update.effective_user.username or str(update.effective_user.id)
    if a.lower() == context.bot.username.lower(): return await update.message.reply_text("I am an automated bot, I cannot complete human tasks!")
    if a.lower() == assigner.lower(): return await update.message.reply_text("You cannot assign tasks to yourself. Please assign it to a team member.")
    if m < 60 or m > 480: return await update.message.reply_text("For productivity reasons, task deadlines must be configured between 60 and 480 minutes.")
    
    dl = datetime.datetime.now(WIB) + datetime.timedelta(minutes=m)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        if not await is_bot_admin(assigner, pool):
            count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE assigned_by=$1 AND status='Pending'", assigner)
            if count >= 4: return await update.message.reply_text("You have reached the maximum limit of 4 active tasks assigned. Please wait for them to complete.")
            
        t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', a, d, dl, assigner)
    
    context.job_queue.run_once(task_reminder, when=dl - datetime.timedelta(minutes=10), data={"assignee": a, "assigner": assigner, "id": t_id, "desc": d}, chat_id=update.effective_chat.id)
    await update.message.reply_text(f"📋 **Task Officially Assigned!**\n@{assigner} assigned Task `{t_id}` to @{a}.\n📝 {d}\n⏳ Must be completed by: {dl.strftime('%H:%M WIB')}", parse_mode="Markdown")

async def task_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed': 
        await context.bot.send_message(context.job.chat_id, f"⚠️ Hello @{context.job.data['assignee']} and @{context.job.data['assigner']}, your task '{context.job.data['desc']}' is about to hit its deadline in exactly 10 minutes!")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await update.message.reply_text("Please provide the numeric ID: `/complete ID`", parse_mode="Markdown")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assignee, status FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("I couldn't find that task in the database.")
        if task['status'] == 'Completed': return await update.message.reply_text("This task is already finished!")
        if task['assignee'] != username: return await update.message.reply_text("Only the specific person assigned to this task can mark it complete.")
        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
    await update.message.reply_text(f"✅ Great job! Task `{t_id}` is officially marked as completed.", parse_mode="Markdown")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    is_adm = await is_bot_admin(username, pool)
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await update.message.reply_text("Please provide the ID: `/canceltask ID`")
    
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("I couldn't find that task.")
        if task['assigned_by'] != username and not is_adm: 
            return await update.message.reply_text("Only the assigner or an Admin can cancel this.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await update.message.reply_text("🗑️ Task successfully cancelled.")

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        tasks = await conn.fetch("SELECT id, task_desc, deadline FROM tasks WHERE status='Pending' AND assignee=$1 ORDER BY deadline", username)
    if not tasks: msg = "🎉 You have no pending tasks! Great job catching up."
    else:
        msg = "📋 **Your Active Tasks**\n\n"
        for t in tasks:
            rem = int((t['deadline'] - now).total_seconds() / 60)
            status = f"{rem}m left" if rem > 0 else "OVERDUE"
            msg += f"🔹 `{t['id']}` | {t['task_desc']} | ⏳ {status}\n"
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: await update.message.reply_text("Please start a DM with me so I can privately send you your task list.")

async def group_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        tasks = await conn.fetch("SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks WHERE status='Pending' ORDER BY deadline")
    if not tasks: msg = "🎉 Zero pending tasks in the entire database."
    else:
        msg = "📋 **Global Pending Tasks**\n\n"
        for t in tasks:
            rem = int((t['deadline'] - now).total_seconds() / 60)
            status = f"{rem}m left" if rem > 0 else "OVERDUE"
            msg += f"🔹 `{t['id']}` | **{t['task_desc']}**\nTo: @{t['assignee']} | By: @{t['assigned_by']} | ⏳ {status}\n\n"
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: pass

# --- 6/ AWAY MODE ---
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        status = await conn.fetchrow("SELECT end_time FROM away_status WHERE username=$1", username)
        if status: return await update.message.reply_text(f"You are already marked as Away until {status['end_time'].astimezone(WIB).strftime('%m/%d %H:%M WIB')}. Please type `/back` to reset.", parse_mode="Markdown")

    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 1)]
        if len(parts) < 2 or not all(parts): raise ValueError
        reason, time_str = parts[0], parts[1]
        end_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
        if end_time < datetime.datetime.now(WIB): 
            return await update.message.reply_text("The time provided is in the past! Please set a future time.")
    except ValueError: return await update.message.reply_text("Time format error. Strictly use `MM/DD/YYYY HH.MM` (e.g., `06/25/2026 14.30`).", parse_mode="Markdown")
    except: return await update.message.reply_text("Format error: `/away Reason , MM/DD/YYYY HH.MM`", parse_mode="Markdown")

    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3)', username, reason, end_time)
    
    for j in context.job_queue.get_jobs_by_name(f"away_{username}"): j.schedule_removal()
    context.job_queue.run_once(auto_return_away, when=end_time, data={"username": username, "chat_id": update.effective_chat.id}, name=f"away_{username}")
    await update.message.reply_text(f"🏖️ @{username} is away until {end_time.strftime('%b %d at %H:%M WIB')}.")

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username)
        if not status: return await update.message.reply_text("You are not marked as Away. Your status is already available 🟢.")
    
    for j in context.job_queue.get_jobs_by_name(f"away_{username}"): j.schedule_removal()
    await process_return(username, context.bot, update.effective_chat.id)

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE): 
    await process_return(context.job.data['username'], context.bot, context.job.data['chat_id'])

async def process_return(username, bot, chat_id=None):
    pool = bot.application.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        mentions = await conn.fetch('SELECT mentioner, message, chat_title, created_at FROM away_mentions WHERE away_username=$1 ORDER BY created_at ASC', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
        
    msg = f"🎉 **A warm welcome back, @{username}!** You are now marked as **🟢 Available**.\n\n"
    if mentions:
        msg += "Here are the mentions you missed:\n\n"
        for m in mentions:
            t_str = m['created_at'].astimezone(WIB).strftime('%m/%d %H:%M WIB')
            msg += f"🔹 [{t_str}] in **{m['chat_title']}**\n**@{m['mentioner']}**: \"{m['message']}\"\n\n"
    else: msg += "It was quiet! You had absolutely zero mentions."
        
    if chat_id: 
        try: await bot.send_message(chat_id, f"Welcome back @{username}! Your status is 🟢 Available. I've DM'd you your missed notifications.")
        except: pass
    if user_id: 
        try: await bot.send_message(user_id, msg, parse_mode="Markdown")
        except: pass

async def