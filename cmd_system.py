import datetime
import logging
import json
import re
import asyncio
import sys
import importlib
from openai import OpenAI as GroqClient          # Groq uses OpenAI-compatible SDK
from google import genai                           # Gemini kept as fallback only
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, GROQ_API_KEY, is_super, is_bot_admin, log_action, update_user_menu, delete_cmd, schedule_kb_timeout, cancel_kb_timeout
import cmd_user 
import cmd_system_help

logger = logging.getLogger(__name__)

ABOUT_TEXT = """🚀 **Meet Nukhba Manager: Your Ultimate AI Workspace Companion**

Welcome to [RAWWY] Nukhba Manager—a premium, all-in-one enterprise Telegram assistant designed to supercharge team productivity, elevate workplace culture, and inject a little fun into the daily grind.

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

_[RAWWY] Nukhba Manager isn't just managing the chat—it's managing the success, morale, and efficiency of the entire team. Type /help to dive in!_"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    user_id  = update.effective_user.id
    pool     = context.bot_data.get('db_pool')

    if update.effective_chat.type == "private":
        # ✅ Mark this user as DM-able — they've started a private chat with the bot.
        # This is the ONLY reliable way to know Telegram allows us to DM them.
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (username, user_id, can_dm) VALUES ($1, $2, TRUE) "
                "ON CONFLICT (username) DO UPDATE SET user_id=$2, can_dm=TRUE",
                username, user_id
            )
        await update_user_menu(user_id, username, pool, context.bot)

        # Handle deep-link payloads — /start <payload>
        payload = context.args[0] if context.args else ""
        if payload == "open_help":
            await cmd_system_help.help_command(update, context)
            return
        if payload == "open_command":
            import cmd_command_nav
            await cmd_command_nav.command_nav(update, context)
            return

    await update.message.reply_text(
        "✅ **Hello! [RAWWY] Nukhba Manager is fully operational.**\n\n"
        "Type `/help` to see the command manual or `/command` to browse all available commands.",
        parse_mode="Markdown"
    )

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
    txt = (update.message.text or "").strip().lower().split()[0] if update.message else ""
    if txt in ("/config", "/configs"):
        return await update.message.reply_text(
            "💡 `/config` has moved.\n\n"
            "• Use /manual to receive the full PDF guide\n"
            "• Use /command to browse commands interactively",
            parse_mode="Markdown"
        )
    await update.message.reply_text(
        "❓ Unknown command. Use /help to see all commands, or /manual for the full user guide."
    )

async def security_track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat   = result.chat
    pool   = context.bot_data.get('db_pool')

    old_status = result.old_chat_member.status  # what the bot was before
    new_status = result.new_chat_member.status  # what the bot is now

    # ── Bot was just added (wasn't a member before) ───────────────────────────
    if old_status in ('left', 'kicked') and new_status in ('member', 'administrator'):
        inviter = result.from_user.username or str(result.from_user.id)
        invited_by_admin = await is_bot_admin(inviter, pool)
        if not invited_by_admin:
            # Unauthorised add — leave immediately
            try:
                await context.bot.send_message(
                    chat.id,
                    "❌ **Access Denied.**\n\nI can only be added by authorised administrators. Leaving now."
                )
            except Exception:
                pass
            try:
                await context.bot.leave_chat(chat.id)
            except Exception:
                pass
            return
        # Authorised add — register the group
        async with pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2',
                chat.id, chat.title
            )
        return

    # ── Bot was promoted to admin by someone (was already a member) ───────────
    # This covers the case where the bot was added by a Super Admin as a plain
    # member, and later someone (admin/owner of the group) promotes it.
    # We ALLOW this — the bot stays and updates its group record.
    if old_status == 'member' and new_status == 'administrator':
        async with pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO active_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2',
                chat.id, chat.title
            )
        return

    # ── Bot was demoted or left ───────────────────────────────────────────────
    if new_status in ('left', 'kicked'):
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
                    # Only auto-cancel away if the user has the toggle enabled
                    autocancel_key = f"aw_autocancel_{username}"
                    if context.user_data.get(autocancel_key):
                        for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
                            j.schedule_removal()
                        import cmd_user
                        recap_msg = await cmd_user.process_return(username, pool, context.bot)
                        try:
                            await context.bot.send_message(update.effective_user.id, f"✅ {recap_msg}", parse_mode="Markdown")
                        except Exception:
                            pass
                        bot_data['away_cache']['time'] = 0
                        context.user_data.pop(autocancel_key, None)

                if mentions_to_log:
                    for a in mentions_to_log:
                        await conn.execute('INSERT INTO away_mentions (away_username, mentioner, message, chat_title) VALUES ($1, $2, $3, $4)', a['username'], username, text, chat.title or "DM")
                        
                        last_notified = a['last_notified']
                        if not last_notified or (now - last_notified.astimezone(WIB)).total_seconds() > 3600:
                            end_str = a['end_time'].astimezone(WIB).strftime('%b %d at %H:%M') if a.get('end_time') else 'an unspecified time'
                            await update.message.reply_text(
                                f"👋 Just a heads-up — @{a['username']} is currently away.\n"                                f"📝 Reason: _{a['reason']}_\n"                                f"⏰ Back by: {end_str} WIB\n\n"                                f"_Your message has been noted and will be delivered when they return._",
                                parse_mode="Markdown"
                            )
                            await conn.execute('UPDATE away_status SET last_notified=$1 WHERE username=$2', now, a['username'])
                            bot_data['away_cache']['time'] = 0 

    except Exception as e:
        logger.error(f"Global tracker error: {e}")


class _AIResponse:
    """Thin wrapper so callers can always do response.text regardless of provider."""
    def __init__(self, text: str):
        self.text = text


async def _call_groq(prompt: str, max_retries: int = 3, base_delay: int = 5) -> _AIResponse:
    """
    Call Groq API (primary AI provider).
    Uses llama-3.3-70b-versatile as primary, falls back to llama-3.1-8b-instant.
    Groq is OpenAI-SDK-compatible and free with no credit card required.
    """
    models_to_try = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    last_err = None

    for model_name in models_to_try:
        delay = base_delay
        for attempt in range(1, max_retries + 1):
            try:
                client = GroqClient(
                    api_key=GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1"
                )
                resp = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1500,
                )
                return _AIResponse(resp.choices[0].message.content)
            except Exception as e:
                last_err = e
                err_str = str(e)
                is_retryable = (
                    "429" in err_str or "rate_limit" in err_str.lower() or
                    "503" in err_str or "unavailable" in err_str.lower() or
                    "502" in err_str or "connection" in err_str.lower()
                )
                if is_retryable and attempt < max_retries:
                    logger.warning(
                        f"Groq transient error on {model_name} "
                        f"(attempt {attempt}/{max_retries}): {err_str[:80]}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                break  # non-retryable or exhausted → try next model

    raise last_err


async def _call_gemini_fallback(prompt: str, max_retries: int = 2, base_delay: int = 5) -> _AIResponse:
    """
    Gemini fallback — only used when Groq is completely unavailable.
    """
    models_to_try = ['gemini-2.5-flash-lite', 'gemini-2.5-flash']
    last_err = None

    for model_name in models_to_try:
        delay = base_delay
        for attempt in range(1, max_retries + 1):
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=prompt
                )
                return _AIResponse(resp.text)
            except Exception as e:
                last_err = e
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str:
                    break
                is_retryable = (
                    "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or
                    "503" in err_str or "UNAVAILABLE" in err_str
                )
                if is_retryable and attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                break

    raise last_err


async def _generate_content_with_retry(client, contents, max_retries=3, base_delay=5) -> _AIResponse:
    """
    Main AI dispatch: Groq (primary) → Gemini (fallback).
    The `client` param is kept for backwards compatibility but is no longer used;
    clients are created internally per provider.
    """
    # Try Groq first (free, fast, generous daily quota)
    if GROQ_API_KEY:
        try:
            return await _call_groq(contents, max_retries=max_retries, base_delay=base_delay)
        except Exception as groq_err:
            logger.warning(f"Groq failed, falling back to Gemini: {groq_err}")

    # Fall back to Gemini if Groq unavailable or key missing
    if GEMINI_API_KEY:
        return await _call_gemini_fallback(contents, max_retries=2, base_delay=base_delay)

    raise RuntimeError("No AI provider available. Set GROQ_API_KEY (recommended) or GEMINI_API_KEY.")


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
        resp = await _generate_content_with_retry(None, prompt)
        await context.bot.send_message(update.effective_user.id, f"📝 **What You Missed in {update.effective_chat.title}:**\n\n{resp.text}", parse_mode="Markdown")
        await temp.delete()
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            await temp.edit_text("⏳ **Gemini Rate Limited.** The AI is currently busy handling too many requests. Please try your recap again in a few minutes.")
        else:
            await temp.edit_text(f"❌ Failed to generate recap. Error: {err_str[:100]}")

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
    uid = update.effective_user.id
    msg = await context.bot.send_message(uid, f"**Review your feedback:**\n\n_{text}_\n\nDoes this look correct?", reply_markup=kb, parse_mode="Markdown")
    await schedule_kb_timeout(context, uid, msg.message_id, uid)

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
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        return await update.message.reply_text("❌ No AI API key configured. Set GROQ_API_KEY in environment variables.")
    
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
        client = None  # clients are managed inside _generate_content_with_retry
        
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
            
        # Call AI with robust async retry handler and model fallback
        response = await asyncio.wait_for(
            _generate_content_with_retry(client, system_prompt),
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

        prefix = "🤖 **About Me:**\n\n" if is_bot_query else "🤖 **AI Response:**\n\n"
        inline_prefix = "🤖 **Nukhba Manager:** " if is_bot_query else "🤖 **AI:** "
        
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
        err_str = str(e)
        # Detect true API-key exhaustion vs transient rate limit vs other errors
        is_resource_exhausted = "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "rate_limit" in err_str.lower()
        is_key_invalid = "API_KEY_INVALID" in err_str or "API key not valid" in err_str or ("invalid" in err_str.lower() and "key" in err_str.lower())
        is_no_provider = "No AI provider available" in err_str

        if is_no_provider:
            try:
                await temp.edit_text("❌ **No AI key configured.** Please set `GROQ_API_KEY` in your Railway environment variables.")
            except Exception:
                pass
        elif is_key_invalid:
            try:
                await temp.edit_text("❌ **AI API Key Invalid.** Please update `GROQ_API_KEY` in Railway environment variables and redeploy.")
            except Exception:
                pass
            async with pool.acquire() as conn:
                super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
            if super_id:
                try:
                    await context.bot.send_message(super_id, f"⚠️ **CRITICAL:** AI API key is invalid or expired.\n\nError: `{err_str[:300]}`\n\nUpdate `GROQ_API_KEY` in Railway and redeploy.", parse_mode="Markdown")
                except Exception:
                    pass
        elif is_resource_exhausted:
            try:
                await temp.edit_text("⏳ **AI Rate Limited.** Daily free-tier quota reached. Please try again later (resets at midnight UTC).")
            except Exception:
                pass
            logger.warning(f"AI rate limit hit: {err_str[:200]}")
        else:
            try:
                await temp.edit_text(f"❌ AI Error: {err_str[:300]}")
            except Exception:
                pass
            logger.error(f"AI unexpected error: {err_str}")
            
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

# Alias — /ai maps to the same function as /gemini used to
ask_ai = ask_gemini

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
