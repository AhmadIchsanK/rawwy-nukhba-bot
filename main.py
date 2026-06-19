import logging
import datetime
import pytz
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE") 
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- IN-MEMORY STORAGE (Temporary until PostgreSQL is connected) ---
away_users = {}
birthdays = {}

# --- COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the user."""
    await update.message.reply_text(
        "🤖 Manager Bot is online! Timezone set to WIB.\n"
        "Type /help to see what I can do."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a list of commands to the user via Direct Message."""
    help_text = (
        "🛠️ *Manager Bot Commands*\n\n"
        "*/start* - Check if the bot is online\n"
        "*/away [reason]* - Set your status to away (e.g., /away Sick leave)\n"
        "*/back* - Remove your away status\n"
        "*/settrivia [HH:MM]* - Set the daily trivia time (WIB timezone)\n"
        "*/addbday [DD-MM]* - Save your birthday (e.g., /addbday 25-12)\n"
        "*/help* - Receive this list of commands"
    )
    
    try:
        await context.bot.send_message(chat_id=update.effective_user.id, text=help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await update.message.reply_text("I've sent you a DM with the list of commands! 📬")
    except Exception:
        if update.effective_chat.type != "private":
            await update.message.reply_text("I can't send you a DM yet! Please start a private chat with me first.")

async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets a user's status to away."""
    username = update.effective_user.username
    if not username:
        await update.message.reply_text("You need a Telegram username to use this feature!")
        return

    reason = " ".join(context.args) if context.args else "Away on leave"
    away_users[username] = reason
    await update.message.reply_text(f"✅ @{username} is marked as AWAY. Reason: {reason}")

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a user's away status."""
    username = update.effective_user.username
    if username in away_users:
        del away_users[username]
        await update.message.reply_text(f"Welcome back, @{username}! Away status removed.")
    else:
        await update.message.reply_text("You aren't currently marked as away.")

async def add_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves birthday, deletes the group message, and sends success DM."""
    user = update.effective_user
    
    # 1. Attempt to delete the message (Requires 'Delete Messages' admin permission)
    if update.effective_chat.type != "private":
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete message. Bot might not be admin. Error: {e}")

    # 2. Parse the date
    if not context.args:
        msg = "❌ Please provide a date. Format: /addbday DD-MM (e.g., /addbday 25-12)"
    else:
        date_str = context.args[0]
        birthdays[user.username] = date_str
        msg = f"🎂 Success! I've saved your birthday as {date_str}. I'll remind the team when it's time!"

    # 3. Send DM Confirmation
    try:
        await context.bot.send_message(chat_id=user.id, text=msg)
    except Exception:
        # Fallback if bot cannot DM the user
        if update.effective_chat.type != "private":
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=f"@{user.username} I saved your birthday, but I couldn't DM you! Please start a chat with me."
            )

# --- MESSAGE INTERCEPTOR ---

async def check_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Listens to all messages to see if an 'away' user was tagged."""
    if not update.message or not update.message.text:
        return

    text = update.message.text
    for username, reason in away_users.items():
        if f"@{username}" in text:
            await update.message.reply_text(f"⚠️ Just a heads up, @{username} is currently away.\nStatus: {reason}")

# --- SCHEDULED JOBS ---

async def send_trivia(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    await context.bot.send_message(
        chat_id=chat_id, 
        text="🧠 *Daily Trivia Time!*\n\nWhat is the capital of Australia?\n\n(First correct answer gets a point!)",
        parse_mode="Markdown"
    )

async def set_trivia_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        time_str = context.args[0]
        hour, minute = map(int, time_str.split(':'))
        target_time = datetime.time(hour=hour, minute=minute, tzinfo=WIB)
        
        current_jobs = context.job_queue.get_jobs_by_name(f"trivia_{chat_id}")
        for job in current_jobs:
            job.schedule_removal()
            
        context.job_queue.run_daily(send_trivia, time=target_time, chat_id=chat_id, name=f"trivia_{chat_id}")
        await update.message.reply_text(f"✅ Daily trivia scheduled for {time_str} WIB!")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /settrivia HH:MM (e.g., /settrivia 14:30)")

# --- MAIN APPLICATION ---

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Register Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    app.add_handler(CommandHandler("addbday", add_birthday))
    app.add_handler(CommandHandler("settrivia", set_trivia_time))

    # Register Interceptor
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_mentions))

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()