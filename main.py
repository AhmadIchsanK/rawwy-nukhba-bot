import logging, datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from core import BOT_TOKEN, DATABASE_URL, WIB, init_db, log_action
import cmd_system, cmd_user, cmd_admin, cmd_trivia

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def post_init_wrapper(application: Application):
    """Initializes the database connection pool and synchronizes all menu arrays."""
    await init_db(application)
    
    # Unified Menu Command Registration Matrix (Matches /help explicitly)
    system_hints = [
        ("help", "📖 View Nukhba Manual"),
        ("gemini", "🤖 Ask Gemini AI"),
        ("ask", "🤖 Ask about Nukhba Bot"),
        ("newevent", "📅 Schedule an event"),
        ("editevent", "📅 Edit your event"),
        ("events", "📅 View upcoming events"),
        ("poll", "📊 Interactive Team Poll"),
        ("thanks", "🌟 Give a Star (Reply)"),
        ("myquota", "🌟 Check Star Quota left"),
        ("mystar", "🌟 Monthly Stars earned"),
        ("totalstar", "🌟 All-time Stars earned"),
        ("leaderboard", "🏆 Top RAWWY Stars"),
        ("mypoint", "🧠 View your Trivia Points"),
        ("addlib", "📚 Save a library asset"),
        ("editlib", "📚 Edit your asset"),
        ("dellib", "📚 Delete your asset"),
        ("getlib", "📚 Retrieve an asset"),
        ("library", "📚 Browse the Library"),
        ("assign", "⚡ Assign a task"),
        ("complete", "⚡ Mark task complete"),
        ("mytasks", "⚡ View your active tasks"),
        ("away", "🏖️ Set away status"),
        ("back", "🏖️ Return to available"),
        ("feedback", "💡 Submit Feedback")
    ]
    try:
        await application.bot.set_my_commands(system_hints)
        logger.info("✅ Direct Message & Group pop-out command menus fully synchronized.")
    except Exception as e:
        logger.error(f"Failed to push quick menu updates: {e}")

async def daily_morning_log(context: ContextTypes.DEFAULT_TYPE):
    """Automated morning diagnostic check running at 7:00 AM WIB."""
    pool = context.bot_data.get('db_pool')
    target_date = datetime.datetime.now(WIB).date()
    try:
        from crons import generate_audit_report
        msg = await generate_audit_report(pool, target_date)
        async with pool.acquire() as conn:
            admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
            from core import SUPER_OWNER
            super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
        
        admin_ids = {a['user_id'] for a in admins if a['user_id']}
        if super_id: admin_ids.add(super_id)
        
        for uid in admin_ids:
            try: await context.bot.send_message(uid, msg, parse_mode="Markdown")
            except: pass
    except Exception as e:
        logger.error(f"Failed to run daily morning log: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global system fallback exception catcher."""
    logger.error("⚠️ Exception encountered during runtime processing:", exc_info=context.error)
    pool = context.bot_data.get('db_pool')
    u_id = update.effective_user.id if update and hasattr(update, 'effective_user') and update.effective_user else 0
    c_id = update.effective_chat.id if update and hasattr(update, 'effective_chat') and update.effective_chat else 0
    if pool:
        try:
            await log_action(pool, u_id, c_id, "System", "Error", f"Unhandled runtime exception: {context.error}")
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, 0, 1) ON CONFLICT (date) DO UPDATE SET errors = bot_stats.errors + 1")
        except:
            pass

# ----------------------------------------------------
# 🛡️ DYNAMIC AUTODISCOVERY FALLBACK BRIDGES
# ----------------------------------------------------
async def dynamic_thanks_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['thanks_command', 'give_star', 'send_star', 'cmd_thanks', 'thanks', 'give_thanks']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Star command handler configuration mismatch inside cmd_user module.")

async def dynamic_quota_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['my_quota', 'check_my_quota', 'view_my_quota', 'view_quota', 'quota_command', 'quota']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Quota command handler configuration mismatch inside cmd_user module.")

async def dynamic_mystar_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['my_stars', 'check_my_stars', 'view_my_stars', 'view_stars', 'stars_command', 'mystar', 'my_star']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Monthly star status checker mismatch inside cmd_user module.")

async def dynamic_totalstar_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['total_stars', 'check_total_stars', 'view_total_stars', 'totalstar', 'total_star']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ All-time star status checker mismatch inside cmd_user module.")

async def dynamic_leaderboard_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['leaderboard', 'view_leaderboard', 'check_leaderboard', 'cmd_leaderboard']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Leaderboard command handler configuration mismatch inside cmd_user module.")

async def dynamic_addlib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['add_lib', 'add_library', 'save_library', 'cmd_addlib']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library storage command configuration mismatch inside cmd_user module.")

async def dynamic_editlib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['edit_lib', 'edit_library', 'modify_library', 'cmd_editlib']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library modification command configuration mismatch inside cmd_user module.")

async def dynamic_dellib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['del_lib', 'delete_lib', 'del_library', 'delete_library', 'cmd_dellib']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library deletion command configuration mismatch inside cmd_user module.")

async def dynamic_getlib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['get_lib', 'get_library', 'fetch_library', 'cmd_getlib']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library asset retrieval configuration mismatch inside cmd_user module.")

async def dynamic_library_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['library', 'browse_library', 'list_library', 'view_library', 'cmd_library', 'list_lib']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Main library viewing layout configuration mismatch inside cmd_user module.")

async def dynamic_mytasks_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['my_tasks', 'view_my_tasks', 'check_my_tasks', 'list_my_tasks', 'cmd_mytasks']:
        if hasattr(cmd_user, attr): return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Pending task viewer configuration mismatch inside cmd_user module.")

def main():
    """Application factory loop setting up routers."""
    if not BOT_TOKEN: return

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = post_init_wrapper
    app.add_error_handler(error_handler)

    # Trivia Module Handlers
    app.add_handler(CommandHandler("mypoint", cmd_trivia.my_point))
    app.add_handler(CommandHandler("settriviachannel", cmd_trivia.set_trivia_channel))
    app.add_handler(CommandHandler("unsettriviachannel", cmd_admin.unset_trivia_channel))
    app.add_handler(CommandHandler("settriviatheme", cmd_trivia.set_trivia_theme))
    app.add_handler(CommandHandler("settriviatime", cmd_trivia.set_trivia_time))
    app.add_handler(CommandHandler("settriviadays", cmd_trivia.set_trivia_days))
    app.add_handler(CommandHandler("settriviaopts", cmd_trivia.set_trivia_opts))
    app.add_handler(CommandHandler("settriviatimeout", cmd_trivia.set_trivia_timeout))
    app.add_handler(CommandHandler("setsupertimeout", cmd_trivia.set_super_timeout))
    app.add_handler(CommandHandler("pausetrivia", cmd_trivia.pause_trivia))
    app.add_handler(CommandHandler("resumetrivia", cmd_trivia.resume_trivia))
    app.add_handler(CommandHandler("forcetrivia", cmd_trivia.force_trivia))
    app.add_handler(CommandHandler("forcesupertrivia", cmd_trivia.force_super_trivia))
    app.add_handler(CommandHandler("canceltrivia", cmd_trivia.cancel_trivia))
    app.add_handler(CommandHandler("admin_kp", cmd_trivia.admin_kp))
    app.add_handler(CallbackQueryHandler(cmd_trivia.trivia_callback, pattern="^triv_"))

    # Core User Command Handlers
    app.add_handler(CommandHandler("start", cmd_system.start))
    app.add_handler(CommandHandler("help", cmd_system.help_command))
    app.add_handler(CommandHandler("gemini", cmd_system.ask_gemini))
    app.add_handler(CommandHandler("ask", cmd_system.ask_bot))
    app.add_handler(CommandHandler("feedback", cmd_system.submit_feedback))
    
    app.add_handler(CommandHandler("newevent", cmd_user.create_event))
    app.add_handler(CommandHandler("editevent", cmd_user.edit_event))
    app.add_handler(CommandHandler("events", cmd_user.list_events))
    app.add_handler(CommandHandler("poll", cmd_user.create_poll))
    
    app.add_handler(CommandHandler("thanks", dynamic_thanks_fallback))
    app.add_handler(CommandHandler("myquota", dynamic_quota_fallback))
    app.add_handler(CommandHandler("mystar", dynamic_mystar_fallback))
    app.add_handler(CommandHandler("totalstar", dynamic_totalstar_fallback))
    app.add_handler(CommandHandler("leaderboard", dynamic_leaderboard_fallback))
    
    app.add_handler(CommandHandler("addlib", dynamic_addlib_fallback))
    app.add_handler(CommandHandler("editlib", dynamic_editlib_fallback))
    app.add_handler(CommandHandler("dellib", dynamic_dellib_fallback))
    app.add_handler(CommandHandler("getlib", dynamic_getlib_fallback))
    app.add_handler(CommandHandler("library", dynamic_library_fallback))
    
    app.add_handler(CommandHandler("assign", cmd_user.assign_task))
    app.add_handler(CommandHandler("complete", cmd_user.complete_task))
    app.add_handler(CommandHandler("mytasks", dynamic_mytasks_fallback))
    
    app.add_handler(CommandHandler("away", cmd_user.set_away))
    app.add_handler(CommandHandler("back", cmd_user.set_back))

    # Administrative Controls Matrix
    app.add_handler(CommandHandler("addbday", cmd_admin.add_bday))
    app.add_handler(CommandHandler("editbday", cmd_admin.edit_bday))
    app.add_handler(CommandHandler("delbday", cmd_admin.del_bday))
    app.add_handler(CommandHandler("setbdaychannel", cmd_admin.set_bday_channel))
    app.add_handler(CommandHandler("unsetbdaychannel", cmd_admin.unset_bday_channel))
    app.add_handler(CommandHandler("setbdaytime", cmd_admin.set_bday_time))
    app.add_handler(CommandHandler("bdayconfig", cmd_admin.bday_config))
    app.add_handler(CommandHandler("listbdays", cmd_admin.list_bdays))
    app.add_handler(CommandHandler("addbday_batch", cmd_admin.addbday_batch))
    app.add_handler(CommandHandler("delbday_batch", cmd_admin.delbday_batch))
    
    app.add_handler(CommandHandler("checkquota", cmd_admin.check_quota))
    app.add_handler(CommandHandler("admin_stars", cmd_admin.admin_stars))
    app.add_handler(CommandHandler("setweeklyquota", cmd_admin.set_weekly_quota))
    
    app.add_handler(CommandHandler("checklimit", cmd_admin.check_limit))
    app.add_handler(CommandHandler("admin_limit", cmd_admin.admin_limit))
    app.add_handler(CommandHandler("setweeklylimit", cmd_admin.set_weekly_limit))
    
    app.add_handler(CommandHandler("attendance", cmd_admin.attendance))
    app.add_handler(CommandHandler("forceback", cmd_admin.force_back))
    app.add_handler(CommandHandler("grouptasks", cmd_admin.group_tasks))
    app.add_handler(CommandHandler("cancelevent", cmd_admin.cancel_event))
    app.add_handler(CommandHandler("canceltask", cmd_admin.cancel_task))
    app.add_handler(CommandHandler("cancelpoll", cmd_admin.cancel_poll_admin))
    app.add_handler(CommandHandler("addlib_batch", cmd_admin.addlib_batch))
    app.add_handler(CommandHandler("dellib_batch", cmd_admin.dellib_batch))
    
    app.add_handler(CommandHandler("schedule", cmd_admin.schedule_announcement))
    app.add_handler(CommandHandler("listschedules", cmd_admin.list_schedules))
    app.add_handler(CommandHandler("delschedule", cmd_admin.del_schedule))
    app.add_handler(CommandHandler("announce", cmd_admin.announce))
    app.add_handler(CommandHandler("editannounce", cmd_admin.edit_announce))
    app.add_handler(CommandHandler("delannounce", cmd_admin.del_announce))
    app.add_handler(CommandHandler("groupid", cmd_admin.check_group_id))
    app.add_handler(CommandHandler("auditlog", cmd_admin.get_audit_log))
    
    app.add_handler(CommandHandler("feedbacklist", cmd_admin.feedback_list))
    app.add_handler(CommandHandler("analyze_feedback", cmd_admin.analyze_feedback))
    app.add_handler(CommandHandler("alltimefeedback", cmd_admin.all_time_feedback))

    # Super Owner Scope Handlers
    app.add_handler(CommandHandler("addadmin", cmd_admin.add_admin_req))
    app.add_handler(CommandHandler("deladmin", cmd_admin.del_admin_req))
    app.add_handler(CommandHandler("listadmins", cmd_admin.list_admins))
    app.add_handler(CommandHandler("removemember", cmd_admin.remove_member_req))
    app.add_handler(CommandHandler("graveyard", cmd_admin.graveyard))
    app.add_handler(CommandHandler("botstatus", cmd_admin.bot_status))
    app.add_handler(CommandHandler("pause", cmd_admin.pause_bot))
    app.add_handler(CommandHandler("restart", cmd_admin.restart_bot))
    app.add_handler(CommandHandler("super_reset", cmd_admin.super_reset_req))

    # Callback Processing Dispatches
    app.add_handler(CallbackQueryHandler(cmd_user.rsvp_callback, pattern="^rsvp_"))
    app.add_handler(CallbackQueryHandler(cmd_user.poll_callback, pattern="^pollst_"))
    app.add_handler(CallbackQueryHandler(cmd_admin.super_callback, pattern="^sup_"))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER, cmd_system.security_track_chats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_system.global_tracker))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_system.unknown_command))

    # Background Automated Timing Sweeps
    app.job_queue.run_repeating(cmd_trivia.trivia_timeout_sweeper, interval=10)
    app.job_queue.run_repeating(cmd_trivia.trivia_cron_job, interval=60)
    app.job_queue.run_repeating(cmd_admin.process_schedules, interval=30)
    app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(cmd_trivia.run_monthly_trivia_reset, time=datetime.time(hour=13, minute=0, tzinfo=WIB))
    app.job_queue.run_repeating(crons_poll_cleanup, interval=3600)

    logger.info("🚀 [RW] Nukhba Manager initialized. Starting event polling loops...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

async def crons_poll_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Bridge runner to clear dead poll state fields safely."""
    from crons import poll_cleanup
    await poll_cleanup(context)

if __name__ == '__main__':
    main()
