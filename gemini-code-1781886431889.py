import logging, datetime, pytz, os, asyncpg
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL")
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- HELPERS ---
async def is_admin(update: Update) -> bool:
    """Checks if the user is an admin in the group."""
    if update.effective_chat.type == "private": return True
    try:
        member = await update.effective_chat.get_member(update.effective_user.id)
        return member.status in ['creator', 'administrator']
    except:
        return False

# --- DATABASE SETUP ---
async def init_db(app: Application):
    if not DATABASE_URL:
        logger.error("DATABASE_URL missing!")
        return
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS kudos (username TEXT PRIMARY KEY, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0, quota INT DEFAULT 3);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (username TEXT PRIMARY KEY, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (id SERIAL PRIMARY KEY, username TEXT, bday TEXT);''')
        
    commands = [
        BotCommand("help", "Show Nukhba Manager Guide"),
        BotCommand("away", "[Away] Reason , MM/DD/YYYY HH.MM"),
        BotCommand("back", "[Away] Remove away status early"),
        BotCommand("thanks", "[Stars] (Reply) Give a RAWWY Star"),
        BotCommand("leaderboard", "[Stars] Top RAWWY Stars"),
        BotCommand("checkstars", "[Stars] (Admin) Check user Stars"),
        BotCommand("admin_stars", "[Stars] (Admin) Modify quotas/totals"),
        BotCommand("newevent", "[Events] Title , MM/DD/YYYY HH.MM , RemMins"),
        BotCommand("editevent", "[Events] ID , Title , MM/DD/YYYY HH.MM , RemMins"),
        BotCommand("cancelevent", "[Events] ID - Cancel an event"),
        BotCommand("events", "[Events] Upcoming events"),
        BotCommand("assign", "[Tasks] @user , Mins (Max 72) , Task desc"),
        BotCommand("complete", "[Tasks] ID - Mark task done"),
        BotCommand("tasks", "[Tasks] View pending tasks"),
        BotCommand("addlib", "[Library] Name , Content"),
        BotCommand("getlib", "[Library] Name"),
        BotCommand("library", "[Library] View assets"),
        BotCommand("addbday", "[Bday] (Admin) @user , MM/DD"),
        BotCommand("poll", "[Polls] Question , Hours , Opt1 , Opt2")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Advanced Database & Menus Configured!")

# --- CORE COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 [RW] Nukhba Manager is online!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🛠️ *[RW] Nukhba Manager Guide*\n\n"
        "*🏖️ Away Mode*\n`/away Reason , MM/DD/YYYY HH.MM`\n`/back`\n\n"
        "*🌟 RAWWY Stars*\n`/thanks` (reply to msg)\n`/leaderboard`\n"
        "*(Admin)* `/checkstars @user`\n"
        "*(Admin)* `/admin_stars @user , [set_quota/add_total/sub_total] , [amount]`\n\n"
        "*📅 Events*\n`/newevent Title , MM/DD/YYYY HH.MM , ReminderMins`\n"
        "`/editevent ID , Title , MM/DD/YYYY HH.MM , ReminderMins`\n"
        "`/cancelevent ID`\n`/events`\n\n"
        "*📋 Tasks (Max 72m)*\n`/assign @user , 60 , Task`\n`/complete [id]`\n`/tasks`\n\n"
        "*🎂 Birthdays (Admin Only)*\n`/addbday @user , MM/DD`\n`/listbdays`\n\n"
        "*📊 Polls*\n`/poll Question , Hours , Opt1 , Opt2`\n\n"
        "*📚 Library*\n`/addlib Name , Link`\n`/getlib [name]`\n`/library`"
    )
    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("📬 Guide sent to DM!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("❌ Please start a DM with me first!")

# --- 8/ AWAY SYSTEM ---
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if "," not in text:
        return await update.message.reply_text(
            "🏖️ **Set Away Status:**\nTap to copy and fill out:\n\n`/away Reason , MM/DD/YYYY HH.MM`", 
            parse_mode="Markdown"
        )
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 2: raise ValueError
        reason, time_str = parts[0], parts[1]
        end_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
        if end_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ Error: Time cannot be in the past.")
    except Exception:
        return await update.message.reply_text("❌ Error: Invalid format. Please use exactly `Reason , MM/DD/YYYY HH.MM` (e.g. `Lunch , 06/20/2026 13.00`).")

    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3) ON CONFLICT (username) DO UPDATE SET reason=$2, end_time=$3, last_notified=NULL', username, reason, end_time)
    
    context.job_queue.run_once(auto_return_away, when=end_time, data=username, name=f"away_{username}")
    await update.message.reply_text(f"✅ @{username} is away until {end_time.strftime('%m/%d %H:%M WIB')}.")

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE):
    await process_return(context.job.data, context.bot)

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_return(update.effective_user.username, context.bot, update.effective_chat.id)

async def process_return(username, bot, chat_id=None):
    pool = bot.application.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username)
        if not status: return
        
        mentions = await conn.fetch('SELECT mentioner, message, chat_title FROM away_mentions WHERE away_username=$1', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)

    msg = "👋 Welcome back! Here is what you missed:\n\n"
    if not mentions: msg += "No one mentioned you."
    else:
        for m in mentions: msg += f"🔹 **@{m['mentioner']}** in *{m['chat_title']}*:\n\"{m['message']}\"\n\n"
    
    try: 
        if chat_id: await bot.send_message(chat_id, f"Welcome back @{username}! I've wiped your away status.")
        # DM recap
        # Requires user to have interacted via DM. Using username is tricky natively, usually user_id is needed for DMs.
        # This assumes the bot can reach them, or logs it.
    except Exception as e: logger.error(f"Could not send away summary: {e}")

async def check_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    chat_title = update.effective_chat.title or "Private Chat"
    mentioner = update.effective_user.username
    now = datetime.datetime.now(WIB)
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        aways = await conn.fetch('SELECT username, reason, end_time, last_notified FROM away_status')
        for a in aways:
            if f"@{a['username']}" in text:
                await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], mentioner, text, chat_title)
                last = a['last_notified']
                if not last or (now - last).total_seconds() > 3600:
                    time_str = a['end_time'].strftime('%m/%d %H:%M WIB') if a['end_time'] else 'later'
                    await update.message.reply_text(f"⚠️ @{a['username']} is away until {time_str}, will reach you back later.\n(Reason: {a['reason']})")
                    await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])

# --- 3/ RAWWY STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Error: You must reply to a message to give a Star!")
    giver = update.effective_user.username
    receiver = update.message.reply_to_message.from_user.username
    if giver == receiver: return await update.message.reply_text("❌ Error: You cannot give RAWWY Stars to yourself!")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        giver_data = await conn.fetchrow('SELECT quota FROM kudos WHERE username=$1', giver)
        if giver_data and giver_data['quota'] <= 0:
            return await update.message.reply_text("❌ Error: You have used all your RAWWY Stars for this week!")
            
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 2) ON CONFLICT (username) DO UPDATE SET quota = kudos.quota - 1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points = kudos.monthly_points + 1, all_time_points = kudos.all_time_points + 1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
        
    await update.message.reply_text(f"🌟 **RAWWY Star Awarded!**\n@{receiver} received a star from @{giver}!\nTotal RAWWY Stars: {score}", parse_mode="Markdown")

async def check_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return await update.message.reply_text("❌ Error: Admin privileges required.")
    if not context.args: return await update.message.reply_text("❌ Error: Provide a username (e.g. `/checkstars @user`)")
    target = context.args[0].replace("@", "")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        data = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
    if not data: return await update.message.reply_text(f"❌ Error: @{target} has no RAWWY Star records.")
    
    msg = f"🌟 **RAWWY Stars for @{target}**\nTotal All Time: {data['all_time_points']}\nMonthly: {data['monthly_points']}\nRemaining Quota to give: {data['quota']}"
    try: await context.bot.send_message(update.effective_user.id, msg)
    except: await update.message.reply_text(msg)

async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return await update.message.reply_text("❌ Error: Admin privileges required.")
    text = " ".join(context.args)
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3: raise ValueError
        target = parts[0].replace("@", "")
        action = parts[1].lower()
        amount = int(parts[2])
    except: return await update.message.reply_text("❌ Error: Invalid format. Use: `/admin_stars @user , set_quota/add_total/sub_total , amount`")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        if action == "set_quota": await conn.execute('UPDATE kudos SET quota=$1 WHERE username=$2', amount, target)
        elif action == "add_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points+$1 WHERE username=$2', amount, target)
        elif action == "sub_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points-$1 WHERE username=$2', amount, target)
        else: return await update.message.reply_text("❌ Error: Invalid action. Choose set_quota, add_total, or sub_total.")
    await update.message.reply_text(f"✅ RAWWY Stars updated successfully for @{target}.")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        records = await conn.fetch('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 5')
    if not records: return await update.message.reply_text("📊 **Monthly Leaderboard**\nNo points have been given out yet this month!")
    board = "📊 **Monthly Leaderboard**\n\n"
    for i, r in enumerate(records, 1): board += f"{i}. @{r['username']} - {r['monthly_points']} pts\n"
    await update.message.reply_text(board, parse_mode="Markdown")

# --- 1/ EVENT MANAGEMENT ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "," not in text:
        return await update.message.reply_text("📅 **Create Event:**\nTap to copy:\n\n`/newevent Title , MM/DD/YYYY HH.MM , ReminderMins`", parse_mode="Markdown")
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3: raise ValueError
        title, time_str, rem_str = parts[0], parts[1], parts[2]
        event_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
        rem_mins = int(rem_str)
        if event_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ Error: Event time cannot be in the past.")
    except Exception: return await update.message.reply_text("❌ Error: Invalid format. Example: `/newevent Sync , 06/25/2026 14.00 , 15`")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        event_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by) VALUES ($1, $2, $3) RETURNING id', title, event_time, update.effective_user.username)

    keyboard = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{event_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{event_id}_Not Going")], [InlineKeyboardButton("🤔 Tentative", callback_data=f"rsvp_{event_id}_Tentative")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    rem_time = event_time - datetime.timedelta(minutes=rem_mins)
    if rem_time > datetime.datetime.now(WIB):
        context.job_queue.run_once(event_reminder, when=rem_time, chat_id=update.effective_chat.id, data={"id": event_id, "title": title}, name=f"event_{event_id}")

    await update.message.reply_text(f"📅 **{title}**\n🕒 {event_time.strftime('%m/%d/%Y %H:%M')} WIB\n\n*RSVPs:*\nNo one yet.", reply_markup=reply_markup, parse_mode="Markdown")

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "," not in text:
        return await update.message.reply_text("✏️ **Edit Event:**\nTap to copy:\n\n`/editevent ID , New Title , MM/DD/YYYY HH.MM , ReminderMins`", parse_mode="Markdown")
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 4: raise ValueError
        event_id = int(parts[0])
        title = parts[1]
        event_time = WIB.localize(datetime.datetime.strptime(parts[2], "%m/%d/%Y %H.%M"))
        rem_mins = int(parts[3])
    except Exception: return await update.message.reply_text("❌ Error: Invalid format. Example: `/editevent 1 , Sync , 06/25/2026 14.00 , 15`")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        res = await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, event_time, event_id)
        if res == "UPDATE 0": return await update.message.reply_text("❌ Error: Event ID not found.")
    
    for job in context.job_queue.get_jobs_by_name(f"event_{event_id}"): job.schedule_removal()
    rem_time = event_time - datetime.timedelta(minutes=rem_mins)
    if rem_time > datetime.datetime.now(WIB):
        context.job_queue.run_once(event_reminder, when=rem_time, chat_id=update.effective_chat.id, data={"id": event_id, "title": title}, name=f"event_{event_id}")
    await update.message.reply_text(f"✅ Event {event_id} successfully updated.")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: event_id = int(context.args[0])
    except: return await update.message.reply_text("🗑️ **Cancel Event:**\nTap to copy:\n\n`/cancelevent ID`", parse_mode="Markdown")
        
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        result = await conn.execute('DELETE FROM events WHERE id=$1', event_id)
    if result == "DELETE 0": return await update.message.reply_text("❌ Error: Event ID not found.")
    for job in context.job_queue.get_jobs_by_name(f"event_{event_id}"): job.schedule_removal()
    await update.message.reply_text(f"🗑️ Event {event_id} has been cancelled completely.")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if not events: return await update.message.reply_text("There are no upcoming events!")
    msg = "📅 **Upcoming Events**\n\n"
    for e in events: msg += f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, event_id, status = query.data.split("_")
    username = query.from_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status=$3', int(event_id), username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(event_id))
        event = await conn.fetchrow('SELECT title, event_time FROM events WHERE id=$1', int(event_id))
    if not event: return await query.answer("Event deleted.")
    
    text = f"📅 **{event['title']}**\n🕒 {event['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB\n\n*RSVPs:*\n"
    for r in all_rsvps:
        icon = "✅" if r['status'] == 'Going' else "❌" if r['status'] == 'Not Going' else "🤔"
        text += f"{icon} @{r['username']}\n"
    await query.edit_message_text(text=text, reply_markup=query.message.reply_markup, parse_mode="Markdown")
    await query.answer(f"Marked as {status}!")

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        rsvps = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    mentions = " ".join([f"@{r['username']}" for r in rsvps])
    await context.bot.send_message(context.job.chat_id, f"⏰ Event **{context.job.data['title']}** starting soon!\n{mentions}", parse_mode="Markdown")

# --- 7/ TASKS WITH DEADLINES ---
async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "," not in text:
        return await update.message.reply_text("📋 **Assign Task:**\nTap to copy:\n\n`/assign @user , Minutes , Task desc`", parse_mode="Markdown")
    
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3: raise ValueError
        assignee = parts[0].replace("@", "")
        mins = int(parts[1])
        desc = parts[2]
        if mins < 1 or mins > 72: return await update.message.reply_text("❌ Error: Deadline must be between 1 and 72 minutes.")
    except Exception: return await update.message.reply_text("❌ Error: Invalid format. Ensure minutes is a number.")

    now = datetime.datetime.now(WIB)
    deadline_time = now + datetime.timedelta(minutes=mins)

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline) VALUES ($1, $2, $3) RETURNING id', assignee, desc, deadline_time)

    # 1/10th reminder
    total_seconds = (deadline_time - now).total_seconds()
    reminder_time = deadline_time - datetime.timedelta(seconds=(total_seconds * 0.1))
    context.job_queue.run_once(task_reminder, when=reminder_time, data={"assignee": assignee, "id": t_id}, chat_id=update.effective_chat.id)

    await update.message.reply_text(f"📋 **Task `{t_id}` Assigned to @{assignee}!**\n📝 {desc}\n⏳ Deadline: {deadline_time.strftime('%H:%M WIB')}", parse_mode="Markdown")

async def task_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed':
        await context.bot.send_message(context.job.chat_id, f"⚠️ @{context.job.data['assignee']} - Task `{context.job.data['id']}` is almost due!", parse_mode="Markdown")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: t_id = int(context.args[0])
    except: return await update.message.reply_text("✅ **Complete Task:**\nTap to copy:\n\n`/complete ID`", parse_mode="Markdown")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        res = await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
        if res == "UPDATE 0": return await update.message.reply_text("❌ Error: Task not found.")
    await update.message.reply_text(f"✅ Task `{t_id}` marked complete!", parse_mode="Markdown")

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        tasks = await conn.fetch("SELECT id, assignee, task_desc FROM tasks WHERE status = 'Pending' ORDER BY id ASC")
    if not tasks: return await update.message.reply_text("🎉 No pending tasks! Everyone is caught up.")
    msg = "📋 **Pending Tasks**\n\n"
    for t in tasks: msg += f"🔹 **ID `{t['id']}`** | @{t['assignee']} | {t['task_desc']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- 4/ BIRTHDAYS ---
async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return await update.message.reply_text("❌ Error: Admin privileges required.")
    text = " ".join(context.args)
    if not text or "," not in text: return await update.message.reply_text("🎂 **Add Birthday:**\nTap to copy:\n\n`/addbday @user , MM/DD`", parse_mode="Markdown")
    try:
        parts = [p.strip() for p in text.split(",")]
        user = parts[0].replace("@", "")
        bday = parts[1]
        datetime.datetime.strptime(bday, "%m/%d") # Validate format
    except: return await update.message.reply_text("❌ Error: Invalid format. Ensure date is MM/DD.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', user, bday)
    await update.message.reply_text(f"🎂 Added birthday for @{user} on {bday}.")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return await update.message.reply_text("❌ Error: Admin privileges required.")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        bdays = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    if not bdays: return await update.message.reply_text("No birthdays saved.")
    msg = "🎂 **Team Birthdays**\n" + "\n".join([f"• @{b['username']}: {b['bday']}" for b in bdays])
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- 2/ POLLING SYSTEM ---
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "," not in text:
        return await update.message.reply_text("📊 **Create Poll:**\nTap to copy:\n\n`/poll Question , Hours , Opt1 , Opt2`", parse_mode="Markdown")
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 4: raise ValueError
        duration = int(parts[1]) * 3600
    except: return await update.message.reply_text("❌ Error: Invalid format. Ensure hours is a number and you provide at least 2 options.")
    
    await context.bot.send_poll(chat_id=update.effective_chat.id, question=parts[0], options=parts[2:12], is_anonymous=False, allows_multiple_answers=True, open_period=duration)

# --- 5/ LIBRARY ---
async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "," not in text: return await update.message.reply_text("📚 **Add to Library:**\nTap to copy:\n\n`/addlib Name , Link or Text`", parse_mode="Markdown")
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 2: raise ValueError
        name = parts[0].lower()
        content = parts[1]
    except: return await update.message.reply_text("❌ Error: Invalid format.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO library (name, content, added_by) VALUES ($1, $2, $3) ON CONFLICT (name) DO UPDATE SET content=EXCLUDED.content, added_by=EXCLUDED.added_by', name, content, update.effective_user.username)
    await update.message.reply_text(f"✅ Resource **'{name}'** saved!", parse_mode="Markdown")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("📂 **Get Library Asset:**\nTap to copy:\n\n`/getlib AssetName`", parse_mode="Markdown")
    name = " ".join(context.args).strip().lower()
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        record = await conn.fetchrow('SELECT content, added_by FROM library WHERE name=$1', name)
    if not record: return await update.message.reply_text(f"❌ Error: Asset '{name}' not found.")
    await update.message.reply_text(f"📂 **{name.title()}** (@{record['added_by']}):\n{record['content']}", parse_mode="Markdown")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        records = await conn.fetch('SELECT name FROM library ORDER BY name ASC')
    if not records: return await update.message.reply_text("The library is empty.")
    await update.message.reply_text("📚 **Library**\n" + "\n".join([f"• `{r['name']}`" for r in records]), parse_mode="Markdown")

# --- MAIN RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("checkstars", check_stars))
    app.add_handler(CommandHandler("admin_stars", admin_stars))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    
    app.add_handler(CommandHandler("newevent", create_event))
    app.add_handler(CommandHandler("editevent", edit_event))
    app.add_handler(CommandHandler("cancelevent", cancel_event))
    app.add_handler(CommandHandler("events", list_events))
    app.add_handler(CallbackQueryHandler(rsvp_callback, pattern="^rsvp_"))
    
    app.add_handler(CommandHandler("assign", assign_task))
    app.add_handler(CommandHandler("complete", complete_task))
    app.add_handler(CommandHandler("tasks", list_tasks))
    
    app.add_handler(CommandHandler("addbday", add_bday))
    app.add_handler(CommandHandler("listbdays", list_bdays))
    
    app.add_handler(CommandHandler("poll", create_poll))
    
    app.add_handler(CommandHandler("addlib", add_lib))
    app.add_handler(CommandHandler("getlib", get_lib))
    app.add_handler(CommandHandler("library", list_lib))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_mentions))

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()