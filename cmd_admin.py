import datetime, logging, pytz
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, delete_cmd, log_action, update_user_menu
from cmd_user import process_return

logger = logging.getLogger(__name__)

# --- BACKGROUND AUTOMATION WORKERS ---
async def unpin_event(context):
    try: await context.bot.unpin_chat_message(chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id'])
    except: pass

async def event_reminder(context):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    if r: await context.bot.send_message(context.job.chat_id, f"⏰ Event **{context.job.data['title']}** starting soon.\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

async def task_reminder(context):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: status = await conn.fetchval("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if status != 'Completed': await context.bot.send_message(context.job.chat_id, f"⚠️ Task approaching deadline in 10 minutes!")

async def auto_return_away(context):
    pool = context.bot_data.get('db_pool')
    username = context.job.data['username']
    uid = await pool.fetchval("SELECT user_id FROM users WHERE username=$1", username)
    msg = await process_return(username, pool, context.bot)
    await log_action(pool, uid or 0, context.job.data['chat_id'], "Away Status", "Removed", f"@{username} auto-returned")
    if uid:
        try: await context.bot.send_message(uid, msg, parse_mode="Markdown")
        except: pass

# --- CANCELLATION HANDLERS ---
async def cancel_event(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
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

async def cancel_task(update, context):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: t_id = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/canceltask ID`")
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task: return await context.bot.send_message(update.effective_user.id, "❌ Task not found.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await context.bot.send_message(update.effective_user.id, "✅ Task deleted.")

async def cancel_poll_admin(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    if not update.message.reply_to_message or not update.message.reply_to_message.poll:
        return await context.bot.send_message(update.effective_user.id, "❌ Reply to live poll with `/cancelpoll`.")
    try:
        await context.bot.stop_poll(update.effective_chat.id, update.message.reply_to_message.message_id)
        await context.bot.send_message(update.effective_user.id, "✅ Poll stopped.")
    except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

# --- GEMINI MANAGER CONTROLS ---
async def set_weekly_limit(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: limit = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/setweeklylimit 20`")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO config (key, value) VALUES ('gemini_weekly_limit', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(limit))
    await context.bot.send_message(update.effective_user.id, f"✅ Global limit set to {limit}.")

async def admin_gemini(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 2)]
        t = parts[0].replace("@", "").lower(); act = parts[1].lower(); amt = int(parts[2])
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/admin_gemini @user , [set/add/sub] , Amount`")
    async with pool.acquire() as conn:
        if act == "set": await conn.execute("UPDATE users SET gemini_quota=$1 WHERE username=$2", amt, t)
        elif act == "add": await conn.execute("UPDATE users SET gemini_quota=gemini_quota+$1 WHERE username=$2", amt, t)
        elif act == "sub": await conn.execute("UPDATE users SET gemini_quota=gemini_quota-$1 WHERE username=$2", amt, t)
    await context.bot.send_message(update.effective_user.id, "✅ AI Quota modified.")

async def check_gemini_quota(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    target = context.args[0].lower().replace("@", "") if context.args else 'all'
    async with pool.acquire() as conn:
        if target == 'all':
            recs = await conn.fetch('SELECT username, gemini_quota FROM users ORDER BY gemini_quota ASC')
            msg = "✅ 🤖 **AI Quotas**\n" + "\n".join([f"@{r['username']}: {r['gemini_quota']}" for r in recs])
        else:
            r = await conn.fetchval('SELECT gemini_quota FROM users WHERE username=$1', target)
            msg = f"✅ @{target} Quota left: {r}" if r is not None else "❌ User not found."
    await context.bot.send_message(update.effective_user.id, msg[:4000])

async def set_gemini_quota(update, context): await admin_gemini(update, context)

# --- RAWWY STARS QUOTA CONTROLS ---
async def check_quota(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    target = context.args[0].lower().replace("@", "") if context.args else 'all'
    async with pool.acquire() as conn:
        if target == 'all':
            recs = await conn.fetch('SELECT username, quota FROM kudos')
            msg = "✅ 🌟 **Star Quotas**\n" + "\n".join([f"@{r['username']}: {r['quota']}" for r in recs])
        else:
            r = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', target)
            msg = f"✅ @{target} Quota left: {r}" if r is not None else "❌ User not found."
    await context.bot.send_message(update.effective_user.id, msg)

async def admin_stars(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
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

# --- LIBRARY ENGINE CONTROLS ---
async def del_lib(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: name = context.args[0].lower().strip()
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/dellib asset_name`")
    async with pool.acquire() as conn:
        res = await conn.execute('DELETE FROM library WHERE name=$1', name)
        if res == "DELETE 0": return await context.bot.send_message(update.effective_user.id, "❌ Asset doesn't exist.")
    await context.bot.send_message(update.effective_user.id, f"✅ Asset '{name}' dropped.")

# --- BIRTHDAY INFRASTRUCTURE ---
async def set_bday_channel(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    if update.effective_chat.type == "private": return await context.bot.send_message(update.effective_user.id, "❌ Run inside group.")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO config (key, value) VALUES ('bday_channel', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(update.effective_chat.id))
    await context.bot.send_message(update.effective_user.id, f"✅ Birthday channel locked to {update.effective_chat.title}.")

async def set_bday_time(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: h, m = map(int, context.args[0].split(':'))
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format: `/setbdaytime HH:MM`")
    formatted_time = f"{h:02d}:{m:02d}"
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO config (key, value) VALUES ('bday_time', $1) ON CONFLICT (key) DO UPDATE SET value=$1", formatted_time)
    from crons import schedule_bday_job
    await schedule_bday_job(context.application)
    await context.bot.send_message(update.effective_user.id, f"✅ Alerts scheduled daily at {formatted_time} WIB.")

async def bday_config(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn:
        channel = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'")
        time_val = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'") or "10:00"
    await context.bot.send_message(update.effective_user.id, f"✅ 🎂 **Birthday Config**\n📢 Channel ID: `{channel}`\n⏰ Time: `{time_val} WIB`", parse_mode="Markdown")

async def add_bday(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: parts = [p.strip() for p in " ".join(context.args).split(",")]
    except: return
    u, b = parts[0].replace("@", "").lower(), parts[1]
    async with pool.acquire() as conn:
        exist = await conn.fetchval('SELECT bday FROM birthdays WHERE lower(username)=$1', u)
        if exist: return await context.bot.send_message(update.effective_user.id, f"❌ Registered already ({exist}).")
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
    await context.bot.send_message(update.effective_user.id, "✅ Birthday logged.")

async def edit_bday(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u, b = parts[0].replace("@", "").lower(), parts[1]
    except: return
    async with pool.acquire() as conn:
        res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE lower(username)=$2', b, u)
    if res == "UPDATE 0": return await context.bot.send_message(update.effective_user.id, "❌ User not found.")
    await context.bot.send_message(update.effective_user.id, "✅ Birthday entry updated.")

async def del_bday(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: u = context.args[0].replace("@", "").lower()
    except: return
    async with pool.acquire() as conn: await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", u)
    await context.bot.send_message(update.effective_user.id, "✅ Birthday dropped.")

async def list_bdays(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn: b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    msg = "🎂 **Birthdays Matrix**\n" + "\n".join([f"• @{x['username']}: {x['bday']}" for x in b])
    await context.bot.send_message(update.effective_user.id, msg)

# --- BULK DATA PROCESSING MODULES ---
async def addlib_batch(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            try:
                is_p = False; raw = item
                if raw.lower().endswith(", private"): is_p = True; raw = raw[:-9].strip()
                p = [x.strip() for x in raw.split(",", 1)]
                await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING', p[0].lower(), p[1], 'AdminBatch', is_p)
            except: pass
    await context.bot.send_message(update.effective_user.id, "✅ Library batch processed.")

async def dellib_batch(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items: await conn.execute('DELETE FROM library WHERE name=$1', item.lower().strip())
    await context.bot.send_message(update.effective_user.id, "✅ Library drop batch processed.")

async def addbday_batch(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            try:
                p = [x.strip() for x in item.split(",")]
                await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2) ON CONFLICT DO NOTHING', p[0].replace("@", "").lower(), p[1])
            except: pass
    await context.bot.send_message(update.effective_user.id, "✅ Birthday batch processed.")

async def delbday_batch(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items: await conn.execute('DELETE FROM birthdays WHERE lower(username)=$1', item.replace("@", "").strip().lower())
    await context.bot.send_message(update.effective_user.id, "✅ Birthday drop batch processed.")

# --- AI INSIGHT BRIEF ENGINE ---
async def analyze_feedback(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    if not GEMINI_API_KEY: return await context.bot.send_message(update.effective_user.id, "❌ API Key Missing.")
    arg = "".join(context.args).strip() if context.args else ""
    try:
        async with pool.acquire() as conn:
            if "," in arg:
                st, en = [p.strip() for p in arg.split(",", 1)]
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at::date >= $1 AND created_at::date <= $2 ORDER BY created_at ASC", datetime.datetime.strptime(st, "%Y-%m-%d").date(), datetime.datetime.strptime(en, "%Y-%m-%d").date())
                range_desc = f"from {st} to {en}"
            elif arg:
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at::date = $1 ORDER BY created_at ASC", datetime.datetime.strptime(arg, "%Y-%m-%d").date())
                range_desc = f"for specific date: {arg}"
            else:
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at ASC")
                range_desc = f"within default active period (last 7 days)"
        if not reports: return await context.bot.send_message(update.effective_user.id, f"✅ Backlog clean {range_desc}.")
        temp = await context.bot.send_message(update.effective_user.id, "⏳ Generating detailed product analysis brief...")
        raw_data = "".join([f"• [{r['created_at'].astimezone(WIB).strftime('%Y-%m-%d')}] @{r['username']}: {r['report']}\n" for r in reports])
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
            for chunk in [reply[i:i+4000] for i in range(0, len(reply), 4000)]: await context.bot.send_message(update.effective_user.id, chunk, parse_mode="Markdown")
        else: await temp.edit_text(reply, parse_mode="Markdown")
    except Exception as e: await context.bot.send_message(update.effective_user.id, f"❌ Analysis Error: {e}")

async def all_time_feedback(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    async with pool.acquire() as conn: recs = await conn.fetch("SELECT username, report, created_at FROM bug_reports ORDER BY created_at DESC")
    if not recs: return await context.bot.send_message(update.effective_user.id, "🪹 Historical archive feedback empty.")
    msg = "📋 🗄️ **Historical Archive Feedback Feed**\n\n" + "".join([f"• `[{r['created_at'].astimezone(WIB).strftime('%d/%m/%Y')}]` @{r['username']}: {r['report']}\n" for r in recs])
    if len(msg) > 4000:
        for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]: await context.bot.send_message(update.effective_user.id, chunk, parse_mode="Markdown")
    else: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

# --- BROADCAST PIPIELINES ---
async def announce(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error.")
    async with pool.acquire() as conn:
        a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", parts[1])
        targets = await conn.fetch("SELECT chat_id FROM active_groups") if parts[0].lower() == "all" else [{"chat_id": int(parts[0])}]
        for t in targets:
            try:
                m = await context.bot.send_message(t['chat_id'], f"📢 **[RW] NUKHBA BROADCAST**\n\n{parts[1]}", parse_mode="Markdown")
                await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
            except: pass
    await context.bot.send_message(update.effective_user.id, "✅ Broadcast sent.")

async def edit_announce(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
    except: return
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", int(parts[0]))
        for m in msgs:
            try: await context.bot.edit_message_text(f"📢 **[RW] NUKHBA BROADCAST**\n\n{parts[1]}", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
            except: pass
        await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", parts[1], int(parts[0]))
    await context.bot.send_message(update.effective_user.id, "✅ Announcement updated.")

async def del_announce(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    try: a_id = int(context.args[0])
    except: return
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try: await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
            except: pass
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, "✅ Announcement dropped.")

# --- METRICS & DIAGNOSTICS ---
async def check_group_id(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    if update.effective_chat.type in ['group', 'supergroup']:
        await context.bot.send_message(update.effective_chat.id, f"✅ 📌 **Group Info**\nTitle: `{update.effective_chat.title}`\nID: `{update.effective_chat.id}`", parse_mode="Markdown")
    else:
        async with pool.acquire() as conn: groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
        msg = "✅ 📈 **Tracked Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups]) if groups else "❌ No active groups."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def get_audit_log(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool): return
    from crons import generate_audit_report
    msg = await generate_audit_report(pool, datetime.datetime.now(WIB).date())
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def bot_status(update, context):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_super(update.effective_user.username): return
    async with pool.acquire() as conn:
        g = await conn.fetch("SELECT chat_id, title FROM active_groups")
        u = await conn.fetchval("SELECT COUNT(*) FROM users")
        t = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Pending'")
        l = await conn.fetchval("SELECT COUNT(*) FROM library")
        b = await conn.fetchval("SELECT COUNT(*) FROM birthdays")
    msg = f"✅ 📈 **Status**\n👥 Tracked: `{u}`\n📋 Tasks: `{t}`\n📚 Assets: `{l}`\n🎂 Birthdays: `{b}`\n🏠 Groups: `{len(g)}`"
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

# --- SUPER ACTIONS MATRIX ---
async def super_reset_req(update, context):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    target = context.args[0].lower() if context.args else 'all'
    kb = [[InlineKeyboardButton("⚠️ Wipe", callback_data=f"sup_reset_{target}"), InlineKeyboardButton("Cancel", callback_data="sup_cancel")]]
    await context.bot.send_message(update.effective_user.id, f"Wipe matrix `{target}`?", reply_markup=InlineKeyboardMarkup(kb))

async def request_super_action(update, context, action, label):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username): return
    t = context.args[0].replace("@", "").lower()
    kb = [[InlineKeyboardButton("Confirm", callback_data=f"sup_{action}_{t}"), InlineKeyboardButton("Cancel", callback_data="sup_cancel")]]
    await context.bot.send_message(update.effective_user.id, f"Run {label} on {t}?", reply_markup=InlineKeyboardMarkup(kb))

async def add_admin_req(u, c): await request_super_action(u, c, "addadmin", "Promote Admin")
async def del_admin_req(u, c): await request_super_action(u, c, "deladmin", "Demote Admin")
async def remove_member_req(u, c): await request_super_action(u, c, "removemember", "Offboard User")

async def super_callback(update, context):
    q = update.callback_query; username = q.from_user.username or str(q.from_user.id)
    if not await is_super(username): return
    if q.data == "sup_cancel": return await q.edit_message_text("Cancelled.")
    parts = q.data.split("_"); act = parts[1]; t = parts[2]; pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        if act == "addadmin":
            await conn.execute('INSERT INTO bot_admins (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
            await q.edit_message_text(f"Promoted @{t}.")
        elif act == "deladmin":
            await conn.execute('DELETE FROM bot_admins WHERE username=$1', t)
            await q.edit_message_text(f"Demoted @{t}.")
        elif act == "removemember":
            await conn.execute('DELETE FROM kudos WHERE username=$1', t)
            await conn.execute('DELETE FROM birthdays WHERE username=$1', t)
            await q.edit_message_text(f"Offboarded @{t}.")
        elif act == "reset":
            if t in ["stars", "all"]: await conn.execute("TRUNCATE kudos CASCADE")
            if t in ["birthdays", "all"]: await conn.execute("TRUNCATE birthdays CASCADE")
            await q.edit_message_text(f"Wiped `{t}` database matrix.")

async def list_admins(update, context):
    pool = context.bot_data.get('db_pool')
    if not await is_super(update.effective_user.username): return
    async with pool.acquire() as conn: recs = await conn.fetch('SELECT username FROM bot_admins')
    await context.bot.send_message(update.effective_user.id, "👑 **Admins:**\n" + "\n".join([f"• @{r['username']}" for r in recs]))

async def graveyard(update, context):
    pool = context.bot_data.get('db_pool')
    if not await is_super(update.effective_user.username): return
    async with pool.acquire() as conn: recs = await conn.fetch('SELECT * FROM graveyard')
    await context.bot.send_message(update.effective_user.id, "🪦 **Graveyard:**\n" + "\n".join([f"• @{r['username']}" for r in recs]))
