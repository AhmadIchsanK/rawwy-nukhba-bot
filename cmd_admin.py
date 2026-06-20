import datetime, logging
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core import WIB, SUPER_OWNER, GEMINI_API_KEY, is_super, is_bot_admin, delete_cmd, log_action, update_user_menu

# Import process_return for force_back
from cmd_user import process_return

logger = logging.getLogger(__name__)

# --- EVENTS / TASKS ADMIN ---
async def unpin_event(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.unpin_chat_message(chat_id=context.job.data['chat_id'], message_id=context.job.data['msg_id'])
    except: pass

async def event_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: r = await conn.fetch('SELECT username FROM rsvps WHERE event_id=$1 AND status=$2', context.job.data['id'], 'Going')
    if not r: return
    await context.bot.send_message(context.job.chat_id, f"⏰ Hey everyone! The event **{context.job.data['title']}** is starting very soon.\n" + " ".join([f"@{x['username']}" for x in r]), parse_mode="Markdown")

async def task_reminder(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: task = await conn.fetchrow("SELECT status FROM tasks WHERE id=$1", context.job.data['id'])
    if task and task['status'] != 'Completed': 
        await context.bot.send_message(context.job.chat_id, f"⚠️ Hello @{context.job.data['assignee']} and @{context.job.data['assigner']}, your task '{context.job.data['desc']}' is about to hit its deadline in exactly 10 minutes!")

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: e_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/cancelevent ID`")
    
    try:
        async with pool.acquire() as conn: 
            ev = await conn.fetchrow('SELECT chat_id, msg_id FROM events WHERE id=$1', e_id)
            if not ev: return await context.bot.send_message(update.effective_user.id, "❌ Event not found.")
            await conn.execute('DELETE FROM events WHERE id=$1', e_id)
            
        for j in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"): j.schedule_removal()
        for j in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"): j.schedule_removal()
        try: await context.bot.unpin_chat_message(chat_id=ev['chat_id'], message_id=ev['msg_id'])
        except: pass
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Event Cancelled", "Success", f"Event ID {e_id} cancelled by admin")
        await context.bot.send_message(update.effective_user.id, "✅ 🗑️ Event cancelled and removed.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    is_adm = await is_bot_admin(username, pool)
    try: t_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ Please provide the ID: `/canceltask ID`")
    
    try:
        async with pool.acquire() as conn:
            task = await conn.fetchrow('SELECT assigned_by FROM tasks WHERE id=$1', t_id)
            if not task: return await context.bot.send_message(update.effective_user.id, "❌ I couldn't find that task.")
            if task['assigned_by'] != username and not is_adm: 
                return await context.bot.send_message(update.effective_user.id, "❌ Only the assigner or an Admin can cancel this.")
            await conn.execute("DELETE FROM tasks WHERE id=$1", t_id)
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Task Cancelled", "Success", f"Task {t_id} cancelled")
        await context.bot.send_message(update.effective_user.id, "✅ 🗑️ Task successfully cancelled.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def del_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    is_adm = await is_bot_admin(username, pool)
    
    try: name = [p.strip() for p in " ".join(context.args).split(",") if p.strip()][0].lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Please provide an asset to delete: `/dellib Name`")
    
    try:
        async with pool.acquire() as conn:
            asset = await conn.fetchrow('SELECT added_by FROM library WHERE name=$1', name)
            if not asset: 
                return await context.bot.send_message(update.effective_user.id, "❌ That asset doesn't exist.")
            
            if asset['added_by'] != username and not is_adm:
                return await context.bot.send_message(update.effective_user.id, "❌ You can only delete assets that you personally added.")
            
            await conn.execute('DELETE FROM library WHERE name=$1', name)
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Library Delete", "Success", f"Asset '{name}' deleted")
        await context.bot.send_message(update.effective_user.id, f"✅ 🗑️ The asset '{name}' was successfully removed.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

# --- POLL ADMIN ---
async def cancel_poll_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.poll:
        return await context.bot.send_message(update.effective_user.id, "❌ Please reply to a live poll message with `/cancelpoll`.")
    
    try:
        await context.bot.stop_poll(update.effective_chat.id, update.message.reply_to_message.message_id)
        await context.bot.send_message(update.effective_user.id, "✅ Poll successfully stopped.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ Failed to stop poll: {e}")

async def poll_reminder(context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.send_message(context.job.data['chat_id'], f"⏳ **Attention team!** The poll '{context.job.data['q']}' is ending in 15 minutes! Please get your votes in.", reply_to_message_id=context.job.data['msg_id'], parse_mode="Markdown")
    except: pass

# --- GEMINI ADMIN ---
async def set_weekly_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try: limit = int(context.args[0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ Format error: `/setweeklylimit 20`")
    
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO config (key, value) VALUES ('gemini_weekly_limit', $1) ON CONFLICT (key) DO UPDATE SET value=$1", str(limit))
        await context.bot.send_message(update.effective_user.id, f"✅ Global Gemini weekly limit successfully set to {limit}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def admin_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        parts = [p.strip() for p in " ".join(context.args).split(",", 2) if p.strip()]
        t = parts[0].replace("@", "").lower(); act = parts[1].lower(); amt = int(parts[2])
        if act not in ['add', 'sub', 'set']: raise ValueError
    except: 
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/admin_gemini @user , [set/add/sub] , Amount`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn:
            if act == "set": await conn.execute("UPDATE users SET gemini_quota=$1 WHERE username=$2", amt, t)
            elif act == "add": await conn.execute("UPDATE users SET gemini_quota=gemini_quota+$1 WHERE username=$2", amt, t)
            elif act == "sub": await conn.execute("UPDATE users SET gemini_quota=gemini_quota-$1 WHERE username=$2", amt, t)
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Admin Gemini", "Success", f"Used '{act}' {amt} on @{t}'s quota.")
        await context.bot.send_message(update.effective_user.id, f"✅ Gemini quota for @{t} updated via '{act}' by {amt}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def check_gemini_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: target = " ".join(context.args).replace("@", "").strip().lower()
    except: return await context.bot.send_message(update.effective_user.id, "❌ Please use: `/checkgeminiquota all` OR `/checkgeminiquota @user`")
    if not target: return await context.bot.send_message(update.effective_user.id, "❌ Please provide a user or 'all'.")
    
    try:
        async with pool.acquire() as conn:
            if target == 'all':
                recs = await conn.fetch('SELECT username, gemini_quota FROM users ORDER BY gemini_quota ASC')
                msg = "✅ 🤖 **Team Gemini Quotas**\n" + "\n".join([f"@{r['username']} - Quota: {r['gemini_quota']}" for r in recs]) if recs else "❌ No records found."
            else:
                r = await conn.fetchval('SELECT gemini_quota FROM users WHERE username=$1', target)
                msg = f"✅ 🤖 **@{target} Gemini Audit**\nQuota left: {r}" if r is not None else "❌ User not found in database."
        await context.bot.send_message(update.effective_user.id, msg[:4000])
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def set_gemini_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_gemini(update, context)

# --- AI ANALYTICS ---
async def analyze_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    if not await is_bot_admin(username, pool): return
    if not GEMINI_API_KEY:
        return await context.bot.send_message(update.effective_user.id, "❌ System Error: GEMINI_API_KEY is not configured.")

    try:
        async with pool.acquire() as conn:
            # Query updated to remove strict created_at requirement
            reports = await conn.fetch("SELECT username, report FROM bug_reports")
            
        if not reports:
            return await context.bot.send_message(update.effective_user.id, "✅ 🎉 Your backlog is completely clean! There is zero feedback to analyze.")
            
        temp_msg = await context.bot.send_message(update.effective_user.id, "⏳ Compiling data and booting up Gemini for analysis... This might take a few seconds.")
        
        raw_data = ""
        for r in reports:
            raw_data += f"• @{r['username']} reported: {r['report']}\n"
            
        ai_prompt = (
            "You are a Senior Product Manager and Lead Software Engineer for an enterprise Telegram bot. "
            "Analyze the following raw user feedback and bug reports. Please provide a highly structured Markdown report with the following sections:\n"
            "1. 🚨 **Critical Bugs**: Identify actual broken features. Suggest technical solutions or code-level fixes to resolve them.\n"
            "2. 💡 **Feature Requests**: Group user requests into actionable new features. Rank them by perceived impact.\n"
            "3. 🔄 **Duplicates**: Point out if multiple users are asking for the same thing.\n\n"
            f"Here is the raw data:\n\n{raw_data}"
        )
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=ai_prompt
        )
        
        reply_text = f"✅ 🤖 **Gemini AI Product Analysis**\n\n{response.text}"
        
        if len(reply_text) > 4000:
            await temp_msg.delete()
            chunks = [reply_text[i:i+4000] for i in range(0, len(reply_text), 4000)]
            for chunk in chunks:
                await context.bot.send_message(update.effective_user.id, chunk, parse_mode="Markdown")
        else:
            await temp_msg.edit_text(reply_text, parse_mode="Markdown")
            
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Feedback Analytics", "Success", f"@{username} ran analysis.")
        
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ AI Execution Error: {e}")
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Feedback Analytics", "Error", str(e))

# --- BROADCASTS ---
async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",", 1) if p.strip()]
        if len(parts) < 2: raise ValueError
        target, msg = parts[0], parts[1]
    except Exception as e: 
        await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Error", str(e))
        return await context.bot.send_message(update.effective_user.id, "❌ Format: `/announce [ChatID or All] , Message`", parse_mode="Markdown")
    
    try:
        async with pool.acquire() as conn:
            a_id = await conn.fetchval("INSERT INTO announcements (text) VALUES ($1) RETURNING id", msg)
            targets = await conn.fetch("SELECT chat_id FROM active_groups") if target.lower() == "all" else [{"chat_id": int(target)}]
            
            if not targets:
                await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Failed", "No target groups configured.")
                return await context.bot.send_message(update.effective_user.id, "❌ Failed to send announcement.\nReason: No target groups configured.")
            
            sent = 0
            failed = 0
            for t in targets:
                try:
                    formatted_msg = f"📢 **[RW] NUKHBA BROADCAST**\n\nHello Nukhba,\n\n{msg}\n\nYalla Yalla"
                    m = await context.bot.send_message(t['chat_id'], formatted_msg, parse_mode="Markdown")
                    await conn.execute("INSERT INTO announcement_messages (announcement_id, chat_id, message_id) VALUES ($1, $2, $3)", a_id, t['chat_id'], m.message_id)
                    sent += 1
                except Exception as e: 
                    failed += 1
                    await log_action(pool, update.effective_user.id, t['chat_id'], "Announcement", "Error", f"Failed in group {t['chat_id']}: {str(e)}")

        if sent > 0:
            await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Success", f"Broadcast {a_id} sent to {sent} groups.")
            await context.bot.send_message(update.effective_user.id, f"✅ Announcement sent successfully to {sent} group(s).", parse_mode="Markdown")
        
        if failed > 0:
            await log_action(pool, update.effective_user.id, update.effective_chat.id, "Announcement", "Failed", f"Broadcast {a_id} failed in {failed} groups.")
            await context.bot.send_message(update.effective_user.id, f"❌ Failed to send announcement to {failed} group(s).\nReason: Bot lacks permission or group not found.", parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def edit_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: 
        parts = [p.strip() for p in " ".join(context.args).split(",", 1) if p.strip()]
        a_id = int(parts[0]); new_msg = parts[1]
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/editannounce ID , New Msg`")
    
    try:
        async with pool.acquire() as conn:
            msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
            for m in msgs:
                try: await context.bot.edit_message_text(f"📢 **[RW] NUKHBA BROADCAST**\n\nHello Nukhba,\n\n{new_msg}\n\nYalla Yalla", chat_id=m['chat_id'], message_id=m['message_id'], parse_mode="Markdown")
                except: pass
            await conn.execute("UPDATE announcements SET text=$1 WHERE id=$2", new_msg, a_id)
        await context.bot.send_message(update.effective_user.id, f"✅ Updated Announcement {a_id}.")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: {e}")

async def del_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    try: a_id = int([p.strip() for p in " ".join(context.args).split(",") if p.strip()][0])
    except: return await context.bot.send_message(update.effective_user.id, "❌ `/delannounce ID`")
    
    try:
        async with pool.acquire() as conn:
            msgs = await conn.fetch("SELECT chat_id, message_id FROM announcement_messages WHERE announcement_id=$1", a_id)
            for m in msgs:
                try: await context.bot.delete_message(chat_id=m['chat_id'], message_id=m['message_id'])
                except: pass
            await conn.execute("DELETE FROM announcements WHERE id=$1", a_id)
            await conn.execute("DELETE FROM announcement_messages WHERE announcement_id=$1", a_id)
        await context.bot.send_message(update.effective_user.id, f"✅ Deleted Announcement {a_id}.")
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

async def get_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(username, pool): return
    
    try:
        target_date = datetime.datetime.now(WIB).date()
        msg = await generate_audit_report(pool, target_date)
        await context.bot.send_message(update.effective_user.id, msg, parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_user.id, f"❌ System Error: `{e}`", parse_mode="Markdown")

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
