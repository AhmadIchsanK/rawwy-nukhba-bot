import datetime, logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, delete_cmd, log_action, is_bot_admin

logger = logging.getLogger(__name__)

# --- 1/ EVENTS ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 2) if p.strip()]
        if len(parts) < 3: raise ValueError
        title = parts[0]
        e_time = WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H.%M"))
        rem = int(parts[2])
        if e_time < datetime.datetime.now(WIB): return await update.message.reply_text("❌ I cannot schedule events in the past. Please select a future date and time.")
    except ValueError:
        return await update.message.reply_text("❌ Time format error. Please strictly use `MM/DD/YYYY HH.MM`.")
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Created", "Error", str(e))
        return await update.message.reply_text("❌ Incorrect format. Please use: `/newevent Title , MM/DD/YYYY HH.MM , RemMins`")
    
    kb = [[InlineKeyboardButton("✅ Going", callback_data="rsvp_temp_Going"), InlineKeyboardButton("❌ Not Going", callback_data="rsvp_temp_Not Going")]]
    msg = await update.message.reply_text(f"✅ 📅 **{title} has been scheduled!**\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\nNo RSVPs yet.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    
    try: await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except: pass 
    
    async with pool.acquire() as conn: 
        e_id = await conn.fetchval('INSERT INTO events (title, event_time, created_by, chat_id, msg_id) VALUES ($1, $2, $3, $4, $5) RETURNING id', title, e_time, username, update.effective_chat.id, msg.message_id)
    
    new_kb = [[InlineKeyboardButton("✅ Going", callback_data=f"rsvp_{e_id}_Going"), InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not Going")]]
    await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
    
    # Import locally to avoid circular dependencies
    from cmd_admin import event_reminder, unpin_event
    context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
    context.job_queue.run_once(unpin_event, when=e_time, data={"chat_id": update.effective_chat.id, "msg_id": msg.message_id}, name=f"event_unpin_{e_id}")
    await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Created", "Success", f"Event '{title}' created")

async def edit_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        raw_args = " ".join(context.args)
        id_part, rest = raw_args.split(",", 1)
        title_part, time_str, rem_str = [p.strip() for p in rest.rsplit(",", 2)]
        e_id = int(id_part.strip()); title = title_part; e_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M")); rem = int(rem_str)
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Updated", "Error", str(e))
        return await update.message.reply_text("❌ Please use: `/editevent ID , Title , MM/DD/YYYY HH.MM , RemMins`")
    
    try:
        async with pool.acquire() as conn: 
            ev = await conn.fetchrow('SELECT created_by FROM events WHERE id=$1', e_id)
            if not ev: return await update.message.reply_text("❌ Event not found.")
            if ev['created_by'] != username and not await is_bot_admin(username, pool):
                return await update.message.reply_text("❌ Only the event creator or an admin can edit this event.")
                
            await conn.execute('UPDATE events SET title=$1, event_time=$2 WHERE id=$3', title, e_time, e_id)
            
        for job in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"): job.schedule_removal()
        
        from cmd_admin import event_reminder
        context.job_queue.run_once(event_reminder, when=e_time - datetime.timedelta(minutes=rem), chat_id=update.effective_chat.id, data={"id": e_id, "title": title}, name=f"event_rem_{e_id}")
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Updated", "Success", f"Event ID {e_id} updated")
        await update.message.reply_text(f"✅ Event `{e_id}` updated.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: events = await conn.fetch('SELECT id, title, event_time FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 5')
        if not events: return await update.message.reply_text("❌ No upcoming events scheduled.")
        await update.message.reply_text("✅ 📅 **Upcoming Events**\n" + "\n".join([f"🔹 **{e['title']}** (ID: `{e['id']}`)\n🕒 {e['event_time'].astimezone(WIB).strftime('%m/%d/%Y %H:%M')} WIB" for e in events]), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def rsvp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data.startswith("rsvp_temp"): return await q.answer("Initializing, please wait a second...")
    _, e_id, status = q.data.split("_")
    username = q.from_user.username or str(q.from_user.id)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO rsvps (event_id, username, status) VALUES ($1, $2, $3) ON CONFLICT (event_id, username) DO UPDATE SET status=$3', int(e_id), username, status)
        all_rsvps = await conn.fetch('SELECT username, status FROM rsvps WHERE event_id=$1', int(e_id))
        event = await conn.fetchrow('SELECT title, event_time FROM events WHERE id=$1', int(e_id))
    if not event: return await q.answer("Event deleted.")
    
    text = f"📅 **{event['title']}**\n🕒 {event['event_time'].astimezone(WIB).strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\n"
    for r in all_rsvps: text += f"{'✅' if r['status']=='Going' else '❌'} @{r['username']}\n"
    
    await q.edit_message_text(text, reply_markup=q.message.reply_markup, parse_mode="Markdown")
    await q.answer(status)
    await log_action(pool, q.from_user.id, update.effective_chat.id, "RSVP", "Success", f"User {username} RSVP {status} to event {e_id}")

# --- 2/ POLLS ---
def get_poll_kb(draft, pid):
    anon_str = "👻 Anonymous: ON" if draft['anon'] else "👻 Anonymous: OFF"
    multi_str = "☑️ Multiple Options" if draft['multi'] else "☑️ Single Option"
    quiz_str = f"🧠 Quiz (Ans: {draft['quiz_idx']+1})" if draft['quiz_idx'] >= 0 else "🧠 Quiz Mode: OFF"
    hrs_str = f"⏳ Duration: {draft['hours']}h"

    kb = [
        [InlineKeyboardButton(anon_str, callback_data=f"pollst_{pid}_anon"),
         InlineKeyboardButton(multi_str, callback_data=f"pollst_{pid}_multi")],
        [InlineKeyboardButton(quiz_str, callback_data=f"pollst_{pid}_quiz"),
         InlineKeyboardButton(hrs_str, callback_data=f"pollst_{pid}_hrs")],
        [InlineKeyboardButton("🚀 Finish Now", callback_data=f"pollst_{pid}_send")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"pollst_{pid}_cancel")]
    ]
    return InlineKeyboardMarkup(kb)

async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private": return await update.message.reply_text("❌ Polls must be created in a group.")
    pool = context.bot_data.get('db_pool')
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        if len(parts) < 3: raise ValueError
        question = parts[0]
        options = parts[1:11] 
    except Exception as e:
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Poll Create", "Error", str(e))
        return await update.message.reply_text("❌ Format error. Use: `/poll Question , Option 1 , Option 2 , ...`")

    pid = update.message.message_id
    context.chat_data[f"poll_{pid}"] = {
        'owner': update.effective_user.id,
        'q': question,
        'opts': options,
        'anon': False,
        'multi': False,
        'quiz_idx': -1,
        'hours': 24
    }

    opts_str = "\n".join([f"{i+1}. {o}" for i, o in enumerate(options)])
    text = f"📊 **Interactive Poll Setup**\n\n**Question:** {question}\n\n**Options:**\n{opts_str}\n\n_Configure settings below and click Finish Now._"

    await update.message.reply_text(text, reply_markup=get_poll_kb(context.chat_data[f"poll_{pid}"], pid), parse_mode="Markdown")

async def poll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")
    pid = int(parts[1])
    action = parts[2]

    draft = context.chat_data.get(f"poll_{pid}")
    if not draft:
        await q.message.delete()
        return await q.answer("❌ Poll session expired.", show_alert=True)

    if update.effective_user.id != draft['owner']:
        return await q.answer("❌ Only the creator can configure this poll.", show_alert=True)

    if action == "anon":
        draft['anon'] = not draft['anon']
    elif action == "multi":
        if draft['quiz_idx'] >= 0: return await q.answer("❌ Multiple answers are disabled in Quiz mode!", show_alert=True)
        draft['multi'] = not draft['multi']
    elif action == "quiz":
        draft['quiz_idx'] += 1
        if draft['quiz_idx'] >= len(draft['opts']): draft['quiz_idx'] = -1
        if draft['quiz_idx'] >= 0: draft['multi'] = False
    elif action == "hrs":
        cycles = [1, 6, 12, 24, 48, 72]
        idx = cycles.index(draft['hours']) if draft['hours'] in cycles else 0
        draft['hours'] = cycles[(idx + 1) % len(cycles)]
    elif action == "cancel":
        del context.chat_data[f"poll_{pid}"]
        await q.message.delete()
        return await q.answer("✅ Poll setup cancelled.")
    elif action == "send":
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn:
            active = await conn.fetchval("SELECT end_time FROM active_polls WHERE chat_id=$1 AND user_id=$2 AND end_time > NOW()", update.effective_chat.id, draft['owner'])
            if active:
                return await q.answer(f"❌ You already have an active poll running here until {active.astimezone(WIB).strftime('%H:%M WIB')}!", show_alert=True)

        dur = draft['hours'] * 3600
        try:
            msg = await context.bot.send_poll(
                chat_id=update.effective_chat.id,
                question=draft['q'],
                options=draft['opts'],
                is_anonymous=draft['anon'],
                allows_multiple_answers=draft['multi'],
                type='quiz' if draft['quiz_idx'] >= 0 else 'regular',
                correct_option_id=draft['quiz_idx'] if draft['quiz_idx'] >= 0 else None,
                open_period=dur
            )
            end_time = datetime.datetime.now(WIB) + datetime.timedelta(seconds=dur)
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO active_polls (chat_id, user_id, end_time) VALUES ($1, $2, $3) ON CONFLICT (chat_id, user_id) DO UPDATE SET end_time=$3", update.effective_chat.id, draft['owner'], end_time)

            rem_time = end_time - datetime.timedelta(minutes=15)
            if dur > 900:
                from cmd_admin import poll_reminder
                context.job_queue.run_once(poll_reminder, when=rem_time, data={"chat_id": update.effective_chat.id, "q": draft['q'], "msg_id": msg.message_id})

            del context.chat_data[f"poll_{pid}"]
            await q.message.delete()
            return await q.answer("✅ Poll launched successfully!")
        except Exception as e:
            return await q.answer(f"❌ Failed to launch poll: {str(e)}", show_alert=True)

    await q.edit_message_reply_markup(reply_markup=get_poll_kb(draft, pid))
    await q.answer()

# --- 3/ STARS ---
async def give_thanks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Please reply to a specific user's message to give them a Star!")
    giver = update.effective_user.username or str(update.effective_user.id)
    receiver_user = update.message.reply_to_message.from_user
    receiver = receiver_user.username or str(receiver_user.id)
    pool = context.bot_data.get('db_pool')
    
    if receiver_user.is_bot: return await update.message.reply_text("❌ Oops! I appreciate the thought, but bots cannot receive RAWWY Stars.")
    if giver == receiver: return await update.message.reply_text("❌ Nice try! You cannot convert your Star Quota to yourself. Please share the love with the team.")
    
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', giver)
            q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', giver)
            if q <= 0: 
                return await update.message.reply_text("❌ You have completely depleted your Star Quota for this week! Please wait for the Monday reset.")
            
            await conn.execute('UPDATE kudos SET quota=quota-1 WHERE username=$1', giver)
            await conn.execute('INSERT INTO kudos (username, monthly_points, all_time_points) VALUES ($1, 1, 1) ON CONFLICT (username) DO UPDATE SET monthly_points=kudos.monthly_points+1, all_time_points=kudos.all_time_points+1', receiver)
            score = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', receiver)
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Star Given", "Success", f"@{giver} gave star to @{receiver}")
        await update.message.reply_text(f"✅ 🌟 **Star Sent!**\n@{receiver} received a RAWWY Star from @{giver}!\nThey now have {score} total Stars.", parse_mode="Markdown")
        try: await context.bot.send_message(update.effective_user.id, f"✅ 🌟 You sent a star! You have **{q - 1} Star Quota** remaining this week.")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def my_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO kudos (username, quota) VALUES ($1, 3) ON CONFLICT DO NOTHING', user)
            q = await conn.fetchval('SELECT quota FROM kudos WHERE username=$1', user)
        await update.message.reply_text(f"✅ 🌟 Hello @{user}, you currently have **{q} Star Quota** left to give to others this week.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def my_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: pts = await conn.fetchval('SELECT monthly_points FROM kudos WHERE username=$1', user)
        if not pts or pts == 0: await update.message.reply_text("❌ You haven't received any RAWWY Stars this month yet. Keep helping others!")
        else: await update.message.reply_text(f"✅ 🌟 Awesome! You have received **{pts} RAWWY Stars** this month.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def total_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: pts = await conn.fetchval('SELECT all_time_points FROM kudos WHERE username=$1', user)
        if not pts or pts == 0: await update.message.reply_text("❌ You haven't collected any RAWWY Stars historically.")
        else: await update.message.reply_text(f"✅ 🌟 Impressive! You have collected a total of **{pts} RAWWY Stars** all-time.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

# --- 4/ LIBRARY ---
async def add_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_args = " ".join(context.args)
    if not raw_args: return await update.message.reply_text("❌ Looks like you missed something! Format: `/addlib Name , Link/Content , [private]`", parse_mode="Markdown")
    pool = context.bot_data.get('db_pool')
    try:
        is_private = False
        if raw_args.lower().endswith(", private"):
            is_private = True
            raw_args = raw_args[:-9].strip()
            await delete_cmd(update)
        parts = [p.strip() for p in raw_args.split(",", 1)]
        if len(parts) < 2: raise ValueError
        name = parts[0].lower(); content = parts[1]
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Add", "Error", str(e))
        return await update.message.reply_text("❌ Oops! The format seems a bit off. Please use: `/addlib Name , Content`")
    
    try:
        username = update.effective_user.username or str(update.effective_user.id)
        async with pool.acquire() as conn:
            exist = await conn.fetchval('SELECT name FROM library WHERE name=$1', name)
            if exist: return await update.message.reply_text(f"❌ That name ('{name}') is already taken! Please pick a unique name or use `/editlib` to update it.", parse_mode="Markdown")
            await conn.execute('INSERT INTO library (name, content, added_by, is_private) VALUES ($1, $2, $3, $4)', name, content, username, is_private)
        
        target_chat = update.effective_user.id if is_private else update.effective_chat.id
        try: await context.bot.send_message(target_chat, f"✅ Asset **'{name}'** added by {update.effective_user.first_name}! {'🔒 (Private)' if is_private else ''}", parse_mode="Markdown")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def edit_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 1)]
        if len(parts) < 2: raise ValueError
        name = parts[0].lower(); content = parts[1]
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Edit", "Error", str(e))
        return await update.message.reply_text("❌ Format error: `/editlib Name , New Content`")
    
    try:
        async with pool.acquire() as conn:
            asset = await conn.fetchrow('SELECT added_by FROM library WHERE name=$1', name)
            if not asset: return await update.message.reply_text("❌ I couldn't find that asset.")
            if asset['added_by'] != username and not await is_bot_admin(username, pool):
                return await update.message.reply_text("❌ Only the original author or an Admin can edit this file.")
            
            await conn.execute('UPDATE library SET content=$1 WHERE name=$2', content, name)
        await update.message.reply_text(f"✅ Asset **'{name}'** has been successfully updated.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def get_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: name = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await update.message.reply_text("❌ What asset are you looking for? Try: `/getlib Name`")
    
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            r = await conn.fetchrow('SELECT content, is_private, added_by FROM library WHERE name=$1', name)
            
        if not r: return await update.message.reply_text("❌ Hmm, I couldn't find that asset in the library.")
        if r['is_private']:
            await delete_cmd(update)
            if r['added_by'] != username:
                return await context.bot.send_message(update.effective_user.id, "❌ Sorry, you don't have permission to view this private file.")
            try: await context.bot.send_message(update.effective_user.id, f"✅ 🔒 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
            except: await update.message.reply_text("❌ Please start a DM with me so I can send your private files securely.")
        else:
            await update.message.reply_text(f"✅ 📂 **{name.title()}**:\n{r['content']}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def list_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            recs = await conn.fetch('SELECT name, is_private, added_by FROM library ORDER BY name ASC')
        if not recs: return await update.message.reply_text("❌ 📚 Library is empty.")
        
        msg = "✅ 📚 **RAWWY Library**\n"
        for r in recs:
            if r['is_private']:
                if r['added_by'] == username:
                    msg += f"• 🔒 `{r['name']}` (Private)\n"
            else:
                msg += f"• 📂 `{r['name']}`\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

# --- 5/ TASKS ---
async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    try: 
        raw_args = " ".join(context.args)
        parts = [p.strip() for p in raw_args.rsplit(",", 2)]
        if len(parts) < 3 or not all(parts): raise ValueError
        a = parts[0].replace("@", ""); m = int(parts[1]); d = parts[2]
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Task Assign", "Error", str(e))
        return await update.message.reply_text("❌ You missed some details! Format: `/assign @user , Minutes , Task description`", parse_mode="Markdown")
        
    try:
        assigner = update.effective_user.username or str(update.effective_user.id)
        if a.lower() == context.bot.username.lower(): return await update.message.reply_text("❌ I am an automated bot, I cannot complete human tasks!")
        if a.lower() == assigner.lower(): return await update.message.reply_text("❌ You cannot assign tasks to yourself. Please assign it to a team member.")
        if m < 60 or m > 480: return await update.message.reply_text("❌ For productivity reasons, task deadlines must be configured between 60 and 480 minutes.")
        
        dl = datetime.datetime.now(WIB) + datetime.timedelta(minutes=m)
        async with pool.acquire() as conn: 
            if not await is_bot_admin(assigner, pool):
                count = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE assigned_by=$1 AND status='Pending'", assigner)
                if count >= 4: return await update.message.reply_text("❌ You have reached the maximum limit of 4 active tasks assigned. Please wait for them to complete.")
                
            t_id = await conn.fetchval('INSERT INTO tasks (assignee, task_desc, deadline, assigned_by) VALUES ($1, $2, $3, $4) RETURNING id', a, d, dl, assigner)
        
        from cmd_admin import task_reminder
        context.job_queue.run_once(task_reminder, when=dl - datetime.timedelta(minutes=10), data={"assignee": a, "assigner": assigner, "id": t_id, "desc": d}, chat_id=update.effective_chat.id)
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Task Assign", "Success", f"Task {t_id} assigned to @{a}")
        await update.message.reply_text(f"✅ 📋 **Task Officially Assigned!**\n@{assigner} assigned Task `{t_id}` to @{a}.\n📝 {d}\n⏳ Must be completed by: {dl.strftime('%H:%M WIB')}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await update.message.reply_text("❌ Please provide the numeric ID: `/complete ID`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn:
            task = await conn.fetchrow('SELECT assignee, status FROM tasks WHERE id=$1', t_id)
            if not task: return await update.message.reply_text("❌ I couldn't find that task in the database.")
            if task['status'] == 'Completed': return await update.message.reply_text("❌ This task is already finished!")
            if task['assignee'] != username: return await update.message.reply_text("❌ Only the specific person assigned to this task can mark it complete.")
            await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", t_id)
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Task Complete", "Success", f"Task {t_id} completed")
        await update.message.reply_text(f"✅ Great job! Task `{t_id}` is officially marked as completed.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    now = datetime.datetime.now(WIB)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn: 
            tasks = await conn.fetch("SELECT id, task_desc, deadline FROM tasks WHERE status='Pending' AND assignee=$1 ORDER BY deadline", username)
        if not tasks: msg = "✅ 🎉 You have no pending tasks! Great job catching up."
        else:
            msg = "✅ 📋 **Your Active Tasks**\n\n"
            for t in tasks:
                rem = int((t['deadline'] - now).total_seconds() / 60)
                status = f"{rem}m left" if rem > 0 else "OVERDUE"
                msg += f"🔹 `{t['id']}` | {t['task_desc']} | ⏳ {status}\n"
        try: await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
        except: await update.message.reply_text("❌ Please start a DM with me so I can privately send you your task list.")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

# --- 6/ AWAY MODE ---
async def process_return(username, pool, bot):
    async with pool.acquire() as conn:
        mentions = await conn.fetch('SELECT mentioner, message, chat_title, created_at FROM away_mentions WHERE away_username=$1 ORDER BY created_at ASC', username)
        await conn.execute('DELETE FROM away_status WHERE username=$1', username)
        await conn.execute('DELETE FROM away_mentions WHERE away_username=$1', username)
        
    msg = f"✅ 🎉 A warm welcome back, @{username}! You are now marked as 🟢 Available.\n\n"
    if mentions:
        msg += "Here is your Away Mentions Recap:\n\n"
        for m in mentions:
            t_str = m['created_at'].astimezone(WIB).strftime('%m/%d %H:%M WIB')
            msg += f"🔹 [{t_str}] in **{m['chat_title']}**\n**@{m['mentioner']}**: \"{m['message']}\"\n\n"
    else: 
        msg += "It was quiet! You had absolutely zero mentions while you were away."
    return msg

async def set_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    try:
        async with pool.acquire() as conn:
            status = await conn.fetchrow("SELECT end_time FROM away_status WHERE username=$1", username)
            if status: return await update.message.reply_text(f"❌ You are already marked as Away until {status['end_time'].astimezone(WIB).strftime('%m/%d %H:%M WIB')}. Please type `/back` to reset.", parse_mode="Markdown")

        try:
            raw_args = " ".join(context.args)
            parts = [p.strip() for p in raw_args.rsplit(",", 1)]
            if len(parts) < 2 or not all(parts): raise ValueError
            reason, time_str = parts[0], parts[1]
            end_time = WIB.localize(datetime.datetime.strptime(time_str, "%m/%d/%Y %H.%M"))
            if end_time < datetime.datetime.now(WIB): 
                return await update.message.reply_text("❌ The time provided is in the past! Please set a future time.")
        except ValueError: return await update.message.reply_text("❌ Time format error. Strictly use `MM/DD/YYYY HH.MM` (e.g., `06/25/2026 14.30`).", parse_mode="Markdown")
        except Exception as e:
            await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Error", str(e))
            return await update.message.reply_text("❌ Format error: `/away Reason , MM/DD/YYYY HH.MM`", parse_mode="Markdown")

        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO away_status (username, reason, end_time) VALUES ($1, $2, $3)', username, reason, end_time)
        
        for j in context.job_queue.get_jobs_by_name(f"away_{username}"): j.schedule_removal()
        
        from cmd_admin import auto_return_away
        context.job_queue.run_once(auto_return_away, when=end_time, data={"username": username, "chat_id": update.effective_chat.id}, name=f"away_{username}")
        
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Set", f"@{username} set away status")
        await update.message.reply_text(f"✅ 🏖️ @{username} is away until {end_time.strftime('%b %d at %H:%M WIB')}.")
    except Exception as e:
        await update.message.reply_text(f"❌ System Error: {e}")

async def set_back(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            status = await conn.fetchrow('SELECT * FROM away_status WHERE username=$1', username)
            uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", username)
            if not status:
                if uid: 
                    try: await context.bot.send_message(uid, "❌ You are not currently marked as Away. Your status is already Available 🟢.", parse_mode="Markdown")
                    except: pass
                return
        
        for j in context.job_queue.get_jobs_by_name(f"away_{username}"): j.schedule_removal()
        msg = await process_return(username, pool, context.bot)
        
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Away Status", "Removed", f"@{username} manually returned")
        if uid:
            try: await context.bot.send_message(uid, msg, parse_mode="Markdown")
            except: pass
    except Exception as e:
        logger.error(f"Set back error: {e}")
