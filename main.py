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
    
    # Set up Telegram's pop-up menu command hints automatically at launch
    user_commands = [
        ("start", "Start the bot manager"),
        ("help", "Get the complete user manual via DM"),
        ("gemini", "Ask the AI any general question"),
        ("ask", "Ask about the bot's features"),
        ("newevent", "Schedule a group event"),
        ("events", "List upcoming events"),
        ("poll", "Launch an interactive poll builder"),
        ("thanks", "Give 1 RAWWY star to a message reply"),
        ("myquota", "Check remaining star sends left"),
        ("mystar", "Check stars earned this month"),
        ("totalstar", "Check stars earned all-time"),
        ("leaderboard", "View stars leaderboard"),
        ("addlib", "Save an asset to library"),
        ("editlib", "Edit a saved library asset"),
        ("dellib", "Delete a saved library asset"),
        ("getlib", "Retrieve a library asset"),
        ("library", "Browse saved team library assets"),
        ("assign", "Assign a task with a deadline"),
        ("complete", "Mark an assigned task complete"),
        ("mytasks", "View your active assigned tasks"),
        ("away", "Set your team away status"),
        ("back", "Return early from away status"),
        ("mypoint", "Securely check your trivia points via DM"),
        ("feedback", "Submit suggestions or reports")
    ]
    try:
        await application.bot.set_my_commands(user_commands)
        logger.info("✅ Pop-up command hint menus synced successfully with Telegram.")
    except Exception as e:
        logger.error(f"Failed to set pop-up command menus: {e}")

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

def main():
    """Application factory loop setting up handlers, jobs, and webhook routers."""
    if not BOT_TOKEN:
        logger.critical("❌ CRITICAL ERROR: BOT_TOKEN is unconfigured in core.py!")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = post_init_wrapper
    app.add_error_handler(error_handler)

    # ----------------------------------------------------
    # 🧠 SECTION 1: TRIVIA ENGINE MODULE
    # ----------------------------------------------------
    app.add_handler(CommandHandler("mypoint", cmd_trivia.my_point))
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
    app.add_handler(CallbackQueryHandler(cmd_trivia.trivia_callback, pattern="^triv_"))

    # ----------------------------------------------------
    # 🟢 SECTION 2: CORE TEAM USER ENGINE (cmd_user.py matches)
    # ----------------------------------------------------
    app.add_handler(CommandHandler("start", cmd_system.start))
    app.add_handler(CommandHandler("help", cmd_system.help_command))
    app.add_handler(CommandHandler("gemini", cmd_system.ask_gemini))
    app.add_handler(CommandHandler("ask", cmd_system.ask_bot))
    app.add_handler(CommandHandler("feedback", cmd_system.submit_feedback))
    
    app.add_handler(CommandHandler("newevent", cmd_user.create_event))
    app.add_handler(CommandHandler("editevent", cmd_user.edit_event))
    app.add_handler(CommandHandler("events", cmd_user.list_events))
    app.add_handler(CommandHandler("poll", cmd_user.create_poll))
    
    app.add_handler(CommandHandler("thanks", cmd_user.give_thanks))
    app.add_handler(CommandHandler("myquota", cmd_user.my_quota))
    app.add_handler(CommandHandler("mystar", cmd_user.my_star))
    app.add_handler(CommandHandler("totalstar", cmd_user.total_star))
    app.add_handler(CommandHandler("leaderboard", cmd_user.leaderboard))
    
    app.add_handler(CommandHandler("addlib", cmd_user.add_lib))
    app.add_handler(CommandHandler("editlib", cmd_user.edit_lib))
    app.add_handler(CommandHandler("dellib", cmd_admin.del_lib))  # Cleanly routed to your admin file
    app.add_handler(CommandHandler("getlib", cmd_user.get_lib))
    app.add_handler(CommandHandler("library", cmd_user.list_lib))
    
    app.add_handler(CommandHandler("assign", cmd_user.assign_task))
    app.add_handler(CommandHandler("complete", cmd_user.complete_task))
    app.add_handler(CommandHandler("mytasks", cmd_user.my_tasks))
    
    app.add_handler(CommandHandler("away", cmd_user.set_away))
    app.add_handler(CommandHandler("back", cmd_user.set_back))

    # ----------------------------------------------------
    # 🔐 SECTION 3: BOT ADMIN UTILITIES (cmd_admin.py matches)
    # ----------------------------------------------------
    app.add_handler(CommandHandler("addbday", cmd_admin.add_bday))
    app.add_handler(CommandHandler("editbday", cmd_admin.edit_bday))
    app.add_handler(CommandHandler("delbday", cmd_admin.del_bday))
    app.add_handler(CommandHandler("setbdaychannel", cmd_admin.set_bday_channel))
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

    # ----------------------------------------------------
    # 👑 SECTION 4: SUPER OWNER EXCLUSIVES
    # ----------------------------------------------------
    app.add_handler(CommandHandler("addadmin", cmd_admin.add_admin_req))
    app.add_handler(CommandHandler("deladmin", cmd_admin.del_admin_req))
    app.add_handler(CommandHandler("listadmins", cmd_admin.list_admins))
    app.add_handler(CommandHandler("removemember", cmd_admin.remove_member_req))
    app.add_handler(CommandHandler("graveyard", cmd_admin.graveyard))
    app.add_handler(CommandHandler("botstatus", cmd_admin.bot_status))
    app.add_handler(CommandHandler("pause", cmd_admin.pause_bot))
    app.add_handler(CommandHandler("restart", cmd_admin.restart_bot))
    app.add_handler(CommandHandler("super_reset", cmd_admin.super_reset_req))

    # ----------------------------------------------------
    # ⚙️ SECTION 5: CALLBACK ROUTING INTERCEPTS
    # ----------------------------------------------------
    app.add_handler(CallbackQueryHandler(cmd_user.rsvp_callback, pattern="^rsvp_"))
    app.add_handler(CallbackQueryHandler(cmd_user.poll_callback, pattern="^pollst_"))
    app.add_handler(CallbackQueryHandler(cmd_admin.super_callback, pattern="^sup_"))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER, cmd_system.security_track_chats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_system.global_tracker))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_system.unknown_command))

    # ----------------------------------------------------
    # ⏱️ SECTION 6: BACKGROUND JOBS & CRON WORKERS
    # ----------------------------------------------------
    app.job_queue.run_repeating(cmd_trivia.trivia_timeout_sweeper, interval=10)
    app.job_queue.run_repeating(cmd_trivia.trivia_cron_job, interval=60)
    app.job_queue.run_repeating(cmd_admin.process_schedules, interval=30)
    app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(cmd_trivia.run_monthly_trivia_reset, time=datetime.time(hour=13, minute=0, tzinfo=WIB))

    logger.info("🚀 [RW] Nukhba Manager initialized. Starting event polling loops...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
