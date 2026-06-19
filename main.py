import logging
import datetime
import pytz
import os
import asyncpg
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE") 
DATABASE_URL = os.getenv("DATABASE_URL")
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

away_users = {}
birthdays = {}

# --- DATABASE SETUP ---
async def init_db(app: Application):
    """Connects to Postgres and creates the tables if they don't exist."""
    if not DATABASE_URL:
        logger.error("DATABASE_URL is missing!")
        return
    
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    
    async with app.bot_data['db_pool'].acquire() as conn:
        # Create table for points
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS kudos (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                monthly_points INT DEFAULT 0,
                all_time_points INT DEFAULT 0
            );
        ''')
        
        # Create table for the Mini Library
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS library (
                name TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                added_by TEXT
            );
        ''')
    logger.info("✅ Database connected and tables verified!")

# --- FEATURE 3: COMMENDATIONS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give a point to a teammate by replying to their message."""
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

    # Update database
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        # Insert or update the receiver's score
        await conn.execute('''
            INSERT INTO kudos (user_id, username, monthly_points, all_time_points)
            VALUES ($1, $2, 1, 1)
            ON CONFLICT (user_id) DO UPDATE 
            SET monthly_points = kudos.monthly_points + 1,
                all_time_points = kudos.all_time_points + 1,
                username = $2;
        ''', receiver.id, receiver.username or receiver.first_name)
        
        # Fetch their new monthly score to show in chat
        new_score = await conn.fetchval('SELECT monthly_points FROM kudos WHERE user_id = $1', receiver.id)

    await update.message.reply_text(
        f"🌟 **Point Awarded!**\n"
        f"@{receiver.username or receiver.first_name} received an appreciation point from @{giver.username or giver.first_name}!\n"
        f"They now have {new_score} points this month.",
        parse_mode="Markdown"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the top helpers of the month."""
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        # Get top 5 users sorted by monthly points
        records = await conn.fetch('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 5')
    
    if not records:
        await update.message.reply_text("📊 **Monthly Leaderboard**\nNo points have been given out yet this month!")
        return
        
    board = "📊 **Monthly Leaderboard**\n\n"
    for i, record in enumerate(records, 1):
        board += f"{i}. @{record['username']} - {record['monthly_points']} pts\n"
        
    await update.message.reply_text(board, parse_mode="Markdown")

    # --- FEATURE 5: MINI RESOURCE LIBRARY ---

async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a new resource to the library. Format: /addlib name | link"""
    # Combine all arguments into one string
    text = " ".join(context.args)
    
    # Check if they used the "|" separator
    if "|" not in text:
        await update.message.reply_text(
            "❌ **Incorrect format!**\n"
            "Please use a `|` to separate the name and the content.\n"
            "Example: `/addlib logo | https://drive.google.com/...`",
            parse_mode="Markdown"
        )
        return
        
    # Split the text into the name and the content
    name, content = text.split("|", 1)
    name = name.strip().lower() # Lowercase makes it easier to search later
    content = content.strip()
    username = update.effective_user.username or update.effective_user.first_name

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        # Insert or replace the resource
        await conn.execute('''
            INSERT INTO library (name, content, added_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (name) DO UPDATE 
            SET content = EXCLUDED.content, added_by = EXCLUDED.added_by;
        ''', name, content, username)

    await update.message.reply_text(f"✅ Resource **'{name}'** has been saved to the library!", parse_mode="Markdown")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retrieves a resource. Format: /getlib name"""
    if not context.args:
        await update.message.reply_text("❌ What are you looking for? (e.g., `/getlib logo`)", parse_mode="Markdown")
        return
        
    name = " ".join(context.args).strip().lower()
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        record = await conn.fetchrow('SELECT content, added_by FROM library WHERE name = $1', name)
        
    if record:
        await update.message.reply_text(
            f"📂 **{name.title()}** (Added by @{record['added_by']}):\n{record['content']}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ I couldn't find anything named '{name}' in the library.")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all available resources in the library."""
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        records = await conn.fetch('SELECT name FROM library ORDER BY name ASC')
        
    if not records:
        await update.message.reply_text("The library is currently empty!")
        return
        
    # Create a bulleted list of all names
    item_list = "\n".join([f"• `{record['name']}`" for record in records])
    await update.message.reply_text(f"📚 **Mini Resource Library**\n\n{item_list}\n\nType `/getlib [name]` to retrieve one.", parse_mode="Markdown")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes a resource. Format: /dellib name"""
    if not context.args:
        await update.message.reply_text("❌ What do you want to delete? (e.g., `/dellib logo`)", parse_mode="Markdown")
        return
        
    name = " ".join(context.args).strip().lower()
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        result = await conn.execute('DELETE FROM library WHERE name = $1', name)
        
    # result will be something like "DELETE 1" or "DELETE 0"
    if result == "DELETE 0":
        await update.message.reply_text(f"❌ '{name}' wasn't in the library to begin with.")
    else:
        await update.message.reply_text(f"🗑️ Resource '{name}' has been deleted.")

# --- ORIGINAL FEATURES (Start, Away, Help, Trivia) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Manager Bot is online with Database support!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🛠️ *Manager Bot Commands*\n\n"
        "*/away [reason]* - Set away status\n"
        "*/back* - Remove away status\n"
        "*/thanks* - Reply to someone's message to give them a point\n"
        "*/leaderboard* - See the top helpers this month\n"
    )
    try:
        await context.bot.send_message(chat_id=update.effective_user.id, text=help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await update.message.reply_text("I've sent you a DM with the list of commands! 📬")
    except Exception:
        if update.effective_chat.type != "private":
            await update.message.reply_text("I can't send you a DM yet! Please start a private chat with me first.")

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

# --- MAIN APPLICATION ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Register Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("addlib", add_lib))
    app.add_handler(CommandHandler("getlib", get_lib))
    app.add_handler(CommandHandler("dellib", del_lib))
    app.add_handler(CommandHandler("library", list_lib))

    # Register Interceptors
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_mentions))

    # Initialize Database on Startup
    app.post_init = init_db

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
