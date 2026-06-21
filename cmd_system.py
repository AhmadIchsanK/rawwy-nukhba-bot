import datetime, logging, json, re, asyncio, sys, importlib
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, log_action, update_user_menu, delete_cmd
import cmd_system_help

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if update.effective_chat.type == "private":
        await update_user_menu(update.effective_user.id, username, pool, context.bot)
    await update.message.reply_text("✅ **Hello! [RW] Nukhba Manager is fully operational.** Type `/help` to see the command manual.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_system_help.help_command(update, context)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ **Unknown Command.** Please type `/help` to see valid commands.", parse_mode="Markdown")

async def security_track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result: return
    chat = result.chat
    status = result.new_chat_member.status
    pool = context.bot_data.get('db_pool')
    
    if status in ['member', 'administrator']:
        inviter = result.from_user.username or str(result.from_user.id)
        if not await is_bot_admin(inviter, pool):
            try:
                await context.bot.send_message(chat.id, "❌ **Access Denied.** Leaving chat.")
                await context.bot.leave_chat(chat.id)
            except: pass
            return
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
    elif status in ['left', 'kicked']:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM active_groups WHERE chat_id=$1', chat.id)

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    pool = context.bot_data.get('db_pool')
    now = datetime.datetime.now(WIB)
    username = update.effective_user.username or str(update.effective_user.id)
    chat = update.effective_chat
    text = update.message.text
    
    # Handle Feedback Edit Flow
    if context.user_data.get('editing_feedback') and chat.type == "private":
        context.user_data['editing_feedback'] = False
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO feedback_drafts (user_id, text) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET text=$2", update.effective_user.id, text)
        await process_feedback_submission(update, context, text)
        return
    
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO users (username, user_id) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET user_id=$2", username, update.effective_user.id)
            await conn.execute("INSERT INTO bot_stats (date, uses) VALUES (CURRENT_DATE, 1) ON CONFLICT (date) DO UPDATE SET uses = bot_stats.uses + 1")
            
            if chat.type in ['group', 'supergroup']:
                await conn.execute('INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2', chat.id, chat.title)
                await conn.execute('INSERT INTO chat_history (chat_id, username, message) VALUES ($1, $2, $3)', chat.id, username, text)
                
            is_away = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username)
            if is_away:
                for j in context.job_queue.get_jobs_by_name(f"away_{username}"): j.schedule_removal()
                import cmd_user
                recap_msg = await cmd_user.process_return(username, pool, context.bot)
                try: await context.bot.send_message(update.effective_user.id, f"✅ {recap_msg}", parse_mode="Markdown")
                except: pass
            
            aways = await conn.fetch('SELECT username, reason, end_time, last_notified FROM away_status')
            for a in aways:
                if f"@{a['username']}" in text:
                    await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], username, text, chat.title or "DM")
                    if not a['last_notified'] or (now - a['last_notified']).total_seconds() > 3600:
                        await update.message.reply_text(f"Just a heads up, @{a['username']} is away.\n(Reason: {a['reason']})")
                        await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])
    except Exception as e:
        logger.error(f"Global tracker error: {e}")

# --- WDIM (What Did I Miss) ---
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
        try: await context.bot.send_message(update.effective_user.id, "✅ You haven't missed any messages in this group recently!")
        except: await update.message.reply_text("❌ Please start a DM with me first to receive your recap.")
        return
        
    temp = await update.message.reply_text("⏳ Generating your missed activity recap... sending to DM shortly.")
    
    raw_text = "\n".join([f"[{h['created_at'].strftime('%H:%M')}] @{h['username']}: {h['message']}" for h in history])
    prompt = f"Summarize this group chat history concisely. Focus ONLY on main topics discussed, events, and notable activity. Do not output a raw message dump.\n\n{raw_text[:25000]}"
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=prompt)
        await context.bot.send_message(update.effective_user.id, f"📝 **What You Missed in {update.effective_chat.title}:**\n\n{resp.text}", parse_mode="Markdown")
        await temp.delete()
    except Exception as e:
        await temp.edit_text(f"❌ Failed to generate recap. Please DM me first.")

# --- FEEDBACK OVERHAUL ---
async def submit_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if update.effective_chat.type != "private":
        try: await context.bot.send_message(update.effective_user.id, "💡 Please type `/feedback [your suggestion]` here to submit it privately.", parse_mode="Markdown")
        except: await update.message.reply_text("❌ Please DM me first to submit feedback securely.")
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
        context.user_data['editing_feedback'] = True
        await q.edit_message_text("✏️ Please type your updated feedback now. (You only get one edit chance).")
    elif action == "fb_submit":
        username = q.from_user.username or str(q.from_user.id)
        async with pool.acquire() as conn:
            text = await conn.fetchval("SELECT text FROM feedback_drafts WHERE user_id=$1", q.from_user.id)
            if not text: return await q.edit_message_text("❌ Draft expired.")
            await conn.execute("INSERT INTO bug_reports (username, report) VALUES ($1, $2)", username, text)
            await conn.execute("DELETE FROM feedback_drafts WHERE user_id=$1", q.from_user.id)
        await q.edit_message_text(f"✅ **Feedback Recorded Successfully:**\n\n_{text}_", parse_mode="Markdown")

# --- GEMINI AI & KNOWLEDGE BASE ---
async def process_gemini_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, is_bot_query: bool = False):
    if not prompt: return await update.message.reply_text("❌ Please provide a prompt.")
    if not GEMINI_API_KEY: return await update.message.reply_text("❌ GEMINI_API_KEY unconfigured.")
    
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    try:
        is_adm = await is_bot_admin(username, pool)
        async with pool.acquire() as conn:
            limit_str = await conn.fetchval("SELECT value FROM config WHERE key='gemini_weekly_limit'") or '20'
            limit = int(limit_str)
            await conn.execute("INSERT INTO users (username, user_id, gemini_quota) VALUES ($1, $2, $3) ON CONFLICT (username) DO NOTHING", username, update.effective_user.id, limit)
            
            if not is_adm:
                limit_left = await conn.fetchval("SELECT gemini_quota FROM users WHERE username=$1", username)
                if limit_left <= 0: return await update.message.reply_text(f"❌ AI limit depleted ({limit}/{limit}).")
                await conn.execute("UPDATE users SET gemini_quota = gemini_quota - 1 WHERE username=$1", username)
                limit_msg = f"_(Limit left: {limit_left - 1})_"
            else: limit_msg = "_(Admin: No Limit)_"
            
            # Fetch Bot Knowledge Configuration
            configs = await conn.fetch("SELECT key, value FROM config")
            config_dict = {c['key']: c['value'] for c in configs}
            
    except Exception as e: return await update.message.reply_text(f"❌ DB Error: {e}")

    temp = await update.message.reply_text("⏳ Thinking...")
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
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
                f"- Max Away Days: {config_dict.get('max_away_days', 14)}\n\n"
                f"User Question: {prompt}"
            )
        else:
            system_prompt = prompt
            
        response = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=system_prompt)
        reply = response.text
        
        dm_len = int(config_dict.get('dm_length', 500))
        prefix = "🤖 **About Me:**\n\n" if is_bot_query else "🤖 **Gemini AI:**\n\n"
        
        if len(reply) > dm_len and update.effective_chat.type != "private":
            try:
                await send_md_chunks(context.bot, update.effective_user.id, reply, prefix)
                await temp.edit_text(f"✅ Sent the answer to your DMs!\n\n{limit_msg}", parse_mode="Markdown")
            except:
                await temp.edit_text("❌ Please open a DM with me first.")
                if not is_adm: async with pool.acquire() as conn: await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)
        else:
            await temp.delete()
            await send_md_chunks(context.bot, update.effective_chat.id, reply, prefix, f"\n\n{limit_msg}")
    except Exception as e:
        await temp.edit_text(f"❌ AI Error: {e}")
        if not is_adm: async with pool.acquire() as conn: await conn.execute("UPDATE users SET gemini_quota = gemini_quota + 1 WHERE username=$1", username)

async def send_md_chunks(bot, chat_id, text, prefix="", suffix=""):
    limit = 3800
    full = f"{prefix}{text}{suffix}"
    if len(full) <= limit:
        try: await bot.send_message(chat_id, full, parse_mode="Markdown")
        except: await bot.send_message(chat_id, full)
        return

    chunks = []; current_chunk = prefix
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > limit:
            chunks.append(current_chunk); current_chunk = line + "\n"
        else: current_chunk += line + "\n"
    if len(current_chunk) + len(suffix) > limit: chunks.append(current_chunk); chunks.append(suffix)
    else: current_chunk += suffix; chunks.append(current_chunk)
    for chunk in chunks:
        if chunk.strip():
            try: await bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except: await bot.send_message(chat_id, chunk)

async def ask_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), False)

async def ask_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_gemini_request(update, context, " ".join(context.args), True)
