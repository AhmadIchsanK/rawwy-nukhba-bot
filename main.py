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
    """Checks if user is the Super Owner."""
    if not username: 
        return False
    return username.lower() == SUPER_OWNER

async def is_bot_admin(username: str, pool) -> bool:
    """Checks if user is Super Owner OR a designated Bot Admin."""
    if await is_super(username): 
        return True
    if not username: 
        return False
    async with pool.acquire() as conn:
        res = await conn.fetchrow('SELECT username FROM bot_admins WHERE username=$1', username.lower())
        return bool(res)

async def delete_cmd(update: Update):
    """Silently deletes an admin command to keep the chat clean."""
    if update.effective_chat.type != "private":
        try: 
            await update.message.delete()
        except: 
            pass

# --- DATABASE SETUP ---
async def init_db(app: Application):
    if not DATABASE_URL:
        logger.error("DATABASE_URL missing!")
        return
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_admins (username TEXT PRIMARY KEY);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS kudos (username TEXT PRIMARY KEY, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0, quota INT DEFAULT 3);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT, is_private BOOLEAN DEFAULT FALSE);''')
        try: 
            await conn.execute('''ALTER TABLE library ADD COLUMN is_private BOOLEAN DEFAULT FALSE;''')
        except: 
            pass
        
        await conn.execute('''CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE, assigned_by TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (username TEXT PRIMARY KEY, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (id SERIAL PRIMARY KEY, username TEXT, bday TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcements (id SERIAL PRIMARY KEY, text TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS announcement_messages (announcement_id INT, chat_id BIGINT, message_id BIGINT);''')
        
    commands = [
        BotCommand("help", "View Manager Guide"),
        BotCommand("newevent", "[1. Events] Title , MM/DD/YYYY HH.MM , RemMins"),
        BotCommand("editevent", "[1. Events] ID , Title , MM/DD/YYYY HH.MM , RemMins"),
        BotCommand("cancelevent", "[1. Events] Cancel ID"),
        BotCommand("events", "[1. Events] View Schedule"),
        BotCommand("poll", "[2. Polls] Question , Hours , Opt1 , Opt2"),
        BotCommand("thanks", "[3. Stars] (Reply) Send RAWWY Star"),
        BotCommand("mystars", "[3. Stars] Check your quota"),
        BotCommand("leaderboard", "[3. Stars] Top Star earners"),
        BotCommand("addlib", "[4. Library] Name , Content , [private]"),
        BotCommand("getlib", "[4. Library] Get Name"),
        BotCommand("library", "[4. Library] Browse assets"),
        BotCommand("dellib", "[4. Library] Remove Name"),
        BotCommand("assign", "[5. Tasks] @user , Mins (Max 480) , Task"),
        BotCommand("complete", "[5. Tasks] Mark done (Assignee only)"),
        BotCommand("canceltask", "[5. Tasks] Drop task (Assigner only)"),
        BotCommand("mytasks", "[5. Tasks] View your to-do list"),
        BotCommand("away", "[6. Away] Reason , MM/DD/YYYY HH.MM"),
        BotCommand("back", "[6. Away] I'm back!")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Enterprise Database, Auto-Leave & Menus Configured!")

# --- CORE & AUTH COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 **[RW] Nukhba Manager is globally online!** Type `/help` to dive in.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    is_admin = await is_bot_admin(username, pool)
    is_owner = await is_super(username)

    help_text = (
        "🚀 *[RW] Nukhba Manager Guide*\n\n"
        "📅 *1/ Events (Syncs & Meets)*\n`/newevent Title , MM/DD/YYYY HH.MM , RemMins`\n`/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`\n`/cancelevent ID` | `/events`\n\n"
        "📊 *2/ Quick Polls*\n`/poll Question , Hours , Opt1 , Opt2`\n\n"
        "🌟 *3/ RAWWY Stars (Show some love!)*\n`/thanks` (reply) | `/mystars` | `/leaderboard`\n\n"
        "📚 *4/ RAWWY Library (Knowledge Base)*\n`/addlib Name , Content , private` *(Optional: type 'private' at the end to lock it!)*\n`/getlib [name]` | `/library` | `/dellib [name]`\n\n"
        "⚡ *5/ Quick Tasks (Get stuff done)*\n`/assign @user , 60 , Task` *(Max 480m)*\n`/complete ID` | `/canceltask ID` | `/mytasks`\n\n"
        "🏖️ *6/ Away Mode (Brb, touching grass)*\n`/away Reason , MM/DD/YYYY HH.MM` | `/back`"
    )
    
    if is_admin:
        help_text += (
            "\n\n🔐 *BOT ADMIN COMMANDS*\n"
            "🎂 *Birthdays:* `/addbday @user , MM/DD` | `/listbdays`\n"
            "🌟 *Stars Data:* `/checkstars all` | `/checkstars @user`\n"
            "⚙️ *Edit Stars:* `/admin_stars @user , [set_quota/add_total/sub_total] , [amount]`\n"
            "📢 *Broadcast:* `/announce All , Message` | `/editannounce ID , Msg` | `/delannounce ID`"
        )
    if is_owner:
        help_text += (
            "\n\n👑 *SUPER OWNER COMMANDS*\n"
            "🛡️ *Access:* `/addadmin @user` | `/deladmin @user` | `/listadmins`\n"
            "🛑 *Offboarding:* `/removemember @user` (Wipes data & drops tasks)\n"
            "📈 *System:* `/botstatus` (View active groups & stats)\n"
            "☢️ *Wipe:* `/super_reset [stars/tasks/library/events/away]`"
        )

    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": 
            await update.message.reply_text("📬 I've slid into your DMs with the manual!")
    except:
        if update.effective_chat.type != "private": 
            await update.message.reply_text("❌ Oops! I can't DM you. Please message me directly first!")

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

# --- SUPER OWNER FEATURES ---
async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): 
        return
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

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): 
        return
    try: 
        target = context.args[0].replace("@", "").lower()
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ Use `/addadmin @user`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
    await context.bot.send_message(update.effective_user.id, f"✅ @{target} is now a Bot Admin.")

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): 
        return
    try: 
        target = context.args[0].replace("@", "").lower()
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ Use `/deladmin @user`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        res = await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
    if res != "DELETE 0":
        await context.bot.send_message(update.effective_user.id, f"🗑️ @{target} removed from Admins.")
    else:
        await context.bot.send_message(update.effective_user.id, "❌ User not an admin.")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): 
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        admins = await conn.fetch('SELECT username FROM bot_admins')
    if admins:
        msg = "👑 **Bot Admins**\n" + "\n".join([f"• @{a['username']}" for a in admins])
    else:
        msg = "👑 **Bot Admins**\nNone (Only Super Owner exists)."
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): 
        return
    try: 
        target = context.args[0].replace("@", "")
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ Use `/removemember @user`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM bot_admins WHERE username=$1', target.lower())
        await conn.execute('DELETE FROM kudos WHERE username=$1', target)
        await conn.execute('DELETE FROM birthdays WHERE username=$1', target)
        await conn.execute('DELETE FROM away_status WHERE username=$1', target)
        await conn.execute("UPDATE tasks SET assignee='Unassigned' WHERE assignee=$1", target)
    await context.bot.send_message(update.effective_user.id, f"🗑️ **Member Offboarded:** @{target}'s data wiped. Tasks reassigned.", parse_mode="Markdown")

async def super_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): 
        return
    try: 
        feat = context.args[0].lower()
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ `/super_reset [stars/tasks/library/events/away]`")
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
        except Exception as e: 
            await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

# --- 9/ ADMIN BROADCAST ---
async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): 
        return
    text = " ".join(context.args)
    if "," not in text: 
        return await context.bot.send_message(update.effective_user.id, "❌ `/announce All , Message`")
    try: 
        target, msg = [p.strip() for p in text.split(",", 1)]
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ Missing message.")
    async with pool.acquire() as conn:
        a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", msg)
        targets = await conn.fetch("SELECT chat_id FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target)}]
        sent = 0
        for t in targets:
            try:
                m = await context.bot.send_message(t['chat_id'], f"📢 **ADMIN ANNOUNCEMENT**\n\n{msg}", parse_mode="Markdown")
                await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
                sent += 1
            except: 
                pass
    await context.bot.send_message(update.effective_user.id, f"Campagn complete. Announcement `{a_id}` sent to {sent} groups.")

async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): 
        return
    try: 
        a_id, new_msg = [p.strip() for p in " ".join(context.args).split(",", 1)]
        a_id = int(a_id)
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ `/editannounce ID , New Msg`")
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try: 
                await context.bot.edit_message_text(f"📢 **ADMIN ANNOUNCEMENT**\n\n{new_msg}", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
            except: 
                pass
        await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", new_msg, a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Updated Announcement {a_id}.")

async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): 
        return
    try: 
        a_id = int(context.args[0])
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ `/delannounce ID`")
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try: 
                await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
            except: 
                pass
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
        await conn.execute("DELETE FROM announcement_messages WHERE announcement_id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Deleted Announcement {a_id}.")

# --- 4/ RAWWY LIBRARY ---
async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if "," not in text: 
        return await update.message.reply_text("❌ `/addlib Name , Link , [private]`")
    try:
        parts = [p.strip() for p in text.split(",")]
        name = parts[0].lower()
        content = parts[1]
        is_private = False
        if len(parts) >= 3 and parts[2].lower() == 'private':
            is_private = True
            await delete_cmd(update)
    except: 
        return await update.message.reply_text("❌ Invalid format.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4) ON CONFLICT (name) DO UPDATE SET content=EXCLUDED.content, added_by=EXCLUDED.added_by, is_private=EXCLUDED.is_private', name, content, update.effective_user.username, is_private)
    
    target_chat = update.effective_user.id if is_private else update.effective_chat.id
    try: 
        await context.bot.send_message(target_chat, f"✅ Saved **{name}**! {'🔒 (Private)' if is_private else ''}", parse_mode="Markdown")
    except: 
        pass

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: 
        return await update.message.reply_text("❌ `/getlib Name`")
    name = " ".join(context.args).strip().lower()
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT content, added_by, is_private FROM library WHERE name=$1', name)
        
    if not r: 
        return await update.message.reply_text("❌ Not found.")
    
    if r['is_private']:
        await delete_cmd(update)
        if r['added_by'] != update.effective_user.username:
            return await context.bot.send_message(update.effective_user.id, "❌ You do not have permission to view this private file.")
        try: 
            await context.bot.send_message(update.effective_user.id, f"🔒 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
        except: 
            await context.bot.send_message(update.effective_user.id, "❌ Start a DM with me to view your private files.")
    else:
        await update.message.reply_text(f"📂 **{name.title()}** (@{r['added_by']}):\n{r['content']}", parse_mode="Markdown")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
    if not recs: 
        return await update.message.reply_text("📚 Library is empty.")
    
    msg = "📚 **RAWWY Library**\n"
    for r in recs:
        if r['is_private']:
            if r['added_by'] == update.effective_user.username:
                msg += f"• 🔒 `{r['name']}` (Private)\n"
        else:
            msg += f"• 📂 `{r['name']}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: 
        return await update.message.reply_text("❌ `/dellib Name`")
    name = " ".join(context.args).strip().lower()
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT added_by, is_private FROM library WHERE name=$1', name)
        if not r: 
            return await update.message.reply_text("❌ Not found.")
        if r['is_private']:
            await delete_cmd(update)
            if r['added_by'] != update.effective_user.username: 
                return await context.bot.send_message(update.effective_user.id, "❌ Not your private file.")
        await conn.execute('DELETE FROM library WHERE name=$1', name)
    target = update.effective_user.id if r['is_private'] else update.effective_chat.id
    try: 
        await context.bot.send_message(target, "🗑️ Deleted.")
    except: 
        pass

# --- 6/ AWAY SYSTEM ---
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if "," not in text: 
        return await update.message.reply_text("❌ Format: `/away Reason , MM/DD/YYYY HH.MM`")
    try:
        reason, time_str = [p.strip() for p in text.split(",", 1)]
        end_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
        if end_time < datetime.datetime.now(WIB): 
            return await update.message.reply_text("❌ Return time cannot be in the past.")
    except: 
        return await update.message.reply_text("❌ Format: `MM/DD/YYYY HH.MM`")

    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3) ON CONFLICT (username) DO UPDATE SET reason=$2, end_time=$3, last_notified=NULL', username, reason, end_time)
    context.job_queue.run_once(auto_return_away, when=end_time, data=username, name=f"away_{username}")
    await update.message.reply_text(f"🏖️ @{username} is touching grass until {end_time.strftime('%m/%d %H:%M WIB')}.")

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE): 
    await process_return(context.job.data, context.bot)

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    await process_return(update.effective_user.username, context.bot, update.effective_chat.id)

async def process_return(username, bot, chat_id=None):
    pool = bot.application.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        mentions = await conn.fetch('SELECT mentioner, message, chat_title FROM away_mentions WHERE away_username=$1', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
    if mentions:
        msg = "👋 Welcome back! Here is what you missed:\n\n" + "".join([f"🔹 **@{m['mentioner']}** in *{m['chat_title']}*:\n\"{m['message']}\"\n\n" for m in mentions])
    else:
        msg = "👋 Welcome back! No mentions missed."
    try: 
        if chat_id: 
            await bot.send_message(chat_id, f"Welcome back @{username}! Removed your Away status.")
    except: 
        pass

# --- GLOBAL TRACKER ---
async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: 
        return
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn: 
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
    text, mentioner = update.message.text, update.effective_user.username
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        aways = await conn.fetch('SELECT username, reason, end_time, last_notified FROM away_status')
        for a in aways:
            if f"@{a['username']}" in text:
                await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], mentioner, text, chat.title or "DM")
                if not a['last_notified'] or (now - a['last_notified']).total_seconds() > 3600:
                    await update.message.reply_text(f"🏖️ @{a['username']} is away until {a['end_time'].strftime('%m/%d %H:%M WIB')}.\n(Reason: {a['reason']})")
                    await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])

# --- 3/ RAWWY STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: 
        return await update.message.reply_text("❌ Reply to a message!")
    giver, receiver = update.effective_user.username, update.message.reply_to_message.from_user.username
    if giver == receiver or update.message.reply_to_message.from_user.is_bot: 
        return await update.message.reply_text("❌ Bots/Yourself cannot get stars.")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
        if q <= 0: 
            return await update.message.reply_text("❌ You are out of RAWWY Stars!")
        await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
    await update.message.reply_text(f"🌟 **RAWWY Star Awarded!**\n@{receiver} received a star from @{giver}!\nTotal: {score}")

async def my_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 @{user}, you have **{q} RAWWY Stars** left.")

async def check_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): 
        return
    try: 
        target = context.args[0].replace("@", "")
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ `/checkstars all` OR `/checkstars @user`")
    async with pool.acquire() as conn:
        if target.lower() == 'all':
            recs = await conn.fetch('SELECT username, quota, all_time_points FROM kudos')
            msg = "🌟 **Team Stars**\n" + "\n".join([f"@{r['username']} - Quota: {r['quota']} | Total: {r['all_time_points']}" for r in recs]) if recs else "Empty."
        else:
            r = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
            msg = f"🌟 **@{target}**\nTotal: {r['all_time_points']} | Monthly: {r['monthly_points']} | Quota: {r['quota']}" if r else "❌ Not found."
    try: 
        await context.bot.send_message(update.effective_user.id, msg)
    except: 
        pass

async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): 
        return
    try:
        t, act, amt = [p.strip() for p in " ".join(context.args).split(",", 2)]
        t = t.replace("@", "")
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ `/admin_stars @user , set_quota/add_total/sub_total , amount`")
    async with pool.acquire() as conn:
        if act == "set_quota": await conn.execute('UPDATE kudos SET quota=$1 WHERE username=$2', int(amt), t)
        elif act == "add_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points+$1 WHERE username=$2', int(amt), t)
        elif act == "sub_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points-$1 WHERE username=$2', int(amt), t)
    await context.bot.send_message(update.effective_user.id, f"✅ Stars updated for @{t}.")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        recs = await conn.fetch('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 5')
    if not recs: 
        return await update.message.reply_text("📊 **Leaderboard**\nNo points given!")
    await update.message.reply_text("📊 **Leaderboard**\n" + "\n".join([f"{i}. @{r['username']} - {r['monthly_points']} pts" for i, r in enumerate(recs, 1)]), parse_mode="Markdown")

# --- 1/ EVENTS & 2/ POLLS & 5/ TASKS & BDAY ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        title, t_str, rem = [p.strip() for p in " ".join(context.args).split(",", 2)]
        e_time = WIB.localize(datetime.datetime.strptime(t_str, "%m/%d/%Y %H.%M"))
    except: 
        return await update.message.reply_text("❌ `/newevent Title , MM/DD/YYYY HH.MM , RemMins`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by) VALUES ($1, $2, $3) RETURNING id', title, e_time, update.effective_user.username)
    kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not", callback_data=f"rsvp_{e_id}_Not Going")]]
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=int(rem)), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_{e_id}")
    await update.message.reply_text(f"📅 **{title}**\n🕒 {e_time.strftime('%m/%d/%Y %H:%M')} WIB", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        e_id, title, t_str, rem = [p.strip() for p in " ".join(context.args).split(",", 3)]
        e_time = WIB.localize(datetime.datetime.strptime(t_str, "%m/%d/%Y %H.%M"))
    except: 
        return await update.message.reply_text("❌ `/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, int(e_id))
    for job in context.job_queue.get_jobs_by_name(f"event_{e_id}"): 
        job.schedule_removal()
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=int(rem)), chat_id=update.effective_chat.id, data={"id": int(e_id), "title": title}, name=f"event_{e_id}")
    await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        e_id = int(context.args[0])
    except: 
        return await update.message.reply_text("❌ `/cancelevent ID`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute('DELETE FROM events WHERE id=$1', e_id)
    for j in context.job_queue.get_jobs_by_name(f"event_{e_id}"): 
        j.schedule_removal()
    await update.message.reply_text("🗑️ Cancelled.")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if events:
        await update.message.reply_text("📅 **Upcoming**\n" + "\n".join([f"🔹 **{e['title']}**\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")
    else:
        await update.message.reply_text("No events scheduled.", parse_mode="Markdown")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, e_id, status = q.data.split("_")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT DO UPDATE SET status=$3', int(e_id), q.from_user.username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title FROM events WHERE id=$1', int(e_id))
    if not event: 
        return await q.answer("Deleted.")
    await q.edit_message_text(f"📅 **{event['title']}**\n" + "".join([f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n" for r in all_rsvps]), reply_markup=q.message.reply_markup, parse_mode="Markdown")
    await q.answer(status)

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.job_queue.application.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    await context.bot.send_message(context.job.chat_id, f"⏰ **{context.job.data['title']}** starting!\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        a, m, d = [p.strip() for p in " ".join(context.args).split(",", 2)]
        a = a.replace("@", "")
        m = int(m)
    except: 
        return await update.message.reply_text("❌ `/assign @user , Mins , Task`")
    dl = datetime.datetime.now(WIB) + datetime.timedelta(minutes=m)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', a, d, dl, update.effective_user.username)
    await update.message.reply_text(f"📋 **Task `{t_id}` assigned!**\n📝 {d}\n⏳ Due: {dl.strftime('%H:%M')}", parse_mode="Markdown")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        t_id = int(context.args[0])
    except: 
        return await update.message.reply_text("❌ `/complete ID`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        t = await conn.fetchrow('SELECT assignee FROM tasks WHERE id=$1', t_id)
        if t and t['assignee'] == update.effective_user.username: 
            await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
    await update.message.reply_text(f"✅ Task `{t_id}` completed.")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        t_id = int(context.args[0])
    except: 
        return await update.message.reply_text("❌ `/canceltask ID`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await update.message.reply_text("🗑️ Cancelled.")

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        tasks = await conn.fetch("SELECT id, task_desc, deadline FROM tasks WHERE status='Pending' AND assignee=$1 ORDER BY deadline", update.effective_user.username)
    if tasks:
        msg = "📋 **Your Tasks**\n" + "".join([f"🔹 `{t['id']}` | {t['task_desc']} | ⏳ {int((t['deadline'] - now).total_seconds()/60)}m left\n" for t in tasks])
    else:
        msg = "🎉 Clear!"
    try: 
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: 
        pass

async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        dur = int(parts[1]) * 3600
    except: 
        return await update.message.reply_text("❌ `/poll Question , Hours , Opt1 , Opt2`")
    await context.bot.send_poll(update.effective_chat.id, parts[0], parts[2:], is_anonymous=False, allows_multiple_answers=True, open_period=dur)

async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): 
        return
    try: 
        u, b = [p.strip() for p in " ".join(context.args).split(",")]
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ `/addbday @user , MM/DD`")
    async with pool.acquire() as conn: 
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u.replace("@", ""), b)
    await context.bot.send_message(update.effective_user.id, f"🎂 Added {u}.")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): 
        return
    async with pool.acquire() as conn: 
        b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    if b:
        msg = "🎂 **Birthdays**\n" + "\n".join([f"• @{x['username']}: {x['bday']}" for x in b])
    else:
        msg = "None saved."
    await context.bot.send_message(update.effective_user.id, msg)

# --- RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("deladmin", del_admin))
    app.add_handler(CommandHandler("listadmins", list_admins))
    app.add_handler(CommandHandler("removemember", remove_member))
    app.add_handler(CommandHandler("super_reset", super_reset))
    app.add_handler(CommandHandler("botstatus", bot_status))
    
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(CommandHandler("editannounce", edit_announce))
    app.add_handler(CommandHandler("delannounce", del_announce))
    
    app.add_handler(CommandHandler("away", set_away))
    app.add_handler(CommandHandler("back", set_back))
    
    app.add_handler(CommandHandler("thanks", give_thanks))
    app.add_handler(CommandHandler("mystars", my_stars))
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
    app.add_handler(CommandHandler("canceltask", cancel_task))
    app.add_handler(CommandHandler("mytasks", my_tasks))
    
    app.add_handler(CommandHandler("addbday", add_bday))
    app.add_handler(CommandHandler("listbdays", list_bdays))
    
    app.add_handler(CommandHandler("poll", create_poll))
    
    app.add_handler(CommandHandler("addlib", add_lib))
    app.add_handler(CommandHandler("getlib", get_lib))
    app.add_handler(CommandHandler("library", list_lib))
    app.add_handler(CommandHandler("dellib", del_lib))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, security_check))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_tracker))

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
