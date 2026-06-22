import datetime
import logging
import json
import re
import asyncio
import sys
import importlib
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, log_action, update_user_menu, delete_cmd
import cmd_user 
import cmd_system_help

logger = logging.getLogger(__name__)

ABOUT_TEXT = """🚀 **Meet Nukhba Manager: Your Ultimate AI Workspace Companion**

Welcome to [RW] Nukhba Manager—a premium, all-in-one enterprise Telegram assistant designed to supercharge team productivity, elevate workplace culture, and inject a little fun into the daily grind.

Powered by Google's Gemini 2.5 AI, Nukhba isn't just a chatbot; it's a dedicated digital team manager that organizes your workflow, tracks engagement, and keeps everyone connected.

Here is everything Nukhba brings to your workspace:

🤖 **1. Advanced AI & Analytics**
• **Gemini Direct Access:** Ask complex questions, translate text, or brainstorm ideas right in the chat.
• **"What Did I Miss?" (/wdim):** Been away? Nukhba reads the last 48 hours of chat history and sends you a beautifully formatted, AI-generated summary of key topics and decisions via Direct Message.
• **Hyper-Personalized Cheers:** Feeling unmotivated? Set your personal goals and vibe, and Nukhba’s AI will generate a tailored, high-energy motivational pep-talk just for you.
• **Smart Feedback Analysis:** Admins can instantly summarize weekly team feedback into actionable insights (Problem, Suggestion, Next Step) using AI.

⚡ **2. Productivity & Task Management**
• **Task Delegation:** Assign tasks with strict minute-based deadlines. Nukhba tracks pending work and pings assignees 10 minutes before their deadline expires.
• **Asset Library:** A centralized team database. Save, edit, and instantly retrieve important links, texts, or files. Need to share something sensitive? Save it as a "private" asset to be delivered securely via DM.
• **Event Scheduling:** Schedule team events with integrated, clickable RSVP buttons. Nukhba automatically pins the event and notifies attendees when it’s about to start.
• **Interactive Polls:** Build advanced team polls with options for anonymous voting, multiple choices, or even strict "Quiz" modes with designated correct answers.

🌟 **3. Team Culture & Engagement**
• **RAWWY Stars System:** A peer-to-peer kudos economy! Award a limited weekly quota of "Stars" to teammates who went above and beyond. Track who shines the brightest on the Monthly and All-Time Leaderboards.
• **Automated Birthdays:** Never miss a celebration. Register team birthdays and Nukhba will automatically broadcast a celebratory message in your designated channel at your preferred time.
• **Smart Away Mode:** Going on PTO or stepping into a meeting? Set your status to Away. Nukhba will politely notify anyone who tags you, record all your missed mentions, and securely deliver them to you the moment you return.

🎮 **4. The Trivia Engine**
Keep the team's minds sharp with Nukhba's fully automated, high-stakes Trivia Engine!
• **Daily Trivia:** Configurable daily questions spanning 11 themes (from Science to Pop Culture). Race against a live countdown timer to lock in your answer and earn Knowledge Points (KP).
• **Weekly Super Trivia:** A brutal, high-stakes Sunday challenge with 6 options and heavy KP penalties for incorrect answers.
• **Strict Mechanics:** Zero second chances. Answers lock instantly. Rounds end the second the timer hits zero or 3 winners claim the top spots, immediately revealing the correct explanation.

🛡️ **5. Absolute Admin Control**
Nukhba offers total granular control for management:
• **Dynamic Configurations:** Adjust AI limits, star quotas, task limits, and trivia timeouts through interactive inline dashboard panels.
• **Broadcasts & Scheduling:** Send instant announcements across all company groups, or schedule recurring daily/weekly messages.
• **Real-Time Audit Logs:** A complete diagnostic tracker. View real-time logs of exactly who did what, or receive an automated daily AI-digested audit report every night.
• **Super Owner Privileges:** God-mode controls to promote/demote admins, securely offboard leaving members (moving their data to the "Graveyard"), pause the system, or execute factory database wipes.

_[RW] Nukhba Manager isn't just managing the chat—it's managing the success, morale, and efficiency of the entire team. Type /help to dive in!_"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
    await update.message.reply_text("✅ **Hello! [RW] Nukhba Manager is fully operational.** Type `/help` to see the command manual.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_system_help.help_command(update, context)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    user_id = update.effective_user.id
    pool = context.bot_data.get('db_pool')

    async with pool.acquire() as conn:
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_about TIMESTAMP WITH TIME ZONE")
        await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO NOTHING", username, user_id)
        
        last_about = await conn.fetchval("SELECT last_about FROM users WHERE username=$1", username)
        now = datetime.datetime.now(datetime.timezone.utc)
        
        if last_about:
            # Fix timezone crash if timestamp is naive
            if last_about.tzinfo is None:
                last_about = last_about.replace(tzinfo=datetime.timezone.utc)
            time_diff = now - last_about
            if time_diff.total_seconds() < 7 * 24 * 3600:
                rem_days = 7 - time_diff.days
                if update.effective_chat.type != "private":
                    return await context.bot.send_message(update.effective_chat.id, f"⏳ **Cooldown:** You can only request the About guide once a week. Please try again in {rem_days} days.", parse_mode="Markdown")
                else:
                    return await context.bot.send_message(user_id, f"⏳ **Cooldown:** You can only request the About guide once a week. Please try again in {rem_days} days.", parse_mode="Markdown")

    try:
        await send_md_chunks(context.bot, user_id, ABOUT_TEXT)
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET last_about=$1 WHERE username=$2", now, username)
        if update.effective_chat.type != "private":
            await context.bot.send_message(update.effective_chat.id, "✅ **Success:** The comprehensive Nukhba Manager guide has been securely sent to your DMs!", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"About command DM failed: {e}")
        if update.effective_chat.type != "private":
            await context.bot.send_message(update.effective_chat.id, "❌ **Error:** I couldn't send you a DM. Please start a private chat with me first and try again.", parse_mode="Markdown")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ **Unknown Command.** Please type `/help` to see valid commands.", parse_mode="Markdown")

async def security_track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    status = result.new_chat_member.status
    pool = context.bot_data.get('db_pool')
    
    if status in ['member', 'administrator']:
        inviter = result.from_user.username or str(result.from_user.id)
        if not await is_bot_admin(inviter, pool):
            try:
                await context.bot.send_message(chat.id, "❌ **Access Denied.** Leaving chat.")
                await context.bot.leave_chat(chat.id)
            except Exception:
                pass
            return
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    pool = context.bot_data.get('db_pool')
    now = datetime.datetime.now(WIB)
    username = update.effective_user.username or str(update.effective_user.id)
    chat = update.effective_chat
    text = update.message.text
    
    try:
        bot_data = context.bot_data
        
        bot_data.setdefault('chat_buffer', [])
        bot_data.setdefault('seen_users', set())
        bot_data.setdefault('seen_groups', set())
        bot_data.setdefault('away_cache', {'time': 0, 'data': []})
        bot_data.setdefault('stats_uses', 0)
        
        bot_data['stats_uses'] += 1

        needs_user_update = username not in bot_data['seen_users']
        needs_group_update = chat.type in ['group', 'supergroup'] and chat.id not in bot_data['seen_groups']

        now_ts = now.timestamp()
        if now_ts - bot_data['away_cache']['time'] > 60:
            async with pool.acquire() as conn:
                bot_data['away_cache']['data'] = await conn.fetch('SELECT username, reason, end_time, last_notified FROM away_status')
                bot_data['away_cache']['time'] = now_ts
                
        aways = bot_data['away_cache']['data']
        mentions_to_log = []
        is_returning = False

        for a in aways:
            if a['username'] == username:
                is_returning = True
            if f"@{a['username']}" in text:
                mentions_to_log.append(a)

        if chat.type in ['group', 'supergroup']:
            bot_data['chat_buffer'].append((chat.id, username, text))

        buffer_ready = len(bot_data['chat_buffer']) >= 15
        
        if needs_user_update or needs_group_update or is_returning or mentions_to_log or buffer_ready:
            async with pool.acquire() as conn:
                
                if needs_user_update:
                    await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET user_id=$2", username, update.effective_user.id)
                    bot_data['seen_users'].add(username)
                    
                if needs_group_update:
                    await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
                    bot_data['seen_groups'].add(chat.id)

                if bot_data['chat_buffer']:
                    buffer_copy = bot_data['chat_buffer'][:]
                    bot_data['chat_buffer'].clear()
                    await conn.executemany('INSERT INTO chat_history (chat_id, username, message) VALUES ($1, $2, $3)', buffer_copy)

                if bot_data['stats_uses'] > 0:
                    uses_to_log = bot_data['stats_uses']
                    bot_data['stats_uses'] = 0
                    await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, $1, 0) ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + $1", uses_to_log)

                if is_returning:
                    for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
                        j.schedule_removal()
                    import cmd_user
                    recap_msg = await cmd_user.process_return(username, pool, context.bot)
                    try:
                        await context.bot.send_message(update.effective_user.id, f"✅ {recap_msg}", parse_mode="Markdown")
                    except Exception:
                        pass
                    bot_data['away_cache']['time'] = 0 

                if mentions_to_log:
                    for a in mentions_to_log:
                        await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], username, text, chat.title or "DM")
                        
                        last_notified = a['last_notified']
                        if not last_notified or (now - last_notified.astimezone(WIB)).total_seconds() > 3600:
                            await update.message.reply_text(f"Just a heads up, @{a['username']} is away.\n(Reason: {a['reason']})")
                            await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])
                            bot_data['away_cache']['time'] = 0 

    except Exception as e:
        logger.error(f"Global tracker error: {e}")

async def what_did_i_miss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if update.effective_chat.type == "private":
        return await update.message.reply_text("❌ This command must be used in a group.")
        
    pool = context.bot_data.get('db_pool')
    username = update.effective_user.username or str(update.effective_user.id)
    chat_id = update.effective_chat.id
    
    async with pool.acquire() as conn:
        last_msg_time = await conn.fetchval("SELECT created_at FROM chat_history WHERE username=$1 AND chat_id=$2 ORDER BY created_at DESC OFFSET 1 LIMIT 1", username, chat_id)
        limit_time = datetime.datetime.now(WIB) - datetime.timedelta(hours=48)
        target_time = max(last_msg_time, limit_time) if last_msg_time else limit_time
        history = await conn.fetch("SELECT username, message, created_at FROM chat_history WHERE chat_id=$1 AND created_at > $2 ORDER BY created_at ASC", chat_id, target_time)
        
    if not history:
        try:
            await context.bot.send_message(update.effective_user.id, "✅ You haven't missed any messages in this group recently!")
        except Exception:
            await update.message.reply_text("❌ Please start a DM with me first to receive your recap.")
        return
        
    temp = await update.message.reply_text("⏳ Generating your missed activity recap... sending to DM shortly.")
    
    raw_text = "\n".join([f"[{h['created_at'].strftime('%H:%M')}] @{h['username']}: {h['message']}" for h in history])
    prompt = f"You are Nukhba Manager. Summarize this group chat history concisely. Focus ONLY on main topics discussed, announcements, events mentioned, polls, trivia, and notable activity. Do not output a raw message dump. Be conversational and highly readable.\n\n{raw_text[:25000]}"
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = await asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=prompt)
        await context.bot.send_message(update.effective_user.id, f"📝 **What You Missed in {update.effective_chat.title}:**\n\n{resp.text}", parse_mode="Markdown")
        await temp.delete()
    except Exception:
        await temp.edit_text(f"❌ Failed to generate recap. Please DM me first.")

async def submit_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if update.effective_chat.type != "private":
        try:
            await context.bot.send_message(update.effective_user.id, "💡 Please type `/feedback [your suggestion]` here to submit it privately.", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("❌ Please DM me first to submit feedback securely.")
        return
        
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("❌ Usage: `/feedback [explain issue or request here]`", parse_mode="Markdown")
        
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO feedback_drafts (user_id, text) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET text=$2", update.effective_user.id, text)
        
    await process_feedback_submission(update, context, text)

async def process_feedback_submission(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Submit", callback_data="fb_submit")],
        [InlineKeyboardButton("✏️ Edit Once", callback_data="fb_edit")]
    ])
    await context.bot.send_message(update.effective_user.id, f"**Review your feedback:**\n\n_{text}_\n\nDoes this look correct?", reply_markup=kb, parse_mode="Markdown")

async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    action = q.data
    pool = context.bot_data.get('db_pool')
    
    if action == "fb_edit":
        context.user_data['inline_step'] = 'editing_feedback'
        context.user_data['inline_owner'] = update.effective_user.id
        await q.edit_message_text("✏️ Please type your updated feedback now. (You only get one edit chance).")
    elif action == "fb_submit":
        username = q.from_user.username or str(q.from_user.id)
        async with pool.acquire() as conn:
            text = await conn.fetchval("SELECT text FROM feedback_drafts WHERE user_id=$1", q.from_user.id)
            if not text:
                return await q.edit_message_text("❌ Draft expired.")
            await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", username, text)
            await conn.execute("DELETE FROM feedback_drafts WHERE user_id=$1", q.from_user.id)
            
            feedback_channel = await conn.fetchval("SELECT value FROM config WHERE key='feedback_channel'")
        await q.edit_message_text(f"✅ **Feedback Recorded Successfully:**\n\n_{text}_", parse_mode="Markdown")
        if feedback_channel:
            try:
                await context.bot.send_message(int(feedback_channel), f"💡 **New Feedback from @{username}:**\n\n{text}")
            except Exception:
                pass

async def process_gemini_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, is_bot_query: bool = False):
    if not prompt:
        return await update.message.reply_text("❌ Please provide a prompt.")
    if not GEMINI_API_KEY:
        return await update.message.reply_text("❌ GEMINI_API_KEY unconfigured.")
    
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    try:
        is_adm = await is_bot_admin(username, pool)
        is_sup = await is_super(username)
        async with pool.acquire() as conn:
            limit_str = await conn.fetchval("SELECT value FROM config WHERE key='gemini_weekly_limit'") or '20'
            limit = int(limit_str)
            await conn.execute("INSERT INTO users (username, user_id, gemini_quota) VALUES ($1, $2, $3) ON CONFLICT (username) DO NOTHING", username, update.effective_user.id, limit)
            
            if not is_adm:
                limit_left = await conn.fetchval("SELECT gemini_quota FROM users WHERE username=$1", username)
                if limit_left <= 0:
                    return await update.message.reply_text(f"❌ AI limit depleted ({limit}/{limit}).")
                await conn.execute("UPDATE users SET gemini_quota = gemini_quota - 1 WHERE username=$1", username)
                quota_msg = f"_(Limit left: {limit_left - 1})_"
            else:
                quota_msg = "_(Admin: No Limit)_"
            
            configs = await conn.fetch("SELECT key, value FROM config")
            config_dict = {c['key']: c['value'] for c in configs}
            
    except Exception as e:
        return await update.message.reply_text(f"❌ DB Error: {e}")

    temp = await update.message.reply_text("⏳ Thinking...")
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        bt = "`" * 3
        
        if is_bot_query:
            from commands_manifest import COMMANDS
            cmd_list = "\n".join([f"- /{c['name']}: {c['desc']}" for c in COMMANDS])
            
            system_prompt = (
                "You are Nukhba Manager, an advanced Telegram bot. "
                "You have absolute knowledge of all your capabilities.\n\n"
                "== COMMAND REFERENCE ==\n" + cmd_list + "\n\n"
                "== LIVE SYSTEM LIMITS ==\n"
                f"- Weekly Gemini Limit: {config_dict.get('gemini_weekly_limit', 20)}\n"
                f"- Default Star Quota: {config_dict.get('star_quota', 3)}\n"
                f"- Max Tasks per User: {config_dict.get('max_tasks', 4)}\n"
                f"- Max Events per User: {config_dict.get('max_events', 5)}\n"
                f"- Max Away Days: {config_dict.get('max_away_days', 14)}\n\n"
                f"- Trivia timeout: {config_dict.get('trivia_reg_to', 60)}s\n\n"
                "⚠️ STRICT RULE: Your response must NEVER exceed 3000 characters.\n"
            )
            
            if is_adm:
                system_prompt += (
                    "If the admin asks to configure or change a hidden setting, "
                    "output a JSON block exactly like this:\n"
                    f"{bt}json\n"
                    '[{"key": "dm_length", "value": "1000"}, {"key": "star_quota", "value": "5"}]\n'
                    f"{bt}\n"
                )
                
            if is_sup:
                system_prompt += (
                    "⚠️ ROOT PRIVILEGES: To modify python code, output a hotpatch:\n"
                    f"{bt}json\n"
                    "[\n"
                    "  {\n"
                    '    "action": "hotpatch",\n'
                    '    "code": "print(\'hi\')"\n'
                    "  }\n"
                    "]\n"
                    f"{bt}\n"
                )
            
            system_prompt += "\nUser Question: " + prompt
        else:
            system_prompt = "⚠️ STRICT RULE: Your response must NEVER exceed 3000 characters. Be concise.\n\nUser Prompt: " + prompt
            
        response = await asyncio.wait_for(
            asyncio.to_thread(client.models.generate_content, model='gemini-2.0-flash', contents=system_prompt),
            timeout=120.0
        )
        
        reply = response.text
        
        if len(reply) > 3000:
            reply = reply[:2997] + "..."
            
        config_msg = ""
        if is_bot_query and is_adm:
            match = re.search(r"`{3}json\s*\n(.*?)\n\s*`{3}", reply, re.DOTALL)
            if match:
                try:
                    configs = json.loads(match.group(1))
                    async with pool.acquire() as conn:
                        for c in configs:
                            await conn.execute("INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2", c['key'], str(c['value']))
                    reply = re.sub(r"`{3}json\s*\n(.*?)\n\s*`{3}", "", reply, flags=re.DOTALL).strip()
                    config_msg = "\n\n⚙️ *Dynamic configurations successfully applied to the database!*"
                except Exception as e:
                    logger.error(f"Config parse error: {e}")
        
        async with pool.acquire() as conn:
            dm_len_str = await conn.fetchval("SELECT value FROM config WHERE key='dm_length'")
            dm_len = int(dm_len_str) if dm_len_str and dm_len_str.isdigit() else 1000

        prefix = "🤖 **About Me:**\n\n" if is_bot_query else "🤖 **Gemini AI Response:**\n\n"
        inline_prefix = "🤖 **Nukhba Manager:** " if is_bot_query else "🤖 **Gemini:** "
        
        final_reply = reply + config_msg
        
        if len(final_reply) > dm_len and update.effective_chat.type != "private":
            try:
                try:
                    await context.bot.send_message(update.effective_user.id, f"{prefix}{final_reply}", parse_mode="Markdown")
                except Exception:
                    await context.bot.send_message(update.effective_user.id, f"{prefix}{final_reply}")
                
                try:
                    await temp.edit_text(f"✅ It's a bit long, so I sent the answer to your DMs!\n\n{quota_msg}", parse_mode="Markdown")
                except Exception:
                    await temp.edit_text(f"✅ It's a bit long, so I sent the answer to your DMs!\n\n{quota_msg}")
            except Exception:
                try:
                    await temp.edit_text("❌ Please open a private chat with me first so I can DM you.")
                except Exception:
                    pass
                if not is_adm:
                    async with pool.acquire() as conn:
                        await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)
        else: 
            try:
                await temp.edit_text(f"{inline_prefix}{final_reply}\n\n{quota_msg}", parse_mode="Markdown")
            except Exception:
                await temp.edit_text(f"{inline_prefix}{final_reply}\n\n{quota_msg}")
                
    except asyncio.TimeoutError:
        try:
            await temp.edit_text("❌ **AI Timeout:** I thought about it for 120 seconds but couldn't find an answer in time. Please try a simpler request.")
        except Exception:
            pass
        if not is_adm:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)
    except Exception as e:
        if "429" in str(e).lower() or "quota" in str(e).lower():
            try:
                await temp.edit_text("❌ Gemini API credit limit depleted (429). Admins notified.")
            except Exception:
                pass
            async with pool.acquire() as conn:
                admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
                super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
            admin_ids = {a['user_id'] for a in admins if a['user_id']}
            if super_id:
                admin_ids.add(super_id)
            for uid in admin_ids:
                try:
                    await context.bot.send_message(uid, "⚠️ **CRITICAL:** Gemini API limit depleted.", parse_mode="Markdown")
                except Exception:
                    pass
        else: 
            try:
                await temp.edit_text(f"❌ AI Error: {e}")
            except Exception:
                pass
            
        if not is_adm:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)

async def send_md_chunks(bot, chat_id, text, prefix="", suffix=""):
    limit = 3800
    full = f"{prefix}{text}{suffix}"
    if len(full) <= limit:
        try:
            await bot.send_message(chat_id, full, parse_mode="Markdown")
        except Exception:
            await bot.send_message(chat_id, full)
        return

    chunks = []
    current_chunk = prefix
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > limit:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
            
    if len(current_chunk) + len(suffix) > limit:
        chunks.append(current_chunk)
        chunks.append(suffix)
    else:
        current_chunk += suffix
        chunks.append(current_chunk)

    for chunk in chunks:
        if chunk.strip():
            try:
                await bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except Exception:
                await bot.send_message(chat_id, chunk)

async def ask_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), False)

async def ask_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), True)


# ─────────────────────────────────────────────
# BACKGROUND BUFFER FLUSHER
# ─────────────────────────────────────────────
async def flush_chat_buffer(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
        
    buffer = context.bot_data.get('chat_buffer', [])
    stats_uses = context.bot_data.get('stats_uses', 0)
    
    if not buffer and stats_uses == 0:
        return

    try:
        async with pool.acquire() as conn:
            if buffer:
                buffer_copy = buffer[:]
                context.bot_data['chat_buffer'].clear()
                await conn.executemany(
                    'INSERT INTO chat_history (chat_id, username, message) VALUES ($1, $2, $3)', 
                    buffer_copy
                )
                
            if stats_uses > 0:
                context.bot_data['stats_uses'] = 0
                await conn.execute(
                    "INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, $1, 0) "
                    "ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + $1", 
                    stats_uses
                )
    except Exception as e:
        logger.error(f"Failed to auto-flush memory buffer: {e}")
