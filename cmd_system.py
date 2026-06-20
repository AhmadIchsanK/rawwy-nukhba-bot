import datetime, logging
from google import genai
from telegram import Update
from telegram.ext import ContextTypes
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, log_action, update_user_menu
import cmd_user 

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private": await update_user_menu(update.effective_user.id, username, pool, context.bot)
    await update.message.reply_text("✅ **Hello! [RW] Nukhba Manager is fully operational.** Type `/help` to see the command manual.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private": await update_user_menu(update.effective_user.id, username, pool, context.bot)
    help_text = (
        "🚀 *[RW] Nukhba Manager Guide*\n\n"
        "🤖 *1/ Gemini AI*\n`/gemini Ask any question` - Solves problems or translates text.\n`/ask Ask about the bot` - Ask how to use Nukhba's features.\n\n"
        "📅 *2/ Events*\n`/newevent Title , MM/DD/YYYY HH.MM , RemMins` - Schedules a pinned event.\n`/events` - View upcoming events.\n\n"
        "📊 *3/ Polls*\n`/poll Question , Opt1 , Opt2` - Launches interactive poll builder.\n\n"
        "🌟 *4/ RAWWY Stars*\n`/thanks` (Reply) - Give 1 Star.\n`/myquota` - Check remaining sends.\n`/mystar` - Stars earned this month.\n`/totalstar` - Stars earned all-time.\n`/leaderboard` - Stars earned leaderboard.\n\n"
        "📚 *5/ Library*\n`/addlib Name , Content` - Save an asset.\n`/editlib Name , Content` - Edit your asset.\n`/dellib Name` - Delete your asset.\n`/getlib Name` - Pull an asset.\n`/library` - Browse everything.\n\n"
        "⚡ *6/ Tasks*\n`/assign @user , 60 , Task description` - Deadline in 60-480m.\n`/complete ID` - Close task.\n`/mytasks` - View your active tasks.\n\n"
        "🏖️ *7/ Away Mode*\n`/away Reason , MM/DD/YYYY HH.MM` - Set away status.\n`/back` - Return early and receive missed mentions.\n\n"
        "💡 *Extras*\n`/feedback Your feedback or request here`"
    )
    is_adm = await is_bot_admin(username, pool)
    if is_adm:
        help_text += (
            "\n\n🔐 *[RW] NUKHBA ADMIN SUITE*\n\n"
            "🎂 *Birthdays*\n`/addbday @user , MM/DD`\n`/editbday @user , MM/DD`\n`/delbday @user`\n`/setbdaychannel` (Run in target group)\n`/setbdaytime HH:MM`\n`/bdayconfig` | `/listbdays`\n`/addbday_batch` | `/delbday_batch`\n\n"
            "🌟 *Stars & Quotas*\n`/checkquota all` or `@user`\n`/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`\n`/checkgeminiquota all` or `@user`\n`/admin_gemini @user , [set/add/sub] , Amount`\n`/setweeklylimit 30`\n\n"
            "⚙️ *Management*\n`/attendance` - See who is Away in this group.\n`/forceback @user` - Force stop user away status.\n`/grouptasks` - See pending tasks in the database.\n`/cancelevent ID` | `/canceltask ID` | `/cancelpoll` (Reply)\n`/addlib_batch` | `/dellib_batch`\n\n"
            "📢 *System & Broadcasts*\n`/schedule [ChatID/all] , [once/daily/weekly] , [Time] , [yes/no] , [Message]`\n`/listschedules` | `/delschedule ID`\n`/announce [ChatID/All] , Message`\n`/editannounce ID , New Msg` | `/delannounce ID`\n`/groupid` - Check current group or all groups.\n`/auditlog` - Pull diagnostics log now.\n\n"
            "🤖 *AI Insight*\n`/feedbacklist` - View last 7 days of feedback.\n`/analyze_feedback` - Standard (7 days) or custom parameters.\n`/alltimefeedback` - Review historical database archives."
        )
        if await is_super(username):
            help_text += (
                "\n\n👑 *SUPER OWNER EXCLUSIVES*\n"
                "🛡️ *Access:* `/addadmin @user` | `/deladmin @user` | `/listadmins`\n"
                "🛑 *Offboarding:* `/removemember @user`\n"
                "🪦 *Graveyard:* `/graveyard`\n"
                "📈 *System:* `/botstatus`\n"
                "🛑 *Power:* `/pause` | `/restart`\n"
                "☢️ *Wipe:* `/super_reset [stars/tasks/library/events/away/birthdays/all]`"
            )
    try:
        await context.bot.send_message(update.effective_user.id, help_text, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("✅ I have securely sent the manual to your Direct Messages!")
    except:
        if update.effective_chat.type != "private": await update.message.reply_text("❌ I cannot send you a DM yet. Please start a private chat with me first!")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ **Unknown Command.** Please type `/help` to see valid commands or check with your admin.", parse_mode="Markdown")

async def security_track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result: return
    chat = result.chat
    status = result.new_chat_member.status
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
        super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
    admin_ids = {a['user_id'] for a in admins if a['user_id']}
    if super_id: admin_ids.add(super_id)
    now_str = datetime.datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S WIB')
    
    if status in ['member', 'administrator']:
        inviter = result.from_user.username or str(result.from_user.id)
        if not await is_bot_admin(inviter, pool):
            try:
                await context.bot.send_message(chat.id, "❌ **Access Denied.** I am a private enterprise system. You are not authorized to deploy me here. Leaving chat.")
                await context.bot.leave_chat(chat.id)
                await log_action(pool, update.effective_user.id, chat.id, "Security", "Warning", f"Unauthorized invite by @{inviter}")
            except: pass
            return
        async with pool.acquire() as conn: await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
        try: await context.bot.send_message(chat.id, "✅ **Authorization confirmed.** [RW] Nukhba Manager is locked in and syncing data.")
        except: pass
        member_count = await chat.get_member_count()
        adm_msg = f"✅ **Bot Joined Group**\n\nGroup Name: {chat.title}\nGroup ID: `{chat.id}`\nMember Count: {member_count}\nTime: {now_str}"
        for uid in admin_ids:
            try: await context.bot.send_message(uid, adm_msg, parse_mode="Markdown")
            except: pass
        await log_action(pool, update.effective_user.id, chat.id, "System", "Success", "Bot joined group successfully.")
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn: await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)
        adm_msg = f"⚠️ **Bot Left Group**\n\nGroup Name: {chat.title}\nGroup ID: `{chat.id}`\nTime: {now_str}"
        for uid in admin_ids:
            try: await context.bot.send_message(uid, adm_msg, parse_mode="Markdown")
            except: pass
        await log_action(pool, update.effective_user.id, chat.id, "System", "Warning", "Bot left or was removed from group.")

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    pool = context.bot_data.get('db_pool'); now = datetime.datetime.now(WIB); username = update.effective_user.username or str(update.effective_user.id)
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET user_id=$2", username, update.effective_user.id)
            await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, 1, 0) ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + 1")
            chat = update.effective_chat
            if chat.type in ['group', 'supergroup']: await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
            text = update.message.text
            is_away = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username)
            if is_away:
                for j in context.job_queue.get_jobs_by_name(f"away_{username}"): j.schedule_removal()
                recap_msg = await cmd_user.process_return(username, pool, context.bot)
                await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Removed", f"@{username} auto-returned via chat")
                try:
                    uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
                    if uid: await context.bot.send_message(uid, f"✅ {recap_msg}", parse_mode="Markdown")
                except: pass
            aways = await conn.fetch('SELECT username, reason, end_time, last_notified FROM away_status')
            for a in aways:
                if f"@{a['username']}" in text:
                    await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], username, text, update.effective_chat.title or "DM")
                    if not a['last_notified'] or (now - a['last_notified']).total_seconds() > 3600:
                        rem = a['end_time'].astimezone(WIB) - now
                        if rem.total_seconds() > 0:
                            d = rem.days; h = rem.seconds // 3600; m = (rem.seconds % 3600) // 60
                            if d > 0: t_str = f"{d} days, {h} hours, and {m} minutes"
                            elif h > 0: t_str = f"{h} hours and {m} minutes"
                            else: t_str = f"{m} minutes"
                            await update.message.reply_text(f"Just a polite heads up, @{a['username']} is currently away for another {t_str}.\n(Reason: {a['reason']})")
                            await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])
    except Exception as e: await log_action(pool, update.effective_user.id, update.effective_chat.id, "System", "Error", f"Global tracker exception: {e}")

async def submit_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: return await update.message.reply_text("❌ Please type: `/feedback [explain issue or request here]`", parse_mode="Markdown")
    username = update.effective_user.username or str(update.effective_user.id); pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", username, text)
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Feedback", "Success", f"Feedback submitted by @{username}")
        await update.message.reply_text("✅ 💡 Feedback securely filed for analysis.")
    except Exception as e: await update.message.reply_text(f"❌ System Error: {e}")

async def process_gemini_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, is_bot_query: bool = False):
    if not prompt: return await update.message.reply_text("❌ Please provide a prompt.")
    username = update.effective_user.username or str(update.effective_user.id); pool = context.bot_data.get('db_pool')
    if not GEMINI_API_KEY: return await update.message.reply_text("❌ GEMINI_API_KEY unconfigured.")
    try:
        is_adm = await is_bot_admin(username, pool)
        async with pool.acquire() as conn:
            limit_str = await conn.fetchval("SELECT value FROM config WHERE key='gemini_weekly_limit'")
            limit = int(limit_str) if limit_str and limit_str.isdigit() else 20
            await conn.execute("INSERT INTO users (username, user_id, gemini_quota) VALUES ($1, $2, $3) ON CONFLICT (username) DO NOTHING", username, update.effective_user.id, limit)
            if not is_adm:
                quota = await conn.fetchval("SELECT gemini_quota FROM users WHERE username=$1", username)
                if quota <= 0: return await update.message.reply_text(f"❌ AI quota depleted ({limit}/{limit}).")
                await conn.execute("UPDATE users SET gemini_quota = gemini_quota - 1 WHERE username=$1", username)
                quota_msg = f"_(Quota left: {quota - 1})_"
            else: quota_msg = "_(Admin: Unlimited)_"
    except Exception as e: return await update.message.reply_text(f"❌ DB Error: {e}")

    temp = await update.message.reply_text("⏳ Thinking...")
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        if is_bot_query:
            system_prompt = "You are Nukhba Manager, an enterprise Telegram bot. Your features: Gemini AI (/gemini), Events (/newevent, /events), Polls (/poll), RAWWY Stars (/thanks, /leaderboard), Library (/addlib, /getlib), Tasks (/assign, /complete), Away mode (/away, /back), and Feedback (/feedback). Answer this user question clearly and concisely about how to use your commands:\nUser Question: " + prompt
        else:
            system_prompt = prompt
            
        response = client.models.generate_content(model='gemini-2.5-flash', contents=system_prompt)
        reply = response.text
        
        prefix = "🤖 **About Me:**\n\n" if is_bot_query else "🤖 **Gemini AI Response:**\n\n"
        inline_prefix = "🤖 **Nukhba Manager:** " if is_bot_query else "🤖 **Gemini:** "
        
        if len(reply) > 500 and update.effective_chat.type != "private":
            try:
                await context.bot.send_message(update.effective_user.id, f"{prefix}{reply}", parse_mode="Markdown")
                await temp.edit_text(f"✅ It's a bit long, so I sent the answer to your DMs!\n\n{quota_msg}", parse_mode="Markdown")
            except:
                await temp.edit_text("❌ Please open a private chat with me first so I can DM you.")
                if not is_adm:
                    async with pool.acquire() as conn: await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)
        else: await temp.edit_text(f"{inline_prefix}{reply}\n\n{quota_msg}", parse_mode="Markdown")
    except Exception as e:
        if "429" in str(e).lower() or "quota" in str(e).lower():
            await temp.edit_text("❌ Gemini API credit limit depleted (429). Admins notified.")
            async with pool.acquire() as conn:
                admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
                super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
            admin_ids = {a['user_id'] for a in admins if a['user_id']}; admin_ids.add(super_id) if super_id else None
            for uid in admin_ids:
                try: await context.bot.send_message(uid, "⚠️ **CRITICAL:** Gemini API limit depleted.", parse_mode="Markdown")
                except: pass
        else: await temp.edit_text(f"❌ AI Error: {e}")
        if not is_adm:
            async with pool.acquire() as conn: await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)

async def ask_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), False)

async def ask_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), True)
