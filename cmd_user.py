import datetime
import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, delete_cmd, is_bot_admin

logger = logging.getLogger(__name__)

async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        parts = [p.strip() for p in " ".join(context.args).rsplit(",", 2) if p.strip()]
        if len(parts) < 3:
            raise ValueError
        title = parts[0]
        e_time = WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H:%M"))
        rem = int(parts[2])
        if e_time < datetime.datetime.now(WIB):
            return await update.message.reply_text("❌ Cannot schedule in the past.")
    except Exception:
        return await update.message.reply_text("❌ Format: `/newevent [Title] , [MM/DD/YYYY HH:MM] , [RemMins]`", parse_mode="Markdown")
    
    async with pool.acquire() as conn:
        max_e = int(await conn.fetchval("SELECT value FROM config WHERE key='max_events'") or 5)
        if not await is_bot_admin(username, pool):
            count = await conn.fetchval("SELECT COUNT(*) FROM events WHERE created_by=$1 AND event_time > NOW()", username)
            if count >= max_e:
                return await update.message.reply_text(f"❌ Max {max_e} active events allowed.")
    
    kb = [[InlineKeyboardButton("✅ Going", callback_data="rsvp_temp_Going"), InlineKeyboardButton("❌ Not Going", callback_data="rsvp_temp_Not")]]
    msg = await update.message.reply_text(f"✅ 📅 **{title} scheduled!**\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\nNone", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    
    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except Exception:
        pass 
        
    async with pool.acquire() as conn:
        e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by, chat_id, msg_id) VALUES ($1, $2, $3, $4, $5) RETURNING id', title, e_time, username, update.effective_chat.id, msg.message_id)
    
    new_kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not")]]
    await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
    
    from cmd_admin import event_reminder, unpin_event
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
    context.job_queue.run_once(unpin_event, when=e_time, data={"chat_id": update.effective_chat.id, "msg_id": msg.message_id}, name=f"event_unpin_{e_id}")

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        parts = " ".join(context.args).split(",", 1)
        e_id = int(parts[0].strip())
        title, time_str, rem_str = [p.strip() for p in parts[1].rsplit(",", 2)]
        e_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H:%M"))
        rem = int(rem_str)
    except Exception:
        return await update.message.reply_text("❌ Format: `/editevent [ID] , [Title] , [MM/DD/YYYY HH:MM] , [RemMins]`", parse_mode="Markdown")
    
    async with pool.acquire() as conn:
        ev = await conn.fetchrow('SELECT created_by FROM events WHERE id=$1', e_id)
        if not ev:
            return await update.message.reply_text("❌ Event not found.")
        if ev['created_by'] != username and not await is_bot_admin(username, pool):
            return await update.message.reply_text("❌ Unauthorized.")
        await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, e_id)
        
    for job in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"):
        job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"):
        job.schedule_removal()
        
    from cmd_admin import event_reminder
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
    await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
        
    if not events:
        return await update.message.reply_text("❌ No upcoming events scheduled.")
        
    msg = "✅ 📅 **Upcoming Events**\n\n"
    for e in events:
        msg += f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB\n\n"
        
    await update.message.reply_text(msg, parse_mode="Markdown")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data.startswith("rsvp_temp"):
        return await q.answer("Initializing...")
    
    _, e_id, status = q.data.split("_")
    username = q.from_user.username or str(q.from_user.id)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status=$3', int(e_id), username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title, event_time FROM events WHERE id=$1', int(e_id))
        
    if not event:
        return await q.answer("Event deleted.")
        
    text = f"📅 **{event['title']}**\n🕒 {event['event_time'].astimezone(WIB).strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\n"
    for r in all_rsvps:
        text += f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n"
        
    await q.edit_message_text(text, reply_markup=q.message.reply_markup, parse_mode="Markdown")
    await q.answer(status)

async def get_poll_kb(pid, pool):
    async with pool.acquire() as conn:
        d = await conn.fetchrow("SELECT * FROM poll_drafts WHERE pid=$1", pid)
    if not d:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"👻 Anon: {'ON' if d['anon'] else 'OFF'}", callback_data=f"pollst_{pid}_anon"), InlineKeyboardButton("☑️ Multi" if d['multi'] else "☑️ Single", callback_data=f"pollst_{pid}_multi")],
        [InlineKeyboardButton(f"🧠 Quiz ({d['quiz_idx']+1})" if d['quiz_idx'] >= 0 else "🧠 Quiz: OFF", callback_data=f"pollst_{pid}_quiz"), InlineKeyboardButton(f"⏳ {d['hours']}h", callback_data=f"pollst_{pid}_hrs")],
        [InlineKeyboardButton("🚀 Finish", callback_data=f"pollst_{pid}_send"), InlineKeyboardButton("❌ Cancel", callback_data=f"pollst_{pid}_cancel")]
    ])

async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return await update.message.reply_text("❌ Group only.")
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        q = parts[0]
        opts = parts[1:11]
    except Exception:
        return await update.message.reply_text("❌ Format: `/poll [Question] , [Opt1] , [Opt2]`", parse_mode="Markdown")
    if len(opts) < 2:
        return await update.message.reply_text("❌ Need at least 2 options.")
        
    pid = update.message.message_id
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO poll_drafts (pid, owner, q, opts, anon, multi, quiz_idx, hours) VALUES ($1, $2, $3, $4, False, False, -1, 24)", pid, update.effective_user.id, q, json.dumps(opts))
    
    opts_str = ""
    for i, o in enumerate(opts):
        opts_str += f"{i+1}. {o}\n"
        
    kb = await get_poll_kb(pid, pool)
    if kb:
        await update.message.reply_text(f"📊 **Poll Setup**\n\n**Q:** {q}\n\n{opts_str}", reply_markup=kb, parse_mode="Markdown")

async def poll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, pid_str, act = q.data.split("_")
    pid = int(pid_str)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        draft = await conn.fetchrow("SELECT * FROM poll_drafts WHERE pid=$1", pid)
        if not draft:
            await q.message.delete()
            return await q.answer("Draft expired.", show_alert=True)
        if update.effective_user.id != draft['owner']:
            return await q.answer("Unauthorized.", show_alert=True)
        
        if act == "anon":
            await conn.execute("UPDATE poll_drafts SET anon = NOT anon WHERE pid=$1", pid)
        elif act == "multi":
            await conn.execute("UPDATE poll_drafts SET multi = NOT multi WHERE pid=$1", pid)
        elif act == "quiz":
            nxt = -1 if draft['quiz_idx'] >= len(json.loads(draft['opts'])) - 1 else draft['quiz_idx'] + 1
            await conn.execute("UPDATE poll_drafts SET quiz_idx=$1, multi=False WHERE pid=$2", nxt, pid)
        elif act == "hrs":
            cycles = [1, 6, 12, 24, 48, 72]
            nxt = cycles[(cycles.index(draft['hours']) + 1) % 6] if draft['hours'] in cycles else 24
            await conn.execute("UPDATE poll_drafts SET hours=$1 WHERE pid=$2", nxt, pid)
        elif act == "cancel":
            await conn.execute("DELETE FROM poll_drafts WHERE pid=$1", pid)
            await q.message.delete()
            return await q.answer("Cancelled.")
        elif act == "send":
            opts = json.loads(draft['opts'])
            dur = draft['hours'] * 3600
            try:
                msg = await context.bot.send_poll(update.effective_chat.id, draft['q'], opts, is_anonymous=draft['anon'], allows_multiple_answers=draft['multi'], type='quiz' if draft['quiz_idx'] >= 0 else 'regular', correct_option_id=draft['quiz_idx'] if draft['quiz_idx'] >= 0 else None, open_period=dur)
                end_time = datetime.datetime.now(WIB) + datetime.timedelta(seconds=dur)
                await conn.execute("INSERT INTO active_polls (chat_id, user_id, end_time) VALUES ($1, $2, $3) ON CONFLICT (chat_id, user_id) DO UPDATE SET end_time=$3", update.effective_chat.id, draft['owner'], end_time)
                await conn.execute("DELETE FROM poll_drafts WHERE pid=$1", pid)
                await q.message.delete()
                return await q.answer("Launched!")
            except Exception as e:
                return await q.answer(f"Error: {e}", show_alert=True)
            
    kb = await get_poll_kb(pid, pool)
    if kb:
        await q.edit_message_reply_markup(reply_markup=kb)

async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("❌ Reply to a message to give a Star!")
    
    giver = update.effective_user.username or str(update.effective_user.id)
    receiver_user = update.message.reply_to_message.from_user
    receiver = receiver_user.username or str(receiver_user.id)
    
    if receiver_user.is_bot or giver == receiver:
        return await update.message.reply_text("❌ Cannot star bots or yourself.")
        
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        sq_str = await conn.fetchval("SELECT value FROM config WHERE key='star_quota'")
        sq = int(sq_str) if sq_str and sq_str.isdigit() else 3
        
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, $2) ON CONFLICT DO NOTHING', giver, sq)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
        if q <= 0:
            return await update.message.reply_text("❌ Quota empty until Monday.")
            
        await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
        await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
        score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
        
    await update.message.reply_text(f"✅ 🌟 @{receiver} received a Star from @{giver}! (Total: {score})")

async def my_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        sq_str = await conn.fetchval("SELECT value FROM config WHERE key='star_quota'")
        sq = int(sq_str) if sq_str and sq_str.isdigit() else 3
        await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, $2) ON CONFLICT DO NOTHING', user, sq)
        q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"✅ You have **{q} Star Quota** left.", parse_mode="Markdown")

async def my_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        pts = await conn.fetchval('SELECT monthly_points FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"✅ Monthly Stars: **{pts or 0}**", parse_mode="Markdown")

async def total_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        pts = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', user)
    await update.message.reply_text(f"✅ All-Time Stars: **{pts or 0}**", parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core import delete_cmd
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        monthly = await conn.fetch("SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 5")
        all_time = await conn.fetch("SELECT username, all_time_points FROM kudos WHERE all_time_points > 0 ORDER BY all_time_points DESC LIMIT 5")
    
    msg = "🏆 **RAWWY Stars Leaderboard** 🏆\n\n📅 **This Month's Top Stars:**\n"
    if monthly:
        for i, r in enumerate(monthly):
            msg += f"{i+1}. @{r['username']} - {r['monthly_points']}\n"
    else:
        msg += "None.\n"
        
    msg += "\n🌟 **All-Time Top Stars:**\n"
    if all_time:
        for i, r in enumerate(all_time):
            msg += f"{i+1}. @{r['username']} - {r['all_time_points']}\n"
    else:
        msg += "None.\n"
        
    await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")

async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core import delete_cmd
    raw = " ".join(context.args)
    if not raw:
        return await update.message.reply_text("❌ Format: `/addlib [Name] , [Content]`", parse_mode="Markdown")
    
    is_p = False
    if raw.lower().endswith(", private"):
        is_p = True
        raw = raw[:-9].strip()
        await delete_cmd(update)
        
    try:
        parts = [p.strip() for p in raw.split(",", 1)]
        name = parts[0].lower()
        content = parts[1]
    except Exception:
        return await update.message.reply_text("❌ Format error.")
        
    pool = context.bot_data.get('db_pool')
    username = update.effective_user.username or str(update.effective_user.id)
    
    async with pool.acquire() as conn:
        if await conn.fetchval('SELECT name FROM library WHERE name=$1', name):
            return await update.message.reply_text("❌ Name taken.")
        await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4)', name, content, username, is_p)
        
    try:
        await context.bot.send_message(update.effective_user.id if is_p else update.effective_chat.id, f"✅ Asset **'{name}'** added! {'🔒' if is_p else ''}", parse_mode="Markdown")
    except Exception:
        pass

async def edit_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        name = parts[0].lower()
        content = parts[1]
    except Exception:
        return await update.message.reply_text("❌ Format error.")
        
    async with pool.acquire() as conn:
        asset = await conn.fetchrow('SELECT added_by FROM library WHERE name=$1', name)
        if not asset:
            return await update.message.reply_text("❌ Not found.")
        if asset['added_by'] != username and not await is_bot_admin(username, pool):
            return await update.message.reply_text("❌ Unauthorized.")
        await conn.execute('UPDATE library SET content=$1 WHERE name=$2', content, name)
        
    await update.message.reply_text(f"✅ Updated **'{name}'**.", parse_mode="Markdown")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core import delete_cmd
    try:
        name = context.args[0].lower().strip()
    except Exception:
        return await update.message.reply_text("❌ Format: `/getlib [Name]`", parse_mode="Markdown")
        
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        r = await conn.fetchrow('SELECT content, is_private, added_by FROM library WHERE name=$1', name)
        
    if not r:
        return await update.message.reply_text("❌ Not found.")
        
    if r['is_private']:
        await delete_cmd(update)
        if r['added_by'] != username:
            return await context.bot.send_message(update.effective_user.id, "❌ Private file.")
        try:
            await context.bot.send_message(update.effective_user.id, f"✅ 🔒 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("❌ Please DM me first.")
    else:
        await update.message.reply_text(f"✅ 📂 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
    if not recs:
        return await update.message.reply_text("❌ Empty.")
        
    msg = "✅ 📚 **Library**\n"
    for r in recs:
        if not r['is_private'] or r['added_by'] == username:
            msg += f"• {'🔒' if r['is_private'] else '📂'} `{r['name']}`\n"
            
    await update.message.reply_text(msg, parse_mode="Markdown")

async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    try:
        parts = [p.strip() for p in " ".join(context.args).rsplit(",", 2)]
        a = parts[0].replace("@", "")
        m = int(parts[1])
        d = parts[2]
    except Exception:
        return await update.message.reply_text("❌ Format: `/assign [@user] , [Mins] , [Desc]`", parse_mode="Markdown")
        
    assigner = update.effective_user.username or str(update.effective_user.id)
    if a.lower() == assigner.lower():
        return await update.message.reply_text("❌ Cannot self-assign.")
    if m < 60 or m > 480:
        return await update.message.reply_text("❌ Must be 60-480m.")
        
    dl = datetime.datetime.now(WIB) + datetime.timedelta(minutes=m)
    async with pool.acquire() as conn:
        max_t = int(await conn.fetchval("SELECT value FROM config WHERE key='max_tasks'") or 4)
        if not await is_bot_admin(assigner, pool):
            count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE assigned_by=$1 AND status='Pending'", assigner)
            if count >= max_t:
                return await update.message.reply_text(f"❌ Max {max_t} active assigned tasks allowed.")
        t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', a, d, dl, assigner)
        
    from cmd_admin import task_reminder
    context.job_queue.run_once(task_reminder, when=dl - datetime.timedelta(minutes=10), data={"assignee": a, "assigner": assigner, "id": t_id, "desc": d}, chat_id=update.effective_chat.id)
    await update.message.reply_text(f"✅ Task `{t_id}` assigned to @{a}.\n📝 {d}\n⏳ Due: {dl.strftime('%H:%M WIB')}", parse_mode="Markdown")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        t_id = int(context.args[0])
    except Exception:
        return await update.message.reply_text("❌ Format: `/complete [ID]`", parse_mode="Markdown")
        
    async with pool.acquire() as conn:
        task = await conn.fetchrow('SELECT assignee, status FROM tasks WHERE id=$1', t_id)
        if not task:
            return await update.message.reply_text("❌ Not found.")
        if task['status'] == 'Completed':
            return await update.message.reply_text("❌ Already done.")
        if task['assignee'] != username:
            return await update.message.reply_text("❌ Only assignee can complete.")
        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
        
    await update.message.reply_text(f"✅ Task `{t_id}` marked complete.", parse_mode="Markdown")

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        tasks = await conn.fetch("SELECT id, task_desc, deadline FROM tasks WHERE status='Pending' AND assignee=$1 ORDER BY deadline", username)
        
    if not tasks:
        return await update.message.reply_text("✅ No pending tasks.")
        
    msg = "✅ 📋 **Your Active Tasks**\n\n"
    for t in tasks:
        msg += f"🔹 `{t['id']}` | {t['task_desc']} | ⏳ {int((t['deadline'] - now).total_seconds() / 60)}m\n"
        
    try:
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Please DM me first.")

async def process_return(username, pool, bot):
    async with pool.acquire() as conn:
        mentions = await conn.fetch('SELECT mentioner, message, chat_title, created_at FROM away_mentions WHERE away_username=$1 ORDER BY created_at ASC', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
        
    msg = f"✅ 🎉 Welcome back, @{username}! Status: 🟢 Available.\n\n"
    if mentions:
        msg += "Away Mentions:\n\n"
        for m in mentions:
            msg += f"🔹 [{m['created_at'].astimezone(WIB).strftime('%m/%d %H:%M')}] in {m['chat_title']}\n@{m['mentioner']}: \"{m['message']}\"\n\n"
    else:
        msg += "No mentions while away."
    return msg

async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            status = await conn.fetchrow("SELECT end_time FROM away_status WHERE username=$1", username)
            if status:
                return await update.message.reply_text(f"❌ Already Away until {status['end_time'].astimezone(WIB).strftime('%m/%d %H:%M')}.")
                
        parts = [p.strip() for p in " ".join(context.args).rsplit(",", 1)]
        reason = parts[0]
        end_time = WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H:%M"))
        if end_time < datetime.datetime.now(WIB):
            return await update.message.reply_text("❌ Time is in the past.")
    except Exception:
        return await update.message.reply_text("❌ Format: `/away [Reason] , [MM/DD/YYYY HH:MM]`", parse_mode="Markdown")
        
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3)', username, reason, end_time)
        
    for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
        j.schedule_removal()
        
    from cmd_admin import auto_return_away
    context.job_queue.run_once(auto_return_away, when=end_time, data={"username": username, "chat_id": update.effective_chat.id}, name=f"away_{username}")
    await update.message.reply_text(f"✅ 🏖️ @{username} is away until {end_time.strftime('%b %d at %H:%M')}.")

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core import delete_cmd
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        if not await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username):
            return
        uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
        
    for j in context.job_queue.get_jobs_by_name(f"away_{username}"):
        j.schedule_removal()
        
    msg = await process_return(username, pool, context.bot)
    if uid:
        try:
            await context.bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception:
            pass
