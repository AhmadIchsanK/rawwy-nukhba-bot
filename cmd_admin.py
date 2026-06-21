import datetime
import logging
import json
import pytz
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, delete_cmd, log_action

logger = logging.getLogger(__name__)

async def send_md(context, chat_id, text):
    chunk = ""
    for line in text.split('\n'):
        if len(chunk) + len(line) > 3800:
            try:
                await context.bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(chat_id, chunk)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        try:
            await context.bot.send_message(chat_id, chunk, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id, chunk)

async def bot_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    
    async with pool.acquire() as conn:
        gl = await conn.fetchval("SELECT value FROM config WHERE key='gemini_weekly_limit'") or '20'
        sq = await conn.fetchval("SELECT value FROM config WHERE key='star_quota'") or '3'
        mt = await conn.fetchval("SELECT value FROM config WHERE key='max_tasks'") or '4'
        ma = await conn.fetchval("SELECT value FROM config WHERE key='max_away_days'") or '14'
        me = await conn.fetchval("SELECT value FROM config WHERE key='max_events'") or '5'
        
    text = (
        "⚙️ **NUKHBA GLOBAL CONFIGURATION**\n\n"
        f"🤖 AI Limit: `{gl} queries/wk`\n"
        f"🌟 Star Quota: `{sq} stars/wk`\n"
        f"⚡ Max Tasks: `{mt} pending/user`\n"
        f"📅 Max Events: `{me} active/user`\n"
        f"🏖️ Max Away: `{ma} days`"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 AI Limit ({gl})", callback_data="cfg_gemini"), InlineKeyboardButton(f"🌟 Star Quota ({sq})", callback_data="cfg_stars")],
        [InlineKeyboardButton(f"⚡ Max Tasks ({mt})", callback_data="cfg_tasks"), InlineKeyboardButton(f"📅 Max Events ({me})", callback_data="cfg_events")],
        [InlineKeyboardButton(f"🏖️ Max Away ({ma})", callback_data="cfg_away")]
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(q.from_user.username, pool):
        return await q.answer("Unauthorized", show_alert=True)
    
    act = q.data.split("_")[1]
    keys = {"gemini": "gemini_weekly_limit", "stars": "star_quota", "tasks": "max_tasks", "events": "max_events", "away": "max_away_days"}
    increments = {"gemini": 5, "stars": 1, "tasks": 1, "events": 1, "away": 2}
    
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM config WHERE key=$1", keys[act])
        new_val = int(val) + increments[act] if val else increments[act]
        if new_val > 100:
            new_val = 1
        await conn.execute("INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2", keys[act], str(new_val))
        
    await q.answer(f"{act.title()} updated to {new_val}.")
    await bot_config(update, context)

async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type == "private":
        return await update.message.reply_text("❌ Run inside group.")
    
    target = context.args[0].lower() if context.args else ""
    valid = {"bday": "bday_channel", "trivia": "trivia_target_chat", "stars": "stars_channel", "feedback": "feedback_channel"}
    if target not in valid:
        return await update.message.reply_text("❌ Usage: `/setchannel <bday|trivia|stars|feedback>`")
    
    async with pool.acquire() as conn:
        if target == "trivia":
            await conn.execute("INSERT INTO trivia_config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2", "target_chat_id", str(update.effective_chat.id))
        else:
            await conn.execute("INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2", valid[target], str(update.effective_chat.id))
    await update.message.reply_text(f"✅ Channel binding for `{target}` locked to this group.", parse_mode="Markdown")

async def unset_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    
    target = context.args[0].lower() if context.args else ""
    valid = {"bday": "bday_channel", "trivia": "trivia_target_chat", "stars": "stars_channel", "feedback": "feedback_channel"}
    if target not in valid:
        return await update.message.reply_text("❌ Usage: `/unsetchannel <bday|trivia|stars|feedback>`")
    
    async with pool.acquire() as conn:
        if target == "trivia":
            await conn.execute("DELETE FROM trivia_config WHERE key=$1", "target_chat_id")
        else:
            await conn.execute("DELETE FROM config WHERE key=$1", valid[target])
    await update.message.reply_text(f"✅ Channel binding for `{target}` has been cleared.", parse_mode="Markdown")

async def analyze_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if not GEMINI_API_KEY:
        return await update.message.reply_text("❌ API Key Missing.")
    
    arg = " ".join(context.args).strip() if context.args else ""
    try:
        async with pool.acquire() as conn:
            if "to" in arg.lower():
                st, en = [p.strip() for p in arg.lower().split("to", 1)]
                s_dt = datetime.datetime.strptime(st, "%m/%d/%Y").date()
                e_dt = datetime.datetime.strptime(en, "%m/%d/%Y").date()
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at::date >= $1 AND created_at::date <= $2 ORDER BY created_at ASC", s_dt, e_dt)
                range_desc = f"from {st} to {en}"
            else:
                reports = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at ASC")
                range_desc = "last 7 days"
    except Exception:
        return await update.message.reply_text(f"❌ Date error. Use MM/DD/YYYY to MM/DD/YYYY")

    if not reports:
        return await update.message.reply_text(f"✅ Backlog clean for {range_desc}.")
    temp = await update.message.reply_text("⏳ Generating structured feedback analysis brief...")
    
    raw_data = "\n".join([f"• @{r['username']}: {r['report']}" for r in reports])

    ai_prompt = (
        f"Analyze this team feedback ({range_desc}).\n"
        "Output strictly this format and nothing else. Be concise and strategic.\n\n"
        "### 🚨 Summary\n[Summary of issues]\n\n"
        "### 💡 Suggestion\n[Practical workflow enhancements]\n\n"
        "### 🚀 Next Step\n[Actionable steps for the team]\n\n"
        f"Data:\n{raw_data}"
    )
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=ai_prompt)
        await temp.delete()
        await send_md(context, update.effective_user.id, f"✅ 🤖 **Gemini Analytics ({range_desc})**\n\n{response.text}")
    except Exception as e:
        await update.message.reply_text(f"❌ Analysis Error: {e}")

async def unpin_event(context):
    try:
        await context.bot.unpin_chat_message(chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id'])
    except Exception:
        pass

async def event_reminder(context):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    if r:
        await context.bot.send_message(context.job.chat_id, f"⏰ Event **{context.job.data['title']}** starting soon.\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

async def task_reminder(context):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if status != 'Completed':
        await context.bot.send_message(context.job.chat_id, f"⚠️ Task approaching deadline in 10 minutes!")

async def auto_return_away(context):
    pool = context.bot_data.get('db_pool')
    username = context.job.data['username']
    async with pool.acquire() as conn:
        uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
    
    import cmd_user
    msg = await cmd_user.process_return(username, pool, context.bot)
    await log_action(pool, uid or 0, context.job.data['chat_id'], "Away Status", "Removed", f"@{username} auto-returned")
    if uid:
        try:
            await context.bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception:
            pass

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        e_id = int(context.args[0])
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/cancelevent [ID]`")
    async with pool.acquire() as conn:
        ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
        if not ev:
            return await context.bot.send_message(update.effective_user.id, "❌ Event not found.")
        await conn.execute('DELETE FROM events WHERE id=$1', e_id)
    for j in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"):
        j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"):
        j.schedule_removal()
    try:
        await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
    except Exception:
        pass
    await context.bot.send_message(update.effective_user.id, "✅ Event cancelled.")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    is_adm = await is_bot_admin(username, pool)
    try:
        t_id = int(context.args[0])
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/canceltask [ID]`")
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
        if not task:
            return await context.bot.send_message(update.effective_user.id, "❌ Task not found.")
        if task['assigned_by'] != username and not is_adm:
            return await context.bot.send_message(update.effective_user.id, "❌ Unauthorized.")
        await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
    await context.bot.send_message(update.effective_user.id, "✅ Task deleted.")

async def cancel_poll_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.poll:
        return await context.bot.send_message(update.effective_user.id, "❌ Reply to live poll with `/cancelpoll`.")
    try:
        await context.bot.stop_poll(update.effective_chat.id, update.message.reply_to_message.message_id)
        await context.bot.send_message(update.effective_user.id, "✅ Poll stopped.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

async def check_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    target = context.args[0].lower().replace("@", "") if context.args else 'all'
    async with pool.acquire() as conn:
        if target == 'all':
            recs = await conn.fetch('SELECT username, gemini_quota FROM users ORDER BY gemini_quota ASC')
            msg = "✅ 🤖 **AI Limits**\n" + "\n".join([f"@{r['username']}: {r['gemini_quota']}" for r in recs])
        else:
            r = await conn.fetchval('SELECT gemini_quota FROM users WHERE username=$1', target)
            msg = f"✅ @{target} Limit left: {r}" if r is not None else "❌ User not found."
    await context.bot.send_message(update.effective_user.id, msg[:4000])

async def admin_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 2)]
        t = parts[0].replace("@", "").lower()
        act = parts[1].lower()
        amt = int(parts[2])
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/admin_limit [@user] , [set|add|sub] , [Amount]`")
    
    async with pool.acquire() as conn:
        if act == "set":
            await conn.execute("UPDATE users SET gemini_quota=$1 WHERE username=$2", amt, t)
        elif act == "add":
            await conn.execute("UPDATE users SET gemini_quota=gemini_quota+$1 WHERE username=$2", amt, t)
        elif act == "sub":
            await conn.execute("UPDATE users SET gemini_quota=gemini_quota-$1 WHERE username=$2", amt, t)
    await context.bot.send_message(update.effective_user.id, "✅ AI Limit modified.")

async def check_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
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
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 3)]
        t = parts[0].replace("@", "").lower()
        field = parts[1].lower()
        act = parts[2].lower()
        amt = int(parts[3])
        col = 'monthly_points' if field == 'monthly' else 'all_time_points' if field == 'total' else 'quota'
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/admin_stars [@user] , [quota|monthly|total] , [set|add|sub] , [Amount]`")
    
    async with pool.acquire() as conn:
        await conn.execute(f'INSERT INTO kudos (username) VALUES ($1) ON CONFLICT DO NOTHING', t)
        if act == "add":
            await conn.execute(f'UPDATE kudos SET {col}={col}+$1 WHERE username=$2', amt, t)
        elif act == "sub":
            await conn.execute(f'UPDATE kudos SET {col}={col}-$1 WHERE username=$2', amt, t)
        else:
            await conn.execute(f'UPDATE kudos SET {col}=$1 WHERE username=$2', amt, t)
    await context.bot.send_message(update.effective_user.id, "✅ Stars modified.")

async def add_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u = parts[0].replace("@", "").lower()
        b = parts[1]
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/addbday [@user] , [MM/DD]`")
    async with pool.acquire() as conn:
        exist = await conn.fetchval('SELECT bday FROM birthdays WHERE lower(username)=$1', u)
        if exist:
            return await context.bot.send_message(update.effective_user.id, f"❌ Registered already ({exist}).")
        await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2)', u, b)
    await context.bot.send_message(update.effective_user.id, "✅ Birthday logged.")

async def edit_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",")]
        u = parts[0].replace("@", "").lower()
        b = parts[1]
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/editbday [@user] , [MM/DD]`")
    async with pool.acquire() as conn:
        res = await conn.execute('UPDATE birthdays SET bday=$1 WHERE lower(username)=$2', b, u)
    if res == "UPDATE 0":
        return await context.bot.send_message(update.effective_user.id, "❌ User not found.")
    await context.bot.send_message(update.effective_user.id, "✅ Birthday entry updated.")

async def del_bday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        u = context.args[0].replace("@", "").lower()
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/delbday [@user]`")
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM birthdays WHERE lower(username)=$1", u)
    await context.bot.send_message(update.effective_user.id, "✅ Birthday dropped.")

async def list_bdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    async with pool.acquire() as conn:
        b = await conn.fetch('SELECT username, bday FROM birthdays ORDER BY bday')
    msg = "🎂 **Birthdays Matrix**\n" + "\n".join([f"• @{x['username']}: {x['bday']}" for x in b])
    await context.bot.send_message(update.effective_user.id, msg)

async def addlib_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            try:
                is_p = False
                raw = item
                if raw.lower().endswith(", private"):
                    is_p = True
                    raw = raw[:-9].strip()
                p = [x.strip() for x in raw.split(",", 1)]
                await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING', p[0].lower(), p[1], 'AdminBatch', is_p)
            except Exception:
                pass
    await context.bot.send_message(update.effective_user.id, "✅ Library batch processed.")

async def dellib_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            await conn.execute('DELETE FROM library WHERE name=$1', item.lower().strip())
    await context.bot.send_message(update.effective_user.id, "✅ Library drop batch processed.")

async def addbday_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            try:
                p = [x.strip() for x in item.split(",")]
                await conn.execute('INSERT INTO birthdays (username, bday) VALUES ($1, $2) ON CONFLICT DO NOTHING', p[0].replace("@", "").lower(), p[1])
            except Exception:
                pass
    await context.bot.send_message(update.effective_user.id, "✅ Birthday batch processed.")

async def delbday_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    lines = update.message.text.split('\n')
    items = [lines[0].split(' ', 1)[1].strip()] if len(lines[0].split(' ', 1)) > 1 else []
    items.extend([l.strip() for l in lines[1:] if l.strip()])
    async with pool.acquire() as conn:
        for item in items:
            await conn.execute('DELETE FROM birthdays WHERE lower(username)=$1', item.replace("@", "").strip().lower())
    await context.bot.send_message(update.effective_user.id, "✅ Birthday drop batch processed.")

async def feedback_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    async with pool.acquire() as conn:
        recs = await conn.fetch("SELECT username, report, created_at FROM bug_reports WHERE created_at >= NOW() - INTERVAL '7 days' ORDER BY created_at ASC")
    if not recs:
        return await context.bot.send_message(update.effective_user.id, "🪹 No feedback logged in the last 7 days.")
    msg = "📋 **Feedback Feed (Last 7 Days)**\n\n"
    for r in recs:
        msg += f"• `[{r['created_at'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')}]` @{r['username']}: {r['report']}\n"
    await send_md(context, update.effective_user.id, msg)

async def all_time_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    async with pool.acquire() as conn:
        recs = await conn.fetch("SELECT username, report, created_at FROM bug_reports ORDER BY created_at DESC")
    if not recs:
        return await context.bot.send_message(update.effective_user.id, "🪹 Archive context feedback empty.")
    msg = "📋 🗄️ **Historical Archive Feedback Feed**\n\n"
    for r in recs:
        msg += f"• `[{r['created_at'].astimezone(WIB).strftime('%m/%d/%Y')}]` @{r['username']}: {r['report']}\n"
    await send_md(context, update.effective_user.id, msg)

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Format error.")
    async with pool.acquire() as conn:
        a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", parts[1])
        targets = await conn.fetch("SELECT chat_id FROM active_groups") if parts[0].lower() == "all" else [{"chat_id": int(parts[0])}]
        for t in targets:
            try:
                m = await context.bot.send_message(t['chat_id'], f"📢 **[RW] NUKHBA BROADCAST**\n\n{parts[1]}", parse_mode="Markdown")
                await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
            except Exception:
                pass
    await context.bot.send_message(update.effective_user.id, "✅ Broadcast sent.")

async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
    except Exception:
        return
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", int(parts[0]))
        for m in msgs:
            try:
                await context.bot.edit_message_text(f"📢 **[RW] NUKHBA BROADCAST**\n\n{parts[1]}", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
            except Exception:
                pass
        await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", parts[1], int(parts[0]))
    await context.bot.send_message(update.effective_user.id, "✅ Announcement updated.")

async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        a_id = int(context.args[0])
    except Exception:
        return
    async with pool.acquire() as conn:
        msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
        for m in msgs:
            try:
                await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
            except Exception:
                pass
        await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
    await context.bot.send_message(update.effective_user.id, "✅ Announcement dropped.")

async def check_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        await context.bot.send_message(update.effective_chat.id, f"✅ 📌 **Group Info**\nTitle: `{update.effective_chat.title}`\nID: `{update.effective_chat.id}`", parse_mode="Markdown")
    else:
        async with pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id, title FROM active_groups")
        msg = "✅ 📈 **Tracked Groups:**\n\n" + "\n".join([f"• `{g['chat_id']}` : {g['title']}" for g in groups]) if groups else "❌ No active groups logged."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def get_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    from crons import generate_audit_report
    msg = await generate_audit_report(pool, datetime.datetime.now(WIB).date())
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_super(update.effective_user.username):
        return
    async with pool.acquire() as conn:
        g = await conn.fetch("SELECT chat_id, title FROM active_groups")
        u = await conn.fetchval("SELECT COUNT(*) FROM users")
        t = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status='Pending'")
        l = await conn.fetchval("SELECT COUNT(*) FROM library")
        b = await conn.fetchval("SELECT COUNT(*) FROM birthdays")
    await context.bot.send_message(update.effective_user.id, f"✅ 📈 **Status**\n👥 Tracked: `{u}`\n📋 Tasks: `{t}`\n📚 Assets: `{l}`\n🎂 Birthdays: `{b}`\n🏠 Groups: `{len(g)}`", parse_mode="Markdown")

async def force_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        target = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].replace("@", "")
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Usage: `/forceback [@user]`")
    try:
        async with pool.acquire() as conn:
            status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', target)
            if not status:
                return await context.bot.send_message(update.effective_user.id, f"❌ @{target} is Available 🟢.")
        for j in context.job_queue.get_jobs_by_name(f"away_{target}"):
            j.schedule_removal()
        
        import cmd_user
        msg = await cmd_user.process_return(target, pool, context.bot)
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Force Removed", f"@{update.effective_user.username} forced @{target} back")
        async with pool.acquire() as conn:
            uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", target)
        if uid:
            try:
                await context.bot.send_message(uid, f"⚠️ Admin removed Away status.\n\n{msg}", parse_mode="Markdown")
            except Exception:
                pass
        await context.bot.send_message(update.effective_user.id, f"✅ Forced @{target} back to Available.", parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

async def attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    now = datetime.datetime.now(WIB)
    try:
        async with pool.acquire() as conn:
            aways = await conn.fetch('SELECT username, end_time FROM away_status')
        msg = "✅ 📊 **Team Attendance Status**\n\n"
        if aways:
            msg += "🔴 **CURRENTLY AWAY:**\n"
            for a in aways:
                rem = a['end_time'].astimezone(WIB) - now
                d = rem.days
                h = rem.seconds // 3600
                m = (rem.seconds % 3600) // 60
                msg += f"• @{a['username']} (Returns in {f'{d}d {h}h {m}m' if d > 0 else f'{h}h {m}m'})\n"
            msg += "\n🟢 *Everyone else is assumed Available.*"
        else:
            msg += "🟢 Everyone is currently Available."
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

async def group_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    now = datetime.datetime.now(WIB)
    try:
        async with pool.acquire() as conn:
            tasks = await conn.fetch("SELECT id, assignee, assigned_by, task_desc, deadline FROM tasks WHERE status='Pending' ORDER BY deadline")
        if not tasks:
            msg = "✅ 🎉 Zero pending tasks."
        else:
            msg = "✅ 📋 **Global Pending Tasks**\n\n"
            for t in tasks:
                rem = int((t['deadline'] - now).total_seconds() / 60)
                msg += f"🔹 `{t['id']}` | **{t['task_desc']}**\nTo: @{t['assignee']} | By: @{t['assigned_by']} | ⏳ {f'{rem}m left' if rem > 0 else 'OVERDUE'}\n\n"
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ Error: {e}")

async def super_reset_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    target = context.args[0].lower() if context.args else 'all'
    await context.bot.send_message(update.effective_user.id, f"Wipe matrix `{target}`?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ Wipe", callback_data=f"sup_reset_{target}"), InlineKeyboardButton("Cancel", callback_data="sup_cancel")]]))

async def request_super_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, label: str):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    try:
        t = context.args[0].replace("@", "").lower()
    except Exception:
        return
    await context.bot.send_message(update.effective_user.id, f"Run {label} on {t}?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Confirm", callback_data=f"sup_{action}_{t}"), InlineKeyboardButton("Cancel", callback_data="sup_cancel")]]))

async def add_admin_req(u, c):
    await request_super_action(u, c, "addadmin", "Promote Admin")

async def del_admin_req(u, c):
    await request_super_action(u, c, "deladmin", "Demote Admin")

async def remove_member_req(u, c):
    await request_super_action(u, c, "removemember", "Offboard User")

async def super_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await is_super(q.from_user.username):
        return
    if q.data == "sup_cancel":
        return await q.edit_message_text("Cancelled.")
    parts = q.data.split("_")
    act = parts[1]
    t = parts[2]
    pool = context.bot_data.get('db_pool')
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
            if t in ["stars", "all"]:
                await conn.execute("TRUNCATE kudos CASCADE")
            if t in ["birthdays", "all"]:
                await conn.execute("TRUNCATE birthdays CASCADE")
            await q.edit_message_text(f"Wiped `{t}` database matrix.")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT username FROM bot_admins')
    await context.bot.send_message(update.effective_user.id, "👑 **Admins:**\n" + "\n".join([f"• @{r['username']}" for r in recs]))

async def graveyard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT * FROM graveyard')
    await context.bot.send_message(update.effective_user.id, "🪦 **Graveyard:**\n" + "\n".join([f"• @{r['username']}" for r in recs]))

async def pause_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO config (key, value) VALUES ('maintenance_mode', 'true') ON CONFLICT (key) DO UPDATE SET value='true'")
    await context.bot.send_message(update.effective_user.id, "⏸️ **System Paused.**", parse_mode="Markdown")

async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO config (key, value) VALUES ('maintenance_mode', 'false') ON CONFLICT (key) DO UPDATE SET value='false'")
    await context.bot.send_message(update.effective_user.id, "▶️ **System Restarted.**", parse_mode="Markdown")

async def process_schedules(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    now = datetime.datetime.now(WIB)
    async with pool.acquire() as conn:
        schedules = await conn.fetch("SELECT * FROM scheduled_announcements")
        for s in schedules:
            should_run = False
            f = s['frequency']
            t_str = s['run_time']
            try:
                if f == 'once':
                    if now >= WIB.localize(datetime.datetime.strptime(t_str, "%m/%d/%Y %H.%M")) and not s['last_run']:
                        should_run = True
                elif f == 'daily':
                    h, m = map(int, t_str.split('.'))
                    if now.hour == h and now.minute == m and (not s['last_run'] or s['last_run'].date() < now.date()):
                        should_run = True
                elif f == 'weekly':
                    day, tm = t_str.split(' ')
                    h, m = map(int, tm.split('.'))
                    if now.weekday() == int(day) and now.hour == h and now.minute == m and (not s['last_run'] or (now - s['last_run'].astimezone(WIB)).days >= 6):
                        should_run = True
            except Exception:
                continue
            
            if should_run:
                msg = f"📢 **Scheduled Announcement**\n\n{s['message']}"
                if s['mention']:
                    users = await conn.fetch("SELECT username FROM users WHERE username IS NOT NULL")
                    msg += f"\n\n👥 " + " ".join([f"@{u['username']}" for u in users])
                targets = [g['chat_id'] for g in await conn.fetch("SELECT chat_id FROM active_groups")] if s['chat_id'] == 'all' else [int(s['chat_id'])]
                for t in targets:
                    try:
                        await send_md(context, t, msg)
                    except Exception:
                        pass
                await conn.execute("UPDATE scheduled_announcements SET last_run=$1 WHERE id=$2", now, s['id'])

async def schedule_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 4)]
        chat_id = parts[0].lower()
        freq = parts[1].lower()
        t_str = parts[2]
        mention = parts[3].lower() in ['mention', 'yes', 'y', 'true']
        msg = parts[4]
        if freq == 'once':
            datetime.datetime.strptime(t_str, "%m/%d/%Y %H.%M")
        elif freq == 'daily':
            h, m = map(int, t_str.split('.'))
            assert 0 <= h <= 23 and 0 <= m <= 59
        elif freq == 'weekly':
            d, tm = t_str.split(' ')
            h, m = map(int, tm.split('.'))
            assert 0 <= int(d) <= 6 and 0 <= h <= 23 and 0 <= m <= 59
        else:
            raise ValueError
    except Exception:
        return await update.message.reply_text("❌ Usage:\n`/schedule [ChatID|all] , [once|daily|weekly] , [Time] , [yes|no] , [Message]`", parse_mode="Markdown")
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO scheduled_announcements (chat_id, frequency, run_time, mention, message, created_by) VALUES ($1, $2, $3, $4, $5, $6)", chat_id, freq, t_str, mention, msg, update.effective_user.username)
    await update.message.reply_text("✅ Announcement scheduled successfully!")

async def list_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    async with pool.acquire() as conn:
        recs = await conn.fetch("SELECT * FROM scheduled_announcements ORDER BY id ASC")
    if not recs:
        return await update.message.reply_text("❌ No active schedules.")
    out = "✅ 🗓️ **Active Schedules**\n\n"
    for r in recs:
        out += f"🔹 `ID: {r['id']}` | **{r['frequency'].upper()}** | ⏰ {r['run_time']}\nTarget: {r['chat_id']} | Tag All: {r['mention']}\n📝 {r['message'][:30]}...\n\n"
    await send_md(context, update.effective_user.id, out)

async def del_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    try:
        s_id = int(context.args[0])
    except Exception:
        return await update.message.reply_text("❌ Format: `/delschedule [ID]`")
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM scheduled_announcements WHERE id=$1", s_id)
        if res == "DELETE 0":
            return await update.message.reply_text("❌ ID not found.")
    await update.message.reply_text(f"✅ Schedule {s_id} deleted.")
