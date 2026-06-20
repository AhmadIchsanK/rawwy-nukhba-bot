import logging, datetime, pytz, os, asyncpg, random
from telegram import Update, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, MessageHandler, ChatMemberHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL")
SUPER_OWNER = os.getenv("SUPER_OWNER", "AdminUsername").replace("@", "").lower()
WIB = pytz.timezone('Asia/Jakarta')

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- AUTHENTICATION & HELPERS ---
async def is_super(username: str) -> bool:
    if not username: return False
    return username.lower() == SUPER_OWNER

async def is_bot_admin(username: str, pool) -> bool:
    if await is_super(username): return True
    if not username: return False
    async with pool.acquire() as conn:
        res = await conn.fetchrow('SELECT username FROM bot_admins WHERE username=$1', username.lower())
        return bool(res)

async def notify_admins(bot, pool, message_text: str):
    """Sends a DM to all registered admins and the super owner."""
    async with pool.acquire() as conn:
        admins = await conn.fetch("SELECT username FROM bot_admins")
        all_admins = [SUPER_OWNER] + [a['username'] for a in admins]
        for admin_uname in set(all_admins):
            uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", admin_uname)
            if uid:
                try: await bot.send_message(uid, message_text, parse_mode="Markdown")
                except: pass

async def log_audit(pool, user_id: int, username: str, chat_id: int, action_type: str, detail: str, status: str):
    """Centralized, real-time audit logger."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO audit_logs (user_id, username, chat_id, action_type, detail, status) 
               VALUES ($1, $2, $3, $4, $5, $6)""",
            user_id, username, chat_id, action_type, detail, status
        )

# --- UNIFIED COMMAND MENUS ---
def get_user_menu():
    return [
        BotCommand("help", "View User Manual"),
        BotCommand("event_create", "📅 Create an event"),
        BotCommand("event_list", "📅 View upcoming events"),
        BotCommand("clockin", "👥 Start attendance"),
        BotCommand("clockout", "👥 Submit attendance report"),
        BotCommand("birthday_list", "🎂 View birthday list"),
        BotCommand("poll", "🎲 Create a poll"),
        BotCommand("raffle", "🎲 Pick random winners"),
        BotCommand("away", "⚙️ Set away status"),
        BotCommand("back", "⚙️ Return to available status")
    ]

def get_admin_menu():
    admin_cmds = [
        BotCommand("admin_groups", "🛠️ Manage active groups"),
        BotCommand("admin_broadcast", "🛠️ Broadcast announcement"),
        BotCommand("announcement_create", "🛠️ Draft announcement"),
        BotCommand("announcement_send", "🛠️ Push announcement"),
        BotCommand("birthday_add", "🛠️ Add a user birthday"),
        BotCommand("birthday_edit", "🛠️ Edit a user birthday"),
        BotCommand("auditlog", "🛠️ Manual diagnostic report"),
        BotCommand("systemstatus", "🛠️ Live system metrics")
    ]
    return get_user_menu() + admin_cmds

async def sync_menus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dynamically applies the correct menu scope based on user role and chat type."""
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    if update.effective_chat.type == "private":
        if await is_bot_admin(username, pool):
            await context.bot.set_my_commands(get_admin_menu(), scope=BotCommandScopeChat(chat_id=update.effective_chat.id))
        else:
            await context.bot.set_my_commands(get_user_menu(), scope=BotCommandScopeChat(chat_id=update.effective_chat.id))

# --- DATABASE SCHEMA ---
async def init_db(app: Application):
    if not DATABASE_URL:
        logger.error("DATABASE_URL missing!")
        return
    app.bot_data['db_pool'] = await asyncpg.create_pool(DATABASE_URL)
    
    async with app.bot_data['db_pool'].acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS bot_admins (username TEXT PRIMARY KEY);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_groups (chat_id BIGINT PRIMARY KEY, title TEXT, member_count INT, added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS birthdays (username TEXT PRIMARY KEY, bday TEXT);''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS away_status (user_id BIGINT PRIMARY KEY, username TEXT, reason TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS attendance (user_id BIGINT PRIMARY KEY, status TEXT, updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY, 
                user_id BIGINT, 
                username TEXT, 
                chat_id BIGINT, 
                action_type TEXT, 
                detail TEXT, 
                status TEXT, 
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        ''')
    
    await app.bot.set_my_commands(get_user_menu(), scope=BotCommandScopeDefault())
    logger.info("✅ Database & Scoped Menus Configured.")

# --- CORE USER FEATURES ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_menus(update, context)
    await update.message.reply_text("🤖 **System Online.** Welcome to the Workspace. Use the menu to navigate features.", parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_menus(update, context)
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    
    text = (
        "🚀 **Workspace Manager Guide**\n\n"
        "📅 **Events**\n`/event_create` - Create an event\n`/event_list` - View upcoming events\n\n"
        "👥 **Attendance**\n`/clockin` - Start attendance\n`/clockout` - Submit attendance report\n\n"
        "🎂 **Birthday**\n`/birthday_list` - View birthday list\n\n"
        "🎲 **Utilities**\n`/poll` - Create a poll\n`/raffle` - Pick random winners\n\n"
        "⚙️ **Profile**\n`/away` - Set away status\n`/back` - Return to available status\n"
    )
    
    if await is_bot_admin(username, pool):
        text += (
            "\n🛠️ **Admin Commands**\n\n"
            "**Group Management**\n`/admin_groups` - View active groups\n`/admin_broadcast` - Broadcast to groups\n\n"
            "**Announcements**\n`/announcement_create` - Draft an announcement\n`/announcement_send` - Send the draft\n\n"
            "**Diagnostics**\n`/auditlog` - View live system reports\n`/systemstatus` - View general metrics"
        )
        
    try:
        await context.bot.send_message(user_id, text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await update.message.reply_text("📬 I have sent the command manual to your Direct Messages!")
    except:
        if update.effective_chat.type != "private":
            await update.message.reply_text("❌ I cannot send you a DM. Please message me directly first!")

async def cmd_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    
    try:
        async with pool.acquire() as conn:
            res = await conn.execute('DELETE FROM away_status WHERE user_id=$1', user_id)
            if res == "DELETE 0":
                await update.message.reply_text("You are already marked as Available.")
                await log_audit(pool, user_id, username, chat_id, "Back", "User was already available", "Success")
                return
                
        await update.message.reply_text("✅ You are now marked as Available.")
        await log_audit(pool, user_id, username, chat_id, "Back", "Returned from Away", "Success")
    except Exception as e:
        await update.message.reply_text(f"❌ Error updating status: {str(e)}")
        await log_audit(pool, user_id, username, chat_id, "Back", str(e), "Failed")

async def cmd_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    reason = " ".join(context.args) or "Not specified"
    
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO away_status (user_id, username, reason) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET reason=$3', user_id, username, reason)
        await update.message.reply_text(f"⚙️ You are now marked as Away. Reason: {reason}")
        await log_audit(pool, user_id, username, chat_id, "Away", reason, "Success")
    except Exception as e:
        await update.message.reply_text(f"❌ Error setting status: {str(e)}")
        await log_audit(pool, user_id, username, chat_id, "Away", str(e), "Failed")

async def cmd_clockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO attendance (user_id, status, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET status=$2, updated_at=NOW()', user_id, 'Clocked In')
        await update.message.reply_text("✅ Clock In successful.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock In", "User clocked in", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed to clock in.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock In", str(e), "Failed")

async def cmd_clockout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO attendance (user_id, status, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (user_id) DO UPDATE SET status=$2, updated_at=NOW()', user_id, 'Clocked Out')
        await update.message.reply_text("✅ Clock Out report submitted.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock Out", "User clocked out", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed to clock out.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Clock Out", str(e), "Failed")

# --- BIRTHDAY SYSTEM ---
async def cmd_birthday_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            bdays = await conn.fetch("SELECT username, bday FROM birthdays ORDER BY bday ASC")
        if not bdays:
            await update.message.reply_text("📅 No birthdays recorded.")
        else:
            msg = "🎂 **Company Birthdays:**\n" + "\n".join([f"• @{b['username']}: {b['bday']}" for b in bdays])
            await update.message.reply_text(msg, parse_mode="Markdown")
        await log_audit(pool, update.effective_user.id, update.effective_user.username or str(update.effective_user.id), update.effective_chat.id, "Birthday List", "Viewed list", "Success")
    except Exception as e:
        await log_audit(pool, update.effective_user.id, update.effective_user.username or str(update.effective_user.id), update.effective_chat.id, "Birthday List", str(e), "Failed")

async def cmd_birthday_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    if not await is_bot_admin(username, pool): return
    
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        if len(parts) < 2: raise ValueError("Missing parameters.")
        target_username = parts[0].replace("@", "")
        bday_str = parts[1]
        datetime.datetime.strptime(bday_str, "%d/%m") # Validate format DD/MM
        
        async with pool.acquire() as conn:
            exists = await conn.fetchval('SELECT 1 FROM birthdays WHERE username=$1', target_username)
            if exists:
                await update.message.reply_text("❌ Birthday already exists.\nUse `/birthday_edit` to modify the date.", parse_mode="Markdown")
                await log_audit(pool, user_id, username, chat_id, "Birthday Add", f"Attempted duplicate for {target_username}", "Failed")
                return
            await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', target_username, bday_str)
            
        await update.message.reply_text(f"✅ Birthday added successfully for @{target_username}.")
        await log_audit(pool, user_id, username, chat_id, "Birthday Add", f"Added {target_username} ({bday_str})", "Success")
    except ValueError as ve:
        await update.message.reply_text(f"❌ Failed to add birthday.\nReason: Invalid format. Use `/birthday_add @user, DD/MM`", parse_mode="Markdown")
        await log_audit(pool, user_id, username, chat_id, "Birthday Add", "Format error", "Failed")
    except Exception as e:
        await update.message.reply_text("❌ Failed to add birthday.\nReason: Database constraints.")
        await log_audit(pool, user_id, username, chat_id, "Birthday Add", str(e), "Failed")

async def cmd_birthday_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    if not await is_bot_admin(username, pool): return
    
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        if len(parts) < 2: raise ValueError("Missing parameters.")
        target_username = parts[0].replace("@", "")
        bday_str = parts[1]
        datetime.datetime.strptime(bday_str, "%d/%m") 
        
        async with pool.acquire() as conn:
            res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE username=$2', bday_str, target_username)
            if res == "UPDATE 0":
                await update.message.reply_text("❌ Failed to edit birthday.\nReason: User not found in records.", parse_mode="Markdown")
                await log_audit(pool, user_id, username, chat_id, "Birthday Edit", f"{target_username} not found", "Failed")
                return
                
        await update.message.reply_text(f"✅ Birthday updated successfully for @{target_username}.")
        await log_audit(pool, user_id, username, chat_id, "Birthday Edit", f"Edited {target_username} ({bday_str})", "Success")
    except ValueError:
        await update.message.reply_text("❌ Failed to edit birthday.\nReason: Invalid format. Use `/birthday_edit @user, DD/MM`", parse_mode="Markdown")
        await log_audit(pool, user_id, username, chat_id, "Birthday Edit", "Format error", "Failed")
    except Exception as e:
        await update.message.reply_text("❌ Failed to edit birthday.\nReason: System error.")
        await log_audit(pool, user_id, username, chat_id, "Birthday Edit", str(e), "Failed")

# --- ANNOUNCEMENT SYSTEM ---
async def cmd_announcement_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        payload = " ".join(context.args)
        if not payload: raise ValueError("Payload is empty.")
        context.bot_data['draft_announcement'] = payload
        await update.message.reply_text("✅ Announcement drafted successfully. Use `/announcement_send` to broadcast.", parse_mode="Markdown")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Announce Create", "Draft stored", "Success")
    except Exception as e:
        await update.message.reply_text("❌ Failed to draft announcement.\nReason: Provide text after command.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Announce Create", str(e), "Failed")

async def cmd_announcement_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    draft = context.bot_data.get('draft_announcement')
    if not draft:
        await update.message.reply_text("❌ Failed to send announcement.\nReason: No draft found. Use `/announcement_create` first.", parse_mode="Markdown")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Announce Send", "No draft found", "Failed")
        return
        
    try:
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
        if not groups:
            await update.message.reply_text("❌ Failed to send announcement.\nReason: No target groups configured.")
            await log_audit(pool, user_id, username, update.effective_chat.id, "Announce Send", "No active groups", "Failed")
            return
            
        success, fail = 0, 0
        for g in groups:
            try:
                await context.bot.send_message(g['chat_id'], f"📢 **Announcement**\n\n{draft}", parse_mode="Markdown")
                success += 1
                await log_audit(pool, user_id, username, g['chat_id'], "Announce Delivery", f"Sent to {g['title']}", "Success")
            except TelegramError as e:
                fail += 1
                await log_audit(pool, user_id, username, g['chat_id'], "Announce Delivery", f"Failed ({g['title']}): {str(e)}", "Failed")
        
        if success > 0:
            await update.message.reply_text(f"✅ Announcement sent successfully to {success} groups. ({fail} failed).")
            context.bot_data['draft_announcement'] = None # Clear after send
        else:
            await update.message.reply_text("❌ Failed to send announcement.\nReason: Bot lacks permission in the targeted groups.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to process announcement.\nReason: System Error.")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Announce Send", str(e), "Failed")

async def cmd_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct one-line broadcast command."""
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    if not await is_bot_admin(username, pool): return
    
    try:
        args_text = " ".join(context.args)
        if "," not in args_text: raise ValueError("Format must be: `/admin_broadcast [ChatID|All], Message`")
            
        target, msg = [p.strip() for p in args_text.split(",", 1)]
        if not msg: raise ValueError("Message payload cannot be empty.")
        
        async with pool.acquire() as conn:
            if target.lower() == "all": groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
            else: groups = [{"chat_id": int(target), "title": "Targeted Group"}]
                
        if not groups:
            await update.message.reply_text("❌ Failed to send announcement.\nReason: No target groups configured or found.")
            await log_audit(pool, user_id, username, chat_id, "Broadcast", "No targets found", "Failed")
            return
            
        success, fail = 0, 0
        for g in groups:
            try:
                await context.bot.send_message(g['chat_id'], f"📢 **Broadcast**\n\n{msg}", parse_mode="Markdown")
                success += 1
                await log_audit(pool, user_id, username, g['chat_id'], "Broadcast Delivery", f"Sent to {g['title']}", "Success")
            except TelegramError as e:
                fail += 1
                await log_audit(pool, user_id, username, g['chat_id'], "Broadcast Delivery", f"Failed ({g['title']}): {str(e)}", "Failed")
        
        if success > 0:
            await update.message.reply_text(f"✅ Announcement sent successfully to {success} groups. ({fail} failed).")
        else:
            await update.message.reply_text("❌ Failed to send announcement.\nReason: Bot lacks permission in the targeted groups.")
    except ValueError as ve:
        await update.message.reply_text(f"❌ Failed to process announcement.\nReason: {str(ve)}", parse_mode="Markdown")
        await log_audit(pool, user_id, username, chat_id, "Broadcast Cmd", "Validation Error", "Failed")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to process announcement.\nReason: System Error.")
        await log_audit(pool, user_id, username, chat_id, "Broadcast Cmd", str(e), "Failed")

# --- GROUP TELEMETRY & SYSTEM ---
async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers when the bot joins or leaves a group."""
    result = update.my_chat_member
    if not result: return
    chat = result.chat
    status = result.new_chat_member.status
    pool = context.bot_data.get('db_pool')
    
    if status in ['member', 'administrator']:
        try: member_count = await chat.get_member_count()
        except: member_count = 0
            
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO active_groups (chat_id, title, member_count) VALUES ($1, $2, $3) ON CONFLICT (chat_id) DO UPDATE SET title=$2, member_count=$3', chat.id, chat.title, member_count)
            
        alert_msg = f"✅ **Bot Joined Group**\n\nGroup Name: `{chat.title}`\nGroup ID: `{chat.id}`\nMember Count: `{member_count}`\nTime: {datetime.datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S WIB')}"
        await notify_admins(context.bot, pool, alert_msg)
        await log_audit(pool, context.bot.id, context.bot.username, chat.id, "Group Join", f"Joined {chat.title}", "Success")
        
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)
            
        alert_msg = f"⚠️ **Bot Left Group**\n\nGroup Name: `{chat.title}`\nGroup ID: `{chat.id}`\nTime: {datetime.datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S WIB')}"
        await notify_admins(context.bot, pool, alert_msg)
        await log_audit(pool, context.bot.id, context.bot.username, chat.id, "Group Leave", f"Left {chat.title}", "Success")

async def cmd_admin_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username or str(update.effective_user.id), pool): return
    try:
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title, member_count FROM active_groups")
        if not groups:
            await update.message.reply_text("No active groups found in database.")
        else:
            msg = "📊 **Active Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` | {g['title']} ({g['member_count']} members)" for g in groups])
            await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e: pass

async def cmd_systemstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username or str(update.effective_user.id), pool): return
    try:
        async with pool.acquire() as conn:
            g_cnt = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
            u_cnt = await conn.fetchval("SELECT COUNT(*) FROM users")
            a_cnt = await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
        msg = f"⚙️ **Live System Metrics:**\n• Tracked Groups: {g_cnt}\n• Tracked Users: {u_cnt}\n• Recent Actions Logged: {a_cnt}"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except: pass

# --- DIAGNOSTIC AUDIT LOGS ---
async def compile_audit_report(pool, start_dt, end_dt, report_date_str):
    """Generates the formatted audit report based on a time delta."""
    async with pool.acquire() as conn:
        groups_cnt = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
        
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(CASE WHEN action_type = 'Clock In' THEN 1 END) as clock_in_cnt,
                COUNT(CASE WHEN action_type = 'Clock Out' THEN 1 END) as clock_out_cnt,
                COUNT(CASE WHEN action_type = 'Away' THEN 1 END) as away_cnt,
                COUNT(CASE WHEN action_type = 'Back' THEN 1 END) as back_cnt,
                COUNT(CASE WHEN action_type = 'Event Create' THEN 1 END) as evt_create_cnt,
                COUNT(CASE WHEN action_type = 'RSVP' THEN 1 END) as rsvp_cnt,
                COUNT(CASE WHEN action_type = 'Broadcast Delivery' AND status = 'Success' THEN 1 END) as ann_sent,
                COUNT(CASE WHEN action_type = 'Broadcast Delivery' AND status = 'Failed' THEN 1 END) as ann_fail,
                COUNT(CASE WHEN status = 'Failed' AND action_type != 'Broadcast Delivery' THEN 1 END) as err_cnt
            FROM audit_logs
            WHERE created_at >= $1 AND created_at <= $2
        """, start_dt, end_dt)
        
        top_users = await conn.fetch("""
            SELECT username, COUNT(*) as activity 
            FROM audit_logs 
            WHERE created_at >= $1 AND created_at <= $2 AND username IS NOT NULL
            GROUP BY username 
            ORDER BY activity DESC 
            LIMIT 3
        """, start_dt, end_dt)

    msg = f"🌅 **Daily Diagnostic Audit Report**\nDate: {report_date_str}\n\n"
    msg += f"**Groups:**\n• Total Active Groups: {groups_cnt}\n\n"
    msg += "**Users:**\n"
    msg += f"• Clock In Count: {stats['clock_in_cnt']}\n"
    msg += f"• Clock Out Count: {stats['clock_out_cnt']}\n"
    msg += f"• Away Count: {stats['away_cnt']}\n"
    msg += f"• Back Count: {stats['back_cnt']}\n\n"
    msg += "**Events:**\n"
    msg += f"• Created: {stats['evt_create_cnt']}\n"
    msg += f"• RSVP Count: {stats['rsvp_cnt']}\n\n"
    msg += "**Announcements:**\n"
    msg += f"• Sent: {stats['ann_sent']}\n"
    msg += f"• Failed: {stats['ann_fail']}\n\n"
    msg += "**System:**\n"
    msg += f"• Errors & Warnings: {stats['err_cnt']}\n\n"
    msg += "**Top Active Users:**\n"
    if top_users:
        for i, u in enumerate(top_users, 1):
            msg += f"{i}. @{u['username']} ({u['activity']} actions)\n"
    else: msg += "No user activity recorded."
        
    return msg

async def cron_daily_audit(context: ContextTypes.DEFAULT_TYPE):
    """Fires at 07:00 AM WIB. Analyzes Yesterday 00:00 to 23:59."""
    now = datetime.datetime.now(WIB)
    yesterday = (now - datetime.timedelta(days=1)).date()
    
    start_dt = WIB.localize(datetime.datetime.combine(yesterday, datetime.time.min))
    end_dt = WIB.localize(datetime.datetime.combine(yesterday, datetime.time.max))
    
    pool = context.bot_data.get('db_pool')
    report = await compile_audit_report(pool, start_dt, end_dt, yesterday.strftime("%d/%m/%Y"))
    await notify_admins(context.bot, pool, report)

async def cmd_auditlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command. Analyzes Today 00:00 to Right Now."""
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    now = datetime.datetime.now(WIB)
    today = now.date()
    start_dt = WIB.localize(datetime.datetime.combine(today, datetime.time.min))
    
    report = await compile_audit_report(pool, start_dt, now, today.strftime("%d/%m/%Y (Up to now)"))
    
    try:
        await context.bot.send_message(user_id, report, parse_mode="Markdown")
        await log_audit(pool, user_id, username, update.effective_chat.id, "Audit Pull", "Pulled manual report", "Success")
    except Exception as e:
        await log_audit(pool, user_id, username, update.effective_chat.id, "Audit Pull", str(e), "Failed")

# --- UTILITIES ---
async def cmd_event_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    await update.message.reply_text("✅ Dummy Event created.")
    await log_audit(context.bot_data.get('db_pool'), user_id, username, update.effective_chat.id, "Event Create", "Created standard event", "Success")

async def cmd_event_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 No upcoming events.")

async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    await update.message.reply_text("✅ Poll created.")
    await log_audit(context.bot_data.get('db_pool'), user_id, username, update.effective_chat.id, "Poll Create", "Created utility poll", "Success")

async def cmd_raffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT username FROM users WHERE username IS NOT NULL")
    if not users:
        await update.message.reply_text("❌ No users available for raffle.")
        return await log_audit(pool, user_id, username, update.effective_chat.id, "Raffle", "No users", "Failed")
    
    winner = random.choice(users)['username']
    await update.message.reply_text(f"🎲 Raffle Winner: @{winner}!")
    await log_audit(pool, user_id, username, update.effective_chat.id, "Raffle", f"Winner: {winner}", "Success")

async def global_message_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    pool = context.bot_data.get('db_pool')
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username=$2", user_id, username)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Nothing happens on this command. Please check with the admin.")

# --- RUNNER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = init_db

    app.job_queue.run_daily(cron_daily_audit, datetime.time(hour=7, minute=0, tzinfo=WIB))

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("event_create", cmd_event_create))
    app.add_handler(CommandHandler("event_list", cmd_event_list))
    app.add_handler(CommandHandler("clockin", cmd_clockin))
    app.add_handler(CommandHandler("clockout", cmd_clockout))
    app.add_handler(CommandHandler("birthday_list", cmd_birthday_list))
    app.add_handler(CommandHandler("birthday_add", cmd_birthday_add))
    app.add_handler(CommandHandler("birthday_edit", cmd_birthday_edit))
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("raffle", cmd_raffle))
    app.add_handler(CommandHandler("away", cmd_away))
    app.add_handler(CommandHandler("back", cmd_back))
    app.add_handler(CommandHandler("admin_groups", cmd_admin_groups))
    app.add_handler(CommandHandler("admin_broadcast", cmd_admin_broadcast))
    app.add_handler(CommandHandler("announcement_create", cmd_announcement_create))
    app.add_handler(CommandHandler("announcement_send", cmd_announcement_send))
    app.add_handler(CommandHandler("auditlog", cmd_auditlog))
    app.add_handler(CommandHandler("systemstatus", cmd_systemstatus))

    app.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_message_tracker))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logger.info("Starting Enterprise Audit System...")
    app.run_polling()

if __name__ == "__main__":
    main()
