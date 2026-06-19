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
    if not username: return False
    return username.lower() == SUPER_OWNER

async def is_bot_admin(username: str, pool) -> bool:
    """Checks if user is Super Owner OR a designated Bot Admin."""
    if await is_super(username): return True
    if not username: return False
    async with pool.acquire() as conn:
        res = await conn.fetchrow('SELECT username FROM bot_admins WHERE username=$1', username.lower())
        return bool(res)

async def delete_cmd(update: Update):
    """Silently deletes an admin command to keep the chat clean."""
    if update.effective_chat.type != "private":
        try: await update.message.delete()
        except: pass

# --- DATABASE SETUP ---
async def init_db(app: Application):
    if not DATABASE_URL:
        logger.error("DATABASE_URL missing!")
        return
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_admins (username TEXT PRIMARY KEY);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS kudos (username TEXT PRIMARY KEY, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0, quota INT DEFAULT 3);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT);''')
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
        BotCommand("help", "Nukhba Manager Guide"),
        BotCommand("newevent", "[Events] Title , MM/DD/YYYY HH.MM , RemMins"),
        BotCommand("editevent", "[Events] ID , Title , MM/DD/YYYY HH.MM , RemMins"),
        BotCommand("cancelevent", "[Events] ID"),
        BotCommand("events", "[Events] Upcoming events"),
        BotCommand("poll", "[Polls] Question , Hours , Opt1 , Opt2"),
        BotCommand("thanks", "[Stars] (Reply) Give a RAWWY Star"),
        BotCommand("mystars", "[Stars] Check your quota"),
        BotCommand("leaderboard", "[Stars] Top RAWWY Stars"),
        BotCommand("addlib", "[Library] Name , Content"),
        BotCommand("getlib", "[Library] Name"),
        BotCommand("library", "[Library] View assets"),
        BotCommand("dellib", "[Library] Name"),
        BotCommand("assign", "[Tasks] @user , Mins (Max 480) , Task"),
        BotCommand("complete", "[Tasks] ID (Assignee only)"),
        BotCommand("canceltask", "[Tasks] ID (Assigner only)"),
        BotCommand("mytasks", "[Tasks] View your tasks via DM"),
        BotCommand("away", "[Away] Reason , MM/DD/YYYY HH.MM"),
        BotCommand("back", "[Away] Remove away status early")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Advanced Database, Auth & Secure Menus Configured!")

# --- CORE & AUTH COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 [RW] Nukhba Manager is globally online! All data is synced.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    is_admin = await is_bot_admin(username, pool)
    is_owner = await is_super(username)

    help_text = (
        "🛠️ *[RW] Nukhba Manager Guide*\n\n"
        "*1/ Event Management*\n`/newevent Title , MM/DD/YYYY HH.MM , RemMins`\n`/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`\n`/cancelevent ID` | `/events`\n\n"
        "*2/ Polling System*\n`/poll Question , Hours , Opt1 , Opt2`\n\n"
        "*3/ RAWWY Stars*\n`/thanks` (reply) | `/mystars` | `/leaderboard`\n\n"
        "*5/ Mini Library*\n`/addlib Name , Content` | `/getlib [name]`\n`/library` | `/dellib [name]`\n\n"
        "*7/ Quick Tasks (Max 480m)*\n`/assign @user , 60 , Task`\n`/complete ID` (Assignee)\n`/canceltask ID` (Assigner)\n`/mytasks` (DM Check)\n\n"
        "*8/ Away Mode*\n`/away Reason , MM/DD/YYYY HH.MM` | `/back`"
    )
    
    if is_admin:
        help_text += (
            "\n\n🔐 *ADMIN COMMANDS (Hidden from Team)*\n"
            "• `/addbday @user , MM/DD` | `/listbdays`\n"
            "• `/checkstars all` OR `/checkstars @user`\n"
            "• `/admin_stars @user , [set_quota/add_total/sub_total] , [amount]`\n"
            "• `/announce All , Message`\n"
            "• `/editannounce ID , Msg` | `/delannounce ID`"
        )
    if is_owner:
        help_text += (
            "\n\n👑 *SUPER OWNER COMMANDS*\n"
            "• `/addadmin @user` | `/deladmin @user` | `/listadmins`\n"
            "• `/removemember @user` (Complete offboarding wipe)\n"
            "• `/super_reset [stars/tasks/library/events/away]`"
        )

    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("📬 Guide sent to your DM!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("❌ Error: I cannot DM you. Please message me directly first!")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return await context.bot.send_message(update.effective_user.id, "❌ Error: Super Owner Access Only.")
    try: target = context.args[0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: Use `/addadmin @user`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
    await context.bot.send_message(update.effective_user.id, f"✅ @{target} is now a Global Bot Admin.")

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return await context.bot.send_message(update.effective_user.id, "❌ Error: Super Owner Access Only.")
    try: target = context.args[0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: Use `/deladmin @user`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        res = await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
    if res == "DELETE 0": await context.bot.send_message(update.effective_user.id, f"❌ Error: @{target} is not an admin.")
    else: await context.bot.send_message(update.effective_user.id, f"🗑️ @{target} removed from Global Admins.")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return await context.bot.send_message(update.effective_user.id, "❌ Error: Super Owner Access Only.")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        admins = await conn.fetch('SELECT username FROM bot_admins')
    
    if not admins: return await context.bot.send_message(update.effective_user.id, "👑 **Bot Admins**\nNone assigned yet (Only Super Owner exists).", parse_mode="Markdown")
    msg = "👑 **Global Bot Admins**\n" + "\n".join([f"• @{a['username']}" for a in admins])
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return await context.bot.send_message(update.effective_user.id, "❌ Error: Super Owner Access Only.")
    try: target = context.args[0].replace("@", "")
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: Use `/removemember @user`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM bot_admins WHERE username=$1', target.lower())
        await conn.execute('DELETE FROM kudos WHERE username=$1', target)
        await conn.execute('DELETE FROM birthdays WHERE username=$1', target)
        await conn.execute('DELETE FROM away_status WHERE username=$1', target)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', target)
        await conn.execute('DELETE FROM rsvps WHERE username=$1', target)
        # Safely reassign tasks so workflow isn't lost
        await conn.execute("UPDATE tasks SET assignee='Unassigned' WHERE assignee=$1", target)
        
    await context.bot.send_message(update.effective_user.id, f"🗑️ **Member Offboarded:** @{target}'s data (Stars, Birthdays, RSVPs, Away Status, Admin rights) has been permanently wiped. Any pending tasks have been marked as 'Unassigned'.", parse_mode="Markdown")

async def super_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return await context.bot.send_message(update.effective_user.id, "❌ Error: Super Owner Access Only.")
    try: feat = context.args[0].lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: `/super_reset [stars/tasks/library/events/away]`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        try:
            if feat == "stars": await conn.execute("TRUNCATE kudos")
            elif feat == "tasks": await conn.execute("TRUNCATE tasks RESTART IDENTITY")
            elif feat == "library": await conn.execute("TRUNCATE library")
            elif feat == "events": await conn.execute("TRUNCATE events CASCADE RESTART IDENTITY")
            elif feat == "away": await conn.execute("TRUNCATE away_status, away_mentions CASCADE")
            else: return await context.bot.send_message(update.effective_user.id, "❌ Error: Invalid feature to reset.")
            await context.bot.send_message(update.effective_user.id, f"⚠️ **SUPER RESET:** {feat.upper()} data wiped completely.")
        except Exception as e:
            await context.bot.send_message(update.effective_user.id, f"❌ Database Error: {e}")

# --- 9/ ADMIN BROADCAST ---
async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return await context.bot.send_message(update.effective_user.id, "❌ Error: Admin Only.")
    
    text = " ".join(context.args)
    if "," not in text: return await context.bot.send_message(update.effective_user.id, "❌ Error: `/announce All , Message`")
    try: target, msg = [p.strip() for p in text.split(",", 1)]
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: Missing message body.")
    
    async with pool.acquire() as conn:
        a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", msg)
        targets = await conn.fetch("SELECT chat_id FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target)}]
        sent_count = 0
        for t in targets:
            try:
                m = await context.bot.send_message(t['chat_id'], f"📢 **ADMIN ANNOUNCEMENT**\n\n{msg}", parse_mode="Markdown")
                await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
                sent_count += 1
            except: pass
    await context.bot.send_message(update.effective_user.id, f"✅ Announcement ID `{a_id}` sent to {sent_count} groups.")

async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    
    text = " ".join(context.args)
    try:
        a_id, new_msg = [p.strip() for p in text.split(",", 1)]
        a_id = int(a_id)
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: `/editannounce ID , New Msg` (Ensure ID is a number).")
    
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        if not msgs: return await context.bot.send_message(update.effective_user.id, "❌ Error: Announcement ID not found.")
        success = 0
        for m in msgs:
            try: 
                await context.bot.edit_message_text(f"📢 **ADMIN ANNOUNCEMENT**\n\n{new_msg}", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
                success += 1
            except: pass
        await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", new_msg, a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Announcement {a_id} updated in {success} groups.")

async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    
    try: a_id = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: `/delannounce ID` (Ensure ID is a number).")
    
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        if not msgs: return await context.bot.send_message(update.effective_user.id, "❌ Error: Announcement ID not found.")
        for m in msgs:
            try: await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
            except: pass
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
        await conn.execute("DELETE FROM announcement_messages WHERE announcement_id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, f"✅ Announcement {a_id} deleted globally.")

# --- 8/ AWAY SYSTEM ---
async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if "," not in text: return await update.message.reply_text("❌ Error: Missing comma separator. Format: `/away Reason , MM/DD/YYYY HH.MM`")
    try:
        reason, time_str = [p.strip() for p in text.split(",", 1)]
        end_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
        if end_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ Error: Return time cannot be in the past.")
    except ValueError: 
        return await update.message.reply_text("❌ Error: Invalid date format. Use strict 24h format: `MM/DD/YYYY HH.MM` (e.g., `06/20/2026 14.30`)")

    username = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        try:
            await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3) ON CONFLICT (username) DO UPDATE SET reason=$2, end_time=$3, last_notified=NULL', username, reason, end_time)
        except Exception as e: return await update.message.reply_text(f"❌ DB Error: {e}")
    
    context.job_queue.run_once(auto_return_away, when=end_time, data=username, name=f"away_{username}")
    await update.message.reply_text(f"✅ @{username} is away until {end_time.strftime('%m/%d %H:%M WIB')}.")

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE): await process_return(context.job.data, context.bot)

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', update.effective_user.username)
        if not status: return await update.message.reply_text("❌ Error: You are not currently marked as Away.")
    await process_return(update.effective_user.username, context.bot, update.effective_chat.id)

async def process_return(username, bot, chat_id=None):
    pool = bot.application.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        mentions = await conn.fetch('SELECT mentioner, message, chat_title FROM away_mentions WHERE away_username=$1', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)

    msg = "👋 Welcome back! Here is what you missed:\n\n"
    if not mentions: msg += "No one mentioned you."
    else:
        for m in mentions: msg += f"🔹 **@{m['mentioner']}** in *{m['chat_title']}*:\n\"{m['message']}\"\n\n"
    try: 
        if chat_id: await bot.send_message(chat_id, f"Welcome back @{username}! I've wiped your away status.")
    except: pass

# --- GLOBAL TRACKER (Groups + Mentions) ---
async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
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
                    await update.message.reply_text(f"⚠️ @{a['username']} is away until {a['end_time'].strftime('%m/%d %H:%M WIB')}.\n(Reason: {a['reason']})")
                    await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])

# --- 3/ RAWWY STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Error: You must reply to the user's message to give a Star!")
    giver, receiver = update.effective_user.username, update.message.reply_to_message.from_user.username
    if giver == receiver: return await update.message.reply_text("❌ Error: You cannot give stars to yourself.")
    if update.message.reply_to_message.from_user.is_bot: return await update.message.reply_text("❌ Error: Bots cannot receive stars.")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
        giver_data = await conn.fetchrow('SELECT quota FROM kudos WHERE username=$1', giver)
        
        if giver_data['quota'] <= 0: return await update.message.reply_text("❌ Error: You have 0 RAWWY Stars left to give this week.")
            
        await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
        
    await update.message.reply_text(f"🌟 **RAWWY Star Awarded!**\n@{receiver} received a star from @{giver}!\nTotal RAWWY Stars: {score}")

async def my_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 @{user}, you have **{q} RAWWY Stars** left to give this week.")

async def check_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return await context.bot.send_message(update.effective_user.id, "❌ Error: Admin Only.")
    try: target = context.args[0].replace("@", "")
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: Use `/checkstars all` OR `/checkstars @user`")
    
    async with pool.acquire() as conn:
        if target.lower() == 'all':
            recs = await conn.fetch('SELECT username, quota, all_time_points FROM kudos')
            if not recs: return await context.bot.send_message(update.effective_user.id, "❌ Error: Database is empty.")
            msg = "🌟 **Team Stars Data**\n" + "\n".join([f"@{r['username']} - Quota: {r['quota']} | Total: {r['all_time_points']}" for r in recs])
        else:
            r = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
            if not r: return await context.bot.send_message(update.effective_user.id, "❌ Error: User not found in database.")
            msg = f"🌟 **@{target}**\nTotal: {r['all_time_points']} | Monthly: {r['monthly_points']} | Quota: {r['quota']}"
    try: await context.bot.send_message(update.effective_user.id, msg)
    except: await update.message.reply_text("❌ Error: Could not DM you.")

async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    
    text = " ".join(context.args)
    try:
        t, act, amt = [p.strip() for p in text.split(",", 2)]
        t = t.replace("@", ""); amt = int(amt)
        if act not in ["set_quota", "add_total", "sub_total"]: raise ValueError
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: `/admin_stars @user , set_quota/add_total/sub_total , amount`")

    async with pool.acquire() as conn:
        if act == "set_quota": await conn.execute('UPDATE kudos SET quota=$1 WHERE username=$2', amt, t)
        elif act == "add_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points+$1 WHERE username=$2', amt, t)
        elif act == "sub_total": await conn.execute('UPDATE kudos SET all_time_points=all_time_points-$1 WHERE username=$2', amt, t)
    await context.bot.send_message(update.effective_user.id, f"✅ RAWWY Stars updated for @{t}.")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        records = await conn.fetch('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 5')
    if not records: return await update.message.reply_text("📊 **Monthly Leaderboard**\nNo points given out yet!")
    await update.message.reply_text("📊 **Monthly Leaderboard**\n" + "\n".join([f"{i}. @{r['username']} - {r['monthly_points']} pts" for i, r in enumerate(records, 1)]), parse_mode="Markdown")

# --- 1/ EVENTS ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    try:
        title, t_str, rem = [p.strip() for p in text.split(",", 2)]
        e_time = WIB.localize(datetime.datetime.strptime(t_str, "%m/%d/%Y %H.%M"))
        if e_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ Error: Time cannot be in the past.")
        rem = int(rem)
    except: return await update.message.reply_text("❌ Error Format: `/newevent Title , MM/DD/YYYY HH.MM , RemMins`")

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by) VALUES ($1, $2, $3) RETURNING id', title, e_time, update.effective_user.username)
    
    kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not Going")]]
    if e_time - datetime.timedelta(minutes=rem) > datetime.datetime.now(WIB):
        context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_{e_id}")
    await update.message.reply_text(f"📅 **{title}**\n🕒 {e_time.strftime('%m/%d/%Y %H:%M')} WIB\n*RSVPs:*\nNo one yet.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    try:
        e_id, title, t_str, rem = [p.strip() for p in text.split(",", 3)]
        e_time = WIB.localize(datetime.datetime.strptime(t_str, "%m/%d/%Y %H.%M"))
        rem = int(rem)
    except: return await update.message.reply_text("❌ Error: `/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        if await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, int(e_id)) == "UPDATE 0": 
            return await update.message.reply_text("❌ Error: Event ID not found.")
            
    for job in context.job_queue.get_jobs_by_name(f"event_{e_id}"): job.schedule_removal()
    if e_time - datetime.timedelta(minutes=rem) > datetime.datetime.now(WIB):
        context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": int(e_id), "title": title}, name=f"event_{e_id}")
    await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: e_id = int(context.args[0])
    except: return await update.message.reply_text("❌ Error: Missing ID. `/cancelevent ID`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        if await conn.execute('DELETE FROM events WHERE id=$1', e_id) == "DELETE 0": 
            return await update.message.reply_text("❌ Error: Event ID not found.")
    for j in context.job_queue.get_jobs_by_name(f"event_{e_id}"): j.schedule_removal()
    await update.message.reply_text(f"🗑️ Event `{e_id}` cancelled globally.", parse_mode="Markdown")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    if not events: return await update.message.reply_text("No upcoming events!")
    await update.message.reply_text("📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, e_id, status = query.data.split("_")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status=$3', int(e_id), query.from_user.username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title, event_time FROM events WHERE id=$1', int(e_id))
    if not event: return await query.answer("Event no longer exists.")
    text = f"📅 **{event['title']}**\n🕒 {event['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB\n*RSVPs:*\n" + "".join([f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n" for r in all_rsvps])
    await query.edit_message_text(text=text, reply_markup=query.message.reply_markup, parse_mode="Markdown")
    await query.answer(f"Marked {status}!")

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    await context.bot.send_message(context.job.chat_id, f"⏰ **{context.job.data['title']}** starting soon!\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

# --- 7/ TASKS ---
async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    try:
        assignee, mins, desc = [p.strip() for p in text.split(",", 2)]
        assignee = assignee.replace("@", "")
        mins = int(mins)
        if mins < 1 or mins > 480: return await update.message.reply_text("❌ Error: Deadline must be between 1 and 480 minutes.")
    except: return await update.message.reply_text("❌ Error: `/assign @user , Mins , Task`")

    now = datetime.datetime.now(WIB)
    deadline = now + datetime.timedelta(minutes=mins)
    assigner = update.effective_user.username

    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', assignee, desc, deadline, assigner)

    context.job_queue.run_once(task_reminder, when=deadline - datetime.timedelta(seconds=(mins*60)*0.1), data={"assignee": assignee, "id": t_id}, chat_id=update.effective_chat.id)
    await update.message.reply_text(f"📋 **Task `{t_id}` to @{assignee}!**\n📝 {desc}\n⏳ Due: {deadline.strftime('%H:%M WIB')}", parse_mode="Markdown")

async def task_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed': 
        await context.bot.send_message(context.job.chat_id, f"⚠️ @{context.job.data['assignee']} - Task `{context.job.data['id']}` is almost due!")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: t_id = int(context.args[0])
    except: return await update.message.reply_text("❌ Error: Missing ID. `/complete ID`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assignee, status FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("❌ Error: Task not found.")
        if task['status'] == 'Completed': return await update.message.reply_text("❌ Error: Task already completed.")
        if task['assignee'] != update.effective_user.username: return await update.message.reply_text("❌ Error: Only the assigned user can complete this task.")
        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
    await update.message.reply_text(f"✅ Task `{t_id}` completed!", parse_mode="Markdown")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: t_id = int(context.args[0])
    except: return await update.message.reply_text("❌ Error: Missing ID. `/canceltask ID`")
    
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task: return await update.message.reply_text("❌ Error: Task not found.")
        if task['assigned_by'] != update.effective_user.username: return await update.message.reply_text("❌ Error: Only the person who assigned this task can cancel it.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await update.message.reply_text(f"🗑️ Task `{t_id}` cancelled.", parse_mode="Markdown")

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        tasks = await conn.fetch("SELECT id, task_desc, deadline FROM tasks WHERE status='Pending' AND assignee=$1 ORDER BY deadline", user)
    if not tasks: msg = "🎉 No pending tasks!"
    else:
        msg = "📋 **Your Active Tasks (Global)**\n\n"
        for t in tasks:
            rem = int((t['deadline'] - now).total_seconds() / 60)
            status = f"{rem}m left" if rem > 0 else "OVERDUE"
            msg += f"🔹 `{t['id']}` | {t['task_desc']} | ⏳ {status}\n"
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: await update.message.reply_text("❌ Error: Please start a DM with me to view your tasks.")

async def yearly_task_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: await conn.execute("TRUNCATE tasks RESTART IDENTITY;")
    logger.info("New Year Task Wipe Complete.")

# --- 4/ BIRTHDAYS ---
async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try:
        u, b = [p.strip() for p in " ".join(context.args).split(",")]
        datetime.datetime.strptime(b, "%m/%d")
    except: return await context.bot.send_message(update.effective_user.id, "❌ Error: `/addbday @user , MM/DD`")
    
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u.replace("@", ""), b)
    await context.bot.send_message(update.effective_user.id, f"🎂 Bday added for @{u}.")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn:
        bdays = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    if not bdays: return await context.bot.send_message(update.effective_user.id, "❌ No birthdays saved in database.")
    await context.bot.send_message(update.effective_user.id, "🎂 **Team Birthdays**\n" + "\n".join([f"• @{b['username']}: {b['bday']}" for b in bdays]), parse_mode="Markdown")

# --- 2/ POLLS & 5/ LIBRARY ---
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 4: raise ValueError
        if len(parts) > 12: return await update.message.reply_text("❌ Error: Maximum 10 options allowed.")
        duration = int(parts[1]) * 3600
    except: return await update.message.reply_text("❌ Error: `/poll Question , Hours , Opt1 , Opt2`")
    
    try:
        await context.bot.send_poll(chat_id=update.effective_chat.id, question=parts[0], options=parts[2:], is_anonymous=False, allows_multiple_answers=True, open_period=duration)
    except Exception as e: await update.message.reply_text(f"❌ API Error: {e}")

async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: n, c = [p.strip() for p in " ".join(context.args).split(",", 1)]
    except: return await update.message.reply_text("❌ Error: `/addlib Name , Link/Content`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO library (name, content, added_by) VALUES ($1, $2, $3) ON CONFLICT (name) DO UPDATE SET content=EXCLUDED.content, added_by=EXCLUDED.added_by', n.lower(), c, update.effective_user.username)
    await update.message.reply_text(f"✅ Saved **{n}**!", parse_mode="Markdown")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("❌ Error: Missing Name. `/getlib Name`")
    n = " ".join(context.args).strip().lower()
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT content, added_by FROM library WHERE name=$1', n)
    if not r: return await update.message.reply_text("❌ Error: Asset not found in database.")
    await update.message.reply_text(f"📂 **{n.title()}** (@{r['added_by']}):\n{r['content']}", parse_mode="Markdown")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT name FROM library ORDER BY name ASC')
    if not recs: return await update.message.reply_text("❌ Library is currently empty.")
    await update.message.reply_text("📚 **Library**\n" + "\n".join([f"• `{r['name']}`" for r in recs]), parse_mode="Markdown")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("❌ Error: Missing Name. `/dellib Name`")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        if await conn.execute('DELETE FROM library WHERE name=$1', " ".join(context.args).strip().lower()) == "DELETE 0": 
            return await update.message.reply_text("❌ Error: Asset not found.")
    await update.message.reply_text("🗑️ Deleted.")

# --- MAIN RUNNER ---
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

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_tracker))

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()