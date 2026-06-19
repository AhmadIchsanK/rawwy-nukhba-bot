import logging
import datetime
import pytz
import os
import asyncpg
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE") 
DATABASE_URL = os.getenv("DATABASE_URL")
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

away_users = {}

# --- DATABASE & MENU SETUP ---
async def init_db(app: Application):
    """Connects to Postgres, creates tables, and sets up the Telegram UI menu."""
    if not DATABASE_URL:
        logger.error("DATABASE_URL is missing!")
        return
    
    # 1. Setup Database Tables
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS kudos (user_id BIGINT PRIMARY KEY, username TEXT, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT NOT NULL, status TEXT DEFAULT 'Pending', assigned_by TEXT);''')
    
    # 2. Setup the Telegram UI Command Menu
    commands = [
        BotCommand("help", "Show the master guide"),
        BotCommand("away", "[reason] - Set your status to away"),
        BotCommand("back", "Remove your away status"),
        BotCommand("thanks", "(Reply to msg) Give a teammate a point"),
        BotCommand("leaderboard", "See the top helpers this month"),
        BotCommand("addlib", "Name | Content - Save an asset"),
        BotCommand("getlib", "[name] - Retrieve an asset"),
        BotCommand("library", "View all saved assets"),
        BotCommand("dellib", "[name] - Delete an asset"),
        BotCommand("newevent", "Title | DD-MM-YYYY HH:MM - Create event"),
        BotCommand("events", "See all upcoming events"),
        BotCommand("rsvp", "[id] [yes/no] - RSVP to an event"),
        BotCommand("delevent", "[id] - Cancel an event"),
        BotCommand("assign", "@user [task] - Give someone a task"),
        BotCommand("complete", "[id] - Mark a task as done"),
        BotCommand("tasks", "View all pending tasks"),
        BotCommand("poll", "Question | Opt1 | Opt2 - Create a poll")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Database connected and UI Menu configured!")


# --- CORE COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Manager Bot is online with Database support! Type /help to see commands.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a complete list of commands to the user via Direct Message."""
    help_text = (
        "🛠️ *Manager Bot Master Guide*\n\n"
        "*🏖️ Status & Away*\n"
        "• `/away [reason]` - Set your status to away\n"
        "• `/back` - Remove your away status\n\n"
        "*🌟 Commendations*\n"
        "• `/thanks` - Reply to a teammate's message to give them a point\n"
        "• `/leaderboard` - See the top helpers this month\n\n"
        "*📚 Mini Library*\n"
        "• `/addlib Name | Content` - Save a link or text asset\n"
        "• `/getlib [name]` - Retrieve an asset\n"
        "• `/library` - View all saved assets\n"
        "• `/dellib [name]` - Delete an asset\n\n"
        "*📅 Events & Meetings*\n"
        "• `/newevent Title | DD-MM-YYYY HH:MM` - Schedule an event\n"
        "• `/events` - See all upcoming events\n"
        "• `/rsvp [id] [yes/no]` - RSVP to an event\n"
        "• `/delevent [id]` - Cancel an event\n\n"
        "*📋 Quick Tasks*\n"
        "• `/assign @username [task]` - Give someone a task\n"
        "• `/complete [id]` - Mark a task as done\n"
        "• `/tasks` - View all pending tasks\n\n"
        "*📊 Polling*\n"
        "• `/poll Question | Opt1 | Opt2` - Create and pin a native poll\n"
    )
    
    try:
        await context.bot.send_message(chat_id=update.effective_user.id, text=help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await update.message.reply_text("I've sent you a DM with the complete list of commands! 📬")
    except Exception:
        if update.effective_chat.type != "private":
            await update.message.reply_text("I can't send you a DM yet! Please click on my profile, start a private chat with me, and try again.")
            
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    reason = " ".join(context.args) if context.args else "Away on leave"
    away_users[username] = reason
    await update.message.reply_text(f"✅ @{username} is marked as AWAY. Reason: {reason}")

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if username in away_users:
        del away_users[username]
        await update.message.reply_text(f"Welcome back, @{username}! Away status removed.")

async def check_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    for username, reason in away_users.items():
        if f"@{username}" in text:
            await update.message.reply_text(f"⚠️ @{username} is currently away.\nStatus: {reason}")


# --- FEATURE 1: EVENT MANAGEMENT ---

async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "|" not in text:
        await update.message.reply_text(
            "📅 **How to create an event:**\n"
            "Tap the text below to copy it, fill in your details, and send!\n\n"
            "`/newevent Event Title | DD-MM-YYYY HH:MM`", 
            parse_mode="Markdown"
        )
        return
        
    title, time_str = text.split("|", 1)
    title = title.strip()
    time_str = time_str.strip()
    username = update.effective_user.username or update.effective_user.first_name
    
    try:
        event_time = datetime.datetime.strptime(time_str, "%d-%m-%Y %H:%M")
        event_time = WIB.localize(event_time)
        if event_time < datetime.datetime.now(WIB):
            await update.message.reply_text("❌ That time is in the past!")
            return
    except ValueError:
        await update.message.reply_text("❌ Invalid time format! Use `DD-MM-YYYY HH:MM`", parse_mode="Markdown")
        return

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        event_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by) VALUES ($1, $2, $3) RETURNING id;', title, event_time, username)
        
    reminder_time = event_time - datetime.timedelta(minutes=15)
    if reminder_time > datetime.datetime.now(WIB):
        context.job_queue.run_once(event_reminder, when=reminder_time, chat_id=update.effective_chat.id, data={"event_id": event_id, "title": title}, name=f"event_{event_id}")
        
    await update.message.reply_text(
        f"📅 **Event Created!** (ID: `{event_id}`)\n"
        f"**{title}**\n🕒 {event_time.strftime('%d %b %Y, %H:%M')} WIB\n\n"
        f"Type `/rsvp {event_id} yes` to join!", 
        parse_mode="Markdown"
    )

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        rsvps = await conn.fetch('SELECT username FROM rsvps WHERE event_id = $1 AND status = $2', data['event_id'], 'yes')
    mentions = " ".join([f"@{r['username']}" for r in rsvps]) if rsvps else "No one RSVP'd 'yes', but"
    await context.bot.send_message(job.chat_id, f"⏰ **REMINDER:** Event **'{data['title']}'** is starting in 15 minutes!\n{mentions}", parse_mode="Markdown")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if not events:
        await update.message.reply_text("There are no upcoming events!")
        return
    msg = "📅 **Upcoming Events**\n\n"
    for e in events:
        local_time = e['event_time'].astimezone(WIB)
        msg += f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {local_time.strftime('%d %b %Y, %H:%M')} WIB\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def rsvp_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        event_id = int(context.args[0])
        status = context.args[1].lower()
        if status not in ['yes', 'no']:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text(
            "✅ **How to RSVP:**\n"
            "Tap the text below to copy it, fill it out, and send!\n\n"
            "`/rsvp EventID yes`\n"
            "*(Change 'yes' to 'no' if you can't make it)*",
            parse_mode="Markdown"
        )
        return
        
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("You need a Telegram username to RSVP!")
        return

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        event = await conn.fetchrow('SELECT title FROM events WHERE id = $1', event_id)
        if not event:
            await update.message.reply_text("❌ Event not found!")
            return
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status = EXCLUDED.status;', event_id, username, status)
        
    emoji = "✅" if status == "yes" else "❌"
    await update.message.reply_text(f"{emoji} @{username} RSVP'd **{status}** for '{event['title']}'", parse_mode="Markdown")

async def delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        event_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "🗑️ **How to delete an event:**\n"
            "Tap the text below to copy it, add the ID, and send!\n\n"
            "`/delevent EventID`",
            parse_mode="Markdown"
        )
        return
        
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        result = await conn.execute('DELETE FROM events WHERE id = $1', event_id)
        
    if result == "DELETE 0":
        await update.message.reply_text("❌ Event not found!")
    else:
        current_jobs = context.job_queue.get_jobs_by_name(f"event_{event_id}")
        for job in current_jobs: job.schedule_removal()
        await update.message.reply_text(f"🗑️ Event {event_id} has been deleted.")


# --- FEATURE 2: POLLING SYSTEM ---

async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    if len(parts) < 3:
        await update.message.reply_text(
            "📊 **How to create a poll:**\n"
            "Tap the text below to copy it, fill in your details, and send!\n\n"
            "`/poll Question | Option 1 | Option 2`", 
            parse_mode="Markdown"
        )
        return
        
    message = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=parts[0],
        options=parts[1:11],
        is_anonymous=True,
        allows_multiple_answers=True
    )
    
    if update.effective_chat.type != "private":
        try:
            await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=message.message_id, disable_notification=False)
        except Exception as e:
            logger.warning(f"Could not pin poll. Bot needs 'Pin Messages' admin rights. Error: {e}")


# --- FEATURE 3: COMMENDATIONS ---

async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ You need to reply to the message of the person you want to thank!")
        return
        
    giver = update.effective_user
    receiver = update.message.reply_to_message.from_user

    if giver.id == receiver.id:
        await update.message.reply_text("❌ You can't give points to yourself!")
        return
    if receiver.is_bot:
        await update.message.reply_text("🤖 I appreciate it, but bots don't need points!")
        return

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (user_id, username, monthly_points, all_time_points) VALUES ($1, $2, 1, 1) ON CONFLICT (user_id) DO UPDATE SET monthly_points = kudos.monthly_points + 1, all_time_points = kudos.all_time_points + 1, username = $2;', receiver.id, receiver.username or receiver.first_name)
        new_score = await conn.fetchval('SELECT monthly_points FROM kudos WHERE user_id = $1', receiver.id)

    await update.message.reply_text(
        f"🌟 **Point Awarded!**\n@{receiver.username or receiver.first_name} received an appreciation point from @{giver.username or giver.first_name}!\nThey now have {new_score} points this month.",
        parse_mode="Markdown"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        records = await conn.fetch('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 5')
    if not records:
        await update.message.reply_text("📊 **Monthly Leaderboard**\nNo points have been given out yet this month!")
        return
    board = "📊 **Monthly Leaderboard**\n\n"
    for i, record in enumerate(records, 1): board += f"{i}. @{record['username']} - {record['monthly_points']} pts\n"
    await update.message.reply_text(board, parse_mode="Markdown")


# --- FEATURE 5: MINI RESOURCE LIBRARY ---

async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text or "|" not in text:
        await update.message.reply_text(
            "📚 **How to add to the library:**\n"
            "Tap the text below to copy it, fill in your details, and send!\n\n"
            "`/addlib Name | Link or Text`",
            parse_mode="Markdown"
        )
        return
        
    name, content = text.split("|", 1)
    name = name.strip().lower() 
    content = content.strip()
    username = update.effective_user.username or update.effective_user.first_name

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO library (name, content, added_by) VALUES ($1, $2, $3) ON CONFLICT (name) DO UPDATE SET content = EXCLUDED.content, added_by = EXCLUDED.added_by;', name, content, username)
    await update.message.reply_text(f"✅ Resource **'{name}'** has been saved to the library!", parse_mode="Markdown")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📂 **How to retrieve an asset:**\n"
            "Tap the text below to copy it, add the name, and send!\n\n"
            "`/getlib AssetName`",
            parse_mode="Markdown"
        )
        return
        
    name = " ".join(context.args).strip().lower()
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        record = await conn.fetchrow('SELECT content, added_by FROM library WHERE name = $1', name)
    if record:
        await update.message.reply_text(f"📂 **{name.title()}** (Added by @{record['added_by']}):\n{record['content']}", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ I couldn't find anything named '{name}' in the library.")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        records = await conn.fetch('SELECT name FROM library ORDER BY name ASC')
    if not records:
        await update.message.reply_text("The library is currently empty!")
        return
    item_list = "\n".join([f"• `{record['name']}`" for record in records])
    await update.message.reply_text(f"📚 **Mini Resource Library**\n\n{item_list}\n\nType `/getlib [name]` to retrieve one.", parse_mode="Markdown")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🗑️ **How to delete an asset:**\n"
            "Tap the text below to copy it, add the name, and send!\n\n"
            "`/dellib AssetName`",
            parse_mode="Markdown"
        )
        return
        
    name = " ".join(context.args).strip().lower()
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        result = await conn.execute('DELETE FROM library WHERE name = $1', name)
    if result == "DELETE 0":
        await update.message.reply_text(f"❌ '{name}' wasn't in the library to begin with.")
    else:
        await update.message.reply_text(f"🗑️ Resource '{name}' has been deleted.")


# --- FEATURE 7: QUICK TASK ASSIGNMENT ---

async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 **How to assign a task:**\n"
            "Tap the text below to copy it, fill in your details, and send!\n\n"
            "`/assign @username Task description`",
            parse_mode="Markdown"
        )
        return

    assignee = context.args[0].replace("@", "")
    task_desc = " ".join(context.args[1:])
    assigned_by = update.effective_user.username or update.effective_user.first_name

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, assigned_by) VALUES ($1, $2, $3) RETURNING id;', assignee, task_desc, assigned_by)

    await update.message.reply_text(
        f"📋 **Task Assigned!** (ID: `{task_id}`)\n👤 To: @{assignee}\n📝 Task: {task_desc}\n\nWhen done, type `/complete {task_id}`", 
        parse_mode="Markdown"
    )

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        task_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "✅ **How to complete a task:**\n"
            "Tap the text below to copy it, add the ID, and send!\n\n"
            "`/complete TaskID`",
            parse_mode="Markdown"
        )
        return

    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT * FROM tasks WHERE id = $1', task_id)
        if not task:
            await update.message.reply_text("❌ Task not found!")
            return
        if task['status'] == 'Completed':
            await update.message.reply_text("✅ That task is already completed!")
            return
        await conn.execute("UPDATE tasks SET status = 'Completed' WHERE id = $1", task_id)

    await update.message.reply_text(f"🎉 **Task Completed!**\nAwesome job, @{username}! Task `{task_id}` ('{task['task_desc']}') is now closed.", parse_mode="Markdown")

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        tasks = await conn.fetch("SELECT id, assignee, task_desc FROM tasks WHERE status = 'Pending' ORDER BY id ASC")
    if not tasks:
        await update.message.reply_text("🎉 No pending tasks! Everyone is caught up.")
        return
    msg = "📋 **Pending Tasks**\n\n"
    for t in tasks: msg += f"🔹 **ID `{t['id']}`** | @{t['assignee']} | {t['task_desc']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


# --- MAIN APPLICATION ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Core
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    
    # Kudos
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    
    # Library
    app.add_handler(CommandHandler("addlib", add_lib))
    app.add_handler(CommandHandler("getlib", get_lib))
    app.add_handler(CommandHandler("dellib", del_lib))
    app.add_handler(CommandHandler("library", list_lib))
    
    # Events
    app.add_handler(CommandHandler("newevent", create_event))
    app.add_handler(CommandHandler("events", list_events))
    app.add_handler(CommandHandler("rsvp", rsvp_event))
    app.add_handler(CommandHandler("delevent", delete_event))
    
    # Tasks
    app.add_handler(CommandHandler("assign", assign_task))
    app.add_handler(CommandHandler("complete", complete_task))
    app.add_handler(CommandHandler("tasks", list_tasks))
    
    # Polls
    app.add_handler(CommandHandler("poll", create_poll))

    # Message Interceptor (Must be last message handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_mentions))

    # Initialize Database & Menus on Startup
    app.post_init = init_db

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
