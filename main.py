import logging, datetime, pytz, os, asyncpg, random
from telegram import Update, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters, ContextTypes
from telegram.error import TelegramError

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL")
SUPER_OWNER = os.getenv("SUPER_OWNER", "AdminUsername").replace("@", "").lower()
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

async def is_super(username: str) -> bool: return username.lower() == SUPER_OWNER if username else False

async def is_bot_admin(username: str, pool) -> bool:
    if await is_super(username): return True
    if not username: return False
    async with pool.acquire() as conn:
        return bool(await conn.fetchrow('SELECT username FROM bot_admins WHERE username=$1', username.lower()))

async def delete_cmd(update: Update):
    if update.effective_chat.type != "private":
        try: await update.message.delete()
        except: pass

async def notify_admins(bot, pool, msg: str):
    async with pool.acquire() as conn:
        admins = await conn.fetch("SELECT username FROM bot_admins")
        for uname in {SUPER_OWNER} | {a['username'] for a in admins}:
            uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", uname)
            if uid:
                try: await bot.send_message(uid, msg, parse_mode="Markdown")
                except: pass

async def log_audit(pool, user_id: int, username: str, chat_id: int, action_type: str, detail: str, status: str):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO audit_logs (user_id, username, chat_id, action_type, detail, status) VALUES ($1, $2, $3, $4, $5, $6)", user_id, username, chat_id, action_type, detail, status)

def get_user_menu():
    return [
        BotCommand("event_create", "📅 Create an event"), BotCommand("event_list", "📅 View upcoming events"),
        BotCommand("clockin", "👥 Start attendance"), BotCommand("clockout", "👥 Submit attendance report"),
        BotCommand("birthday_list", "🎂 View birthday list"), BotCommand("poll", "🎲 Create a poll"),
        BotCommand("raffle", "🎲 Pick random winners"), BotCommand("mystar", "🌟 Stars earned this month"),
        BotCommand("myquota", "🌟 Star Quota left to give"), BotCommand("thanks", "🌟 (Reply) Send a Star"),
        BotCommand("library", "📚 Browse Library"), BotCommand("mytasks", "⚡ View your tasks"),
        BotCommand("away", "⚙️ Set away status"), BotCommand("back", "⚙️ Return to available status"),
        BotCommand("bugreport", "🐛 Report an issue")
    ]

def get_admin_menu():
    return get_user_menu() + [
        BotCommand("admin_groups", "🛠️ Manage active groups"), BotCommand("admin_broadcast", "🛠️ Broadcast announcement"),
        BotCommand("announcement_create", "🛠️ Draft announcement"), BotCommand("announcement_send", "🛠️ Push announcement"),
        BotCommand("birthday_add", "🛠️ Add a user birthday"), BotCommand("birthday_edit", "🛠️ Edit a user birthday"),
        BotCommand("auditlog", "🛠️ Manual diagnostic report"), BotCommand("systemstatus", "🛠️ Live system metrics"),
        BotCommand("admin_stars", "🛠️ Edit Stars"), BotCommand("checkquota", "🛠️ Audit Quotas"),
        BotCommand("grouptasks", "🛠️ View all tasks")
    ]

async def sync_menus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    if update.effective_chat.type == "private":
        menu = get_admin_menu() if await is_bot_admin(username, context.bot_data.get('db_pool')) else get_user_menu()
        await context.bot.set_my_commands(menu, scope=BotCommandScopeChat(chat_id=update.effective_chat.id))

async def init_db(app: Application):
    if not DATABASE_URL: return logger.error("DATABASE_URL missing!")
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT);
            CREATE TABLE IF NOT EXISTS bot_admins (username TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT, member_count INT, added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS birthdays (username TEXT PRIMARY KEY, bday TEXT);
            CREATE TABLE IF NOT EXISTS away_status (user_id BIGINT PRIMARY KEY, username TEXT, reason TEXT, end_time TIMESTAMP WITH TIME ZONE, last_notified TIMESTAMP WITH TIME ZONE);
            CREATE TABLE IF NOT EXISTS away_mentions (id SERIAL PRIMARY KEY, away_username TEXT, mentioner TEXT, message TEXT, chat_title TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS attendance (user_id BIGINT PRIMARY KEY, status TEXT, updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS kudos (username TEXT PRIMARY KEY, monthly_points INT DEFAULT 0, all_time_points INT DEFAULT 0, quota INT DEFAULT 3);
            CREATE TABLE IF NOT EXISTS library (name TEXT PRIMARY KEY, content TEXT NOT NULL, added_by TEXT, is_private BOOLEAN DEFAULT FALSE);
            CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_time TIMESTAMP WITH TIME ZONE NOT NULL, created_by TEXT, chat_id BIGINT, msg_id BIGINT);
            CREATE TABLE IF NOT EXISTS rsvps (event_id INTEGER REFERENCES events(id) ON DELETE CASCADE, username TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (event_id, username));
            CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, assignee TEXT NOT NULL, task_desc TEXT, status TEXT DEFAULT 'Pending', deadline TIMESTAMP WITH TIME ZONE, assigned_by TEXT);
            CREATE TABLE IF NOT EXISTS active_polls (chat_id BIGINT, user_id BIGINT, end_time TIMESTAMP WITH TIME ZONE, PRIMARY KEY(chat_id, user_id));
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS bot_stats (date DATE PRIMARY KEY, uses INT DEFAULT 0, errors INT DEFAULT 0);
            CREATE TABLE IF NOT EXISTS bug_reports (id SERIAL PRIMARY KEY, username TEXT, report TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS graveyard (username TEXT PRIMARY KEY, offboarded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), data_dump TEXT);
            CREATE TABLE IF NOT EXISTS audit_logs (id SERIAL PRIMARY KEY, user_id BIGINT, username TEXT, chat_id BIGINT, action_type TEXT, detail TEXT, status TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
    await app.bot.set_my_commands(get_user_menu(), scope=BotCommandScopeDefault())
    logger.info("✅ DB & Menus Configured.")

async def cron_daily_audit(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    yesterday = (now - datetime.timedelta(days=1)).date()
    start_dt, end_dt = WIB.localize(datetime.datetime.combine(yesterday, datetime.time.min)), WIB.localize(datetime.datetime.combine(yesterday, datetime.time.max))
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        groups_cnt = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
        stats = await conn.fetchrow("""SELECT COUNT(CASE WHEN action_type = 'Clock In' THEN 1 END) as clock_in_cnt, COUNT(CASE WHEN action_type = 'Clock Out' THEN 1 END) as clock_out_cnt, COUNT(CASE WHEN action_type = 'Away' THEN 1 END) as away_cnt, COUNT(CASE WHEN action_type = 'Back' THEN 1 END) as back_cnt, COUNT(CASE WHEN action_type = 'Event Create' THEN 1 END) as evt_create_cnt, COUNT(CASE WHEN action_type = 'RSVP' THEN 1 END) as rsvp_cnt, COUNT(CASE WHEN action_type = 'Announcement' AND status = 'Success' THEN 1 END) as ann_sent, COUNT(CASE WHEN action_type = 'Announcement' AND status = 'Failed' THEN 1 END) as ann_fail, COUNT(CASE WHEN status = 'Failed' THEN 1 END) as err_cnt FROM audit_logs WHERE created_at >= $1 AND created_at <= $2""", start_dt, end_dt)
        top_users = await conn.fetch("SELECT username, COUNT(*) as activity FROM audit_logs WHERE created_at >= $1 AND created_at <= $2 AND username IS NOT NULL GROUP BY username ORDER BY activity DESC LIMIT 3", start_dt, end_dt)
    msg = f"🌅 **Daily Diagnostic Report**\nDate: {yesterday.strftime('%d/%m/%Y')}\n\n**Groups:**\n• Active Groups: {groups_cnt}\n\n**Users:**\n• Clock In: {stats['clock_in_cnt']}\n• Clock Out: {stats['clock_out_cnt']}\n• Away: {stats['away_cnt']}\n• Back: {stats['back_cnt']}\n\n**Events:**\n• Created: {stats['evt_create_cnt']}\n• RSVPs: {stats['rsvp_cnt']}\n\n**Announcements:**\n• Sent: {stats['ann_sent']}\n• Failed: {stats['ann_fail']}\n\n**System:**\n• Errors/Warnings: {stats['err_cnt']}\n\n**Top Active Users:**\n"
    for i, u in enumerate(top_users, 1): msg += f"{i}. @{u['username']} ({u['activity']} actions)\n"
    await notify_admins(context.bot, pool, msg)

async def monthly_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    if now.day != 1: return 
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        top = await conn.fetchrow('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 1')
        if top:
            msg = f"🏆 **Best star earner this month is @{top['username']}!** 🏆\nTotal **{top['monthly_points']} RAWWY Stars** earned. Incredible work! 🌟"
            for g in await conn.fetch('SELECT chat_id FROM active_groups'):
                try: await context.bot.send_message(g['chat_id'], msg, parse_mode="Markdown")
                except: pass
        await conn.execute("UPDATE kudos SET monthly_points = 0")

async def weekly_quota_reset(context: ContextTypes.DEFAULT_TYPE):
    async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute("UPDATE kudos SET quota = 3")

async def daily_bday_announcement(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT username FROM birthdays WHERE bday=$1", datetime.datetime.now(WIB).strftime("%m/%d"))
        t_group = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'")
    if users and t_group:
        msg = "🎉🎂 **HAPPY BIRTHDAY!** 🎂🎉\nPlease join me in sending the warmest wishes to:\n" + "\n".join([f"🎈 @{u['username']}" for u in users])
        try: await context.bot.send_message(int(t_group), msg, parse_mode="Markdown")
        except: pass

async def poll_cleanup(context: ContextTypes.DEFAULT_TYPE):
    async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute("DELETE FROM active_polls WHERE end_time < NOW()")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_menus(update, context)
    await update.message.reply_text("🤖 **System Online.** Use the menu to navigate features.", parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_menus(update, context)
    await update.message.reply_text("🚀 **Workspace Guide**\nUse the dynamic `/` menu to browse all tools.", parse_mode="Markdown")

async def cmd_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, username = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        args = " ".join(context.args).rsplit(",", 1)
        if len(args) < 2: raise ValueError
        reason, end_time = args[0].strip(), WIB.localize(datetime.datetime.strptime(args[1].strip(), "%m/%d/%Y %H.%M"))
        if end_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ Time is in the past!")
        async with pool.acquire() as conn: await conn.execute('INSERT INTO away_status (user_id, username, reason, end_time) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO UPDATE SET reason=$3, end_time=$4', user_id, username, reason, end_time)
        await update.message.reply_text(f"⚙️ Marked Away until {end_time.strftime('%H:%M WIB')}. Reason: {reason}")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Away", reason, "Success")
    except:
        await update.message.reply_text("❌ Format: `/away Reason, MM/DD/YYYY HH.MM`")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Away", "Format Error", "Failed")

async def cmd_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, username = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            mentions = await conn.fetch('SELECT mentioner, message, chat_title, created_at FROM away_mentions WHERE away_username=$1 ORDER BY created_at ASC', username)
            if await conn.execute('DELETE FROM away_status WHERE user_id=$1', user_id) == "DELETE 0":
                return await update.message.reply_text("You are already Available.")
            await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
        msg = "✅ You are now marked as Available.\n\n"
        if mentions: msg += "Here are the mentions you missed:\n" + "".join([f"🔹 [{m['created_at'].astimezone(WIB).strftime('%m/%d %H:%M')}] in {m['chat_title']}\n**@{m['mentioner']}**: {m['message']}\n" for m in mentions])
        await update.message.reply_text(msg, parse_mode="Markdown")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Back", "Returned", "Success")
    except Exception as e: await update.message.reply_text("❌ Error updating status.")

async def cmd_clockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool, uid, uname = context.bot_data.get('db_pool'), update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    try:
        async with pool.acquire() as conn: await conn.execute('INSERT INTO attendance (user_id, status, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET status=$2, updated_at=NOW()', uid, 'Clocked In')
        await update.message.reply_text("✅ Clock In successful.")
        await log_audit(pool, uid, uname, update.effective_chat.id, "Clock In", "User clocked in", "Success")
    except: await update.message.reply_text("❌ Failed to clock in.")

async def cmd_clockout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool, uid, uname = context.bot_data.get('db_pool'), update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    try:
        async with pool.acquire() as conn: await conn.execute('INSERT INTO attendance (user_id, status, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET status=$2, updated_at=NOW()', uid, 'Clocked Out')
        await update.message.reply_text("✅ Clock Out successful.")
        await log_audit(pool, uid, uname, update.effective_chat.id, "Clock Out", "User clocked out", "Success")
    except: await update.message.reply_text("❌ Failed to clock out.")

async def cmd_birthday_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        t_uname, bday_str = parts[0].replace("@", ""), parts[1]
        datetime.datetime.strptime(bday_str, "%d/%m")
        async with pool.acquire() as conn:
            if await conn.fetchval('SELECT 1 FROM birthdays WHERE username=$1', t_uname):
                return await context.bot.send_message(uid, "❌ Birthday already exists. Use `/editbday`.", parse_mode="Markdown")
            await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', t_uname, bday_str)
        await context.bot.send_message(uid, f"✅ Birthday added for @{t_uname}.")
        await log_audit(pool, uid, uname, update.effective_chat.id, "Birthday Add", f"Added {t_uname}", "Success")
    except: await context.bot.send_message(uid, "❌ Format error. Try: `/addbday @user, DD/MM`", parse_mode="Markdown")

async def cmd_birthday_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        t_uname, bday_str = parts[0].replace("@", ""), parts[1]
        datetime.datetime.strptime(bday_str, "%d/%m")
        async with pool.acquire() as conn:
            if await conn.execute('UPDATE birthdays SET bday=$1 WHERE username=$2', bday_str, t_uname) == "UPDATE 0":
                return await context.bot.send_message(uid, "❌ User not found.")
        await context.bot.send_message(uid, f"✅ Birthday updated for @{t_uname}.")
        await log_audit(pool, uid, uname, update.effective_chat.id, "Birthday Edit", f"Edited {t_uname}", "Success")
    except: await context.bot.send_message(uid, "❌ Format error: `/editbday @user, DD/MM`", parse_mode="Markdown")

async def cmd_birthday_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with context.bot_data.get('db_pool').acquire() as conn: bdays = await conn.fetch("SELECT username, bday FROM birthdays ORDER BY bday ASC")
    await update.message.reply_text("🎂 **Birthdays:**\n" + "\n".join([f"• @{b['username']}: {b['bday']}" for b in bdays]) if bdays else "📅 No birthdays recorded.", parse_mode="Markdown")

async def cmd_setbdaychannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private": return await update.message.reply_text("❌ Run this in the target group.")
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute("INSERT INTO config (key, value) VALUES ('bday_channel', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(update.effective_chat.id))
    await update.message.reply_text("✅ This group is now the Birthday channel.")

async def cmd_announcement_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    if not context.args: return await update.message.reply_text("❌ Provide text.")
    context.bot_data['draft_announcement'] = " ".join(context.args)
    await update.message.reply_text("✅ Announcement drafted. Use `/announcement_send` to broadcast.", parse_mode="Markdown")

async def cmd_announcement_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    draft = context.bot_data.get('draft_announcement')
    if not draft: return await update.message.reply_text("❌ No draft found.")
    async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
    success, fail = 0, 0
    for g in groups:
        try:
            await context.bot.send_message(g['chat_id'], f"📢 **Announcement**\n\n{draft}", parse_mode="Markdown")
            success += 1
            await log_audit(pool, uid, uname, g['chat_id'], "Announcement", f"Sent to {g['title']}", "Success")
        except: fail += 1
    await update.message.reply_text(f"✅ Announcement sent to {success} groups. ({fail} failed).")

async def cmd_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    try:
        target, msg = [p.strip() for p in " ".join(context.args).split(",", 1)]
        async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target), "title": "Target"}]
        success = 0
        for g in groups:
            try:
                await context.bot.send_message(g['chat_id'], f"📢 **Broadcast**\n\n{msg}", parse_mode="Markdown")
                success += 1
                await log_audit(pool, uid, uname, g['chat_id'], "Broadcast", f"Sent to {g['title']}", "Success")
            except: pass
        await update.message.reply_text(f"✅ Broadcast sent successfully to {success} groups.")
    except: await update.message.reply_text("❌ Format: `/admin_broadcast [ChatID|All], Message`")

async def cmd_event_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        parts = [p.strip() for p in " ".join(context.args).rsplit(",", 2)]
        title, e_time, rem = parts[0], WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H.%M")), int(parts[2])
        if e_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ Cannot schedule in the past.")
        kb = [[InlineKeyboardButton("✅ Going", callback_data="rsvp_temp_Going"), InlineKeyboardButton("❌ Not Going", callback_data="rsvp_temp_Not Going")]]
        msg = await update.message.reply_text(f"📅 **{title} scheduled!**\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\nNo RSVPs yet.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        try: await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
        except: pass
        async with pool.acquire() as conn: e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by, chat_id, msg_id) VALUES ($1, $2, $3, $4, $5) RETURNING id', title, e_time, uname, update.effective_chat.id, msg.message_id)
        await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not Going")]]))
        await log_audit(pool, update.effective_user.id, uname, update.effective_chat.id, "Event Create", title, "Success")
    except: await update.message.reply_text("❌ Format: `/event_create Title, MM/DD/YYYY HH.MM, RemMins`", parse_mode="Markdown")

async def cmd_event_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with context.bot_data.get('db_pool').acquire() as conn: events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
    await update.message.reply_text("📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]) if events else "📅 No upcoming events.", parse_mode="Markdown")

async def cmd_cancelevent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    try:
        e_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
        async with pool.acquire() as conn:
            ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
            if not ev: return await context.bot.send_message(uid, "❌ Event not found.")
            await conn.execute('DELETE FROM events WHERE id=$1', e_id)
        try: await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
        except: pass
        await context.bot.send_message(uid, "✅ Event cancelled.")
        await log_audit(pool, uid, uname, update.effective_chat.id, "Event Cancel", f"ID {e_id}", "Success")
    except: await context.bot.send_message(uid, "❌ Usage: `/cancelevent ID`")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if "temp" in q.data: return await q.answer("Initializing...")
    _, e_id, status = q.data.split("_")
    uname = q.from_user.username or str(q.from_user.id)
    async with context.bot_data.get('db_pool').acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status=$3', int(e_id), uname, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title, event_time FROM events WHERE id=$1', int(e_id))
    if not event: return await q.answer("Event deleted.")
    text = f"📅 **{event['title']}**\n🕒 {event['event_time'].astimezone(WIB).strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\n" + "".join([f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n" for r in all_rsvps])
    await q.edit_message_text(text, reply_markup=q.message.reply_markup, parse_mode="Markdown")
    await q.answer(status)

async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        dur = int(parts[1]) * 3600
        await context.bot.send_poll(update.effective_chat.id, parts[0], parts[2:], is_anonymous=False, allows_multiple_answers=True, open_period=dur)
    except: await update.message.reply_text("❌ Format: `/poll Question, Hours, Opt1, Opt2`")

async def cmd_raffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with context.bot_data.get('db_pool').acquire() as conn: users = await conn.fetch("SELECT username FROM users WHERE username IS NOT NULL")
    if not users: return await update.message.reply_text("❌ No users available.")
    await update.message.reply_text(f"🎲 Raffle Winner: @{random.choice(users)['username']}!")

async def cmd_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a message to send a Star.")
    giver, receiver = update.effective_user.username or str(update.effective_user.id), update.message.reply_to_message.from_user.username or str(update.message.reply_to_message.from_user.id)
    if update.message.reply_to_message.from_user.is_bot or giver == receiver: return await update.message.reply_text("❌ Invalid target.")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
        if await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver) <= 0: return await update.message.reply_text("❌ Star Quota depleted.")
        await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
    await update.message.reply_text(f"🌟 **Star Sent!** @{receiver} now has {score} total Stars.", parse_mode="Markdown")

async def cmd_myquota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    async with context.bot_data.get('db_pool').acquire() as conn:
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"🌟 You have **{q} Star Quota** left.", parse_mode="Markdown")

async def cmd_mystar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with context.bot_data.get('db_pool').acquire() as conn: pts = await conn.fetchval('SELECT monthly_points FROM kudos WHERE username=$1', update.effective_user.username or str(update.effective_user.id))
    await update.message.reply_text(f"🌟 You have **{pts or 0} RAWWY Stars** this month.", parse_mode="Markdown")

async def cmd_totalstar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with context.bot_data.get('db_pool').acquire() as conn: pts = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', update.effective_user.username or str(update.effective_user.id))
    await update.message.reply_text(f"🌟 You have **{pts or 0} RAWWY Stars** all-time.", parse_mode="Markdown")

async def cmd_checkquota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    target = " ".join(context.args).replace("@", "").strip()
    if not target: return await context.bot.send_message(update.effective_user.id, "❌ Usage: `/checkquota all` or `@user`")
    async with context.bot_data.get('db_pool').acquire() as conn:
        if target.lower() == 'all':
            recs = await conn.fetch('SELECT username, quota, monthly_points, all_time_points FROM kudos')
            msg = "🌟 **Team Stars**\n" + "\n".join([f"@{r['username']} - Q: {r['quota']} | M: {r['monthly_points']}" for r in recs]) if recs else "No records."
        else:
            r = await conn.fetchrow('SELECT monthly_points, all_time_points, quota FROM kudos WHERE username=$1', target)
            msg = f"🌟 **@{target}**\nQuota left: {r['quota']}\nMonthly: {r['monthly_points']}" if r else "User not found."
    await context.bot.send_message(update.effective_user.id, msg)

async def cmd_admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 3)]
        t, field, act, amt = parts[0].replace("@", ""), parts[1].lower(), parts[2].lower(), int(parts[3])
        col = 'monthly_points' if field == 'monthly' else 'all_time_points' if field == 'total' else 'quota'
        async with pool.acquire() as conn:
            await conn.execute(f'INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
            if act == "set": await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, t)
            elif act == "add": await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, t)
            elif act == "sub": await conn.execute(f'UPDATE kudos SET {col}={col}-$1 WHERE username=$2', amt, t)
        await context.bot.send_message(uid, f"✅ Updated stars for @{t}.")
    except: await context.bot.send_message(uid, "❌ Usage: `/admin_stars @user, quota/monthly/total, set/add/sub, Amt`")

async def cmd_addlib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        raw = " ".join(context.args)
        is_private = raw.lower().endswith(", private")
        if is_private: raw, _ = raw.rsplit(",", 1)
        name, content = [p.strip() for p in raw.split(",", 1)]
        async with context.bot_data.get('db_pool').acquire() as conn:
            if await conn.fetchval('SELECT name FROM library WHERE name=$1', name.lower()): return await update.message.reply_text("❌ Name exists.")
            await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4)', name.lower(), content, update.effective_user.username or str(update.effective_user.id), is_private)
        await context.bot.send_message(update.effective_user.id if is_private else update.effective_chat.id, f"✅ Asset '{name}' added.", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Format: `/addlib Name, Content, [private]`")

async def cmd_editlib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.effective_user.username or str(update.effective_user.id)
    try:
        name, content = [p.strip() for p in " ".join(context.args).split(",", 1)]
        async with context.bot_data.get('db_pool').acquire() as conn:
            if await conn.execute('UPDATE library SET content=$1 WHERE name=$2 AND (added_by=$3 OR EXISTS(SELECT 1 FROM bot_admins WHERE username=$3))', content, name.lower(), uname) == "UPDATE 0":
                return await update.message.reply_text("❌ Not found or permission denied.")
        await update.message.reply_text(f"✅ Asset updated.")
    except: await update.message.reply_text("❌ Format: `/editlib Name, Content`")

async def cmd_getlib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.effective_user.username or str(update.effective_user.id)
    try:
        name = [p.strip() for p in " ".join(context.args).split(",")][0].lower()
        async with context.bot_data.get('db_pool').acquire() as conn: r = await conn.fetchrow('SELECT content, is_private, added_by FROM library WHERE name=$1', name)
        if not r: return await update.message.reply_text("❌ Not found.")
        if r['is_private'] and r['added_by'] != uname: return await context.bot.send_message(update.effective_user.id, "❌ Private file.")
        await context.bot.send_message(update.effective_user.id if r['is_private'] else update.effective_chat.id, f"📂 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Usage: `/getlib Name`")

async def cmd_dellib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    try:
        name = [p.strip() for p in " ".join(context.args).split(",")][0].lower()
        async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute('DELETE FROM library WHERE name=$1', name)
        await context.bot.send_message(update.effective_user.id, f"✅ Asset '{name}' deleted.")
    except: pass

async def cmd_library(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.effective_user.username or str(update.effective_user.id)
    async with context.bot_data.get('db_pool').acquire() as conn: recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
    msg = "📚 **Library**\n" + "\n".join([f"• {'🔒' if r['is_private'] else '📂'} `{r['name']}`" for r in recs if not r['is_private'] or r['added_by'] == uname]) if recs else "📚 Empty."
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assigner = update.effective_user.username or str(update.effective_user.id)
    try: 
        a, m, d = [p.strip() for p in " ".join(context.args).rsplit(",", 2)]
        dl = datetime.datetime.now(WIB) + datetime.timedelta(minutes=int(m))
        async with context.bot_data.get('db_pool').acquire() as conn: t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', a.replace("@", ""), d, dl, assigner)
        await update.message.reply_text(f"📋 **Task {t_id} Assigned!**\nTo: @{a}\n📝 {d}\n⏳ Deadline: {dl.strftime('%H:%M WIB')}", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Format: `/assign @user, Minutes, Task description`")

async def cmd_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.effective_user.username or str(update.effective_user.id)
    try:
        t_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
        async with context.bot_data.get('db_pool').acquire() as conn:
            if await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1 AND assignee=$2", t_id, uname) == "UPDATE 0": return await update.message.reply_text("❌ Task not found or permission denied.")
        await update.message.reply_text(f"✅ Task `{t_id}` completed.", parse_mode="Markdown")
    except: await update.message.reply_text("❌ Format: `/complete ID`")

async def cmd_canceltask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uname = update.effective_user.username or str(update.effective_user.id)
    if not await is_bot_admin(uname, context.bot_data.get('db_pool')): return
    try:
        t_id = int([p.strip() for p in " ".join(context.args).split(",")][0])
        async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
        await context.bot.send_message(update.effective_user.id, "🗑️ Task cancelled.")
    except: pass

async def cmd_mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.effective_user.username or str(update.effective_user.id)
    async with context.bot_data.get('db_pool').acquire() as conn: tasks = await conn.fetch("SELECT id, task_desc FROM tasks WHERE status='Pending' AND assignee=$1", uname)
    await update.message.reply_text("📋 **Your Tasks**\n" + "\n".join([f"🔹 `{t['id']}` | {t['task_desc']}" for t in tasks]) if tasks else "🎉 No pending tasks!", parse_mode="Markdown")

async def cmd_grouptasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    async with context.bot_data.get('db_pool').acquire() as conn: tasks = await conn.fetch("SELECT id, assignee, task_desc FROM tasks WHERE status='Pending'")
    msg = "📋 **Global Tasks**\n" + "\n".join([f"🔹 `{t['id']}` | @{t['assignee']} | {t['task_desc']}" for t in tasks]) if tasks else "🎉 Zero pending tasks."
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: pass

async def cmd_admin_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    async with context.bot_data.get('db_pool').acquire() as conn: groups = await conn.fetch("SELECT chat_id, title, member_count FROM active_groups")
    msg = "📊 **Active Groups:**\n" + "\n".join([f"• `{g['chat_id']}` | {g['title']} ({g['member_count'] or 0} members)" for g in groups]) if groups else "No groups."
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: pass

async def cmd_groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text(f"📌 **Group Info**\nTitle: `{update.effective_chat.title}`\nID: `{update.effective_chat.id}`", parse_mode="Markdown")
    else:
        async with context.bot_data.get('db_pool').acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
        msg = "📈 **Tracked Groups:**\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups]) if groups else "No groups."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def cmd_systemstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    async with context.bot_data.get('db_pool').acquire() as conn:
        g, u, a = await conn.fetchval("SELECT COUNT(*) FROM active_groups"), await conn.fetchval("SELECT COUNT(*) FROM users"), await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
    await update.message.reply_text(f"⚙️ **Live Metrics:**\n• Groups: {g}\n• Users: {u}\n• Logs: {a}", parse_mode="Markdown")

async def cmd_auditlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    uid, uname = update.effective_user.id, update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(uname, pool): return
    now = datetime.datetime.now(WIB)
    start_dt = WIB.localize(datetime.datetime.combine(now.date(), datetime.time.min))
    async with pool.acquire() as conn:
        stats = await conn.fetchrow("SELECT COUNT(CASE WHEN action_type='Clock In' THEN 1 END) as clkin, COUNT(CASE WHEN action_type='Away' THEN 1 END) as awy, COUNT(CASE WHEN status='Failed' THEN 1 END) as err FROM audit_logs WHERE created_at >= $1", start_dt)
    msg = f"🌅 **Audit Log (Today)**\n• Clock Ins: {stats['clkin']}\n• Aways: {stats['awy']}\n• Errors: {stats['err']}"
    await context.bot.send_message(uid, msg, parse_mode="Markdown")

async def cmd_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_bot_admin(update.effective_user.username, context.bot_data.get('db_pool')): return
    async with context.bot_data.get('db_pool').acquire() as conn: aways = await conn.fetch('SELECT username, end_time FROM away_status')
    msg = "🔴 **AWAY:**\n" + "\n".join([f"• @{a['username']}" for a in aways]) if aways else "🟢 Everyone is Available."
    try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except: pass

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result: return
    chat, status, pool = result.chat, result.new_chat_member.status, context.bot_data.get('db_pool')
    if status in ['member', 'administrator']:
        inviter = result.from_user.username or str(result.from_user.id)
        if not await is_bot_admin(inviter, pool): return await context.bot.leave_chat(chat.id)
        try: member_count = await chat.get_member_count()
        except: member_count = 0
        async with pool.acquire() as conn: await conn.execute('INSERT INTO active_groups (chat_id, title, member_count) VALUES ($1, $2, $3) ON CONFLICT (chat_id) DO UPDATE SET title=$2, member_count=$3', chat.id, chat.title, member_count)
        await notify_admins(context.bot, pool, f"✅ **Bot Joined Group**\nName: `{chat.title}`\nID: `{chat.id}`\nMembers: {member_count}")
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn: await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)
        await notify_admins(context.bot, pool, f"⚠️ **Bot Left Group**\nName: `{chat.title}`\nID: `{chat.id}`")

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    pool, uid, uname, now = context.bot_data.get('db_pool'), update.effective_user.id, update.effective_user.username or str(update.effective_user.id), datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username=$2", uid, uname)
        if update.effective_chat.type in ['group', 'supergroup']:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO NOTHING', update.effective_chat.id, update.effective_chat.title)

async def cmd_bugreport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: return await update.message.reply_text("Please type: `/bugreport [issue]`")
    async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", update.effective_user.username, text)
    await update.message.reply_text("🐛 Bug securely filed.")

async def super_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    try:
        target = context.args[0].replace("@", "").lower()
        async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
        await update.message.reply_text(f"✅ @{target} promoted.")
    except: pass

async def super_deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    try:
        target = context.args[0].replace("@", "").lower()
        async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
        await update.message.reply_text(f"🗑️ @{target} demoted.")
    except: pass

async def super_listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    async with context.bot_data.get('db_pool').acquire() as conn: admins = await conn.fetch('SELECT username FROM bot_admins')
    await update.message.reply_text("👑 **Admins:**\n" + "\n".join([f"• @{a['username']}" for a in admins]))

async def super_removemember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    try:
        target = context.args[0].replace("@", "")
        async with context.bot_data.get('db_pool').acquire() as conn:
            k = await conn.fetchrow("SELECT all_time_points FROM kudos WHERE username=$1", target)
            await conn.execute("INSERT INTO graveyard (username, data_dump) VALUES ($1, $2)", target, f"Stars: {k['all_time_points'] if k else 0}")
            await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
            await conn.execute('DELETE FROM kudos WHERE username=$1', target)
        await update.message.reply_text(f"🪦 @{target} offboarded.")
    except: pass

async def super_graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    async with context.bot_data.get('db_pool').acquire() as conn: gy = await conn.fetch('SELECT * FROM graveyard')
    await update.message.reply_text("🪦 **Graveyard**\n" + "\n".join([f"• @{g['username']}" for g in gy]) if gy else "Empty.")

async def super_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username): return
    async with context.bot_data.get('db_pool').acquire() as conn: await conn.execute("TRUNCATE kudos, tasks, library, events, rsvps, away_status, away_mentions CASCADE")
    await update.message.reply_text("☢️ Factory wipe complete.")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception handled:", exc_info=context.error)
    if context.bot_data.get('db_pool'):
        try:
            async with context.bot_data.get('db_pool').acquire() as conn:
                await conn.execute("INSERT INTO bot_stats (date, errors) VALUES (CURRENT_DATE, 1) ON CONFLICT (date) DO UPDATE SET errors = bot_stats.errors + 1")
        except: pass

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db
    app.add_error_handler(error_handler)

    app.job_queue.run_daily(cron_daily_audit, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(monthly_leaderboard, datetime.time(hour=13, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(weekly_quota_reset, datetime.time(hour=0, minute=0, tzinfo=WIB), days=(0,))
    app.job_queue.run_daily(daily_bday_announcement, datetime.time(hour=10, minute=0, tzinfo=WIB))
    app.job_queue.run_repeating(poll_cleanup, interval=3600)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clockin", cmd_clockin))
    app.add_handler(CommandHandler("clockout", cmd_clockout))
    app.add_handler(CommandHandler("away", cmd_away))
    app.add_handler(CommandHandler("back", cmd_back))
    
    app.add_handler(CommandHandler("birthday_add", cmd_birthday_add))
    app.add_handler(CommandHandler("birthday_edit", cmd_birthday_edit))
    app.add_handler(CommandHandler("birthday_list", cmd_birthday_list))
    app.add_handler(CommandHandler("setbdaychannel", cmd_setbdaychannel))
    app.add_handler(CommandHandler("addbday", cmd_birthday_add)) 
    app.add_handler(CommandHandler("editbday", cmd_birthday_edit)) 
    
    app.add_handler(CommandHandler("thanks", cmd_thanks))
    app.add_handler(CommandHandler("myquota", cmd_myquota))
    app.add_handler(CommandHandler("mystar", cmd_mystar))
    app.add_handler(CommandHandler("totalstar", cmd_totalstar))
    app.add_handler(CommandHandler("checkquota", cmd_checkquota))
    app.add_handler(CommandHandler("admin_stars", cmd_admin_stars))
    
    app.add_handler(CommandHandler("event_create", cmd_event_create))
    app.add_handler(CommandHandler("newevent", cmd_event_create)) 
    app.add_handler(CommandHandler("event_list", cmd_event_list))
    app.add_handler(CommandHandler("events", cmd_event_list)) 
    app.add_handler(CommandHandler("cancelevent", cmd_cancelevent))
    
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("raffle", cmd_raffle))
    
    app.add_handler(CommandHandler("addlib", cmd_addlib))
    app.add_handler(CommandHandler("editlib", cmd_editlib))
    app.add_handler(CommandHandler("getlib", cmd_getlib))
    app.add_handler(CommandHandler("dellib", cmd_dellib))
    app.add_handler(CommandHandler("library", cmd_library))
    
    app.add_handler(CommandHandler("assign", cmd_assign))
    app.add_handler(CommandHandler("complete", cmd_complete))
    app.add_handler(CommandHandler("mytasks", cmd_mytasks))
    app.add_handler(CommandHandler("canceltask", cmd_canceltask))
    app.add_handler(CommandHandler("grouptasks", cmd_grouptasks))
    
    app.add_handler(CommandHandler("announcement_create", cmd_announcement_create))
    app.add_handler(CommandHandler("announcement_send", cmd_announcement_send))
    app.add_handler(CommandHandler("admin_broadcast", cmd_admin_broadcast))
    app.add_handler(CommandHandler("announce", cmd_admin_broadcast)) 
    app.add_handler(CommandHandler("admin_groups", cmd_admin_groups))
    app.add_handler(CommandHandler("groupid", cmd_groupid))
    app.add_handler(CommandHandler("systemstatus", cmd_systemstatus))
    app.add_handler(CommandHandler("auditlog", cmd_auditlog))
    app.add_handler(CommandHandler("getlog", cmd_auditlog)) 
    app.add_handler(CommandHandler("attendance", cmd_attendance))
    
    app.add_handler(CommandHandler("addadmin", super_addadmin))
    app.add_handler(CommandHandler("deladmin", super_deladmin))
    app.add_handler(CommandHandler("listadmins", super_listadmins))
    app.add_handler(CommandHandler("removemember", super_removemember))
    app.add_handler(CommandHandler("graveyard", super_graveyard))
    app.add_handler(CommandHandler("super_reset", super_reset))
    
    app.add_handler(CommandHandler("bugreport", cmd_bugreport))

    app.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_tracker))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logger.info("Starting Enterprise Audit System...")
    app.run_polling()

if __name__ == "__main__":
    main()
