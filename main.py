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
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in ['creator', 'administrator']

# --- DATABASE SETUP ---
async def init_db(app: Application):
    if not DATABASE_URL:
        logger.error("DATABASE_URL missing!")
        return
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    
    async with app.bot_data['db_pool'].acquire() as conn:
        # 1. RAWWY Stars
        await conn.execute('''CREATE TABLE IF NOT EXISTS kudos (username TEXT PRIMARY KEY, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0, quota INT DEFAULT 3);''')
        # 2. Library
        await conn.execute('''CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT);''')
        # 3. Events & RSVPs
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        # 4. Tasks
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE);''')
        # 5. Away System
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (username TEXT PRIMARY KEY, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT);''')
        # 6. Birthdays
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (id SERIAL PRIMARY KEY, username TEXT, bday TEXT);''')
        
    commands = [
        BotCommand("help", "[RW] Nukhba Manager Guide"),
        BotCommand("away", "Reason | MM/DD/YYYY - HH:MM:SS"),
        BotCommand("back", "Remove away status early"),
        BotCommand("thanks", "(Reply) Give a RAWWY Star"),
        BotCommand("leaderboard", "Top RAWWY Stars"),
        BotCommand("newevent", "Title | DD-MM-YYYY HH:MM | ReminderMins"),
        BotCommand("events", "Upcoming events"),
        BotCommand("assign", "@user 60m | Task desc"),
        BotCommand("complete", "[id] - Mark task done"),
        BotCommand("tasks", "View pending tasks"),
        BotCommand("addlib", "Name | Content"),
        BotCommand("getlib", "[name]"),
        BotCommand("library", "View assets"),
        BotCommand("poll", "Question | Hours | Opt1 | Opt2")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Advanced Database & Menus Configured!")

# --- CORE COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 [RW] Nukhba Manager is online!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🛠️ *[RW] Nukhba Manager Guide*\n\n"
        "*🏖️ Away Mode*\n`/away Reason | MM/DD/YYYY - HH:MM:SS`\n`/back`\n\n"
        "*🌟 RAWWY Stars*\n`/thanks` (reply to msg)\n`/leaderboard`\n"
        "*(Admin)* `/admin_stars @user [set_quota/add_total/sub_total] [amount]`\n\n"
        "*📅 Events*\n`/newevent Title | DD-MM-YYYY HH:MM | ReminderMins`\n`/events`\n\n"
        "*📋 Tasks*\n`/assign @user [optional: 30m/2h] | Task`\n`/complete [id]`\n`/tasks`\n\n"
        "*🎂 Birthdays (Admin Only)*\n`/addbday @user DD-MM`\n`/delbday @user`\n`/listbdays`\n\n"
        "*📊 Polls*\n`/poll Question | Hours | Opt1 | Opt2`\n\n"
        "*📚 Library*\n`/addlib Name | Link`\n`/getlib [name]`\n`/library`"
    )
    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("📬 Guide sent to DM!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("❌ Please start a DM with me first!")

# --- 8/ AWAY SYSTEM ---
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if "|" not in text:
        await update.message.reply_text("❌ Format: `/away Reason | MM/DD/YYYY - HH:MM:SS`", parse_mode="Markdown")
        return
    reason, time_str = text.split("|", 1)
    username = update.effective_user.username
    
    try:
        end_time = datetime.datetime.strptime(time_str.strip(), "%m/%d/%Y - %H:%M:%S")
        end_time = WIB.localize(end_time)
    except ValueError:
        await update.message.reply_text("❌ Invalid time format! Use `MM/DD/YYYY - HH:MM:SS`")
        return

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3) ON CONFLICT (username) DO UPDATE SET reason=$2, end_time=$3, last_notified=NULL', username, reason.strip(), end_time)
    
    # Schedule Auto-Return
    if end_time > datetime.datetime.now(WIB):
        context.job_queue.run_once(auto_return_away, when=end_time, data=username, name=f"away_{username}")
    await update.message.reply_text(f"✅ @{username} is away until {end_time.strftime('%H:%M WIB on %b %d')}.")

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE):
    username = context.job.data
    await process_return(username, context.bot)

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

    # Compile DM
    msg = "👋 Welcome back! Here is what you missed:\n\n"
    if not mentions: msg += "No one mentioned you."
    else:
        for m in mentions: msg += f"🔹 **@{m['mentioner']}** in *{m['chat_title']}*:\n\"{m['message']}\"\n\n"
    
    try: # Try to DM summary
        # Get user_id by trick (bot can only message if chat exists). We assume the user interacted with bot.
        # Alternatively, we broadcast to the group if chat_id is provided.
        if chat_id: await bot.send_message(chat_id, f"Welcome back @{username}! I've wiped your away status.")
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
                # Log mention
                await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], mentioner, text, chat_title)
                
                # Cooldown check (60 mins)
                last = a['last_notified']
                if not last or (now - last).total_seconds() > 3600:
                    time_str = a['end_time'].strftime('%m/%d %H:%M WIB') if a['end_time'] else 'later'
                    await update.message.reply_text(f"⚠️ @{a['username']} is away until {time_str}, will reach you back later.\n(Reason: {a['reason']})")
                    await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])

# --- 3/ RAWWY STARS (COMMENDATIONS) ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a message to give a Star!")
    giver = update.effective_user.username
    receiver = update.message.reply_to_message.from_user.username
    if giver == receiver: return await update.message.reply_text("❌ Can't give stars to yourself!")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        # Check giver quota
        giver_data = await conn.fetchrow('SELECT quota FROM kudos WHERE username=$1', giver)
        if giver_data and giver_data['quota'] <= 0:
            return await update.message.reply_text("❌ You are out of RAWWY Stars for this week!")
            
        # Deduct quota, Add to receiver
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 2) ON CONFLICT (username) DO UPDATE SET quota = kudos.quota - 1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points = kudos.monthly_points + 1, all_time_points = kudos.all_time_points + 1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
        
    await update.message.reply_text(f"🌟 **RAWWY Star Awarded!**\n@{receiver} received a star from @{giver}!\nTotal RAWWY Stars: {score}", parse_mode="Markdown")

async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return await update.message.reply_text("❌ Admin only!")
    try:
        target = context.args[0].replace("@", "")
        action = context.args[1].lower()
        amount = int(context.args[2])
    except: return await update.message.reply_text("❌ Format: `/admin_stars @user [set_quota/add_total/sub_total] [amount]`")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        if action == "set_quota":
            await conn.execute('UPDATE kudos SET quota=$1 WHERE username=$2', amount, target)
        elif action == "add_total":
            await conn.execute('UPDATE kudos SET all_time_points=all_time_points+$1 WHERE username=$2', amount, target)
        elif action == "sub_total":
            await conn.execute('UPDATE kudos SET all_time_points=all_time_points-$1 WHERE username=$2', amount, target)
    await update.message.reply_text(f"✅ RAWWY Stars updated for @{target}.")

# --- 1/ EVENT MANAGEMENT (INLINE KEYBOARD) ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    try:
        title, time_str, rem_str = text.split("|")
        event_time = WIB.localize(datetime.datetime.strptime(time_str.strip(), "%d-%m-%Y %H:%M"))
        rem_mins = int(rem_str.strip())
    except: return await update.message.reply_text("❌ Format: `/newevent Title | DD-MM-YYYY HH:MM | ReminderMins`")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        event_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by) VALUES ($1, $2, $3) RETURNING id', title.strip(), event_time, update.effective_user.username)

    # Setup Buttons
    keyboard = [
        [InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{event_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{event_id}_Not Going")],
        [InlineKeyboardButton("🤔 Tentative", callback_data=f"rsvp_{event_id}_Tentative")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if event_time - datetime.timedelta(minutes=rem_mins) > datetime.datetime.now(WIB):
        context.job_queue.run_once(event_reminder, when=(event_time - datetime.timedelta(minutes=rem_mins)), chat_id=update.effective_chat.id, data={"id": event_id, "title": title.strip()})

    await update.message.reply_text(f"📅 **{title.strip()}**\n🕒 {event_time.strftime('%d %b %Y, %H:%M')} WIB\n\n*RSVPs:*\nNo one yet.", reply_markup=reply_markup, parse_mode="Markdown")

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
    
    # Rebuild Text
    text = f"📅 **{event['title']}**\n🕒 {event['event_time'].astimezone(WIB).strftime('%d %b %Y, %H:%M')} WIB\n\n*RSVPs:*\n"
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
    if "|" not in text: return await update.message.reply_text("❌ Format: `/assign @user [deadline] | Task` (e.g. `/assign @user 60m | Write report`)")
    
    meta, desc = text.split("|", 1)
    meta_parts = meta.split()
    assignee = meta_parts[0].replace("@", "")
    deadline_val = None
    
    now = datetime.datetime.now(WIB)
    deadline_time = None
    
    if len(meta_parts) > 1:
        time_str = meta_parts[1]
        if time_str.endswith('m'): deadline_time = now + datetime.timedelta(minutes=int(time_str[:-1]))
        elif time_str.endswith('h'): deadline_time = now + datetime.timedelta(hours=int(time_str[:-1]))

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline) VALUES ($1, $2, $3) RETURNING id', assignee, desc.strip(), deadline_time)

    # 90% Time Reminder (1/10th remaining)
    if deadline_time:
        total_seconds = (deadline_time - now).total_seconds()
        reminder_time = deadline_time - datetime.timedelta(seconds=(total_seconds * 0.1))
        context.job_queue.run_once(task_reminder, when=reminder_time, data={"assignee": assignee, "id": t_id}, chat_id=update.effective_chat.id)

    dl_str = f"\n⏳ Deadline: {deadline_time.strftime('%H:%M WIB')}" if deadline_time else ""
    await update.message.reply_text(f"📋 **Task `{t_id}` Assigned to @{assignee}!**\n📝 {desc.strip()}{dl_str}", parse_mode="Markdown")

async def task_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed':
        await context.bot.send_message(context.job.chat_id, f"⚠️ @{context.job.data['assignee']} - Task `{context.job.data['id']}` is almost due!", parse_mode="Markdown")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: t_id = int(context.args[0])
    except: return await update.message.reply_text("❌ `/complete [ID]`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
    await update.message.reply_text(f"✅ Task `{t_id}` marked complete!", parse_mode="Markdown")

# --- 4/ BIRTHDAYS (ADMIN) ---
async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return await update.message.reply_text("❌ Admin only!")
    try:
        user = context.args[0].replace("@", "")
        bday = context.args[1]
    except: return await update.message.reply_text("❌ `/addbday @user DD-MM`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', user, bday)
    await update.message.reply_text(f"🎂 Added birthday for @{user} on {bday}.")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        bdays = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    if not bdays: return await update.message.reply_text("No birthdays saved.")
    msg = "🎂 **Team Birthdays**\n" + "\n".join([f"• @{b['username']}: {b['bday']}" for b in bdays])
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- 2/ POLLING SYSTEM (BASIC FOR NOW) ---
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    if len(parts) < 3: return await update.message.reply_text("❌ `/poll Question | Hours | Opt1 | Opt2`")
    
    try: duration = int(parts[1]) * 3600
    except: duration = 86400 # Default 24h
    
    await context.bot.send_poll(chat_id=update.effective_chat.id, question=parts[0], options=parts[2:12], is_anonymous=False, allows_multiple_answers=True, open_period=duration)

# --- MAIN RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    # Away
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    
    # RAWWY Stars
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("admin_stars", admin_stars))
    
    # Events
    app.add_handler(CommandHandler("newevent", create_event))
    app.add_handler(CallbackQueryHandler(rsvp_callback, pattern="^rsvp_"))
    
    # Tasks
    app.add_handler(CommandHandler("assign", assign_task))
    app.add_handler(CommandHandler("complete", complete_task))
    
    # Birthdays
    app.add_handler(CommandHandler("addbday", add_bday))
    app.add_handler(CommandHandler("listbdays", list_bdays))
    
    # Polls
    app.add_handler(CommandHandler("poll", create_poll))

    # Interceptor
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_mentions))

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
