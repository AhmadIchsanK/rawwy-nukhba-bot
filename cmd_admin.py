# --- NUKHBA ADMINISTRATIVE CONTROL MODULE - PART 1 ---
import datetime, logging, pytz
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, delete_cmd, log_action, update_user_menu
from cmd_user import process_return

logger = logging.getLogger(__name__)

async def unpin_event(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.unpin_chat_message(chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id'])
    except: pass

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    if not r: return
    await context.bot.send_message(context.job.chat_id, f"⏰ Event **{context.job.data['title']}** starting soon.\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

async def task_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed': 
        await context.bot.send_message(context.job.chat_id, f"⚠️ Task '{context.job.data['desc']}' approaching deadline in 10 minutes!")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: e_id = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/cancelevent ID`")
    async with pool.acquire() as conn:
        ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
        if not ev: return await context.bot.send_message(update.effective_user.id, "❌ Event not found.")
        await conn.execute('DELETE FROM events WHERE id=$1', e_id)
    for j in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"): j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"): j.schedule_removal()
    try: await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
    except: pass
    await context.bot.send_message(update.effective_user.id, "✅ Event cancelled.")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    is_adm = await is_bot_admin(username, pool)
    try: t_id = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/canceltask ID`")
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task: return await context.bot.send_message(update.effective_user.id, "❌ Task not found.")
        if task['assigned_by'] != username and not is_adm: return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await context.bot.send_message(update.effective_user.id, "✅ Task deleted.")

async def cancel_poll_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    if not update.message.reply_to_message or not update.message.reply_to_message.poll:
        return await context.bot.send_message(update.effective_user.id, "❌ Reply to a live poll with `/cancelpoll`.")
    try:
        await context.bot.stop_poll(update.effective_chat.id, update.message.reply_to_message.message_id)
        await context.bot.send_message(update.effective_user.id, "✅ Poll stopped.")
    except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

async def set_weekly_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: limit = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/setweeklylimit 20`")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO config (key, value) VALUES ('gemini_weekly_limit', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(limit))
    await context.bot.send_message(update.effective_user.id, f"✅ Global limit set to {limit}.")

async def admin_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 2)]
        t = parts[0].replace("@", "").lower(); act = parts[1].lower(); amt = int(parts[2])
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/admin_gemini @user , [set/add/sub] , Amount`")
    async with pool.acquire() as conn:
        if act == "set": await conn.execute("UPDATE users SET gemini_quota=$1 WHERE username=$2", amt, t)
        elif act == "add": await conn.execute("UPDATE users SET gemini_quota=gemini_quota+$1 WHERE username=$2", amt, t)
        elif act == "sub": await conn.execute("UPDATE users SET gemini_quota=gemini_quota-$1 WHERE username=$2", amt, t)
    await context.bot.send_message(update.effective_user.id, "✅ AI Quota modified.")

async def check_gemini_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    target = context.args[0].lower().replace("@", "") if context.args else 'all'
    async with pool.acquire() as conn:
        if target == 'all':
            recs = await conn.fetch('SELECT username, gemini_quota FROM users ORDER BY gemini_quota ASC')
            msg = "✅ 🤖 **AI Quotas**\n" + "\n".join([f"@{r['username']}: {r['gemini_quota']}" for r in recs])
        else:
            r = await conn.fetchval('SELECT gemini_quota FROM users WHERE username=$1', target)
            msg = f"✅ @{target} Quota left: {r}" if r is not None else "❌ User not found."
    await context.bot.send_message(update.effective_user.id, msg[:4000])

async def set_gemini_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_gemini(update, context)

async def check_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    target = context.args[0].lower().replace("@", "") if context.args else 'all'
    async with pool.acquire() as conn:
        if target == 'all':
            recs = await conn.fetch('SELECT username, quota FROM kudos')
            msg = "✅ 🌟 **Star Quotas**\n" + "\n".join([f"@{r['username']}: {r['quota']}" for r in recs])
        else:
            r = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', target)
            msg = f"✅ @{target} Quota left: {r}" if r is not None else "❌ User not found."
    await context.bot.send_message(update.effective_user.id, msg)

async def admin_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 3)]
        t = parts[0].replace("@", "").lower(); field = parts[1].lower(); act = parts[2].lower(); amt = int(parts[3])
        col = 'monthly_points' if field == 'monthly' else 'all_time_points' if field == 'total' else 'quota'
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error.")
    async with pool.acquire() as conn:
        await conn.execute(f'INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
        if act == "set": await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, t)
        elif act == "add": await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, t)
        elif act == "sub": await conn.execute(f'UPDATE kudos SET {col}={col}-$1 WHERE username=$2', amt, t)
    await context.bot.send_message(update.effective_user.id, "✅ Stars modified.")

async def set_bday_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    if update.effective_chat.type == "private": return await context.bot.send_message(update.effective_user.id, "❌ Run inside target group.")
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO config (key, value) VALUES ('bday_channel', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(update.effective_chat.id))
        await context.bot.send_message(update.effective_user.id, f"✅ Birthday channel locked to {update.effective_chat.title}.")
    except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

async def set_bday_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        time_str = context.args[0]
        h, m = map(int, time_str.split(':'))
        if not (0 <= h <= 23 and 0 <= m <= 59): raise ValueError
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/setbdaytime HH:MM`")
    try:
        formatted_time = f"{h:02d}:{m:02d}"
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO config (key, value) VALUES ('bday_time', $1) ON CONFLICT (key) DO UPDATE SET value=$1", formatted_time)
        from crons import schedule_bday_job
        await schedule_bday_job(context.application)
        await context.bot.send_message(update.effective_user.id, f"✅ Alerts scheduled daily at {formatted_time} WIB.")
    except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

async def bday_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        async with pool.acquire() as conn:
            channel = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'")
            time_val = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'") or "10:00"
        msg = f"✅ 🎂 **Birthday Config**\n📢 Channel ID: `{channel}`\n⏰ Time: `{time_val} WIB`"
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")
      # --- NUKHBA ADMINISTRATIVE CONTROL MODULE - PART 2 ---

async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u = parts[0].replace("@", "").lower(); b = parts[1]
        datetime.datetime.strptime(b, "%m/%d")
    except:
        return await context.bot.send_message(update.effective_user.id, "❌ Format error. Try: `/addbday @user , MM/DD`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn:
            exist = await conn.fetchval('SELECT bday FROM birthdays WHERE lower(username)=$1', u)
            if exist: 
                return await context.bot.send_message(update.effective_user.id, f"❌ @{u} already has a birthday registered (Date: {exist}). Use `/editbday` to update it.", parse_mode="Markdown")
            await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
        await context.bot.send_message(update.effective_user.id, f"✅ 🎂 Birthday securely logged for @{u}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def edit_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u = parts[0].replace("@", "").lower(); b = parts[1]
        datetime.datetime.strptime(b, "%m/%d")
    except:
        return await context.bot.send_message(update.effective_user.id, "❌ Format error: `/editbday @user , MM/DD`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn: 
            res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE lower(username)=$2', b, u)
            if res == "UPDATE 0": return await context.bot.send_message(update.effective_user.id, "❌ User not found. Use `/addbday`.")
        await context.bot.send_message(update.effective_user.id, f"✅ 🎂 Birthday updated for @{u}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def del_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try: u = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/delbday @user`")
    
    try:
        async with pool.acquire() as conn:
            res = await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", u)
            if res == "DELETE 0":
                return await context.bot.send_message(update.effective_user.id, f"❌ @{u} not found in birthday database.")
        await context.bot.send_message(update.effective_user.id, f"✅ Removed @{u} from birthday database.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try:
        async with pool.acquire() as conn: b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
        await context.bot.send_message(update.effective_user.id, "✅ 🎂 **Birthdays**\n" + "\n".join([f"• @{x['username']}: {x['bday']}" for x in b]) if b else "❌ None saved.", parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def addlib_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    text = update.message.text
    lines = text.split('\n')
    items = []
    first_line = lines[0].split(' ', 1)
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            try:
                is_p = False
                raw = item
                if raw.lower().endswith(", private"): is_p = True; raw = raw[:-9].strip()
                p = [x.strip() for x in raw.split(",", 1)]
                await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING', p[0].lower(), p[1], 'AdminBatch', is_p)
            except: pass
    await context.bot.send_message(update.effective_user.id, "✅ Library batch processed.")

async def dellib_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    text = update.message.text
    lines = text.split('\n')
    items = []
    first_line = lines[0].split(' ', 1)
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items: await conn.execute('DELETE FROM library WHERE name=$1', item.lower().strip())
    await context.bot.send_message(update.effective_user.id, "✅ Library drop batch processed.")

async def addbday_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    text = update.message.text
    lines = text.split('\n')
    items = []
    first_line = lines[0].split(' ', 1)
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            try:
                p = [x.strip() for x in item.split(",")]
                await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2) ON CONFLICT DO NOTHING', p[0].replace("@", "").lower(), p[1])
            except: pass
    await context.bot.send_message(update.effective_user.id, "✅ Birthday batch processed.")

async def delbday_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    text = update.message.text
    lines = text.split('\n')
    items = []
    first_line = lines[0].split(' ', 1)
    if len(first_line) > 1: items.append(first_line[1].strip())
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items: await conn.execute('DELETE FROM birthdays WHERE lower(username)=$1', item.replace("@", "").strip().lower())
    await context.bot.send_message(update.effective_user.id, "✅ Birthday drop batch processed.")

async def analyze_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    if not GEMINI_API_KEY: return await context.bot.send_message(update.effective_user.id, "❌ API Key Missing.")

    arg = "".join(context.args).strip() if context.args else ""
    try:
        async with pool.acquire() as conn:
            if "," in arg:
                st, en = [p.strip() for p in arg.split(",", 1)]
                s_dt = datetime.datetime.strptime(st, "%Y-%m-%d").date()
                e_dt = datetime.datetime.strptime(en, "%Y-%m-%d").date()
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at::date >= $1 AND created_at::date <= $2 ORDER BY created_at ASC", s_dt, e_dt)
                range_desc = f"from {st} to {en}"
            elif arg:
                tgt = datetime.datetime.strptime(arg, "%Y-%m-%d").date()
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at::date = $1 ORDER BY created_at ASC", tgt)
                range_desc = f"for specific date: {arg}"
            else:
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at ASC")
                range_desc = f"within default active period (last 7 days)"
                
        if not reports: return await context.bot.send_message(update.effective_user.id, f"✅ Backlog clean {range_desc}.")
        
        temp = await context.bot.send_message(update.effective_user.id, "⏳ Generating detailed product analysis brief...")
        
        raw_data = ""
        for r in reports:
            dt = r['created_at'].astimezone(WIB).strftime('%Y-%m-%d')
            raw_data += f"• [{dt}] @{r['username']}: {r['report']}\n"

        ai_prompt = (
            f"You are a Senior Product Manager and Software Architect. Process this grouped team feedback {range_desc}.\n"
            "Produce an expert executive brief strictly matching this structure:\n\n"
            "### 📋 1. Executive Summary\n[Summarize core operational constraints, recurring problem areas, and structural patterns]\n\n"
            "### 💡 2. Expected Suggestions\n[Outline exactly what functional workflow enhancement the team is trying to achieve]\n\n"
            "### 🛠️ 3. Proposed Solutions & Code-Level Implementations\n[Provide architectural execution maps or pseudo-code fixes for doable items]\n\n"
            "### 🔄 4. Actionable Alternatives & Adjustments\n[For complex, high-risk, or non-doable requests, offer robust fallback options]\n\n"
            f"Feedback Feed Data:\n{raw_data}"
        )
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model='gemini-2.5-flash', contents=ai_prompt)
        reply = f"✅ 🤖 **Gemini Architecture Analytics ({range_desc})**\n\n{response.text}"
        
        if len(reply) > 4000:
            await temp.delete()
            for c in [reply[i:i+4000] for i in range(0, len(reply), 4000)]:
                await context.bot.send_message(update.effective_user.id, c, parse_mode="Markdown")
        else: await temp.edit_text(reply, parse_mode="Markdown")
    except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Analysis Error: {e}")

async def all_time_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    async with pool.acquire() as conn:
        recs = await conn.fetch("SELECT username, report, created_at FROM bug_reports ORDER BY created_at DESC")
    if not recs: return await context.bot.send_message(update.effective_user.id, "🪹 Historical archive feedback empty.")
    
    msg = "📋 🗄️ **Historical Archive Feedback Feed**\n\n"
    for r in recs:
        dt = r['created_at'].astimezone(WIB).strftime('%d/%m/%Y')
        msg += f"• `[{dt}]` @{r['username']}: {r['report']}\n"
    if len(msg) > 4000:
        for c in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
            await context.bot.send_message(update.effective_user.id, c, parse_mode="Markdown")
    else: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    now = datetime.datetime.now(WIB)
    
    try:
        async with pool.acquire() as conn: aways = await conn.fetch('SELECT username, end_time FROM away_status')
        msg = "✅ 📊 **Team Attendance Status**\n\n"
        if aways:
            msg += "🔴 **CURRENTLY AWAY:**\n"
            for a in aways:
                rem = a['end_time'].astimezone(WIB) - now
                d = rem.days; h = rem.seconds // 3600; m = (rem.seconds % 3600) // 60
                t_str = f"{d}d {h}h {m}m" if d > 0 else f"{h}h {m}m"
                msg += f"• @{a['username']} (Returns in {t_str})\n"
            msg += "\n🟢 *Everyone else is assumed Available.*"
        else: msg += "🟢 Everyone is currently Available."
        
        try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
        except: pass
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def group_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    now = datetime.datetime.now(WIB)
    try:
        async with pool.acquire() as conn:
            tasks = await conn.fetch("SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks WHERE status='Pending' ORDER BY deadline")
        if not tasks: msg = "✅ 🎉 Zero pending tasks in the entire database."
        else:
            msg = "✅ 📋 **Global Pending Tasks**\n\n"
            for t in tasks:
                rem = int((t['deadline'] - now).total_seconds() / 60)
                status = f"{rem}m left" if rem > 0 else "OVERDUE"
                msg += f"🔹 `{t['id']}` | **{t['task_desc']}**\nTo: @{t['assignee']} | By: @{t['assigned_by']} | ⏳ {status}\n\n"
        try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
        except: pass
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def check_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        if update.effective_chat.type in ['group', 'supergroup']:
            msg = f"✅ 📌 **Current Group Info**\nTitle: `{update.effective_chat.title}`\nID: `{update.effective_chat.id}`"
            try: await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")
            except: pass
        else:
            async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
            if not groups: msg = "❌ I have not detected any active groups yet."
            else: msg = "✅ 📈 **Tracked Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups])
            try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
            except: pass
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
            u_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            t_count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Pending'")
            l_count = await conn.fetchval("SELECT COUNT(*) FROM library")
            b_count = await conn.fetchval("SELECT COUNT(*) FROM birthdays")
        
        msg = "✅ 📈 **Enterprise System Status**\n\n"
        msg += f"👥 Users Tracked: `{u_count}`\n📋 Pending Tasks: `{t_count}`\n📚 Library Assets: `{l_count}`\n🎂 Birthdays Saved: `{b_count}`\n\n"
        msg += f"🏠 **Active Groups ({len(groups)}):**\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups])
        try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
        except: pass
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def get_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        from crons import generate_audit_report
        target_date = datetime.datetime.now(WIB).date()
        msg = await generate_audit_report(pool, target_date)
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: `{e}`", parse_mode="Markdown")

async def force_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "")
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error: `/forceback @user`")
    
    try:
        async with pool.acquire() as conn:
            status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', target)
            if not status: 
                return await context.bot.send_message(update.effective_user.id, f"❌ @{target} is not currently marked as Away. Status is already Available 🟢.")
            
        for j in context.job_queue.get_jobs_by_name(f"away_{target}"): j.schedule_removal()
        msg = await process_return(target, pool, context.bot)
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Force Removed", f"@{username} forced @{target} back")
        
        try: 
            async with pool.acquire() as conn:
                uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", target)
            if uid: await context.bot.send_message(uid, f"⚠️ An Admin has force-removed your Away status.\n\n{msg}", parse_mode="Markdown")
            await context.bot.send_message(update.effective_user.id, f"✅ Successfully forced @{target} back to Available. Digest sent to them.", parse_mode="Markdown")
        except:
            await context.bot.send_message(update.effective_user.id, f"✅ Successfully forced @{target} back to Available.\n\n(Could not DM user, here is their recap:)\n{msg}", parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def auto_return_away(context: ContextTypes.DEFAULT_TYPE): 
    pool = context.bot_data.get('db_pool')
    username = context.job.data['username']
    try:
        async with pool.acquire() as conn:
            uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
        msg = await process_return(username, pool, context.bot)
        await log_action(pool, uid or 0, context.job.data['chat_id'], "Away Status", "Removed", f"@{username} auto-returned")
        if uid:
            try: await context.bot.send_message(uid, msg, parse_mode="Markdown")
            except: pass
    except: pass

# --- SUPER ACTIONS ---
async def super_reset_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error: `/super_reset [stars/tasks/library/events/away/birthdays/all]`", parse_mode="Markdown")
    
    cb_data = f"sup_reset_{target}"
    kb = [[InlineKeyboardButton("⚠️ Yes, Wipe Data", callback_data=cb_data), InlineKeyboardButton("No, Cancel", callback_data="sup_cancel")]]
    await context.bot.send_message(update.effective_user.id, f"⚠️ **FACTORY WIPE MODULE**\nAre you absolutely sure you want to wipe data for `{target}`?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def request_super_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, label: str):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    try: target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "").lower()
    except: return await context.bot.send_message(update.effective_user.id, f"❌ Format error: `/{action} @user`")
    
    cb_data = f"sup_{action}_{target}"
    kb = [[InlineKeyboardButton("Yes, Do it", callback_data=cb_data), InlineKeyboardButton("No, Cancel", callback_data="sup_cancel")]]
    await context.bot.send_message(update.effective_user.id, f"⚠️ Are you sure you want to execute **{label}** on `{target}`?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_admin_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await request_super_action(update, context, "addadmin", "Promote Admin")

async def del_admin_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await request_super_action(update, context, "deladmin", "Demote Admin")

async def remove_member_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await request_super_action(update, context, "removemember", "Offboard User")

async def super_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    username = q.from_user.username or str(q.from_user.id)
    if not await is_super(username): return await q.answer("Unauthorized.")
    if q.data == "sup_cancel":
        await q.edit_message_text("❌ Action cancelled.")
        return await q.answer()
        
    parts = q.data.split("_")
    action = parts[1]; target = parts[2]
    pool = context.bot_data.get('db_pool')
    
    try:
        if action == "addadmin":
            async with pool.acquire() as conn: 
                await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', target)
                uid = await conn.fetchval('SELECT user_id FROM users WHERE username=$1', target)
            if uid:
                try:
                    await update_user_menu(uid, target, pool, context.bot)
                    await context.bot.send_message(uid, "🎉 **Congratulations!** You have been promoted to Global Bot Admin. Type `/help`.", parse_mode="Markdown")
                except: pass
            await q.edit_message_text(f"✅ @{target} is now a Bot Admin.")
            
        elif action == "deladmin":
            async with pool.acquire() as conn: await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
            await q.edit_message_text(f"✅ 🗑️ @{target} removed from Admins.")
            
        elif action == "removemember":
            async with pool.acquire() as conn:
                k = await conn.fetchrow("SELECT * FROM kudos WHERE username=$1", target)
                b = await conn.fetchval("SELECT bday FROM birthdays WHERE username=$1", target)
                c = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Completed' AND assignee=$1", target)
                data_dump = f"Stars: {k['all_time_points'] if k else 0} | Bday: {b} | Tasks Done: {c}"
                await conn.execute("INSERT INTO graveyard (username, data_dump) VALUES ($1, $2)", target, data_dump)
                
                await conn.execute('DELETE FROM bot_admins WHERE username=$1', target)
                await conn.execute('DELETE FROM kudos WHERE username=$1', target)
                await conn.execute('DELETE FROM birthdays WHERE username=$1', target)
                await conn.execute('DELETE FROM away_status WHERE username=$1', target)
                await conn.execute("UPDATE tasks SET assignee='Unassigned' WHERE assignee=$1", target)
            await q.edit_message_text(f"✅ 🪦 @{target} offboarded to graveyard.")

        elif action == "reset":
            async with pool.acquire() as conn:
                if target in ["stars", "all"]: await conn.execute("TRUNCATE kudos CASCADE")
                if target in ["tasks", "all"]: await conn.execute("TRUNCATE tasks RESTART IDENTITY CASCADE")
                if target in ["library", "all"]: await conn.execute("TRUNCATE library CASCADE")
                if target in ["events", "all"]: await conn.execute("TRUNCATE events, rsvps RESTART IDENTITY CASCADE")
                if target in ["birthdays", "all"]: await conn.execute("TRUNCATE birthdays CASCADE")
                if target in ["away", "all"]: await conn.execute("TRUNCATE away_status, away_mentions CASCADE")
            await q.edit_message_text(f"✅ ☢️ Data Wipe for `{target}` successfully executed.", parse_mode="Markdown")
            
    except Exception as e:
        await q.edit_message_text(f"❌ System Error: {e}")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: admins = await conn.fetch('SELECT username FROM bot_admins')
        msg = "✅ 👑 **Bot Admins**\n" + "\n".join([f"• @{a['username']}" for a in admins]) if admins else "✅ 👑 **Bot Admins**\nNone (Only Super Owner exists)."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_super(username): return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: gy = await conn.fetch('SELECT * FROM graveyard')
        if not gy: return await context.bot.send_message(update.effective_user.id, "❌ 🪦 The graveyard is empty.")
        msg = "✅ 🪦 **Employee Graveyard**\n\n"
        for g in gy: msg += f"• @{g['username']} (Left: {g['offboarded_at'].strftime('%m/%d/%Y')})\n  _{g['data_dump']}_\n\n"
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")
