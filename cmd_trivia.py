import datetime, logging, json, asyncio
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, GEMINI_API_KEY, is_bot_admin

logger = logging.getLogger(__name__)

async def ensure_trivia_database(pool):
    async with pool.acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS trivia_config (key VARCHAR(100) PRIMARY KEY, value TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS trivia_scores (username VARCHAR(100) PRIMARY KEY, monthly_kp INT DEFAULT 0, all_time_kp INT DEFAULT 0)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS active_trivia (chat_id BIGINT PRIMARY KEY, message_id BIGINT, question TEXT, options TEXT, correct_index INT, explanation TEXT, winners TEXT DEFAULT '[]', answered_users TEXT DEFAULT '[]', is_super BOOLEAN, created_at TIMESTAMP WITH TIME ZONE, timeout_seconds INT)''')
        
        defaults = {'target_chat_id': '', 'theme': 'random', 'run_time': '12:00', 'days_mode': 'all', 'num_options': '4', 'status': 'active', 'regular_timeout': '120', 'super_timeout': '180', 'last_run_date': ''}
        for k, v in defaults.items():
            await conn.execute('INSERT INTO trivia_config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING', k, v)

async def trivia_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn:
        theme = await conn.fetchval("SELECT value FROM trivia_config WHERE key='theme'") or 'random'
        time_val = await conn.fetchval("SELECT value FROM trivia_config WHERE key='run_time'") or '12:00'
        days = await conn.fetchval("SELECT value FROM trivia_config WHERE key='days_mode'") or 'all'
        opts = await conn.fetchval("SELECT value FROM trivia_config WHERE key='num_options'") or '4'
        reg_to = await conn.fetchval("SELECT value FROM trivia_config WHERE key='regular_timeout'") or '120'
        sup_to = await conn.fetchval("SELECT value FROM trivia_config WHERE key='super_timeout'") or '180'
    
    text = (
        "🧠 **NUKHBA TRIVIA MASTER ENGINE**\n"
        "──────────────────────────────\n"
        f"🧠 Topic Theme: `{theme}`\n"
        f"⏱️ Daily Release: `{time_val} WIB`\n"
        f"📅 Weekly Pattern: `{days}`\n"
        f"🎯 Choice Layout: `{opts} Options`\n"
        f"⏳ Daily Expiry: `{reg_to} seconds`\n"
        f"🚀 High-Stakes Expiry: `{sup_to} seconds`"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Theme (Random)", callback_data="tcfg_theme"), InlineKeyboardButton("⏱️ +1 Hour", callback_data="tcfg_time")],
        [InlineKeyboardButton("📅 Toggle Days", callback_data="tcfg_days"), InlineKeyboardButton("🎯 Options (+1)", callback_data="tcfg_opts")],
        [InlineKeyboardButton("⏳ Expiry (+10s)", callback_data="tcfg_expiry"), InlineKeyboardButton("🚀 Super (+10s)", callback_data="tcfg_supexpiry")]
    ])
    try: await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    except: await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def trivia_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    act = q.data.split("_")[1]
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(q.from_user.username, pool): return await q.answer("Unauthorized", show_alert=True)
    
    async with pool.acquire() as conn:
        if act == "theme":
            curr = await conn.fetchval("SELECT value FROM trivia_config WHERE key='theme'") or "random"
            await conn.execute("UPDATE trivia_config SET value=$1 WHERE key='theme'", "science" if curr == "random" else "history" if curr == "science" else "random")
        elif act == "time":
            curr = await conn.fetchval("SELECT value FROM trivia_config WHERE key='run_time'") or "12:00"
            h = int(curr.split(":")[0])
            await conn.execute("UPDATE trivia_config SET value=$1 WHERE key='run_time'", f"{(h + 1) % 24:02d}:00")
        elif act == "days":
            curr = await conn.fetchval("SELECT value FROM trivia_config WHERE key='days_mode'") or "all"
            nxt = "weekday" if curr == "all" else "weekend" if curr == "weekday" else "all"
            await conn.execute("UPDATE trivia_config SET value=$1 WHERE key='days_mode'", nxt)
        elif act == "opts":
            curr = int(await conn.fetchval("SELECT value FROM trivia_config WHERE key='num_options'") or "4")
            nxt = 4 if curr >= 6 else curr + 1
            await conn.execute("UPDATE trivia_config SET value=$1 WHERE key='num_options'", str(nxt))
        elif act == "expiry":
            curr = int(await conn.fetchval("SELECT value FROM trivia_config WHERE key='regular_timeout'") or "120")
            nxt = 60 if curr >= 120 else curr + 10
            await conn.execute("UPDATE trivia_config SET value=$1 WHERE key='regular_timeout'", str(nxt))
        elif act == "supexpiry":
            curr = int(await conn.fetchval("SELECT value FROM trivia_config WHERE key='super_timeout'") or "180")
            nxt = 60 if curr >= 180 else curr + 10
            await conn.execute("UPDATE trivia_config SET value=$1 WHERE key='super_timeout'", str(nxt))
            
    await q.answer("Settings updated.")
    await trivia_config(update, context)

async def deploy_trivia_round(bot, chat_id: int, is_super: bool, pool):
    async with pool.acquire() as conn:
        theme = await conn.fetchval("SELECT value FROM trivia_config WHERE key='theme'") or 'random'
        opts_num = int(await conn.fetchval("SELECT value FROM trivia_config WHERE key='num_options'") or '4')
        timeout = int(await conn.fetchval("SELECT value FROM trivia_config WHERE key='super_timeout'") if is_super else await conn.fetchval("SELECT value FROM trivia_config WHERE key='regular_timeout'") or '120')
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"Generate 1 multiple choice trivia question. Theme: {theme}. Provide exactly {6 if is_super else opts_num} distinct options. Return strictly JSON: {{'question':'...', 'options':['...'], 'correct_index':0, 'explanation':'...'}}"
    try:
        resp = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=prompt, config={'response_mime_type': 'application/json'})
        data = json.loads(resp.text)
    except Exception as e:
        logger.error(f"Trivia fail: {e}")
        return
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"trivans_{idx}")] for idx, opt in enumerate(data['options'])])
    title = "🚨 🌟 WEEKLY SUPER TRIVIA QUIZ 🌟 🚨" if is_super else "🧠 📅 DAILY TRIVIA ROUND 📅 🧠"
    warning = "\n⚠️ *WARNING: Incorrect answers on Super Quiz deducts -5 KP penalty points!*" if is_super else ""
    
    msg_text = f"{title}\n\n❓ **Question:** {data['question']}\n\n⏱️ **Timer:** `{timeout}` seconds.\n🎯 **Rewards:** 1st: {60 if is_super else 40} KP | 2nd: {45 if is_super else 25} KP | 3rd: {30 if is_super else 10} KP\n{warning}\nTap choice to lock in!"
    
    try:
        sent = await bot.send_message(chat_id, msg_text, reply_markup=kb, parse_mode="Markdown")
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
            await conn.execute('''INSERT INTO active_trivia (chat_id, message_id, question, options, correct_index, explanation, is_super, created_at, timeout_seconds) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8)''', chat_id, sent.message_id, data['question'], json.dumps(data['options']), data['correct_index'], data['explanation'], is_super, timeout)
    except Exception as e: logger.error(f"Deploy fail: {e}")

async def close_trivia_round(bot, chat_id: int, reason: str, pool):
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
        if not room: return
        await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
        
    options = json.loads(room['options'])
    correct_opt = options[room['correct_index']]
    winners = json.loads(room['winners'])
    
    sb = "🏆 **Winners:**\n" + "".join([f"🥇 @{w['username']} ({w['pts']} KP)\n" for w in winners]) if winners else "• No winners."
    text = f"🏁 **Trivia Closed ({reason})**\n\n❓ **Question:** {room['question']}\n✅ **Answer:** {correct_opt}\n\nℹ️ **Explanation:** {room['explanation']}\n\n{sb}"
    try: await bot.edit_message_text(chat_id=chat_id, message_id=room['message_id'], text=text, parse_mode="Markdown")
    except: pass

async def trivia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data.startswith("tcfg_"): return await trivia_config_callback(update, context)
    
    if q.data == "tcancel_confirm":
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn: await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", update.effective_chat.id)
        return await q.edit_message_text("❌ Trivia Round Cancelled. No KP awarded.")
    if q.data == "tcancel_retry":
        return await q.message.delete()
        
    user_choice = int(q.data.split("_")[1])
    username = q.from_user.username or str(q.from_user.id)
    chat_id = update.effective_chat.id
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
        if not room: return await q.answer("❌ Round closed!", show_alert=True)
            
        answered = json.loads(room['answered_users'])
        winners = json.loads(room['winners'])
        
        if username in answered: return await q.answer("❌ You already locked in your answer!", show_alert=True)
        answered.append(username)
        await conn.execute("UPDATE active_trivia SET answered_users=$1 WHERE chat_id=$2", json.dumps(answered), chat_id)
        
        is_correct = (user_choice == room['correct_index'])
        if is_correct:
            pts_scale = [60, 45, 30] if room['is_super'] else [40, 25, 10]
            if len(winners) < 3:
                awarded = pts_scale[len(winners)]
                winners.append({'username': username, 'pts': awarded})
                await conn.execute("UPDATE active_trivia SET winners=$1 WHERE chat_id=$2", json.dumps(winners), chat_id)
                await conn.execute("INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) ON CONFLICT (username) DO UPDATE SET monthly_kp=trivia_scores.monthly_kp+$2, all_time_kp=trivia_scores.all_time_kp+$2", username, awarded)
                await q.answer(f"✅ Correct! Locked in. Earned {awarded} KP.", show_alert=True)
            else: await q.answer("✅ Correct! But top spots are taken.", show_alert=True)
        else:
            if room['is_super']:
                await conn.execute("INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, 0, 0) ON CONFLICT (username) DO UPDATE SET monthly_kp=GREATEST(0, trivia_scores.monthly_kp-5), all_time_kp=GREATEST(0, trivia_scores.all_time_kp-5)", username)
                await q.answer("❌ Incorrect! -5 KP penalty.", show_alert=True)
            else:
                await q.answer("❌ Incorrect! Answer locked.", show_alert=True)
            
        if len(winners) >= 3:
            context.application.create_task(close_trivia_round(context.bot, chat_id, "Top 3 spots claimed!", pool))

async def trivia_timeout_sweeper(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool: return
    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn: rooms = await conn.fetch("SELECT * FROM active_trivia")
    for r in rooms:
        rem = int((r['created_at'] + datetime.timedelta(seconds=r['timeout_seconds'])).astimezone(WIB) - now).total_seconds()
        if rem <= 0:
            await close_trivia_round(context.bot, r['chat_id'], "Time Limit Exceeded", pool)
        else:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"trivans_{idx}")] for idx, opt in enumerate(json.loads(r['options']))])
            title = "🚨 🌟 WEEKLY SUPER TRIVIA QUIZ 🌟 🚨" if r['is_super'] else "🧠 📅 DAILY TRIVIA ROUND 📅 🧠"
            warning = "\n⚠️ *WARNING: Incorrect answers on Super Quiz deducts -5 KP penalty points!*" if r['is_super'] else ""
            msg = f"{title}\n\n❓ **Question:** {r['question']}\n\n⏱️ **Timer:** `{int(rem)}` seconds.\n🎯 **Rewards:** 1st: {60 if r['is_super'] else 40} KP | 2nd: {45 if r['is_super'] else 25} KP | 3rd: {30 if r['is_super'] else 10} KP\n{warning}\nTap choice to lock in!"
            try: await context.bot.edit_message_text(chat_id=r['chat_id'], message_id=r['message_id'], text=msg, reply_markup=kb, parse_mode="Markdown")
            except: pass

async def trivia_cron_job(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool: return
    now = datetime.datetime.now(WIB)
    current_date = now.strftime('%Y-%m-%d'); day_name = now.strftime('%A').lower()
    is_weekend = day_name in ['saturday', 'sunday']
    async with pool.acquire() as conn:
        if await conn.fetchval("SELECT value FROM trivia_config WHERE key='status'") != 'active': return
        if await conn.fetchval("SELECT value FROM trivia_config WHERE key='last_run_date'") == current_date: return
        tgt = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'")
        if not tgt: return
        
        days_mode = await conn.fetchval("SELECT value FROM trivia_config WHERE key='days_mode'") or 'all'
        if days_mode == 'weekday' and is_weekend: return
        if days_mode == 'weekend' and not is_weekend: return
        
        if now.strftime('%H:%M') != (await conn.fetchval("SELECT value FROM trivia_config WHERE key='run_time'") or '12:00'): return
        await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('last_run_date', $1) ON CONFLICT (key) DO UPDATE SET value=$1", current_date)
        
    context.application.create_task(deploy_trivia_round(context.bot, int(tgt), day_name == 'sunday', pool))

async def run_monthly_trivia_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool or datetime.datetime.now(WIB).day != 1: return
    async with pool.acquire() as conn:
        tgt = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'")
        if not tgt: return
        top = await conn.fetch("SELECT username, monthly_kp FROM trivia_scores WHERE monthly_kp > 0 ORDER BY monthly_kp DESC LIMIT 3")
        await conn.execute("UPDATE trivia_scores SET monthly_kp = 0")
    if not top: return
    msg = "🏆 **NUKHBA TRIVIA MONTHLY CHAMPIONS** 🏆\n\n" + "".join([f"{['🥇', '🥈', '🥉'][i]} **@{u['username']}** — {u['monthly_kp']} KP\n" for i, u in enumerate(top)])
    msg += "\n🔄 *Monthly leaderboard reset!*"
    try: await context.bot.send_message(int(tgt), msg, parse_mode="Markdown")
    except: pass

async def my_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: scores = await conn.fetchrow("SELECT monthly_kp, all_time_kp FROM trivia_scores WHERE username=$1", username)
    msg = f"🧠 **Nukhba KP Status** 🧠\n\n🔹 **Monthly:** `{scores['monthly_kp'] if scores else 0}`\n🔹 **All-Time:** `{scores['all_time_kp'] if scores else 0}`"
    try:
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
        if update.effective_chat.type != "private": await update.message.reply_text("✅ Scores delivered to DM!")
    except: await update.message.reply_text("❌ Please start a DM with me first.")

async def set_trivia_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn: await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('target_chat_id', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(update.effective_chat.id))
    await update.message.reply_text("✅ Trivia channel locked to this group.")

async def force_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    await deploy_trivia_round(context.bot, update.effective_chat.id, False, pool)

async def force_super_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    await deploy_trivia_round(context.bot, update.effective_chat.id, True, pool)

async def cancel_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Resume/Retry", callback_data="tcancel_retry"), InlineKeyboardButton("❌ Confirm Cancel", callback_data="tcancel_confirm")]])
    await update.message.reply_text("Active trivia detected. Cancel round?", reply_markup=kb)

async def pause_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn: await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('status', 'paused') ON CONFLICT (key) DO UPDATE SET value='paused'")
    await update.message.reply_text("⏸️ Trivia paused.")

async def resume_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn: await conn.execute("INSERT INTO trivia_config (key, value) VALUES ('status', 'active') ON CONFLICT (key) DO UPDATE SET value='active'")
    await update.message.reply_text("▶️ Trivia resumed.")

async def set_trivia_theme(update: Update, context: ContextTypes.DEFAULT_TYPE): pass # Handled by /triviaconfig now
async def set_trivia_time(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def set_trivia_days(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def set_trivia_opts(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def set_trivia_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def set_super_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE): pass

async def admin_kp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        user = parts[0].replace("@", ""); op = parts[1].lower(); amt = int(parts[2])
    except: return await update.message.reply_text("❌ `/admin_kp @username , [set|add|sub] , amount`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        if op == 'set': await conn.execute('INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) ON CONFLICT (username) DO UPDATE SET monthly_kp=$2, all_time_kp=$2', user, amt)
        elif op == 'add': await conn.execute('UPDATE trivia_scores SET monthly_kp=monthly_kp+$1, all_time_kp=all_time_kp+$1 WHERE username=$2', amt, user)
        elif op == 'sub': await conn.execute('UPDATE trivia_scores SET monthly_kp=GREATEST(0, monthly_kp-$1), all_time_kp=GREATEST(0, all_time_kp-$1) WHERE username=$2', amt, user)
    await update.message.reply_text(f"✅ Modified scores for **@{user}**.")
