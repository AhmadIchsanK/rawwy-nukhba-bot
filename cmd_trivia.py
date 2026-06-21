import datetime, logging, json, re, asyncio
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, GEMINI_API_KEY, is_bot_admin, log_action

logger = logging.getLogger(__name__)

# --- 1/ DATABASE MIGRATIONS & SCHEMA SETUP ---
async def ensure_trivia_database(pool):
    """Safely builds and verifies Postgres tables for trivia metadata & configs."""
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS trivia_config (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS trivia_scores (
                username VARCHAR(100) PRIMARY KEY,
                monthly_kp INT DEFAULT 0,
                all_time_kp INT DEFAULT 0
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS active_trivia (
                chat_id BIGINT PRIMARY KEY,
                message_id BIGINT,
                question TEXT,
                options TEXT,
                correct_index INT,
                explanation TEXT,
                winners TEXT DEFAULT '[]',
                answered_users TEXT DEFAULT '[]',
                is_super BOOLEAN,
                created_at TIMESTAMP WITH TIME ZONE,
                timeout_seconds INT
            )
        ''')
        
        defaults = {
            'target_chat_id': '',
            'theme': 'random',
            'run_time': '12:00',
            'days_mode': 'all',
            'num_options': '4',
            'status': 'active',
            'regular_timeout': '120',
            'super_timeout': '180',
            'last_run_date': ''
        }
        for k, v in defaults.items():
            await conn.execute('''
                INSERT INTO trivia_config (key, value) 
                VALUES ($1, $2) ON CONFLICT (key) DO NOTHING
            ''', k, v)
    logger.info("✅ Trivia module database verification success.")

# --- 2/ TRIVIA GEMINI ENGINE ---
async def generate_trivia_question(is_super: bool, theme: str, num_options: int) -> dict:
    """Contacts Gemini to produce fully formed multi-choice trivia structures."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    opts_num = 6 if is_super else num_options
    prompt_theme = "a broad mixture of general knowledge topics" if theme.lower() == "random" else f"strictly focused around '{theme}'"
    
    system_instruction = (
        "You are an expert trivia master database compiler. Your objective is to return a valid JSON object matching the requested schema.\n\n"
        "Requirements:\n"
        f"1. Generate a single highly engaging multiple-choice trivia question {prompt_theme}.\n"
        f"2. You must provide exactly {opts_num} distinct option answers.\n"
        "3. Select one true correct option index mapped 0-based.\n"
        "4. Provide a fascinating brief description explaining why that choice is scientifically/historically correct.\n"
    )
    
    if is_super:
        system_instruction += "Special Override: This is a Weekly Super Quiz. Make the topic highly advanced, extremely tricky, and covering deep scientific, astronomical, historical, or technological concepts."
    
    prompt = (
        "Respond strictly with a JSON object format. Avoid code wrappers, quotes, or formatting artificial syntax. Example structure:\n"
        '{"question": "What is the capital of France?", "options": ["Paris", "London", "Rome", "Berlin"], "correct_index": 0, "explanation": "Paris is the capital and most populous city of France."}'
    )
    
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-2.5-flash',
            contents=prompt,
            config={'system_instruction': system_instruction, 'response_mime_type': 'application/json'}
        )
        data = json.loads(response.text)
        if not all(k in data for k in ["question", "options", "correct_index", "explanation"]):
            raise ValueError("Incomplete schema parameters returned.")
        return data
    except Exception as e:
        logger.error(f"Gemini Trivia generation error: {e}")
        if is_super:
            return {
                "question": "Which of these subatomic particles was postulated to maintain the exclusion principle?",
                "options": ["Quark", "Fermion", "Boson", "Gluon", "Lepton", "Hadron"],
                "correct_index": 1,
                "explanation": "Enrico Fermi proposed fermions, which comply with Pauli's exclusion principle."
            }
        else:
            return {
                "question": "What is the primary core structural material of Earth's inner core?",
                "options": ["Silicon", "Nickel", "Iron", "Gold"],
                "correct_index": 2,
                "explanation": "Earth's core is primarily composed of an iron-nickel alloy."
            }

# --- 3/ INTERACTIVE UI & DEPLOYMENT ---
async def deploy_trivia_round(bot, chat_id: int, is_super: bool, pool):
    """Generates trivia content and deploys the custom interactive inline interface."""
    async with pool.acquire() as conn:
        theme = await conn.fetchval("SELECT value FROM trivia_config WHERE key='theme'") or 'random'
        opts_str = await conn.fetchval("SELECT value FROM trivia_config WHERE key='num_options'") or '4'
        opts_num = int(opts_str) if opts_str.isdigit() else 4
        
        reg_timeout = await conn.fetchval("SELECT value FROM trivia_config WHERE key='regular_timeout'") or '120'
        sup_timeout = await conn.fetchval("SELECT value FROM trivia_config WHERE key='super_timeout'") or '180'
        timeout = int(sup_timeout) if is_super else int(reg_timeout)
        
    trivia_data = await generate_trivia_question(is_super, theme, opts_num)
    
    title = "🚨 🌟 WEEKLY SUPER TRIVIA QUIZ 🌟 🚨" if is_super else "🧠 📅 DAILY TRIVIA ROUND 📅 🧠"
    warning = "\n⚠️ *WARNING: Incorrect answers on Super Quiz deducts -5 KP penalty points!*" if is_super else ""
    
    msg_text = (
        f"{title}\n\n"
        f"❓ **Question:** {trivia_data['question']}\n\n"
        f"⏱️ **Timer:** This round automatically locks in `{timeout}` seconds.\n"
        f"🎯 **Rewards:** 1st: {60 if is_super else 40} KP | 2nd: {45 if is_super else 30} KP | 3rd: {30 if is_super else 20} KP\n"
        f"{warning}\n"
        "Tap your choice below to lock in your final answer!"
    )
    
    buttons = []
    current_row = []
    for idx, opt in enumerate(trivia_data['options']):
        current_row.append(InlineKeyboardButton(opt, callback_data=f"trivans_{idx}"))
        if len(current_row) == 2:
            buttons.append(current_row)
            current_row = []
    if current_row:
        buttons.append(current_row)
        
    keyboard = InlineKeyboardMarkup(buttons)
    
    try:
        sent_msg = await bot.send_message(chat_id, msg_text, reply_markup=keyboard, parse_mode="Markdown")
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
            await conn.execute('''
                INSERT INTO active_trivia (chat_id, message_id, question, options, correct_index, explanation, is_super, created_at, timeout_seconds)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8)
            ''', chat_id, sent_msg.message_id, trivia_data['question'], json.dumps(trivia_data['options']), trivia_data['correct_index'], trivia_data['explanation'], is_super, timeout)
    except Exception as e:
        logger.error(f"Failed to deploy trivia round: {e}")

# --- 4/ ANSWER REVEAL & STATE CLOSURE ---
async def close_trivia_round(bot, chat_id: int, reason: str, pool):
    """Wipes active session structures, calculates point balance edits, and posts correct details."""
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
        if not room: return
        await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
        
    options = json.loads(room['options'])
    correct_opt = options[room['correct_index']]
    winners = json.loads(room['winners'])
    
    score_board = "🏆 **Leaderboard Winners:**\n"
    if winners:
        for idx, win in enumerate(winners):
            score_board += f"🥇 {idx+1}. @{win['username']} ({win['pts']} KP)\n"
    else:
        score_board += "• No winners recorded this round.\n"
        
    close_text = (
        f"🏁 **Trivia Round Closed ({reason})**\n\n"
        f"❓ **Question:** {room['question']}\n"
        f"✅ **Correct Answer:** {correct_opt}\n\n"
        f"ℹ️ **Explanation:** {room['explanation']}\n\n"
        f"{score_board}"
    )
    
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=room['message_id'], text=close_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to edit trivia close message: {e}")

# --- 5/ CALLBACK PROCESSOR MATRIX ---
async def trivia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes interactive inline taps, manages strict point calculations, and applies penalty configurations."""
    q = update.callback_query
    data_parts = q.data.split("_")
    user_choice = int(data_parts[1])
    username = q.from_user.username or str(q.from_user.id)
    chat_id = update.effective_chat.id
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
        if not room:
            return await q.answer("❌ This trivia round has already closed!", show_alert=True)
            
        answered = json.loads(room['answered_users'])
        winners = json.loads(room['winners'])
        
        if username in answered:
            return await q.answer("❌ You have already submitted an answer for this round!", show_alert=True)
            
        answered.append(username)
        await conn.execute("UPDATE active_trivia SET answered_users=$1 WHERE chat_id=$2", json.dumps(answered), chat_id)
        
        is_correct = (user_choice == room['correct_index'])
        is_super = room['is_super']
        
        if is_correct:
            placement = len(winners)
            points_scale = [60, 45, 30] if is_super else [40, 30, 20]
            
            if placement < 3:
                awarded_pts = points_scale[placement]
                winners.append({'username': username, 'pts': awarded_pts})
                await conn.execute("UPDATE active_trivia SET winners=$1 WHERE chat_id=$2", json.dumps(winners), chat_id)
                
                await conn.execute('''
                    INSERT INTO trivia_scores (username, monthly_kp, all_time_kp)
                    VALUES ($1, $2, $2) ON CONFLICT (username)
                    DO UPDATE SET monthly_kp = trivia_scores.monthly_kp + $2, all_time_kp = trivia_scores.all_time_kp + $2
                ''', username, awarded_pts)
                
                await q.answer(f"🎉 Correct Answer! Placed #{placement+1}. Awarded {awarded_pts} KP!", show_alert=True)
            else:
                await q.answer("🎉 Correct Answer! However, all scoring positions are filled.", show_alert=True)
        else:
            if is_super:
                await conn.execute('''
                    INSERT INTO trivia_scores (username, monthly_kp, all_time_kp)
                    VALUES ($1, 0, 0) ON CONFLICT (username)
                    DO UPDATE SET monthly_kp = GREATEST(0, trivia_scores.monthly_kp - 5), all_time_kp = GREATEST(0, trivia_scores.all_time_kp - 5)
                ''', username)
                await q.answer("❌ Incorrect! Penalty of -5 KP applied.", show_alert=True)
            else:
                await q.answer("❌ Incorrect! Better luck next time.", show_alert=True)
                
        if len(winners) >= 3:
            context.application.create_task(close_trivia_round(context.bot, chat_id, "All top spots claimed!", pool))

# --- 6/ BACKLOG TIMEOUT SWEEPERS ---
async def trivia_timeout_sweeper(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool: return
    async with pool.acquire() as conn:
        lapsed_rooms = await conn.fetch('''
            SELECT chat_id FROM active_trivia 
            WHERE created_at + (timeout_seconds * INTERVAL '1 second') < NOW()
        ''')
    for room in lapsed_rooms:
        await close_trivia_round(context.bot, room['chat_id'], "Time Limit Exceeded", pool)

# --- 7/ SCHEDULERS & BROADCAST ENGINES ---
async def trivia_cron_job(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool: return
    
    now = datetime.datetime.now(WIB)
    current_date = now.strftime('%Y-%m-%d')
    day_name = now.strftime('%A').lower()
    is_weekend = day_name in ['saturday', 'sunday']
    
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT value FROM trivia_config WHERE key='status'") or 'active'
        if status != 'active': return
        
        last_run = await conn.fetchval("SELECT value FROM trivia_config WHERE key='last_run_date'") or ''
        if last_run == current_date: return
        
        run_time_str = await conn.fetchval("SELECT value FROM trivia_config WHERE key='run_time'") or '12:00'
        target_chat_str = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''
        days_mode = await conn.fetchval("SELECT value FROM trivia_config WHERE key='days_mode'") or 'all'
        
        if not target_chat_str: return
        target_chat_id = int(target_chat_str)
        
        if days_mode == 'weekday' and is_weekend: return
        if days_mode == 'weekend' and not is_weekend: return
        
        current_time_str = now.strftime('%H:%M')
        if current_time_str != run_time_str: return
        
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('last_run_date', $1) ON CONFLICT (key) DO UPDATE SET value=$1", current_date)
        
    is_super_day = (day_name == 'sunday')
    context.application.create_task(deploy_trivia_round(context.bot, target_chat_id, is_super_day, pool))

async def run_monthly_trivia_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool: return
    async with pool.acquire() as conn:
        target_chat_str = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''
        if not target_chat_str: return
        target_chat_id = int(target_chat_str)
        
        top_minds = await conn.fetch('''
            SELECT username, monthly_kp FROM trivia_scores 
            WHERE monthly_kp > 0 ORDER BY monthly_kp DESC LIMIT 3
        ''')
        await conn.execute("UPDATE trivia_scores SET monthly_kp = 0")
        
    if not top_minds: return
    announcement = "🏆 **NUKHBA TRIVIA MONTHLY CHAMPIONS** 🏆\n\nCongratulations to our top minds this month! Your brilliance shines supreme:\n\n"
    podiums = ["🥇", "🥈", "🥉"]
    for idx, user in enumerate(top_minds):
        announcement += f"{podiums[idx]} **@{user['username']}** — {user['monthly_kp']} Knowledge Points (KP) earned!\n"
    announcement += "\n🔄 *Monthly leaderboard stats have been reset! All-time stats remain captured. Let the races begin again!*"
    try:
        await context.bot.send_message(target_chat_id, announcement, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to announce monthly reset: {e}")

# --- 8/ USER LEVEL CONTROLS ---
async def my_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends current monthly and all-time user points privately to DM."""
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        scores = await conn.fetchrow("SELECT monthly_kp, all_time_kp FROM trivia_scores WHERE username=$1", username)
        
    monthly = scores['monthly_kp'] if scores else 0
    all_time = scores['all_time_kp'] if scores else 0
    text = (
        f"🧠 **Nukhba Knowledge Point Status** 🧠\n\n"
        f"🔹 **Monthly KP:** `{monthly}`\n"
        f"🔹 **All-Time KP:** `{all_time}`\n\n"
        "Keep exercising your mind in daily challenges!"
    )
    try:
        await context.bot.send_message(update.effective_user.id, text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await update.message.reply_text("✅ Your knowledge scores have been delivered privately to your DMs!")
    except:
        await update.message.reply_text("❌ Failed to message you privately! Please initiate a DM chat with me first.")

# --- 9/ ADMINISTRATIVE MANAGEMENT COMMANDS ---
async def set_trivia_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    chat_id = update.effective_chat.id
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('target_chat_id', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(chat_id))
    await update.message.reply_text(f"✅ Trivia channel destination successfully locked to this group! ID: `{chat_id}`", parse_mode="Markdown")

async def set_trivia_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    theme = " ".join(context.args).strip()
    if not theme: return await update.message.reply_text("❌ Usage: `/settriviatheme [topic_name | random]`")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('theme', $1) ON CONFLICT (key) DO UPDATE SET value=$1", theme)
    await update.message.reply_text(f"✅ Automatic trivia theme updated to: **{theme}**", parse_mode="Markdown")

async def set_trivia_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    time_str = " ".join(context.args).strip()
    if not re.match(r'^\d{2}:\d{2}$', time_str):
        return await update.message.reply_text("❌ Incorrect Time Format! Must match `HH:MM` (using a 24-hour cycle layout).")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('run_time', $1) ON CONFLICT (key) DO UPDATE SET value=$1", time_str)
    await update.message.reply_text(f"✅ Automatic Daily deployment clock set to: **{time_str} WIB**", parse_mode="Markdown")

async def set_trivia_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    days = " ".join(context.args).lower().strip()
    if days not in ['all', 'weekday', 'weekend']:
        return await update.message.reply_text("❌ Invalid days configuration! Select `all`, `weekday`, or `weekend`.")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('days_mode', $1) ON CONFLICT (key) DO UPDATE SET value=$1", days)
    await update.message.reply_text(f"✅ Automatic trivia scheduler days updated to: **{days}**", parse_mode="Markdown")

async def set_trivia_opts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try:
        val = int(context.args[0])
        if val < 4 or val > 6: raise ValueError
    except:
        return await update.message.reply_text("❌ Invalid settings! Number of options must fall within `4` and `6`.")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('num_options', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(val))
    await update.message.reply_text(f"✅ Options layout dynamically config-locked to: **{val} choices**", parse_mode="Markdown")

async def set_trivia_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try:
        val = int(context.args[0])
        if val < 30: raise ValueError
    except:
        return await update.message.reply_text("❌ Minimum timeout threshold limit is 30 seconds.")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('regular_timeout', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(val))
    await update.message.reply_text(f"✅ Regular daily timeout parameters updated to: **{val} seconds**", parse_mode="Markdown")

async def set_super_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try:
        val = int(context.args[0])
        if val < 30: raise ValueError
    except:
        return await update.message.reply_text("❌ Minimum timeout threshold limit is 30 seconds.")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('super_timeout', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(val))
    await update.message.reply_text(f"✅ Weekly super quiz timeout parameters set to: **{val} seconds**", parse_mode="Markdown")

async def pause_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('status', 'paused') ON CONFLICT (key) DO UPDATE SET value='paused'")
    await update.message.reply_text("⏸️ Automatic daily trivia scheduler system **PAUSED**.")

async def resume_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('status', 'active') ON CONFLICT (key) DO UPDATE SET value='active'")
    await update.message.reply_text("▶️ Automatic daily trivia scheduler system **RESUMED**.")

async def force_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    await update.message.reply_text("⏳ Generating Daily Trivia question...")
    await deploy_trivia_round(context.bot, update.effective_chat.id, False, pool)

async def force_super_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    await update.message.reply_text("⏳ Compiling Super Trivia parameters...")
    await deploy_trivia_round(context.bot, update.effective_chat.id, True, pool)

async def cancel_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    chat_id = update.effective_chat.id
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
        if not room: return await update.message.reply_text("❌ No active running trivia found in this group.")
        await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
    try: await context.bot.edit_message_text(chat_id=chat_id, message_id=room['message_id'], text="❌ **Trivia Round Cancelled by Admin.**")
    except: pass
    await update.message.reply_text("✅ Ongoing active running trivia round dropped immediately.")

async def admin_kp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try:
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        user = parts[0].replace("@", "")
        op = parts[1].lower()
        amount = int(parts[2])
        if op not in ['set', 'add', 'sub']: raise ValueError
    except:
        return await update.message.reply_text("❌ Usage Format: `/admin_kp @username , [set|add|sub] , amount`", parse_mode="Markdown")
        
    async with pool.acquire() as conn:
        if op == 'set':
            await conn.execute('''
                INSERT INTO trivia_scores (username, monthly_kp, all_time_kp)
                VALUES ($1, $2, $2) ON CONFLICT (username)
                DO UPDATE SET monthly_kp = $2, all_time_kp = $2
            ''', user, amount)
        elif op == 'add':
            await conn.execute('''
                INSERT INTO trivia_scores (username, monthly_kp, all_time_kp)
                VALUES ($1, $2, $2) ON CONFLICT (username)
                DO UPDATE SET monthly_kp = trivia_scores.monthly_kp + $2, all_time_kp = trivia_scores.all_time_kp + $2
            ''', user, amount)
        elif op == 'sub':
            await conn.execute('''
                INSERT INTO trivia_scores (username, monthly_kp, all_time_kp)
                VALUES ($1, 0, 0) ON CONFLICT (username)
                DO UPDATE SET monthly_kp = GREATEST(0, trivia_scores.monthly_kp - $2), all_time_kp = GREATEST(0, trivia_scores.all_time_kp - $2)
            ''', user, amount)
        scores = await conn.fetchrow("SELECT monthly_kp, all_time_kp FROM trivia_scores WHERE username=$1", user)
    await update.message.reply_text(f"✅ Modified scores for **@{user}**! Monthly score: `{scores['monthly_kp']}` KP | All-time: `{scores['all_time_kp']}` KP.", parse_mode="Markdown")