import logging, datetime, pytz, os, asyncpg
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat, BotCommandScopeDefault
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

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

async def log_star_action(pool, action_text: str):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO star_logs (log_text) VALUES ($1)", action_text)

# --- DYNAMIC MENU BUILDER ---
async def update_user_menu(user_id: int, username: str, pool, bot):
    is_adm = await is_bot_admin(username, pool)
    is_sup = await is_super(username)
    
    base_cmds = [
        BotCommand("help", "View Nukhba Manager Guide"),
        BotCommand("newevent", "[1] Schedule an event"),
        BotCommand("events", "[1] View upcoming events"),
        BotCommand("poll", "[2] Create a team poll"),
        BotCommand("mystar", "[3] RAWWY Stars earned this month"),
        BotCommand("totalstar", "[3] RAWWY Stars earned all-time"),
        BotCommand("myquota", "[3] Star Quota left to give"),
        BotCommand("thanks", "[3] (Reply) Send a Star"),
        BotCommand("addlib", "[4] Save to Library"),
        BotCommand("getlib", "[4] Retrieve from Library"),
        BotCommand("library", "[4] Browse Library"),
        BotCommand("assign", "[5] Assign a task"),
        BotCommand("complete", "[5] Mark task complete"),
        BotCommand("mytasks", "[5] View your tasks"),
        BotCommand("away", "[6] Set Away status"),
        BotCommand("back", "[6] Return from Away"),
        BotCommand("bugreport", "[7] Report issue to Super Admin")
    ]
    
    if is_adm:
        base_cmds.extend([
            BotCommand("help_admin", "View Admin Toolsuite"),
            BotCommand("addbday", "[Admin] Add Birthday"),
            BotCommand("listbdays", "[Admin] List Birthdays"),
            BotCommand("checkstars", "[Admin] Audit Stars"),
            BotCommand("admin_stars", "[Admin] Edit User Stars"),
            BotCommand("cancelevent", "[Admin] Cancel Event"),
            BotCommand("canceltask", "[Admin] Cancel Task"),
            BotCommand("dellib", "[Admin] Delete Asset"),
            BotCommand("announce", "[Admin] Broadcast Message")
        ])
    if is_sup:
        base_cmds.extend([
            BotCommand("addadmin", "[Super] Promote Admin"),
            BotCommand("deladmin", "[Super] Demote Admin"),
            BotCommand("listadmins", "[Super] View Admins"),
            BotCommand("removemember", "[Super] Offboard User"),
            BotCommand("botstatus", "[Super] View Diagnostics"),
            BotCommand("super_reset", "[Super] Factory Wipe")
        ])
        
    try: await bot.set_my_commands(base_cmds, scope=BotCommandScopeChat(chat_id=user_id))
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
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE, assigned_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (username TEXT PRIMARY KEY, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (username TEXT PRIMARY KEY, bday TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcements (id SERIAL PRIMARY KEY, text TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcement_messages (announcement_id INT, chat_id BIGINT, message_id BIGINT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_stats (date DATE PRIMARY KEY, uses INT DEFAULT 0, errors INT DEFAULT 0);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bug_reports (id SERIAL PRIMARY KEY, username TEXT, report TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS star_logs (id SERIAL PRIMARY KEY, log_text TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')

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
        BotCommand("getlib", "[4] Get Library Asset"),
        BotCommand("library", "[4] Browse Library"),
        BotCommand("assign", "[5] Assign Task"),
        BotCommand("complete", "[5] Complete Task"),
        BotCommand("mytasks", "[5] My To-Do List"),
        BotCommand("away", "[6] Go Away"),
        BotCommand("back", "[6] Return")
    ]
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeDefault())
    logger.info("✅ Database & Scoped Menus Configured!")

# --- CORE USER INTERFACE ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, update.effective_user.username, pool, context.bot)
    await update.message.reply_text("🤖 Hello! **[RW] Nukhba Manager is fully operational.** Type `/help` to see the command manual.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, update.effective_user.username, pool, context.bot)
        
    help_text = (
        "🚀 *[RW] Nukhba Manager Guide*\n\n"
        "📅 *1/ Events*\n`/newevent Title , MM/DD/YYYY HH.MM , RemMins`\n`/events`\n\n"
        "📊 *2/ Polls*\n`/poll Question , Hours , Opt1 , Opt2`\n\n"
        "🌟 *3/ RAWWY Stars*\n`/thanks` (reply) | `/myquota` | `/mystar` | `/totalstar`\n\n"
        "📚 *4/ Library*\n`/addlib Name , Content` *(Add 'private' at the end to lock it!)*\n`/getlib Name` | `/library`\n\n"
        "⚡ *5/ Tasks*\n`/assign @user , 60 , Task description` *(Between 60-480m)*\n`/complete ID` | `/mytasks`\n\n"
        "🏖️ *6/ Away Mode*\n`/away Reason , MM/DD/YYYY HH.MM` | `/back`\n\n"
        "🐛 *Extras*\n`/bugreport Explain the issue`"
    )
    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("📬 I have securely sent the manual to your Direct Messages!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("I cannot send you a DM yet. Please start a private chat with me first!")

async def help_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    
    if not await is_bot_admin(username, pool): return
    is_owner = await is_super(username)
    
    help_text = (
        "🔐 *[RW] NUKHBA ADMIN SUITE*\n\n"
        "🎂 *Birthdays:* `/addbday @user , MM/DD` | `/listbdays`\n"
        "🌟 *Stars:* `/checkstars all` | `/checkstars @user`\n"
        "⚙️ *Edit Stars:* `/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`\n"
        "🗑️ *Overrides:* `/cancelevent ID` | `/canceltask ID` | `/dellib Name`\n"
        "📢 *Broadcast:* `/announce [ChatID/All] , Message` | `/editannounce ID , Msg` | `/delannounce ID`"
    )
    if is_owner:
        help_text += (
            "\n\n👑 *SUPER OWNER EXCLUSIVES*\n"
            "🛡️ *Access:* `/addadmin @user` | `/deladmin @user` | `/listadmins`\n"
            "🛑 *Offboarding:* `/removemember @user` (Wipes data & drops tasks)\n"
            "📈 *System:* `/botstatus`\n"
            "☢️ *Wipe:* `/super_reset [stars/tasks/library/events/away]`"
        )
    await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Nothing happens on this command. Please check with the admin or type `/help`.")

# --- CRON JOBS ---
async def daily_morning_log(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        owner_id = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', SUPER_OWNER)
        if not owner_id: return

        stats = await conn.fetchrow('SELECT uses, errors FROM bot_stats WHERE date=CURRENT_DATE - INTERVAL \'1 day\'')
        bugs = await conn.fetch('SELECT username, report FROM bug_reports')
        star_logs = await conn.fetch('SELECT log_text FROM star_logs ORDER BY created_at ASC')
        
        msg = "🌅 **Good Morning, Super Owner. Here is your Daily Diagnostic:**\n\n"
        msg += f"📈 **Usage Yesterday:** {stats['uses'] if stats else 0} interactions\n"
        msg += f"⚠️ **Errors Caught:** {stats['errors'] if stats else 0} errors\n\n"
        msg += "🐛 **Bug Reports:**\n" + ("\n".join([f"- @{b['username']}: {b['report']}" for b in bugs]) if bugs else "No bugs reported! 🎉")
        msg += "\n\n🌟 **RAWWY Star Audit Log:**\n" + ("\n".join([f"- {s['log_text']}" for s in star_logs]) if star_logs else "No admin star modifications yesterday.")

        try: await context.bot.send_message(owner_id, msg, parse_mode="Markdown")
        except: pass
        
        await conn.execute("TRUNCATE bug_reports")
        await conn.execute("TRUNCATE star_logs")

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
    async with pool.acquire() as conn:
        await conn.execute("UPDATE kudos SET quota = 3")

# --- 3/ RAWWY STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: 
        return await update.message.reply_text("Please reply to a specific user's message to give them a Star quota!")
    giver = update.effective_user.username
    receiver_user = update.message.reply_to_message.from_user
    receiver = receiver_user.username
    
    if receiver_user.is_bot: 
        return await update.message.reply_text("Oops! I appreciate the thought, but bots cannot receive RAWWY Stars.")
    if giver == receiver: 
        return await update.message.reply_text("Nice try! You cannot give RAWWY Stars to yourself. Please share the love with the team.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
        if q <= 0: 
            return await update.message.reply_text("You have used up all your RAWWY Star Quota for this week! Wait until Monday for a reset.")
        
        await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
        new_q = q - 1
        
    await update.message.reply_text(f"🌟 **Star Sent!**\n@{receiver} received a RAWWY Star from @{giver}!\n\n*(You have {new_q} Star Quota remaining this week)*", parse_mode="Markdown")

async def my_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 Hello @{user}, you currently have **{q} Star Quota** left to give to others this week.", parse_mode="Markdown")

async def my_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        pts = await conn.fetchval('SELECT monthly_points FROM kudos WHERE username=$1', user)
    if not pts or pts == 0:
        await update.message.reply_text("You haven't received any RAWWY Stars this month yet. Keep helping others to earn some!")
    else:
        await update.message.reply_text(f"🌟 Awesome! You have received **{pts} RAWWY Stars** this month. Keep it up!", parse_mode="Markdown")

async def total_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        pts = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', user)
    if not pts or pts == 0:
        await update.message.reply_text("You haven't collected any RAWWY Stars historically.")
    else:
        await update.message.reply_text(f"🌟 Impressive! You have collected a total of **{pts} RAWWY Stars** of all time.", parse_mode="Markdown")

async def check_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: target = " ".join(context.args).replace("@", "").strip()
    except: return await context.bot.send_message(update.effective_user.id, "Please use: `/checkstars all` OR `/checkstars @user`")
    if not target: return await context.bot.send_message(update.effective_user.id, "Please provide a user or 'all'.")
    
    async with pool.acquire() as conn:
        if target.lower() == 'all':
            recs = await conn.fetch('SELECT username, quota, all_time_points FROM kudos')
            msg = "🌟 **Team Stars Data**\n" + "\n".join([f"@{r['username']} - Quota: {r['quota']} | Total: {r['all_time_points']}" for r in recs]) if recs else "No records found."
        else:
            r = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
            msg = f"🌟 **@{target}**\nTotal: {r['all_time_points']} | Monthly: {r['monthly_points']} | Quota: {r['quota']}" if r else "User not found in database."
    try: await context.bot.send_message(update.effective_user.id, msg)
    except: pass

async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    
    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.split(",", 3) if p.strip()]
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
        
        await log_star_action(pool, f"Admin @{update.effective_user.username} executed '{act}' to modify @{t}'s {field} by {amt}.")
    await context.bot.send_message(update.effective_user.id, f"✅ The {field} stars for @{t} have been successfully updated.")

# --- 5/ QUICK TASKS ---
async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.split(",", 2)]
        if len(parts) < 3 or not all(parts): raise ValueError
        a = parts[0].replace("@", ""); m = int(parts[1]); d = parts[2]
    except: 
        return await update.message.reply_text("You missed some details! Format: `/assign @user , Minutes , Task description`", parse_mode="Markdown")
        
    assigner = update.effective_user.username
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
    pool = context.job_queue.application.bot_data.get('db_pool')
    async with pool.acquire() as conn: task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed': 
        await context.bot.send_message(context.job.chat_id, f"⚠️ Hello @{context.job.data['assignee']} and @{context.job.data['assigner']}, your task '{context.job.data['desc']}' is about to hit its deadline in exactly 10 minutes!")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await update.message.reply_text("Please provide the numeric ID: `/complete ID`", parse_mode="Markdown")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assignee, status FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("I couldn't find that task in the database.")
        if task['status'] == 'Completed': return await update.message.reply_text("This task is already finished!")
        if task['assignee'] != update.effective_user.username: return await update.message.reply_text("Only the specific person assigned to this task can mark it complete.")
        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
    await update.message.reply_text(f"✅ Great job! Task `{t_id}` is officially marked as completed.", parse_mode="Markdown")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await update.message.reply_text("Please provide the ID: `/canceltask ID`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("I couldn't find that task.")
        if task['assigned_by'] != update.effective_user.username and not await is_bot_admin(update.effective_user.username, pool): 
            return await update.message.reply_text("Only the person who assigned this task, or an Admin, can cancel it.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await update.message.reply_text("🗑️ Task successfully cancelled.")

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        tasks = await conn.fetch("SELECT id, task_desc, deadline FROM tasks WHERE status='Pending' AND assignee=$1 ORDER BY deadline", update.effective_user.username)
    if not tasks: msg = "🎉 You have no pending tasks! Great job catching up."
    else:
        msg = "📋 **Your Active Tasks**\n\n"
        for t in tasks:
            rem = int((t['deadline'] - now).total_seconds() / 60)
            status = f"{rem}m left" if rem > 0 else "OVERDUE"
            msg += f"🔹 `{t['id']}` | {t['task_desc']} | ⏳ {status}\n"
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: await update.message.reply_text("Please start a DM with me so I can privately send you your task list.")

# --- 6/ AWAY MODE ---
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        status = await conn.fetchrow("SELECT end_time FROM away_status WHERE username=$1", username)
        if status: return await update.message.reply_text(f"You are already marked as Away until {status['end_time'].astimezone(WIB).strftime('%m/%d %H:%M WIB')}. Please type `/back` if you wish to reset your status.", parse_mode="Markdown")

    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 1)]
        if len(parts) < 2 or not all(parts): raise ValueError
        reason, time_str = parts[0], parts[1]
        end_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
        if end_time < datetime.datetime.now(WIB): 
            return await update.message.reply_text("The date and time you provided is in the past! Please set a future time.")
    except ValueError: 
        return await update.message.reply_text("The time format is incorrect. Please strictly use `MM/DD/YYYY HH.MM` (e.g., `06/25/2026 14.30`).", parse_mode="Markdown")
    except: 
        return await update.message.reply_text("Oops! Make sure you use the exact format: `/away Reason , MM/DD/YYYY HH.MM`", parse_mode="Markdown")

    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3) ON CONFLICT (username) DO UPDATE SET reason=$2, end_time=$3, last_notified=NULL', username, reason, end_time)
    context.job_queue.run_once(auto_return_away, when=end_time, data=username, name=f"away_{username}")
    await update.message.reply_text(f"🏖️ Got it! @{username} is officially set to Away until {end_time.strftime('%b %d at %H:%M WIB')}.")

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', update.effective_user.username)
        if not status: return await update.message.reply_text("You are not currently marked as Away. Your status is already available!")
    await process_return(update.effective_user.username, context.bot, update.effective_chat.id)

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE): await process_return(context.job.data, context.bot)

async def process_return(username, bot, chat_id=None):
    pool = bot.application.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        mentions = await conn.fetch('SELECT mentioner, message, chat_title, created_at FROM away_mentions WHERE away_username=$1 ORDER BY created_at ASC', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
        user_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
        
    msg = f"🎉 **A warm welcome back, @{username}!** Your Away status has been safely cleared, and you are available again.\n\n"
    if mentions:
        msg += "Here is the exact recap of what you missed while you were out:\n\n"
        for m in mentions:
            t_str = m['created_at'].astimezone(WIB).strftime('%m/%d %H:%M WIB')
            msg += f"🔹 [{t_str}] in **{m['chat_title']}**\n**@{m['mentioner']}** mentioned you: \"{m['message']}\"\n\n"
    else:
        msg += "It was surprisingly quiet! You had absolutely zero mentions."
        
    try: 
        if user_id: await bot.send_message(user_id, msg, parse_mode="Markdown")
        if chat_id: await bot.send_message(chat_id, f"Welcome back @{username}! Your status is available again. I have DM'd you your missed notifications.")
    except: pass

# --- ADMINISTRATION CONTROLS ---
async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: 
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.split(",", 1)]
        if len(parts) < 2 or not all(parts): raise ValueError
        target, msg = parts[0], parts[1]
    except: return await context.bot.send_message(update.effective_user.id, "Please correctly use: `/announce [ChatID or All] , Message`", parse_mode="Markdown")
    
    async with pool.acquire() as conn:
        a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", msg)
        targets = await conn.fetch("SELECT chat_id FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target)}]
        sent = 0
        for t in targets:
            try:
                formatted_msg = f"📢 **[RW] NUKHBA BROADCAST**\n\nGreetings Team,\n\n{msg}"
                m = await context.bot.send_message(t['chat_id'], formatted_msg, parse_mode="Markdown")
                await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
                sent += 1
            except: pass
    await context.bot.send_message(update.effective_user.id, f"✅ Broadcast Campaign complete. Announcement ID `{a_id}` successfully hit {sent} groups.", parse_mode="Markdown")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, "Please use the correct format: `/addadmin @user`", parse_mode="Markdown")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
        user_id = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', target)
        
    if user_id:
        try: 
            await update_user_menu(user_id, target, pool, context.bot)
            
            help_text = (
                "🔐 *[RW] NUKHBA ADMIN SUITE*\n\n"
                "🎂 *Birthdays:* `/addbday @user , MM/DD` | `/listbdays`\n"
                "🌟 *Stars:* `/checkstars all` | `/checkstars @user`\n"
                "⚙️ *Edit Stars:* `/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`\n"
                "🗑️ *Overrides:* `/cancelevent ID` | `/canceltask ID` | `/dellib Name`\n"
                "📢 *Broadcast:* `/announce [ChatID/All] , Message` | `/editannounce ID , Msg` | `/delannounce ID`"
            )
            await context.bot.send_message(user_id, f"🎉 **Congratulations!** You have been officially promoted to a Global Bot Admin.\n\n{help_text}", parse_mode="Markdown")
        except: pass
    await context.bot.send_message(update.effective_user.id, f"✅ @{target} has been heavily promoted to Bot Admin.")

async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: 
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.split(",", 1)]
        if len(parts) < 2 or not all(parts): raise ValueError
        u = parts[0].replace("@", ""); b = parts[1]
        datetime.datetime.strptime(b, "%m/%d")
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error. Try: `/addbday @user , MM/DD`", parse_mode="Markdown")
    async with pool.acquire() as conn: 
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET bday=EXCLUDED.bday', u, b)
    await context.bot.send_message(update.effective_user.id, f"🎂 Birthday securely logged for @{u}.")

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    pool = context.bot_data.get('db_pool')
    now = datetime.datetime.now(WIB)
    
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET user_id=$2", update.effective_user.username, update.effective_user.id)
        await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, 1, 0) ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + 1")
        
        chat = update.effective_chat
        if chat.type in ['group', 'supergroup']:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
            
        text, mentioner = update.message.text, update.effective_user.username
        aways = await conn.fetch('SELECT username, reason, end_time, last_notified FROM away_status')
        for a in aways:
            if f"@{a['username']}" in text:
                await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], mentioner, text, chat.title or "DM")
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
    if not text: return await update.message.reply_text("Oops! You forgot to include the issue. Please type: `/bugreport [explain the bug here]`", parse_mode="Markdown")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", update.effective_user.username, text)
    await update.message.reply_text("Thank you so much! I have securely filed this bug report for the Super Admin to review tomorrow morning. 🐛🥾")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception handled:", exc_info=context.error)
    pool = context.bot_data.get('db_pool')
    if pool:
        async with pool.acquire() as conn: await conn.execute("UPDATE bot_stats SET errors = errors + 1 WHERE date=CURRENT_DATE")

async def security_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id: 
            inviter = update.message.from_user.username
            pool = context.bot_data.get('db_pool')
            if not await is_bot_admin(inviter, pool):
                await context.bot.send_message(update.effective_chat.id, "❌ **Access Denied.** I am a private enterprise bot. You are not authorized to deploy me here. Leaving chat.")
                await context.bot.leave_chat(update.effective_chat.id)
                return
            else:
                await context.bot.send_message(update.effective_chat.id, "✅ **Authorization confirmed.** [RW] Nukhba Manager is now online and syncing data.")

# --- EVENTS ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 2)]
        if len(parts) < 3 or not all(parts): raise ValueError
        title = parts[0]; e_time = WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H.%M")); rem = int(parts[2])
        if e_time < datetime.datetime.now(WIB): return await update.message.reply_text("I can't schedule things in the past! Please provide a future date.")
    except: return await update.message.reply_text("Oops, format error! Try: `/newevent Title , MM/DD/YYYY HH.MM , RemMins`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by) VALUES ($1, $2, $3) RETURNING id', title, e_time, update.effective_user.username)
    kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not Going")]]
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_{e_id}")
    await update.message.reply_text(f"📅 **{title} has been scheduled!**\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        raw_args = " ".join(context.args)
        id_part, rest = raw_args.split(",", 1)
        title_part, time_str, rem_str = [p.strip() for p in rest.rsplit(",", 2)]
        e_id = int(id_part.strip()); title = title_part; e_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M")); rem = int(rem_str)
    except: return await update.message.reply_text("Please use: `/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, e_id)
    for job in context.job_queue.get_jobs_by_name(f"event_{e_id}"): job.schedule_removal()
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_{e_id}")
    await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if not events: return await update.message.reply_text("No upcoming events scheduled.")
    await update.message.reply_text("📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}**\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; _, e_id, status = q.data.split("_")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status=$3', int(e_id), q.from_user.username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title FROM events WHERE id=$1', int(e_id))
    if not event: return await q.answer("Event deleted.")
    await q.edit_message_text(f"📅 **{event['title']}**\n" + "".join([f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n" for r in all_rsvps]), reply_markup=q.message.reply_markup, parse_mode="Markdown")
    await q.answer(status)

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.job_queue.application.bot_data.get('db_pool')
    async with pool.acquire() as conn: r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    await context.bot.send_message(context.job.chat_id, f"⏰ Hey everyone! The event **{context.job.data['title']}** is starting very soon.\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

# --- POLLS ---
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.split(",")]
        if len(parts) < 4: raise ValueError
        dur = int(parts[1]) * 3600
        msg = await context.bot.send_poll(update.effective_chat.id, parts[0], parts[2:], is_anonymous=False, allows_multiple_answers=True, open_period=dur)
        rem_time = datetime.datetime.now(WIB) + datetime.timedelta(seconds=dur) - datetime.timedelta(minutes=15)
        if dur > 900:
            context.job_queue.run_once(poll_reminder, when=rem_time, data={"chat_id": update.effective_chat.id, "q": parts[0], "msg_id": msg.message_id})
    except: await update.message.reply_text("Poll format error. Use: `/poll Question , Hours , Opt1 , Opt2`")

async def poll_reminder(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.send_message(context.job.data['chat_id'], f"⏳ **Attention team!** The poll '{context.job.data['q']}' is ending in 15 minutes! Please get your votes in.", reply_to_message_id=context.job.data['msg_id'], parse_mode="Markdown")
    except: pass

# --- LIBRARY ---
async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_args = " ".join(context.args)
    if not raw_args: return await update.message.reply_text("Looks like you missed something! Format: `/addlib Name , Link/Content , [private]`", parse_mode="Markdown")
    try:
        parts = [p.strip() for p in raw_args.split(",")]
        if len(parts) < 2: raise ValueError
        if parts[-1].lower() == 'private':
            is_private = True
            content = ", ".join(parts[1:-1]).strip()
            await delete_cmd(update)
        else:
            is_private = False
            content = ", ".join(parts[1:]).strip()
        name = parts[0].lower()
    except: return await update.message.reply_text("Oops! The format seems a bit off. Please use: `/addlib Name , Content`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4) ON CONFLICT (name) DO UPDATE SET content=EXCLUDED.content, added_by=EXCLUDED.added_by, is_private=EXCLUDED.is_private', name, content, update.effective_user.username, is_private)
    
    target_chat = update.effective_user.id if is_private else update.effective_chat.id
    try: await context.bot.send_message(target_chat, f"✅ The library asset **'{name}'** was successfully added by {update.effective_user.first_name}! {'🔒 (Private)' if is_private else ''}", parse_mode="Markdown")
    except: pass

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: name = " ".join(context.args).strip().lower()
    except: return await update.message.reply_text("What asset are you looking for? Try: `/getlib Name`")
    if not name: return await update.message.reply_text("Please provide the asset name.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT content, added_by, is_private FROM library WHERE name=$1', name)
        
    if not r: return await update.message.reply_text("Hmm, I couldn't find that asset in the library.")
    if r['is_private']:
        await delete_cmd(update)
        if r['added_by'] != update.effective_user.username:
            return await context.bot.send_message(update.effective_user.id, "Sorry, you don't have permission to view this private file.")
        try: await context.bot.send_message(update.effective_user.id, f"🔒 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
        except: await update.message.reply_text("Please start a DM with me so I can send your private files securely.")
    else:
        await update.message.reply_text(f"📂 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: name = " ".join(context.args).strip().lower()
    except: return await context.bot.send_message(update.effective_user.id, "Please provide an asset to delete: `/dellib Name`")
    if not name: return await context.bot.send_message(update.effective_user.id, "Asset name cannot be blank.")
    
    async with pool.acquire() as conn:
        if await conn.execute('DELETE FROM library WHERE name=$1', name) == "DELETE 0": 
            return await context.bot.send_message(update.effective_user.id, "That asset doesn't exist.")
    await context.bot.send_message(update.effective_user.id, f"🗑️ The asset '{name}' was successfully removed.")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
    if not recs: return await update.message.reply_text("📚 Library is empty.")
    
    msg = "📚 **RAWWY Library**\n"
    for r in recs:
        if r['is_private']:
            if r['added_by'] == update.effective_user.username:
                msg += f"• 🔒 `{r['name']}` (Private)\n"
        else:
            msg += f"• 📂 `{r['name']}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, "Please use: `/deladmin @user`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        res = await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
        user_id = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', target)
        
    if res != "DELETE 0":
        if user_id:
            try: await context.bot.send_message(user_id, "⚠️ Your Global Bot Admin privileges have been revoked by the Super Owner.")
            except: pass
        await context.bot.send_message(update.effective_user.id, f"🗑️ @{target} removed from Admins.")
    else:
        await context.bot.send_message(update.effective_user.id, "❌ That user is not currently an admin.")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: admins = await conn.fetch('SELECT username FROM bot_admins')
    msg = "👑 **Bot Admins**\n" + "\n".join([f"• @{a['username']}" for a in admins]) if admins else "👑 **Bot Admins**\nNone (Only Super Owner exists)."
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "")
    except: return await context.bot.send_message(update.effective_user.id, "Please use: `/removemember @user`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM bot_admins WHERE username=$1', target.lower())
        await conn.execute('DELETE FROM kudos WHERE username=$1', target)
        await conn.execute('DELETE FROM birthdays WHERE username=$1', target)
        await conn.execute('DELETE FROM away_status WHERE username=$1', target)
        await conn.execute("UPDATE tasks SET assignee='Unassigned' WHERE assignee=$1", target)
    await context.bot.send_message(update.effective_user.id, f"🗑️ **Member Offboarded:** @{target}'s data has been wiped entirely and tasks safely reassigned.", parse_mode="Markdown")

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        groups = await conn.fetch("SELECT title FROM active_groups")
        u_count = await conn.fetchval("SELECT COUNT(*) FROM kudos")
        t_count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Pending'")
        l_count = await conn.fetchval("SELECT COUNT(*) FROM library")
    
    msg = "📈 **Enterprise System Status**\n\n"
    msg += f"👥 Users Tracked: `{u_count}`\n📋 Pending Tasks: `{t_count}`\n📚 Library Assets: `{l_count}`\n\n"
    msg += f"🏠 **Active Groups ({len(groups)}):**\n" + "\n".join([f"• {g['title']}" for g in groups])
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def super_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    try: feat = context.args[0].lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/super_reset [stars/tasks/library/events/away]`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        try:
            if feat == "stars": await conn.execute("TRUNCATE kudos")
            elif feat == "tasks": await conn.execute("TRUNCATE tasks RESTART IDENTITY")
            elif feat == "library": await conn.execute("TRUNCATE library")
            elif feat == "events": await conn.execute("TRUNCATE events CASCADE RESTART IDENTITY")
            elif feat == "away": await conn.execute("TRUNCATE away_status, away_mentions CASCADE")
            else: return await context.bot.send_message(update.effective_user.id, "❌ Invalid feature to reset.")
            await context.bot.send_message(update.effective_user.id, f"⚠️ **SUPER RESET:** {feat.upper()} data wiped completely.")
        except Exception as e:
            await context.bot.send_message(update.effective_user.id, f"❌ Database Error: {e}")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn: b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    await context.bot.send_message(update.effective_user.id, "🎂 **Birthdays**\n" + "\n".join([f"• @{x['username']}: {x['bday']}" for x in b]) if b else "None saved.")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: e_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/cancelevent ID`")
    
    async with pool.acquire() as conn: 
        if await conn.execute('DELETE FROM events WHERE id=$1', e_id) == "DELETE 0":
            return await context.bot.send_message(update.effective_user.id, "Event not found.")
    for j in context.job_queue.get_jobs_by_name(f"event_{e_id}"): j.schedule_removal()
    await context.bot.send_message(update.effective_user.id, "🗑️ Cancelled.")

async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: 
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.split(",", 1)]
        a_id = int(parts[0]); new_msg = parts[1]
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/editannounce ID , New Msg`")
    
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try: await context.bot.edit_message_text(f"📢 **[RW] NUKHBA BROADCAST**\n\nGreetings Team,\n\n{new_msg}", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
            except: pass
        await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", new_msg, a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Updated Announcement {a_id}.")

async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: a_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/delannounce ID`")
    
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try: await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
            except: pass
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
        await conn.execute("DELETE FROM announcement_messages WHERE announcement_id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Deleted Announcement {a_id}.")

# --- RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db
    app.add_error_handler(error_handler)

    app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(weekly_quota_reset, datetime.time(hour=0, minute=0, tzinfo=WIB), days=(0,))
    # No "days=" argument ensures it checks daily if it's the 1st of the month
    app.job_queue.run_daily(monthly_leaderboard, datetime.time(hour=13, minute=0, tzinfo=WIB))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("help_admin", help_admin_command))
    app.add_handler(CommandHandler("bugreport", report_bug))
    
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("deladmin", del_admin))
    app.add_handler(CommandHandler("listadmins", list_admins))
    app.add_handler(CommandHandler("removemember", remove_member))
    app.add_handler(CommandHandler("super_reset", super_reset))
    app.add_handler(CommandHandler("botstatus", bot_status))
    
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("editannounce", edit_announce))
    app.add_handler(CommandHandler("delannounce", del_announce))
    app.add_handler(CommandHandler("admin_stars", admin_stars))
    app.add_handler(CommandHandler("checkstars", check_stars))
    app.add_handler(CommandHandler("addbday", add_bday))
    app.add_handler(CommandHandler("listbdays", list_bdays))
    app.add_handler(CommandHandler("cancelevent", cancel_event))
    app.add_handler(CommandHandler("canceltask", cancel_task))
    app.add_handler(CommandHandler("dellib", del_lib))
    
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
    app.add_handler(CommandHandler("addlib", add_lib))
    app.add_handler(CommandHandler("getlib", get_lib))
    app.add_handler(CommandHandler("library", list_lib))

    app.add_handler(CallbackQueryHandler(rsvp_callback, pattern="^rsvp_"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, security_check))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_tracker))

    logger.info("Starting Enterprise bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
