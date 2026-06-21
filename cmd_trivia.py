import datetime
import logging
import json
import asyncio
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, GEMINI_API_KEY, is_bot_admin, delete_cmd

logger = logging.getLogger(__name__)

THEME_MAP = {
    "0": "Random", "1": "Movies & TV Shows", "2": "Gaming", "3": "Sports & Esports",
    "4": "Music", "5": "Geography", "6": "General Knowledge", "7": "History",
    "8": "Science & Technology", "9": "Food & Drink", "10": "Anime / Manga & Comics"
}

async def ensure_trivia_database(pool):
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS trivia_scores (username VARCHAR(100) PRIMARY KEY, monthly_kp INT DEFAULT 0, all_time_kp INT DEFAULT 0)
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS active_trivia (
                chat_id BIGINT PRIMARY KEY, message_id BIGINT, question TEXT, options TEXT, correct_index INT,
                explanation TEXT, winners TEXT DEFAULT '[]', answered_users TEXT DEFAULT '[]', is_super BOOLEAN,
                expires_at TIMESTAMP WITH TIME ZONE
            )
        ''')
        defaults = {"trivia_theme": "Random", "trivia_time": "12:00", "trivia_days": "all", "trivia_opts": "4", "trivia_reg_to": "60", "trivia_sup_to": "120"}
        for k, v in defaults.items():
            await conn.execute("INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT DO NOTHING", k, v)

async def trivia_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type != "private":
        return await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ For security, please run `/triviaconfig` in my Direct Messages.")
    
    async with pool.acquire() as conn:
        theme = await conn.fetchval("SELECT value FROM config WHERE key='trivia_theme'") or 'Random'
        t_time = await conn.fetchval("SELECT value FROM config WHERE key='trivia_time'") or '12:00'
        days = await conn.fetchval("SELECT value FROM config WHERE key='trivia_days'") or 'all'
        opts = await conn.fetchval("SELECT value FROM config WHERE key='trivia_opts'") or '4'
        reg_to = await conn.fetchval("SELECT value FROM config WHERE key='trivia_reg_to'") or '60'
    
    context.user_data['tcfg_draft'] = {
        'theme': theme, 'run_time': t_time, 'days': days, 'opts': opts, 'reg_to': reg_to
    }
    await render_tcfg_menu(update, context)

async def render_tcfg_menu(update, context, is_edit=False):
    d = context.user_data.get('tcfg_draft')
    if not d:
        return
    
    text = (
        "🧠 **NUKHBA TRIVIA MASTER ENGINE**\n"
        "──────────────────────────────\n"
        f"🧠 Topic Theme: `{d['theme']}`\n"
        f"⏱️ Daily Release: `{d['run_time']} WIB`\n"
        f"📅 Weekly Pattern: `{d['days']}`\n"
        f"🎯 Choice Layout: `{d['opts']} Options`\n"
        f"⏳ Daily Expiry: `{d['reg_to']} seconds`\n\n"
        "*(Note: Settings only apply after pressing Finish / Save)*"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Theme", callback_data="tcfg_seltheme"), InlineKeyboardButton("📅 Toggle Days", callback_data="tcfg_days")],
        [InlineKeyboardButton("⏱️ +1h", callback_data="tcfg_tadd"), InlineKeyboardButton("⏱️ -1h", callback_data="tcfg_tsub"), InlineKeyboardButton("⏱️ Custom Time", callback_data="tcfg_tcus")],
        [InlineKeyboardButton("🎯 Options Count", callback_data="tcfg_opts"), InlineKeyboardButton("⏳ Expiry (+10s)", callback_data="tcfg_expiry")],
        [InlineKeyboardButton("✅ Finish / Save", callback_data="tcfg_save")]
    ])
    
    if is_edit:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
    else:
        try:
            msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            msg = await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        context.user_data['tcfg_msg_id'] = msg.message_id

async def trivia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pool = context.bot_data.get('db_pool')
    
    if q.data.startswith("tcfg_"):
        if not await is_bot_admin(q.from_user.username, pool):
            return await q.answer("Unauthorized", show_alert=True)
        act = q.data.split("_")[1]
        d = context.user_data.get('tcfg_draft')
        if not d and act != "save":
            return await q.answer("Draft expired. Run /triviaconfig again.", show_alert=True)

        if act == "seltheme":
            buttons = []
            for k, v in THEME_MAP.items():
                buttons.append([InlineKeyboardButton(v, callback_data=f"tcfg_thm_{k}")])
            buttons.append([InlineKeyboardButton("✏️ Custom Input", callback_data="tcfg_thm_custom")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="tcfg_back")])
            return await q.edit_message_text("Select a Theme:", reply_markup=InlineKeyboardMarkup(buttons))
            
        elif act.startswith("thm_"):
            val = q.data.split("_", 2)[2]
            if val == "custom":
                context.user_data['awaiting_tcfg_theme'] = True
                return await q.edit_message_text("✏️ Please type your custom theme in the chat now:")
            else:
                d['theme'] = THEME_MAP.get(val, "Random")
                return await render_tcfg_menu(update, context, True)
                
        elif act == "tadd":
            h, m = map(int, d['run_time'].split(":"))
            d['run_time'] = f"{(h+1)%24:02d}:{m:02d}"
        elif act == "tsub":
            h, m = map(int, d['run_time'].split(":"))
            d['run_time'] = f"{(h-1)%24:02d}:{m:02d}"
        elif act == "tcus":
            context.user_data['awaiting_tcfg_time'] = True
            return await q.edit_message_text("✏️ Please type exact time (HH:MM format, 24-hr):")
            
        elif act == "days":
            d['days'] = "weekday" if d['days'] == "all" else "weekend" if d['days'] == "weekday" else "all"
        elif act == "opts":
            curr = int(d['opts'])
            d['opts'] = str(4 if curr >= 6 else curr + 1)
        elif act == "expiry":
            curr = int(d['reg_to'])
            d['reg_to'] = str(60 if curr >= 120 else curr + 10)
        elif act == "back":
            return await render_tcfg_menu(update, context, True)
        elif act == "save":
            if not d:
                return await q.answer("Draft expired.", show_alert=True)
            async with pool.acquire() as conn:
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_theme'", d['theme'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_time'", d['run_time'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_days'", d['days'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_opts'", d['opts'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_reg_to'", d['reg_to'])
            del context.user_data['tcfg_draft']
            return await q.edit_message_text("✅ **Trivia Config Saved & Applied!**", parse_mode="Markdown")
            
        await q.answer()
        return await render_tcfg_menu(update, context, True)
        
    elif q.data.startswith("tcancel_"):
        if not await is_bot_admin(q.from_user.username, pool):
            return await q.answer("Unauthorized", show_alert=True)
        act = q.data.split("_")[1]
        chat_id = update.effective_chat.id
        async with pool.acquire() as conn: 
            room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
            if room:
                await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
        if act == "confirm":
            await q.message.delete()
            try:
                await context.bot.send_message(chat_id, "❌ **Trivia Round Cancelled by Admin. No Knowledge Points awarded.**", parse_mode="Markdown")
            except Exception:
                pass
            return
        elif act == "retry" and room:
            await q.message.delete()
            return await deploy_trivia(context.bot, chat_id, room['is_super'], pool)
            
    elif q.data.startswith("trivans_"):
        user_choice = int(q.data.split("_")[1])
        username = q.from_user.username or str(q.from_user.id)
        chat_id = update.effective_chat.id
        
        async with pool.acquire() as conn:
            room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
            if not room:
                return await q.answer("Round is closed!", show_alert=True)
                
            answered = json.loads(room['answered_users'])
            winners = json.loads(room['winners'])
            
            if username in answered:
                return await q.answer("❌ You already locked in your answer! No second chances.", show_alert=True)
                
            answered.append(username)
            await conn.execute("UPDATE active_trivia SET answered_users=$1 WHERE chat_id=$2", json.dumps(answered), chat_id)
            
            if user_choice == room['correct_index']:
                pts_scale = [60, 45, 30] if room['is_super'] else [40, 25, 10]
                pts = pts_scale[len(winners)] if len(winners) < 3 else 0
                if pts > 0:
                    winners.append({'username': username, 'pts': pts})
                    await conn.execute("UPDATE active_trivia SET winners=$1 WHERE chat_id=$2", json.dumps(winners), chat_id)
                    await conn.execute("INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) ON CONFLICT (username) DO UPDATE SET monthly_kp=trivia_scores.monthly_kp+$2, all_time_kp=trivia_scores.all_time_kp+$2", username, pts)
                    await q.answer(f"✅ Correct! Locked in. Earned {pts} Knowledge Points.", show_alert=True)
                else:
                    await q.answer("✅ Correct! But top 3 spots are taken.", show_alert=True)
            else:
                if room['is_super']:
                    await conn.execute("INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, 0, 0) ON CONFLICT (username) DO UPDATE SET monthly_kp=GREATEST(0, trivia_scores.monthly_kp-5), all_time_kp=GREATEST(0, trivia_scores.all_time_kp-5)", username)
                    await q.answer("❌ Incorrect! Penalty of -5 Knowledge Points applied.", show_alert=True)
                else:
                    await q.answer("❌ Incorrect! Answer locked.", show_alert=True)
                
            if len(winners) >= 3:
                await close_trivia_round(context.bot, chat_id, "Top 3 Winners Reached!", pool)

async def deploy_trivia(bot, chat_id: int, is_super: bool, pool):
    async with pool.acquire() as conn:
        theme = await conn.fetchval("SELECT value FROM config WHERE key='trivia_theme'") or 'Random'
        opts = int(await conn.fetchval("SELECT value FROM config WHERE key='trivia_opts'") or '4')
        timeout = int(await conn.fetchval("SELECT value FROM config WHERE key='trivia_sup_to'") if is_super else await conn.fetchval("SELECT value FROM config WHERE key='trivia_reg_to'") or '60')
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"Generate 1 multiple choice trivia question. Theme: {theme}. Provide exactly {6 if is_super else opts} options. Return strictly JSON: {{'question':'...', 'options':['...'], 'correct_index':0, 'explanation':'...'}}"
    
    try:
        resp = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=prompt, config={'response_mime_type': 'application/json'})
        data = json.loads(resp.text)
    except Exception:
        return
    
    expires_at = datetime.datetime.now(WIB) + datetime.timedelta(seconds=timeout)
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"trivans_{idx}")] for idx, opt in enumerate(data['options'])])
    
    title = "🚨 WEEKLY SUPER TRIVIA 🚨" if is_super else "🧠 DAILY TRIVIA 🧠"
    msg_text = f"{title}\n\n❓ **{data['question']}**\n\n⏱️ **Time Remaining:** {timeout}s\n*(No second chances. Answer locks immediately!)*"
    
    sent = await bot.send_message(chat_id, msg_text, reply_markup=kb, parse_mode="Markdown")
    
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
        await conn.execute("INSERT INTO active_trivia (chat_id, message_id, question, options, correct_index, explanation, is_super, expires_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)", chat_id, sent.message_id, data['question'], json.dumps(data['options']), data['correct_index'], data['explanation'], is_super, expires_at)

async def close_trivia_round(bot, chat_id, reason, pool):
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
        if not room:
            return
        await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
        
    opts = json.loads(room['options'])
    correct = opts[room['correct_index']]
    winners = json.loads(room['winners'])
    board = "🏆 **Winners:**\n" + "".join([f"🥇 @{w['username']} (+{w['pts']} Knowledge Points)\n" for w in winners]) if winners else "• No winners."
    
    text = f"🏁 **Trivia Closed ({reason})**\n\n❓ {room['question']}\n✅ **Answer:** {correct}\n\nℹ️ **Why:** {room['explanation']}\n\n{board}"
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=room['message_id'], text=text, parse_mode="Markdown")
    except Exception:
        pass

async def trivia_timeout_sweeper(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        rooms = await conn.fetch("SELECT * FROM active_trivia")
    for r in rooms:
        rem = int((r['expires_at'].astimezone(WIB) - now).total_seconds())
        if rem <= 0:
            await close_trivia_round(context.bot, r['chat_id'], "Time Limit Exceeded", pool)
        else:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"trivans_{idx}")] for idx, opt in enumerate(json.loads(r['options']))])
            title = "🚨 WEEKLY SUPER TRIVIA 🚨" if r['is_super'] else "🧠 DAILY TRIVIA 🧠"
            try:
                await context.bot.edit_message_text(chat_id=r['chat_id'], message_id=r['message_id'], text=f"{title}\n\n❓ **{r['question']}**\n\n⏱️ **Time Remaining:** {rem}s\n*(No second chances. Answer locks immediately!)*", reply_markup=kb, parse_mode="Markdown")
            except Exception:
                pass

async def force_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    await deploy_trivia(context.bot, update.effective_chat.id, False, pool)

async def force_super_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    await deploy_trivia(context.bot, update.effective_chat.id, True, pool)

async def cancel_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Resume/Retry", callback_data="tcancel_retry"), InlineKeyboardButton("❌ Confirm Cancel", callback_data="tcancel_confirm")]])
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Active trivia detected. Are you sure you want to cancel with no Knowledge Points awarded?", reply_markup=kb)

async def admin_kp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        user = parts[0].replace("@", "")
        op = parts[1].lower()
        amount = int(parts[2])
    except Exception:
        return await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Usage Format: `/admin_kp [@username] , [set|add|sub] , [amount]`", parse_mode="Markdown")
        
    async with pool.acquire() as conn:
        if op == 'set':
            await conn.execute("INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) ON CONFLICT (username) DO UPDATE SET monthly_kp = $2, all_time_kp = $2", user, amount)
        elif op == 'add':
            await conn.execute("INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) ON CONFLICT (username) DO UPDATE SET monthly_kp = trivia_scores.monthly_kp + $2, all_time_kp = trivia_scores.all_time_kp + $2", user, amount)
        elif op == 'sub':
            await conn.execute("INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, 0, 0) ON CONFLICT (username) DO UPDATE SET monthly_kp = GREATEST(0, trivia_scores.monthly_kp - $2), all_time_kp = GREATEST(0, trivia_scores.all_time_kp - $2)", user, amount)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Modified Knowledge Points for **@{user}**!", parse_mode="Markdown")

async def my_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        scores = await conn.fetchrow("SELECT monthly_kp, all_time_kp FROM trivia_scores WHERE username=$1", username)
    text = f"🧠 **Nukhba Knowledge Point Status** 🧠\n\n🔹 **Monthly Knowledge Points:** `{scores['monthly_kp'] if scores else 0}`\n🔹 **All-Time Knowledge Points:** `{scores['all_time_kp'] if scores else 0}`\n\nKeep exercising your mind!"
    try:
        await context.bot.send_message(update.effective_user.id, text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Your knowledge scores have been delivered privately to your DMs!")
    except Exception:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Failed to message you privately! Please initiate a DM chat with me first.")

async def trivia_cron_job(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    now = datetime.datetime.now(WIB)
    current_date = now.strftime('%Y-%m-%d')
    day_name = now.strftime('%A').lower()
    is_weekend = day_name in ['saturday', 'sunday']
    
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT value FROM config WHERE key='status'") or 'active'
        if status != 'active':
            return
        last_run = await conn.fetchval("SELECT value FROM config WHERE key='last_run_date'") or ''
        if last_run == current_date:
            return
        
        run_time_str = await conn.fetchval("SELECT value FROM config WHERE key='trivia_time'") or '12:00'
        target_chat_str = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''
        days_mode = await conn.fetchval("SELECT value FROM config WHERE key='trivia_days'") or 'all'
        
        if not target_chat_str:
            return
        target_chat_id = int(target_chat_str)
        
        if days_mode == 'weekday' and is_weekend:
            return
        if days_mode == 'weekend' and not is_weekend:
            return
        
        if now.strftime('%H:%M') != run_time_str:
            return
        await conn.execute("INSERT INTO config (key, value) VALUES ('last_run_date', $1) ON CONFLICT (key) DO UPDATE SET value=$1", current_date)
        
    is_super_day = (day_name == 'sunday')
    context.application.create_task(deploy_trivia(context.bot, target_chat_id, is_super_day, pool))

async def run_monthly_trivia_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    async with pool.acquire() as conn:
        target_chat_str = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''
        if not target_chat_str:
            return
        
        top_minds = await conn.fetch("SELECT username, monthly_kp FROM trivia_scores WHERE monthly_kp > 0 ORDER BY monthly_kp DESC LIMIT 3")
        await conn.execute("UPDATE trivia_scores SET monthly_kp = 0")
        
    if not top_minds:
        return
    announcement = "🏆 **NUKHBA TRIVIA MONTHLY CHAMPIONS** 🏆\n\nCongratulations to our top minds this month! Your brilliance shines supreme:\n\n"
    podiums = ["🥇", "🥈", "🥉"]
    for idx, user in enumerate(top_minds):
        announcement += f"{podiums[idx]} **@{user['username']}** — {user['monthly_kp']} Knowledge Points earned!\n"
    announcement += "\n🔄 *Monthly leaderboard stats have been reset! All-time stats remain captured.*"
    try:
        await context.bot.send_message(int(target_chat_str), announcement, parse_mode="Markdown")
    except Exception:
        pass
