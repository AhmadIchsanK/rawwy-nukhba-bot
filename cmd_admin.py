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

async def manage_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
        
    context.user_data['mu_owner'] = update.effective_user.id
    await render_mu_search(update, context, False)

async def render_mu_search(update, context, from_custom_input=False):
    kb = [[InlineKeyboardButton("🔍 Search User", callback_data="mu_search")],
          [InlineKeyboardButton("❌ Cancel", callback_data="mu_cancel")]]
    text = "👥 **User Management Dashboard**\n\nClick below to search for a user to manage."
    
    if from_custom_input:
        msg_id = context.user_data.get('inline_msg_id')
        try:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception:
            pass
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception:
            pass
    else:
        msg = await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        context.user_data['inline_msg_id'] = msg.message_id

async def render_mu_menu(update, context, from_custom_input=False):
    d = context.user_data.get('mu_draft')
    if not d:
        return
        
    text = (
        f"👥 **Managing User: @{d['target_user']}**\n\n"
        f"⭐ Stars Quota: `{d['stars']}`\n"
        f"🧠 Knowledge Points: `{d['kp']}`\n"
        f"🤖 AI Limit: `{d['limit']}`\n\n"
        "*(Changes require ✅ Save)*"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Edit Stars", callback_data="mu_edit_stars"), InlineKeyboardButton("🧠 Edit KP", callback_data="mu_edit_kp")],
        [InlineKeyboardButton("🤖 Edit AI Limit", callback_data="mu_edit_ai"), InlineKeyboardButton("⛔ Offboard", callback_data="mu_offboard")],
        [InlineKeyboardButton("✅ Finish & Save", callback_data="mu_save"), InlineKeyboardButton("❌ Cancel", callback_data="mu_cancel")]
    ])
    
    if from_custom_input:
        msg_id = context.user_data.get('inline_msg_id')
        try:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_id, text=text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass

async def render_mu_edit(update, context, field_name):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("-10", callback_data=f"mu_val_-10_{field_name}"), InlineKeyboardButton("-1", callback_data=f"mu_val_-1_{field_name}"), InlineKeyboardButton("+1", callback_data=f"mu_val_+1_{field_name}"), InlineKeyboardButton("+10", callback_data=f"mu_val_+10_{field_name}")],
        [InlineKeyboardButton("✏️ Custom Amount", callback_data=f"mu_custom_{field_name}")],
        [InlineKeyboardButton("🔙 Back", callback_data="mu_back")]
    ])
    try:
        await update.callback_query.edit_message_text(f"Adjusting **{field_name}**:", reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass

async def manageusers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner = context.user_data.get('mu_owner')
    if owner and q.from_user.id != owner:
        return await q.answer("Unauthorized.", show_alert=True)
        
    act = q.data.split("_", 1)[1]
    d = context.user_data.get('mu_draft')
    
    if act == "cancel":
        context.user_data.pop('mu_draft', None)
        return await q.edit_message_text("❌ User Management Closed.")
        
    if act == "search":
        context.user_data['inline_step'] = 'mu_search'
        context.user_data['inline_owner'] = owner
        return await q.edit_message_text("✏️ Please type the exact `@username` to manage:")
        
    if not d:
        return await q.answer("Draft expired.", show_alert=True)
        
    if act == "edit_stars":
        return await render_mu_edit(update, context, "stars")
    elif act == "edit_kp":
        return await render_mu_edit(update, context, "kp")
    elif act == "edit_ai":
        return await render_mu_edit(update, context, "limit")
        
    elif act.startswith("val_"):
        parts = act.split("_")
        val = int(parts[1])
        field = parts[2]
        d[field] += val
        return await render_mu_menu(update, context)
        
    elif act.startswith("custom_"):
        field = act.split("_")[1]
        context.user_data['inline_step'] = f'mu_custom_{field}'
        context.user_data['inline_owner'] = owner
        return await q.edit_message_text(f"✏️ Type new amount for {field}:")
        
    elif act == "offboard":
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM kudos WHERE username=$1", d['target_user'])
            await conn.execute("DELETE FROM birthdays WHERE username=$1", d['target_user'])
        context.user_data.pop('mu_draft', None)
        return await q.edit_message_text(f"⛔ User @{d['target_user']} offboarded.")
        
    elif act == "back":
        return await render_mu_menu(update, context)
        
    elif act == "save":
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO kudos (username, quota) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET quota=$2", d['target_user'], d['stars'])
            await conn.execute("INSERT INTO users (username, gemini_quota) VALUES ($1, $2) ON CONFLICT (username) DO UPDATE SET gemini_quota=$2", d['target_user'], d['limit'])
            await conn.execute("INSERT INTO trivia_scores (username, all_time_kp, monthly_kp) VALUES ($1, $2, $2) ON CONFLICT (username) DO UPDATE SET all_time_kp=$2, monthly_kp=$2", d['target_user'], d['kp'])
        context.user_data.pop('mu_draft', None)
        return await q.edit_message_text("✅ **User Data Saved!**", parse_mode="Markdown")

async def newsched_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
        
    context.user_data['ns_owner'] = update.effective_user.id
    context.user_data['ns_draft'] = {'target': 'all', 'freq': 'daily', 'time': '12:00', 'mention': False, 'msg': ''}
    await render_ns_menu(update, context, False)

async def render_ns_menu(update, context, from_custom_input=False):
    d = context.user_data.get('ns_draft')
    if not d:
        return
        
    text = (
        "🗓️ **Broadcast Scheduler**\n\n"
        f"🎯 Target: `{d['target']}`\n"
        f"🔄 Frequency: `{d['freq'].upper()}`\n"
        f"⏰ Time: `{d['time']}`\n"
        f"🔔 Tag All: `{'ON' if d['mention'] else 'OFF'}`\n\n"
        f"📝 Message:\n_{d['msg'] if d['msg'] else 'None'}_\n\n"
        "*(Changes require ✅ Save)*"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Edit Target Chat", callback_data="ns_chat"), InlineKeyboardButton("🔄 Toggle Freq", callback_data="ns_freq")],
        [InlineKeyboardButton("⏰ Edit Time", callback_data="ns_time"), InlineKeyboardButton("🔔 Toggle Tag All", callback_data="ns_mention")],
        [InlineKeyboardButton("📝 Edit Message", callback_data="ns_msg")],
        [InlineKeyboardButton("✅ Save & Schedule", callback_data="ns_save"), InlineKeyboardButton("❌ Cancel", callback_data="ns_cancel")]
    ])
    
    if from_custom_input:
        msg_id = context.user_data.get('inline_msg_id')
        try:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_id, text=text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
    else:
        msg = await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        context.user_data['inline_msg_id'] = msg.message_id

async def sched_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner = context.user_data.get('ns_owner')
    if owner and q.from_user.id != owner:
        return await q.answer("Unauthorized.", show_alert=True)
        
    act = q.data.split("_", 1)[1]
    d = context.user_data.get('ns_draft')
    
    if act == "cancel":
        context.user_data.pop('ns_draft', None)
        return await q.edit_message_text("❌ Scheduler Cancelled.")
        
    if not d:
        return await q.answer("Draft expired.", show_alert=True)
        
    if act == "chat":
        context.user_data['inline_step'] = 'ns_chat'
        context.user_data['inline_owner'] = owner
        return await q.edit_message_text("✏️ Please type Target Chat ID or 'all':")
    elif act == "freq":
        cycle = ['once', 'daily', 'weekly']
        d['freq'] = cycle[(cycle.index(d['freq']) + 1) % 3]
        return await render_ns_menu(update, context)
    elif act == "mention":
        d['mention'] = not d['mention']
        return await render_ns_menu(update, context)
    elif act == "time":
        context.user_data['inline_step'] = 'ns_time'
        context.user_data['inline_owner'] = owner
        return await q.edit_message_text("✏️ Please type execution time (HH:MM):")
    elif act == "msg":
        context.user_data['inline_step'] = 'ns_msg'
        context.user_data['inline_owner'] = owner
        return await q.edit_message_text("✏️ Please type the broadcast message:")
    elif act == "save":
        if not d['msg']:
            return await q.answer("Message cannot be empty.", show_alert=True)
        pool = context.bot_data.get('db_pool')
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO scheduled_announcements (chat_id, frequency, run_time, mention, message, created_by) VALUES ($1, $2, $3, $4, $5, $6)", d['target'], d['freq'], d['time'], d['mention'], d['msg'], update.effective_user.username)
        context.user_data.pop('ns_draft', None)
        return await q.edit_message_text("✅ **Broadcast Scheduled!**", parse_mode="Markdown")

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
        
    text = (
        "⚙️ **NUKHBA GLOBAL CONFIGURATION**\n\n"
        f"🤖 AI Limit: `{gl} queries/wk`\n"
        f"🌟 Star Quota: `{sq} stars/wk`\n"
        f"⚡ Max Tasks: `{mt} pending/user`\n"
        f"🏖️ Max Away: `{ma} days`"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 AI Limit ({gl})", callback_data="cfg_gemini"), InlineKeyboardButton(f"🌟 Star Quota ({sq})", callback_data="cfg_stars")],
        [InlineKeyboardButton(f"⚡ Max Tasks ({mt})", callback_data="cfg_tasks"), InlineKeyboardButton(f"🏖️ Max Away ({ma})", callback_data="cfg_away")]
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(q.from_user.username, pool):
        return await q.answer("Unauthorized", show_alert=True)
    
    act = q.data.split("_")[1]
    keys = {"gemini": "gemini_weekly_limit", "stars": "star_quota", "tasks": "max_tasks", "away": "max_away_days"}
    increments = {"gemini": 5, "stars": 1, "tasks": 1, "away": 2}
    
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
    valid = {"bday": "bday_channel", "feedback": "feedback_channel"}
    if target not in valid:
        return await update.message.reply_text("❌ Usage: `/setchannel <bday|feedback>`")
    
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2", valid[target], str(update.effective_chat.id))
    await update.message.reply_text(f"✅ Channel binding for `{target}` locked to this group.", parse_mode="Markdown")

async def unset_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    
    target = context.args[0].lower() if context.args else ""
    valid = {"bday": "bday_channel", "feedback": "feedback_channel"}
    if target not in valid:
        return await update.message.reply_text("❌ Usage: `/unsetchannel <bday|feedback>`")
    
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM config WHERE key=$1", valid[target])
    await update.message.reply_text(f"✅ Channel binding for `{target}` has been cleared.", parse_mode="Markdown")

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

async def super_reset_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    target = context.args[0].lower() if context.args else 'all'
    await context.bot.send_message(update.effective_user.id, f"Wipe matrix `{target}`?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ Wipe", callback_data=f"sup_reset_{target}"), InlineKeyboardButton("Cancel", callback_data="sup_cancel")]]))

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
        if act == "reset":
            if t in ["stars", "all"]:
                await conn.execute("TRUNCATE kudos CASCADE")
            if t in ["birthdays", "all"]:
                await conn.execute("TRUNCATE birthdays CASCADE")
            await q.edit_message_text(f"Wiped `{t}` database matrix.")

async def push_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    changes = " ".join(context.args)
    if not changes:
        return await update.message.reply_text("Provide changes text.")
        
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        curr_ver = await conn.fetchval("SELECT version FROM changelogs ORDER BY created_at DESC LIMIT 1")
        if not curr_ver:
            next_ver = 1.0
        else:
            try:
                next_ver = round(float(curr_ver) + 0.1, 1)
            except Exception:
                next_ver = 1.0
        await conn.execute("INSERT INTO changelogs (version, changes) VALUES ($1, $2)", str(next_ver), changes)
        uids = await conn.fetch("SELECT user_id FROM users WHERE user_id IS NOT NULL")
        
    msg = f"🚀 **Nukhba Manager v{next_ver} Update!**\n\n**Changelog:**\n{changes}"
    for u in uids:
        try:
            await context.bot.send_message(u['user_id'], msg, parse_mode="Markdown")
        except Exception:
            pass
    await update.message.reply_text(f"Pushed v{next_ver}.")

async def update_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
    try:
        parts = " ".join(context.args).split(",", 1)
        ver = parts[0].strip()
        changes = parts[1].strip()
    except Exception:
        return await update.message.reply_text("Format: `/updatechange 1.5 , Fixed stuff`")
        
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO changelogs (version, changes) VALUES ($1, $2)", ver, changes)
        uids = await conn.fetch("SELECT user_id FROM users WHERE user_id IS NOT NULL")
        
    msg = f"🚀 **Nukhba Manager v{ver} Update!**\n\n**Changelog:**\n{changes}"
    for u in uids:
        try:
            await context.bot.send_message(u['user_id'], msg, parse_mode="Markdown")
        except Exception:
            pass
    await update.message.reply_text(f"Pushed v{ver}.")

async def all_command_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not await is_super(update.effective_user.username):
        return
        
    from commands_manifest import COMMANDS
    app_handlers = [h.command[0] for group in context.application.handlers.values() for h in group if isinstance(h, CommandHandler)]
    
    report = "🧪 **System Command Protocol Test**\n\n"
    for c in COMMANDS:
        if c['name'] in app_handlers:
            report += f"/{c['name']} ✅ No issue\n"
        else:
            report += f"/{c['name']} ❌ Error: Unregistered handler\n"
            
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"Analyze this bot diagnostic report and summarize health. Do not rewrite the list. Be brief. \n{report}"
            resp = await asyncio.to_thread(client.models.generate_content, model='gemini-2.5-flash', contents=prompt)
            report += f"\n\n🤖 **AI Health Evaluation:**\n{resp.text}"
        except Exception:
            pass
            
    await send_md(context, update.effective_chat.id, report)

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
