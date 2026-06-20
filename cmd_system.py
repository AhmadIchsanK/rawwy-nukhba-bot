import datetime, logging, json, re, asyncio, sys, importlib
from google import genai
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, log_action, update_user_menu
import cmd_user 

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
    await update.message.reply_text("✅ **Hello! [RW] Nukhba Manager is fully operational.** Type `/help` to see the command manual.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
        
    help_text = (
        "🚀 *[RW] Nukhba Manager Manual*\n\n"
        "🤖 **1/ Gemini AI**\n"
        "`/gemini Ask any question` - Solves problems or translates text.\n"
        "`/ask Ask about Nukhba Bot` - Ask how to use Nukhba's features.\n\n"
        "📅 **2/ Events**\n"
        "`/newevent Title , MM/DD/YYYY HH.MM , RemMins` - Schedules a pinned event.\n"
        "`/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins` - Modifies a scheduled event.\n"
        "`/events` - View upcoming events.\n\n"
        "📊 **3/ Polls**\n"
        "`/poll Question , Opt1 , Opt2` - Launches interactive poll builder.\n\n"
        "🌟 **4/ RAWWY Stars**\n"
        "`/thanks` (Reply) - Give a Star (Reply).\n"
        "`/myquota` - Check Star Quota left.\n"
        "`/mystar` - Monthly Stars earned.\n"
        "`/totalstar` - All-time Stars earned.\n"
        "`/leaderboard` - Top RAWWY Stars.\n\n"
        "🧠 **5/ Trivia**\n"
        "`/mypoint` - View your Trivia Points balance via DM.\n\n"
        "📚 **6/ Library**\n"
        "`/addlib Name , Content` - Save a library asset.\n"
        "`/editlib Name , Content` - Edit your asset.\n"
        "`/dellib Name` - Delete your asset.\n"
        "`/getlib Name` - Retrieve an asset.\n"
        "`/library` - Browse the Library.\n\n"
        "⚡ **7/ Tasks**\n"
        "`/assign @user , Mins , Desc` - Assign a task.\n"
        "`/complete ID` - Mark task complete.\n"
        "`/mytasks` - View your active tasks.\n\n"
        "🏖️ **8/ Away Mode**\n"
        "`/away Reason , MM/DD/YYYY HH.MM` - Set away status.\n"
        "`/back` - Return to available and check notifications.\n\n"
        "💡 **Extras**\n"
        "`/feedback Text here` - Submit Feedback to development matrix."
    )

    is_adm = await is_bot_admin(username, pool)
    if is_adm:
        help_text += (
            "\n\n🔐 *[RW] NUKHBA ADMIN SUITE*\n\n"
            "🧠 *Trivia Management*\n`/settriviachannel` - Set current group for trivia.\n`/settriviatheme [theme]` - Set theme topic.\n`/settriviatime [HH:MM]` - Change release timer.\n`/settriviadays [all/weekday/weekend]` - Change scheduling patterns.\n`/settriviaopts [4-6]` - Change choice count.\n`/settriviatimeout [secs]` | `/setsupertimeout [secs]`\n`/pausetrivia` | `/resumetrivia` - Pause or resume cycles.\n`/forcetrivia` | `/forcesupertrivia` - Trigger rounds immediately.\n`/canceltrivia` - Force drop live trivia round.\n`/admin_kp @user , [set/add/sub] , [amount]` - Edit scores.\n\n"
            "🎂 *Birthdays*\n`/addbday @user , MM/DD`\n`/editbday @user , MM/DD`\n`/delbday @user`\n`/setbdaychannel` (Run in target group)\n`/setbdaytime HH:MM`\n`/bdayconfig` | `/listbdays`\n\n"
            "🌟 *Stars & Quotas*\n`/checkquota all` or `@user`\n`/admin_stars @user , [quota/monthly/total] , [set/add/sub] , Amount`\n`/setweeklyquota 3`\n\n"
            "⚙️ *Management*\n`/attendance` - See who is Away in this group.\n`/forceback @user` - Force stop user away status.\n`/grouptasks` - See pending tasks in the database.\n`/cancelevent ID` | `/canceltask ID` | `/cancelpoll` (Reply)\n\n"
            "📢 *System & Broadcasts*\n`/schedule [ChatID/all] , [once/daily/weekly] , [Time] , [yes/no] , [Message]`\n`/listschedules` | `/delschedule ID`\n`/announce [ChatID/All] , Message`\n`/editannounce ID , New Msg` | `/delannounce ID`\n`/groupid` - Check current group or all groups.\n`/auditlog` - Pull diagnostics log now.\n\n"
            "🤖 *AI Insight*\n`/feedbacklist` - View last 7 days of feedback.\n`/analyze_feedback` - Standard or custom parameters."
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
        if update.effective_chat.type != "private":
            await update.message.reply_text("✅ I have securely sent the manual to your Direct Messages!")
    except:
        if update.effective_chat.type != "private":
            await update.message.reply_text("❌ I cannot send you a DM yet. Please start a private chat with me first!")

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
                await context.bot.send_message(chat.id, "❌ **Access Denied.** I am a private enterprise system. Leaving chat.")
                await context.bot.leave_chat(chat.id)
                await log_action(pool, update.effective_user.id, chat.id, "Security", "Warning", f"Unauthorized invite by @{inviter}")
            except: pass
            return
            
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
        
        try: await context.bot.send_message(chat.id, "✅ **Authorization confirmed.** [RW] Nukhba Manager is locked in and syncing data.")
        except: pass
        
        adm_msg = f"✅ **Bot Joined Group**\nGroup Name: {chat.title}\nGroup ID: `{chat.id}`\nTime: {now_str}"
        for uid in admin_ids:
            try: await context.bot.send_message(uid, adm_msg, parse_mode="Markdown")
            except: pass
            
        await log_action(pool, update.effective_user.id, chat.id, "System", "Success", "Bot joined group successfully.")
        
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)
            
        adm_msg = f"⚠️ **Bot Left Group**\nGroup Name: {chat.title}\nGroup ID: `{chat.id}`\nTime: {now_str}"
        for uid in admin_ids:
            try: await context.bot.send_message(uid, adm_msg, parse_mode="Markdown")
            except: pass
            
        await log_action(pool, update.effective_user.id, chat.id, "System", "Warning", "Bot left or was removed from group.")

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    pool = context.bot_data.get('db_pool')
    now = datetime.datetime.now(WIB)
    username = update.effective_user.username or str(update.effective_user.id)
    
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET user_id=$2", username, update.effective_user.id)
            await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, 1, 0) ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + 1")
            
            chat = update.effective_chat
            if chat.type in ['group', 'supergroup']:
                await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
                
            text = update.message.text
            
            is_away = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username)
            if is_away:
                for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
                    j.schedule_removal()
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
                            d = rem.days
                            h = rem.seconds // 3600
                            m = (rem.seconds % 3600) // 60
                            if d > 0: t_str = f"{d} days, {h} hours, and {m} minutes"
                            elif h > 0: t_str = f"{h} hours and {m} minutes"
                            else: t_str = f"{m} minutes"
                            await update.message.reply_text(f"Just a polite heads up, @{a['username']} is currently away for another {t_str}.\n(Reason: {a['reason']})")
                            await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "System", "Error", f"Global tracker exception: {e}")

async def submit_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: 
        return await update.message.reply_text("❌ Please type: `/feedback [explain issue or request here]`", parse_mode="Markdown")
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", username, text)
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Feedback", "Success", f"Feedback submitted by @{username}")
        await update.message.reply_text("✅ 💡 Feedback securely filed for analysis.")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def process_gemini_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, is_bot_query: bool = False):
    if not prompt: 
        return await update.message.reply_text("❌ Please provide a prompt.")
    
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    if not GEMINI_API_KEY: 
        return await update.message.reply_text("❌ GEMINI_API_KEY unconfigured.")
    
    try:
        is_adm = await is_bot_admin(username, pool)
        is_sup = await is_super(username)
        async with pool.acquire() as conn:
            limit_str = await conn.fetchval("SELECT value FROM config WHERE key='gemini_weekly_limit'")
            limit = int(limit_str) if limit_str and limit_str.isdigit() else 20
            await conn.execute("INSERT INTO users (username, user_id, gemini_quota) VALUES ($1, $2, $3) ON CONFLICT (username) DO NOTHING", username, update.effective_user.id, limit)
            
            if not is_adm:
                limit_left = await conn.fetchval("SELECT gemini_quota FROM users WHERE username=$1", username)
                if limit_left <= 0: 
                    return await update.message.reply_text(f"❌ AI limit depleted ({limit}/{limit}).")
                await conn.execute("UPDATE users SET gemini_quota = gemini_quota - 1 WHERE username=$1", username)
                limit_msg = f"_(Limit left: {limit_left - 1})_"
            else:
                limit_msg = "_(Admin: No Limit)_"
    except Exception as e: 
        return await update.message.reply_text(f"❌ DB Error: {e}")

    temp = await update.message.reply_text("⏳ Thinking...")
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        if is_bot_query:
            system_prompt = (
                "You are Nukhba Manager, an advanced, highly specialized enterprise Telegram bot. "
                "You have absolute, granular knowledge of all your capabilities. Answer precisely, including specific command usage patterns.\n\n"
                "== COMMAND REFERENCE MANUAL ==\n\n"
                "🟢 USER COMMANDS:\n"
                "- /help: Displays this configuration guide.\n"
                "- /gemini <prompt>: Solves general problems, translates text, or writes content. (Consumes weekly AI limit).\n"
                "- /ask <query>: Queries you (this bot) about your features, settings, and commands. (Consumes weekly AI limit).\n"
                "- /newevent <Title> , <MM/DD/YYYY HH.MM> , <RemMins>: Schedules a team event with interactive RSVP (Going/Not Going) buttons, pins it in group chats, and alerts members at RemMins before start.\n"
                "- /editevent <ID> , <Title> , <MM/DD/YYYY HH.MM> , <RemMins>: Modifies an upcoming scheduled event parameters.\n"
                "- /events: Lists the next 5 upcoming scheduled events.\n"
                "- /poll <Question> , <Opt1> , <Opt2> , ...: Launches an interactive group poll with custom options.\n"
                "- /thanks: Award 1 RAWWY Star by REPLYING directly to another user's message. (Consumes 1 Star Quota from you).\n"
                "- /myquota: Checks your remaining Star Quotas left before Monday reset.\n"
                "- /mystar: Shows cumulative RAWWY Stars earned this current month.\n"
                "- /totalstar: Shows cumulative RAWWY Stars earned all-time.\n"
                "- /leaderboard: Displays top Star earners of the month and all-time.\n"
                "- /addlib <Name> , <Content> [, private]: Saves an asset to the shared team database. Append ', private' to deliver content strictly via DM.\n"
                "- /editlib <Name> , <Content>: Modifies library assets you originally added.\n"
                "- /dellib <Name>: Removes library assets you added.\n"
                "- /getlib <Name>: Pulls a saved library asset. Private assets are securely delivered to your Direct Messages.\n"
                "- /library: Lists all browseable library assets.\n"
                "- /assign <@username> , <Minutes> , <Description>: Assigns a task with a firm deadline between 60 to 480 minutes. Pings assignee 10 mins before time expires.\n"
                "- /complete <ID>: Marks an assigned task as finished. Only runnable by the assignee.\n"
                "- /mytasks: Lists your active pending tasks.\n"
                "- /away <Reason> , <MM/DD/YYYY HH.MM>: Sets away status. Auto-notifies other users when mentioned and collects missed mentions.\n"
                "- /back: Manually returns you to Available and triggers a direct message containing missed mentions.\n"
                "- /feedback <Description>: Files team feedback securely.\n"
                "- /mypoint: Displays user current trivia point stats via DM.\n\n"
                "🔐 ADMIN COMMANDS (Admins & Super Owners Only):\n"
                "- /addbday <@username> , <MM/DD>: Registers a member's birthday.\n"
                "- /editbday <@username> , <MM/DD>: Modifies a birthday entry.\n"
                "- /delbday <@username>: Removes a birthday entry.\n"
                "- /setbdaychannel: Locks current group chat to receive automated birthday wishes.\n"
                "- /setbdaytime <HH:MM>: Configures daily time (WIB timezone) for birthday alerts.\n"
                "- /bdayconfig: Shows birthday alert group channel ID and alert time configurations.\n"
                "- /listbdays: Lists all registered birthdays.\n"
                "- /checkquota [all | @username]: Audits remaining Star Quotas.\n"
                "- /admin_stars <@username> , [quota/monthly/total] , [set/add/sub] , <Amount>: Modifies user star records or quota.\n"
                "- /setweeklyquota <Amount>: Sets the global default weekly Star Quota.\n"
                "- /checklimit [all | @username]: Audits remaining weekly AI limit.\n"
                "- /admin_limit <@username> , [set/add/sub] , <Amount>: Modifies a user's AI Limit.\n"
                "- /setweeklylimit <Amount>: Sets the global default weekly AI limit.\n"
                "- /attendance: Displays a real-time list of all users currently Away and scheduled return times.\n"
                "- /forceback <@username>: Forces a user to return from Away status early.\n"
                "- /grouptasks: Displays all active pending tasks globally.\n"
                "- /cancelevent <ID>: Cancels and deletes scheduled events.\n"
                "- /canceltask <ID>: Deletes assigned tasks.\n"
                "- /cancelpoll: Stops and closes a live poll (Run as REPLY to the poll).\n"
                "- /schedule <ChatID/all> , <once/daily/weekly> , <Time> , <yes/no> , <Message>:\n"
                "  Schedules automatic announcements. Time Formats: 'once' (MM/DD/YYYY HH.MM), 'daily' (HH.MM), 'weekly' (<0-6> HH.MM, where 0=Monday). Toggle mention to 'yes' (or 'no') to tag all active users.\n"
                "- /listschedules: View all automated schedules.\n"
                "- /delschedule <ID>: Removes a schedule.\n"
                "- /announce <ChatID/all> , <Message>: Dispatches broadcasts.\n"
                "- /editannounce <ID> , <New Message>: Updates active broadcasts.\n"
                "- /delannounce <ID>: Drops broadcasts.\n"
                "- /groupid: Retrieves current Group ID or lists tracked groups.\n"
                "- /auditlog: Outputs a diagnostics audit report.\n"
                "- /feedbacklist: Displays team feedback from the last 7 days.\n"
                "- /analyze_feedback [MM/DD/YYYY | MM/DD/YYYY , MM/DD/YYYY]: Uses AI to summarize recent feedback backlog.\n"
                "- /settriviachannel: Locks current group to receive daily trivia.\n"
                "- /settriviatheme <theme>: Customizes topic rules.\n"
                "- /settriviatime <HH:MM>: Set daily execution clock.\n"
                "- /settriviadays [all|weekday|weekend]: Set calendar recurrence occurrences.\n"
                "- /settriviaopts [4|5|6]: Set option complexities.\n"
                "- /settriviatimeout <secs>: Set expiration for daily round.\n"
                "- /setsupertimeout <secs>: Set expiration for super quiz.\n"
                "- /forcetrivia: Triggers regular trivia execution immediately.\n"
                "- /forcesupertrivia: Triggers weekly high-stakes super trivia execution immediately.\n"
                "- /canceltrivia: Wipes ongoing active running trivia parameters.\n"
                "- /pausetrivia: Halts the automatic clock schedule tracking sweeps.\n"
                "- /resumetrivia: Reactivates automated clock schedule sweeps.\n"
                "- /admin_kp <@user> , [set/add/sub] , <amount>: Customizes balanced knowledge scores directly.\n\n"
                "👑 SUPER OWNER COMMANDS (Super Owners Only):\n"
                "- /addadmin <@username>: Promotes a user to Bot Admin.\n"
                "- /deladmin <@username>: Demotes an Admin back to standard user.\n"
                "- /listadmins: Lists all current administrators.\n"
                "- /removemember <@username>: Offboards a member, moves metadata safely to graveyard, and archives records.\n"
                "- /graveyard: Displays offboarded users.\n"
                "- /botstatus: Displays global database records and tracked metrics.\n"
                "- /pause: Puts the bot into maintenance mode.\n"
                "- /restart: Restores bot functionality from maintenance mode.\n"
                "- /super_reset <stars/tasks/library/events/away/birthdays/all>: Triggers structural factory wipe.\n\n"
                "Answer the user clearly based on this complete manual.\n"
            )
            if is_adm:
                system_prompt += (
                    "If the admin asks to configure or change a hidden setting (DM length, star quota, or AI limit), "
                    "output a JSON block at the very end of your response exactly like this:\n"
                    "\\`\\`\\`json\n"
                    '[{"key": "dm_length", "value": "800"}, {"key": "star_quota", "value": "5"}]\n'
                    "\\`\\`\\`\n"
                    "Valid keys: `dm_length`, `star_quota`, `gemini_weekly_limit`.\n"
                )
            
            if is_sup:
                system_prompt += (
                    "⚠️ ROOT LEVEL PRIVILEGES DETECTED ⚠️\n"
                    "You are communicating with the Super Owner. You have authorization to hotpatch the runtime, write files, modify codes, and execute features dynamically.\n"
                    "To modify, create, or rewrite any Python module file, output a JSON list block containing the file writes:\n"
                    "\\`\\`\\`json\n"
                    "[\n"
                    "  {\n"
                    '    "action": "write_file",\n'
                    '    "filepath": "cmd_user.py",\n'
                    '    "content": "Full contents of the file..."\n'
                    "  }\n"
                    "]\n"
                    "\\`\\`\\`\n"
                    "To dynamically register a handler, run a command, or update live objects in memory without a container reboot, output a hotpatch:\n"
                    "\\`\\`\\`json\n"
                    "[\n"
                    "  {\n"
                    '    "action": "hotpatch",\n'
                    '    "code": "from telegram.ext import CommandHandler\\nimport cmd_user\\napp.add_handler(CommandHandler(\'newcmd\', cmd_user.handler_func))"\n'
                    "  }\n"
                    "]\n"
                    "\\`\\`\\`\n"
                    "Provide a complete, cleanly written response explaining what changes were made. You are authorized to carry out any software requested."
                )
                
            system_prompt += "\nUser Question: " + prompt
        else:
            system_prompt = prompt
            
        response = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-2.5-flash',
            contents=system_prompt
        )
        reply = response.text
        
        config_msg = ""
        if is_bot_query:
            match = re.search(r'```json\s*\n(.*?)\n\s*
```', reply, re.DOTALL)
            if match:
                try:
                    configs = json.loads(match.group(1))
                    applied_actions = []
                    
                    async with pool.acquire() as conn:
                        for c in configs:
                            action = c.get("action")
                            
                            if not action and "key" in c and is_adm:
                                await conn.execute("INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2", c['key'], str(c['value']))
                                applied_actions.append(f"Config '{c['key']}' set to '{c['value']}'")
                            
                            elif action == "write_file" and is_sup:
                                filepath = c.get("filepath")
                                content = c.get("content")
                                if filepath and content:
                                    with open(filepath, "w", encoding="utf-8") as f:
                                        f.write(content)
                                    mod_name = filepath.replace(".py", "")
                                    if mod_name in sys.modules:
                                        importlib.reload(sys.modules[mod_name])
                                    applied_actions.append(f"Written file '{filepath}' and reloaded module.")
                            
                            elif action == "hotpatch" and is_sup:
                                code_str = c.get("code")
                                if code_str:
                                    local_vars = {
                                        "update": update,
                                        "context": context,
                                        "pool": pool,
                                        "bot": context.bot,
                                        "app": context.application
                                    }
                                    exec(code_str, globals(), local_vars)
                                    applied_actions.append("Active runtime hotpatch executed successfully.")
                                    
                    reply = re.sub(r'```json\s*\n(.*?)\n\s*```', '', reply, flags=re.DOTALL).strip()
                    if applied_actions:
                        config_msg = "\n\n⚙️ **Super System Operations Executed:**\n" + "\n".join([f"• {a}" for a in applied_actions])
                except Exception as e:
                    logger.error(f"Root operation error: {e}")
                    config_msg = f"\n\n⚠️ **Root Operation Failure:** {e}"
        
        async with pool.acquire() as conn:
            dm_len_str = await conn.fetchval("SELECT value FROM config WHERE key='dm_length'")
            dm_len = int(dm_len_str) if dm_len_str and dm_len_str.isdigit() else 500

        prefix = "🤖 **About Me:**\n\n" if is_bot_query else "🤖 **Gemini AI Response:**\n\n"
        inline_prefix = "🤖 **Nukhba Manager:** " if is_bot_query else "🤖 **Gemini:** "
        
        final_reply = reply + config_msg
        
        if len(final_reply) > dm_len and update.effective_chat.type != "private":
            try:
                await send_md_chunks(context.bot, update.effective_user.id, final_reply, prefix)
                await temp.edit_text(f"✅ It's a bit long, so I sent the answer to your DMs!\n\n{limit_msg}", parse_mode="Markdown")
            except:
                try: await temp.edit_text("❌ Please open a private chat with me first so I can DM you.")
                except: pass
                if not is_adm:
                    async with pool.acquire() as conn: 
                        await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)
        else: 
            try: await temp.delete()
            except: pass
            await send_md_chunks(context.bot, update.effective_chat.id, final_reply, inline_prefix, f"\n\n{limit_msg}")
                
    except Exception as e:
        if "429" in str(e).lower() or "quota" in str(e).lower():
            try: await temp.edit_text("❌ Gemini API credit limit depleted (429). Admins notified.")
            except: pass
            async with pool.acquire() as conn:
                admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
                super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
            admin_ids = {a['user_id'] for a in admins if a['user_id']}
            if super_id: admin_ids.add(super_id)
            for uid in admin_ids:
                try: await context.bot.send_message(uid, "⚠️ **CRITICAL:** Gemini API limit depleted.", parse_mode="Markdown")
                except: pass
        else: 
            try: await temp.edit_text(f"❌ AI Error: {e}")
            except: pass
            
        if not is_adm:
            async with pool.acquire() as conn: 
                await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)

async def send_md_chunks(bot, chat_id, text, prefix="", suffix=""):
    limit = 3800
    full = f"{prefix}{text}{suffix}"
    
    if len(full) <= limit:
        try: await bot.send_message(chat_id, full, parse_mode="Markdown")
        except: await bot.send_message(chat_id, full)
        return

    chunks = []
    current_chunk = prefix
    
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > limit:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else: current_chunk += line + "\n"
            
    if len(current_chunk) + len(suffix) > limit:
        chunks.append(current_chunk)
        chunks.append(suffix)
    else:
        current_chunk += suffix
        chunks.append(current_chunk)

    for chunk in chunks:
        if chunk.strip():
            try: await bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except: await bot.send_message(chat_id, chunk)

async def ask_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), False)

async def ask_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), True)
