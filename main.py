import logging, datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from core import BOT_TOKEN, DATABASE_URL, WIB, init_db, log_action
import cmd_system, cmd_user, cmd_admin, cmd_trivia

# Configure standard internal logging trackers
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def post_init_wrapper(application: Application):
    """Initializes the database connection pool at application startup."""
    await init_db(application)
    logger.info("📡 Database pool successfully bound to global application state.")

async def daily_morning_log(context: ContextTypes.DEFAULT_TYPE):
    """Automated morning diagnostic check running at 7:00 AM WIB."""
    pool = context.bot_data.get('db_pool')
    now_str = datetime.datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S WIB')
    logger.info(f"☀️ System status check executed successfully at {now_str}")
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO bot_stats (date, uses, errors) VALUES (CURRENT_DATE, 0, 0) ON CONFLICT (date) DO NOTHING")

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

async def dynamic_thanks_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safely discovers and runs the stars handler under any varying function names inside cmd_user."""
    for attr in ['thanks_command', 'give_star', 'send_star', 'cmd_thanks', 'thanks']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Star command handler configuration mismatch inside cmd_user module.")

async def dynamic_quota_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safely discovers and runs the star quota lookup under any varying function names inside cmd_user."""
    for attr in ['my_quota', 'check_my_quota', 'view_my_quota', 'view_quota', 'quota_command', 'quota']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Quota command handler configuration mismatch inside cmd_user module.")

def main():
    """Application factory loop setting up handlers, jobs, and webhook routers."""
    if not BOT_TOKEN:
        logger.critical("❌ CRITICAL ERROR: BOT_TOKEN is unconfigured in core.py environment variables!")
        return

    # Build the Telegram Application instance
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = post_init_wrapper
    app.add_error_handler(error_handler)

    # ----------------------------------------------------
    # 🧠 SECTION 1: TRIVIA MODULE ROUTING
    # ----------------------------------------------------
    # User level tracking command
    app.add_handler(CommandHandler("mypoint", cmd_trivia.my_point))

    # Administrative configuration settings
    app.add_handler(CommandHandler("settriviachannel", cmd_trivia.set_trivia_channel))
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

    # Register Interactive Inline Keyboard Taps
    app.add_handler(CallbackQueryHandler(cmd_trivia.trivia_callback, pattern="^triv_"))

    # ----------------------------------------------------
    # 🟢 SECTION 2: STANDARD USER FEATURE ROUTING
    # ----------------------------------------------------
    app.add_handler(CommandHandler("start", cmd_system.start))
    app.add_handler(CommandHandler("help", cmd_system.help_command))
    app.add_handler(CommandHandler("gemini", cmd_system.ask_gemini))
    app.add_handler(CommandHandler("ask", cmd_system.ask_bot))
    app.add_handler(CommandHandler("feedback", cmd_system.submit_feedback))
    
    app.add_handler(CommandHandler("newevent", cmd_user.create_event))
    app.add_handler(CommandHandler("events", cmd_user.list_events))
    app.add_handler(CommandHandler("poll", cmd_user.create_poll))
    
    app.add_handler(CommandHandler("thanks", dynamic_thanks_fallback))
    # Secure fallback configuration mapping for /myquota
    app.add_handler(CommandHandler("myquota", dynamic_quota_fallback))
    app.add_handler(CommandHandler("mystar", cmd_user.check_my_stars))
    app.add_handler(CommandHandler("totalstar", cmd_user.check_total_stars))
    app.add_handler(CommandHandler("leaderboard", cmd_user.view_leaderboard))
    
    app.add_handler(CommandHandler("addlib", cmd_user.add_library))
    app.add_handler(CommandHandler("editlib", cmd_user.edit_library))
    app.add_handler(CommandHandler("dellib", cmd_user.del_library))
    app.add_handler(CommandHandler("getlib", cmd_user.get_library))
    app.add_handler(CommandHandler("library", cmd_user.browse_library))
    
    app.add_handler(CommandHandler("assign", cmd_user.assign_task))
    app.add_handler(CommandHandler("complete", cmd_user.complete_task))
    app.add_handler(CommandHandler("mytasks", cmd_user.view_my_tasks))
    
    app.add_handler(CommandHandler("away", cmd_user.set_away))
    app.add_handler(CommandHandler("back", cmd_user.set_back))

    # ----------------------------------------------------
    # 🔐 SECTION 3: PRIVILEGED ADMINISTRATIVE ROUTING
    # ----------------------------------------------------
    app.add_handler(CommandHandler("addbday", cmd_admin.add_birthday))
    app.add_handler(CommandHandler("editbday", cmd_admin.edit_birthday))
    app.add_handler(CommandHandler("delbday", cmd_admin.del_birthday))
    app.add_handler(CommandHandler("setbdaychannel", cmd_admin.set_birthday_channel))
    app.add_handler(CommandHandler("setbdaytime", cmd_admin.set_birthday_time))
    app.add_handler(CommandHandler("bdayconfig", cmd_admin.view_birthday_config))
    app.add_handler(CommandHandler("listbdays", cmd_admin.list_birthdays))
    app.add_handler(CommandHandler("addbday_batch", cmd_admin.add_birthday_batch))
    app.add_handler(CommandHandler("delbday_batch", cmd_admin.del_birthday_batch))
    
    app.add_handler(CommandHandler("checkquota", cmd_admin.check_quota_audit))
    app.add_handler(CommandHandler("admin_stars", cmd_admin.admin_stars_mod))
    app.add_handler(CommandHandler("setweeklyquota", cmd_admin.set_weekly_quota_limit))
    
    app.add_handler(CommandHandler("checklimit", cmd_admin.check_limit_audit))
    app.add_handler(CommandHandler("admin_limit", cmd_admin.admin_limit_mod))
    app.add_handler(CommandHandler("setweeklylimit", cmd_admin.set_weekly_ai_limit))
    
    app.add_handler(CommandHandler("attendance", cmd_admin.view_away_attendance))
    app.add_handler(CommandHandler("forceback", cmd_admin.force_back_user))
    app.add_handler(CommandHandler("grouptasks", cmd_admin.view_global_tasks))
    app.add_handler(CommandHandler("cancelevent", cmd_admin.cancel_event_by_id))
    app.add_handler(CommandHandler("canceltask", cmd_admin.cancel_task_by_id))
    app.add_handler(CommandHandler("cancelpoll", cmd_admin.cancel_active_poll))
    app.add_handler(CommandHandler("addlib_batch", cmd_admin.add_library_batch))
    app.add_handler(CommandHandler("dellib_batch", cmd_admin.del_library_batch))
    
    app.add_handler(CommandHandler("schedule", cmd_admin.create_schedule))
    app.add_handler(CommandHandler("listschedules", cmd_admin.list_schedules))
    app.add_handler(CommandHandler("delschedule", cmd_admin.delete_schedule))
    app.add_handler(CommandHandler("announce", cmd_admin.dispatch_broadcast))
    app.add_handler(CommandHandler("editannounce", cmd_admin.edit_broadcast))
    app.add_handler(CommandHandler("delannounce", cmd_admin.delete_broadcast))
    app.add_handler(CommandHandler("groupid", cmd_admin.check_group_id))
    app.add_handler(CommandHandler("auditlog", cmd_admin.pull_diagnostic_log))
    
    app.add_handler(CommandHandler("feedbacklist", cmd_admin.view_feedback_log))
    app.add_handler(CommandHandler("analyze_feedback", cmd_admin.analyze_recent_feedback))
    app.add_handler(CommandHandler("alltimefeedback", cmd_admin.review_historical_feedback))

    # ----------------------------------------------------
    # 👑 SECTION 4: SUPER OWNER STRUCTURAL EXCLUSIVES
    # ----------------------------------------------------
    app.add_handler(CommandHandler("addadmin", cmd_admin.promote_to_admin))
    app.add_handler(CommandHandler("deladmin", cmd_admin.demote_from_admin))
    app.add_handler(CommandHandler("listadmins", cmd_admin.list_all_admins))
    app.add_handler(CommandHandler("removemember", cmd_admin.offboard_member_records))
    app.add_handler(CommandHandler("graveyard", cmd_admin.view_offboarded_graveyard))
    app.add_handler(CommandHandler("botstatus", cmd_admin.view_system_bot_status))
    app.add_handler(CommandHandler("pause", cmd_admin.trigger_maintenance_pause))
    app.add_handler(CommandHandler("restart", cmd_admin.trigger_maintenance_resume))
    app.add_handler(CommandHandler("super_reset", cmd_admin.trigger_structural_factory_wipe))

    # ----------------------------------------------------
    # ⚙️ SECTION 5: CALLBACK & DATA CONTEXT RESOLVERS
    # ----------------------------------------------------
    app.add_handler(CallbackQueryHandler(cmd_user.event_callback, pattern="^ev_"))
    app.add_handler(CallbackQueryHandler(cmd_user.poll_callback, pattern="^pollst_"))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER, cmd_system.security_track_chats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_system.global_tracker))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_system.unknown_command))

    # ----------------------------------------------------
    # ⏱️ SECTION 6: BACKGROUND CRON ALARMS & TIME CHECKS
    # ----------------------------------------------------
    app.job_queue.run_repeating(cmd_trivia.trivia_timeout_sweeper, interval=10)
    app.job_queue.run_repeating(cmd_trivia.trivia_cron_job, interval=60)
    app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(cmd_trivia.run_monthly_trivia_reset, time=datetime.time(hour=13, minute=0, tzinfo=WIB))

    # Connect polling loops
    logger.info("🚀 [RW] Nukhba Manager initialized. Starting event polling loops...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
