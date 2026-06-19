import logging, datetime, pytz, os, asyncpg
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL")
SUPER_OWNER = os.getenv("SUPER_OWNER", "AdminUsername").replace("@", "").lower()
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- AUTH & HELPERS ---
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
        try: await conn.execute('''ALTER TABLE library ADD COLUMN is_private BOOLEAN DEFAULT FALSE;''')
        except: pass
        
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE, assigned_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (username TEXT PRIMARY KEY, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (id SERIAL PRIMARY KEY, username TEXT, bday TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcements (id SERIAL PRIMARY KEY, text TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcement_messages (announcement_id INT, chat_id BIGINT, message_id BIGINT);''')
        
        # Enterprise Tracking
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_stats (date DATE PRIMARY KEY, uses INT DEFAULT 0, errors INT DEFAULT 0);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bug_reports (id SERIAL PRIMARY KEY, username TEXT, report TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS star_logs (id SERIAL PRIMARY KEY, log_text TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')

    commands = [
        BotCommand("help", "View Manager Guide"),
        BotCommand("newevent", "Title , MM/DD/YYYY HH.MM , RemMins"),
        BotCommand("events", "View Upcoming Schedule"),
        BotCommand("poll", "Question , Hours , Opt1 , Opt2"),
        BotCommand("thanks", "(Reply) Send RAWWY Star"),
        BotCommand("mystars", "Check your Star quota"),
        BotCommand("addlib", "Name , Content , [private]"),
        BotCommand("getlib", "Get an asset by Name"),
        BotCommand("library", "Browse all assets"),
        BotCommand("assign", "@user , Mins (60-480) , Task"),
        BotCommand("complete", "Mark done (Assignee only)"),
        BotCommand("mytasks", "View your to-do list"),
        BotCommand("away", "Reason , MM/DD/YYYY HH.MM"),
        BotCommand("back", "I'm back!"),
        BotCommand("bugreport", "Report a bug to the owner")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Enterprise Database & Automated Cron Routines Configured!")

# --- CORE & HUMANIZED COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Hello there! **[RW] Nukhba Manager is online and tracking.** Feel free to type `/help` to see what I can do.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 *[RW] Nukhba Manager Guide*\n\n"
        "📅 *1/ Events (Syncs & Meets)*\n`/newevent Title , MM/DD/YYYY HH.MM , RemMins`\n`/events` (View schedule)\n\n"
        "📊 *2/ Quick Polls*\n`/poll Question , Hours , Opt1 , Opt2`\n\n"
        "🌟 *3/ RAWWY Stars (Show some love!)*\n`/thanks` (reply to a message to award a star)\n`/mystars` (Check your balance)\n\n"
        "📚 *4/ RAWWY Library (Knowledge Base)*\n`/addlib Name , Content` *(Add 'private' at the end to lock it!)*\n`/getlib Name` | `/library`\n\n"
        "⚡ *5/ Quick Tasks (Get stuff done)*\n`/assign @user , 60 , Task description` *(Between 60-480m)*\n`/complete ID` | `/mytasks`\n\n"
        "🏖️ *6/ Away Mode (Brb, touching grass)*\n`/away Reason , MM/DD/YYYY HH.MM`\n`/back` (Welcome back!)\n\n"
        "🐛 *Extras*\n`/bugreport Explain the issue`"
    )
    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("📬 I've just slipped the manual into your DMs!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("Ah, it looks like I can't DM you yet! Please shoot me a direct message first, then try again.")

async def help_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    
    if not await is_bot_admin(username, pool):
        return # Normal users get totally ignored

    is_owner = await is_super(username)
    help_text = (
        "🔐 *[RW] NUKHBA ADMIN SUITE*\n\n"
        "🎂 *Birthdays:* `/addbday @user , MM/DD` | `/listbdays`\n"
        "🌟 *Stars Audit:* `/checkstars all` | `/checkstars @user`\n"
        "⚙️ *Edit Stars:* `/admin_stars @user , [set_quota/add_total/sub_total] , amount`\n"
        "🗑️ *Overrides:* `/cancelevent ID` | `/canceltask ID` | `/dellib Name`\n"
        "📢 *Broadcast:* `/announce All , Message` | `/editannounce ID , Msg` | `/delannounce ID`"
    )
    if is_owner:
        help_text += (
            "\n\n👑 *SUPER OWNER EXCLUSIVES*\n"
            "🛡️ *Access:* `/addadmin @user` | `/deladmin @user` | `/listadmins`\n"
            "🛑 *Offboarding:* `/removemember @user` (Wipes data & drops tasks)\n"
            "☢️ *Wipe:* `/super_reset [stars/tasks/library/events/away]`"
        )
    await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")

# --- DAILY & MONTHLY CRON JOBS ---
async def daily_morning_log(context: ContextTypes.DEFAULT_TYPE):
    """Fires daily at 7 AM WIB to Super Admin"""
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
        
        msg += "🐛 **Bug Reports:**\n"
        if bugs:
            for b in bugs: msg += f"- @{b['username']}: {b['report']}\n"
        else: msg += "No bugs reported! 🎉\n"
        
        msg += "\n🌟 **RAWWY Star Audit Log:**\n"
        if star_logs:
            for s in star_logs: msg += f"- {s['log_text']}\n"
        else: msg += "No admin star movements yesterday."

        await context.bot.send_message(owner_id, msg, parse_mode="Markdown")
        await conn.execute("TRUNCATE bug_reports")
        await conn.execute("TRUNCATE star_logs")

async def monthly_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    """Fires automatically on the 1st of every month at 1:00 PM WIB"""
    now = datetime.datetime.now(WIB)
    if now.day != 1: return 
    
    month_name = (now - datetime.timedelta(days=1)).strftime("%B")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        top_earner = await conn.fetchrow('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 1')
        groups = await conn.fetch('SELECT chat_id FROM active_groups')
        
        if top_earner:
            msg = f"🏆 **Best star earner this month ({month_name}) is @{top_earner['username']}!** 🏆\n\n"
            msg += f"Total **{top_earner['monthly_points']} RAWWY Stars** earned. Absolutely incredible work! 🌟 Keep up the amazing momentum, team!"
            for g in groups:
                try: await context.bot.send_message(g['chat_id'], msg, parse_mode="Markdown")
                except: pass
        await conn.execute("UPDATE kudos SET monthly_points = 0")

async def report_bug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Oops! You forgot to include the issue. Please type: `/bugreport [explain the bug here]`", parse_mode="Markdown")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", update.effective_user.username, text)
    await update.message.reply_text("Thank you so much! I have securely filed this bug report for the Super Admin to review tomorrow morning. 🐛🥾")

# --- FORTRESS SECURITY (Auto-Leave) ---
async def security_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers when the bot is added to a new group. Leaves if unauthorized."""
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

# --- SUPER OWNER & ADMIN FEATURES ---
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    try: target = [p.strip() for p in " ".join(context.args).split(",")][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, "Please use the correct format: `/addadmin @user`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
        user_id = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', target)
        
    if user_id:
        try: await context.bot.send_message(user_id, "🎉 **Congratulations!** You have been promoted to a Global Bot Admin.\nType `/help_admin` to access your new executive toolsuite.", parse_mode="Markdown")
        except: pass
    await context.bot.send_message(update.effective_user.id, f"✅ @{target} has been promoted to Bot Admin.")

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    try: target = [p.strip() for p in " ".join(context.args).split(",")][0].replace("@", "").lower()
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
    try: target = [p.strip() for p in " ".join(context.args).split(",")][0].replace("@", "")
    except: return await context.bot.send_message(update.effective_user.id, "Please use: `/removemember @user`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM bot_admins WHERE username=$1', target.lower())
        await conn.execute('DELETE FROM kudos WHERE username=$1', target)
        await conn.execute('DELETE FROM birthdays WHERE username=$1', target)
        await conn.execute('DELETE FROM away_status WHERE username=$1', target)
        await conn.execute("UPDATE tasks SET assignee='Unassigned' WHERE assignee=$1", target)
    await context.bot.send_message(update.effective_user.id, f"🗑️ **Member Offboarded:** @{target}'s data has been wiped entirely and tasks safely reassigned.", parse_mode="Markdown")

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
            else: return await context.bot.send_message(update.effective_user.id, "❌ Invalid feature.")
            await context.bot.send_message(update.effective_user.id, f"⚠️ **SUPER RESET:** {feat.upper()} data wiped completely.")
        except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Database Error: {e}")

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: target, msg = [p.strip() for p in " ".join(context.args).split(",", 1)]
    except: return await context.bot.send_message(update.effective_user.id, "Please use: `/announce All , Message`")
    async with pool.acquire() as conn:
        a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", msg)
        targets = await conn.fetch("SELECT chat_id FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target)}]
        sent = 0
        for t in targets:
            try:
                m = await context.bot.send_message(t['chat_id'], f"📢 **ADMIN ANNOUNCEMENT**\n\n{msg}", parse_mode="Markdown")
                await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
                sent += 1
            except: pass
    await context.bot.send_message(update.effective_user.id, f"✅ Announcement ID `{a_id}` sent to {sent} groups.")

async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: a_id, new_msg = [p.strip() for p in " ".join(context.args).split(",", 1)]; a_id = int(a_id)
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/editannounce ID , New Msg`")
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try: await context.bot.edit_message_text(f"📢 **ADMIN ANNOUNCEMENT**\n\n{new_msg}", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
            except: pass
        await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", new_msg, a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Updated Announcement {a_id}.")

async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: a_id = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/delannounce ID`")
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try: await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
            except: pass
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
        await conn.execute("DELETE FROM announcement_messages WHERE announcement_id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Deleted Announcement {a_id}.")

# --- 4/ RAWWY LIBRARY ---
async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    try:
        parts = [p.strip() for p in text.split(",")]
        name = parts[0].lower()
        content = parts[1]
        is_private = False
        if len(parts) >= 3 and parts[2].lower() == 'private':
            is_private = True
            await delete_cmd(update)
    except: return await update.message.reply_text("Oops! The format seems a bit off. Please use: `/addlib Name , Content`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4) ON CONFLICT (name) DO UPDATE SET content=EXCLUDED.content, added_by=EXCLUDED.added_by, is_private=EXCLUDED.is_private', name, content, update.effective_user.username, is_private)
    
    target_chat = update.effective_user.id if is_private else update.effective_chat.id
    try: await context.bot.send_message(target_chat, f"✅ The library asset **'{name}'** was successfully added by {update.effective_user.first_name}! {'🔒 (Private)' if is_private else ''}", parse_mode="Markdown")
    except: pass

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: name = [p.strip() for p in " ".join(context.args).split(",")][0].lower()
    except: return await update.message.reply_text("What asset are you looking for? Try: `/getlib Name`")
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
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: name = [p.strip() for p in " ".join(context.args).split(",")][0].lower()
    except: return await update.message.reply_text("Please provide an asset to delete: `/dellib Name`")
    
    async with pool.acquire() as conn:
        if await conn.execute('DELETE FROM library WHERE name=$1', name) == "DELETE 0": 
            return await update.message.reply_text("That asset doesn't exist.")
    await update.message.reply_text(f"🗑️ The asset '{name}' was successfully removed by {update.effective_user.first_name}.")

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

# --- 6/ AWAY SYSTEM ---
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        reason, time_str = parts[0], parts[1]
        end_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
        if end_time < datetime.datetime.now(WIB): 
            return await update.message.reply_text("I can't time travel just yet! Please make sure your return time is in the future.")
    except: return await update.message.reply_text("Oops! Make sure you use the format: `/away Reason , MM/DD/YYYY HH.MM`")

    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3) ON CONFLICT (username) DO UPDATE SET reason=$2, end_time=$3, last_notified=NULL', username, reason, end_time)
    context.job_queue.run_once(auto_return_away, when=end_time, data=username, name=f"away_{username}")
    await update.message.reply_text(f"🏖️ Got it! @{username} is officially away and touching grass until {end_time.strftime('%b %d at %H:%M WIB')}.")

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE): await process_return(context.job.data, context.bot)
async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE): await process_return(update.effective_user.username, context.bot, update.effective_chat.id)

async def process_return(username, bot, chat_id=None):
    pool = bot.application.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        mentions = await conn.fetch('SELECT mentioner, message, chat_title FROM away_mentions WHERE away_username=$1', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
    msg = "🎉 **Welcome back!** It's great to see you again.\n\nHere is what you missed while you were away:\n\n" + ("It was quiet. No mentions!" if not mentions else "".join([f"🔹 **@{m['mentioner']}** in *{m['chat_title']}*:\n\"{m['message']}\"\n\n" for m in mentions]))
    try: 
        if chat_id: await bot.send_message(chat_id, msg, parse_mode="Markdown")
    except: pass

# --- GLOBAL TRACKER (Usage, Errors, and Away Pings) ---
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
                    rem = a['end_time'] - now
                    d = rem.days; h = rem.seconds // 3600; m = (rem.seconds % 3600) // 60
                    t_str = f"{d} days, {h} hours, and {m} minutes" if d > 0 else f"{h} hours and {m} minutes"
                    
                    await update.message.reply_text(f"Just a polite heads up, @{a['username']} is currently away for another {t_str}.\n(Reason: {a['reason']})")
                    await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])

# --- 3/ RAWWY STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("Please reply to a specific user's message to give them a star!")
    giver, receiver = update.effective_user.username, update.message.reply_to_message.from_user.username
    if giver == receiver or update.message.reply_to_message.from_user.is_bot: return await update.message.reply_text("Haha, nice try! You can't give stars to yourself or to bots.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
        if q <= 0: return await update.message.reply_text("You have used up all your RAWWY Stars for this week! They will restock soon.")
        
        await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
        await log_star_action(pool, f"@{giver} awarded 1 Star to @{receiver}.")
        
    await update.message.reply_text(f"🌟 **Amazing!**\n@{receiver} just received a RAWWY Star from @{giver}!\nThey now hold a total of {score} RAWWY Stars.")

async def my_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 Hello @{user}, you currently have **{q} RAWWY Stars** left to hand out this week.")

async def check_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: target = [p.strip() for p in " ".join(context.args).split(",")][0].replace("@", "")
    except: return await context.bot.send_message(update.effective_user.id, "Please use: `/checkstars all` OR `/checkstars @user`")
    
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
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        t = parts[0].replace("@", ""); act = parts[1].lower(); amt = int(parts[2])
    except: return await context.bot.send_message(update.effective_user.id, "Please use this format: `/admin_stars @user , set_quota/add_total/sub_total , amount`")
    
    async with pool.acquire() as conn:
        if act == "set_quota": await conn.execute('UPDATE kudos SET quota=$1 WHERE username=$2', amt, t)
        elif act == "add_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points+$1 WHERE username=$2', amt, t)
        elif act == "sub_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points-$1 WHERE username=$2', amt, t)
        await log_star_action(pool, f"Admin @{update.effective_user.username} used '{act}' to change @{t}'s stars by {amt}.")
    await context.bot.send_message(update.effective_user.id, f"✅ The Stars system has been successfully updated for @{t}.")

# --- 1/ EVENTS & 2/ POLLS & 5/ TASKS ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
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
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        e_id = int(parts[0]); title = parts[1]; e_time = WIB.localize(datetime.datetime.strptime(parts[2], "%m/%d/%Y %H.%M")); rem = int(parts[3])
    except: return await update.message.reply_text("Please use: `/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, e_id)
    for job in context.job_queue.get_jobs_by_name(f"event_{e_id}"): job.schedule_removal()
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_{e_id}")
    await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: e_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
    except: return await update.message.reply_text("❌ `/cancelevent ID`")
    
    async with pool.acquire() as conn: await conn.execute('DELETE FROM events WHERE id=$1', e_id)
    for j in context.job_queue.get_jobs_by_name(f"event_{e_id}"): j.schedule_removal()
    await update.message.reply_text("🗑️ Cancelled.")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if not events: return await update.message.reply_text("No upcoming events scheduled.")
    await update.message.reply_text("📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}**\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; _, e_id, status = q.data.split("_")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT DO UPDATE SET status=$3', int(e_id), q.from_user.username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title FROM events WHERE id=$1', int(e_id))
    if not event: return await q.answer("Event deleted.")
    await q.edit_message_text(f"📅 **{event['title']}**\n" + "".join([f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n" for r in all_rsvps]), reply_markup=q.message.reply_markup, parse_mode="Markdown")
    await q.answer(status)

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.job_queue.application.bot_data.get('db_pool')
    async with pool.acquire() as conn: r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    await context.bot.send_message(context.job.chat_id, f"⏰ Hey everyone! The event **{context.job.data['title']}** is starting very soon.\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        a = parts[0].replace("@", ""); m = int(parts[1]); d = parts[2]
        if not (60 <= m <= 480): return await update.message.reply_text("For productivity reasons, I can only set tasks between 60 and 480 minutes.")
    except: return await update.message.reply_text("Please use the task format: `/assign @user , Minutes , Task description`")
    
    dl = datetime.datetime.now(WIB) + datetime.timedelta(minutes=m)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', a, d, dl, update.effective_user.username)
    
    context.job_queue.run_once(task_reminder, when=dl - datetime.timedelta(minutes=10), data={"assignee": a, "assigner": update.effective_user.username, "id": t_id, "desc": d}, chat_id=update.effective_chat.id)
    await update.message.reply_text(f"📋 **Task Assigned!**\n@{update.effective_user.username} assigned `{t_id}` to @{a}.\n📝 {d}\n⏳ Due exactly at: {dl.strftime('%H:%M WIB')}", parse_mode="Markdown")

async def task_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.job_queue.application.bot_data.get('db_pool')
    async with pool.acquire() as conn: task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed': 
        await context.bot.send_message(context.job.chat_id, f"⚠️ Hello @{context.job.data['assignee']} and @{context.job.data['assigner']}, just a quick heads up that the task '{context.job.data['desc']}' is about to hit its deadline in 10 minutes!")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
    except: return await update.message.reply_text("Please provide the ID: `/complete ID`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assignee, status FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("I couldn't find that task.")
        if task['status'] == 'Completed': return await update.message.reply_text("This task is already finished!")
        if task['assignee'] != update.effective_user.username: return await update.message.reply_text("Only the person assigned to this task can mark it complete.")
        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
    await update.message.reply_text(f"✅ Great job! Task `{t_id}` is marked as completed.", parse_mode="Markdown")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
    except: return await update.message.reply_text("Please provide the ID: `/canceltask ID`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("I couldn't find that task.")
        if task['assigned_by'] != update.effective_user.username: return await update.message.reply_text("Only the person who assigned this task can cancel it.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await update.message.reply_text("🗑️ Task cancelled.")

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: tasks = await conn.fetch("SELECT id, task_desc, deadline FROM tasks WHERE status='Pending' AND assignee=$1 ORDER BY deadline", update.effective_user.username)
    if not tasks: msg = "🎉 You have no pending tasks! Great job catching up."
    else:
        msg = "📋 **Your Active Tasks**\n\n"
        for t in tasks:
            rem = int((t['deadline'] - now).total_seconds() / 60)
            status = f"{rem}m left" if rem > 0 else "OVERDUE"
            msg += f"🔹 `{t['id']}` | {t['task_desc']} | ⏳ {status}\n"
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: pass

async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        dur = int(parts[1]) * 3600
        msg = await context.bot.send_poll(update.effective_chat.id, parts[0], parts[2:], is_anonymous=False, allows_multiple_answers=True, open_period=dur)
        rem_time = datetime.datetime.now(WIB) + datetime.timedelta(seconds=dur) - datetime.timedelta(minutes=15)
        if dur > 900:
            context.job_queue.run_once(poll_reminder, when=rem_time, data={"chat_id": update.effective_chat.id, "q": parts[0], "msg_id": msg.message_id})
    except: await update.message.reply_text("Poll format error. Use: `/poll Question , Hours , Opt1 , Opt2`")

async def poll_reminder(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.send_message(context.job.data['chat_id'], f"⏳ **Attention team!** The poll '{context.job.data['q']}' is ending in 15 minutes! Please get your votes in.", reply_to_message_id=context.job.data['msg_id'], parse_mode="Markdown")
    except: pass

async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u, b = parts[0].replace("@", ""), parts[1]
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/addbday @user , MM/DD`")
    async with pool.acquire() as conn: await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
    await context.bot.send_message(update.effective_user.id, f"🎂 Added {u}.")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn: b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    await context.bot.send_message(update.effective_user.id, "🎂 **Birthdays**\n" + "\n".join([f"• @{x['username']}: {x['bday']}" for x in b]) if b else "None.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception handled:", exc_info=context.error)
    pool = context.bot_data.get('db_pool')
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE bot_stats SET errors = errors + 1 WHERE date=CURRENT_DATE")

# --- RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db
    app.add_error_handler(error_handler)

    app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(monthly_leaderboard, datetime.time(hour=13, minute=0, tzinfo=WIB))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("help_admin", help_admin_command))
    app.add_handler(CommandHandler("bugreport", report_bug))
    
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("deladmin", del_admin))
    app.add_handler(CommandHandler("removemember", remove_member))
    
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("mystars", my_stars))
    app.add_handler(CommandHandler("admin_stars", admin_stars))
    
    app.add_handler(CommandHandler("newevent", create_event))
    app.add_handler(CommandHandler("events", list_events))
    app.add_handler(CommandHandler("cancelevent", cancel_event))
    
    app.add_handler(CommandHandler("assign", assign_task))
    app.add_handler(CommandHandler("complete", complete_task))
    app.add_handler(CommandHandler("canceltask", cancel_task))
    app.add_handler(CommandHandler("mytasks", my_tasks))
    
    app.add_handler(CommandHandler("poll", create_poll))
    app.add_handler(CommandHandler("addlib", add_lib))
    app.add_handler(CommandHandler("getlib", get_lib))
    app.add_handler(CommandHandler("library", list_lib))
    app.add_handler(CommandHandler("dellib", del_lib))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, security_check))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_tracker))

    logger.info("Starting Enterprise bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
