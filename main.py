import logging, datetime
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters, ContextTypes
from core import BOT_TOKEN, WIB, init_db, log_action
from crons import daily_morning_log, monthly_leaderboard, weekly_quota_reset, poll_cleanup, schedule_bday_job

# Import our split command modules
import cmd_system
import cmd_user
import cmd_admin

logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception handled:", exc_info=context.error)
    pool = context.bot_data.get('db_pool')
    if pool:
        uid = update.effective_user.id if update and hasattr(update, 'effective_user') and update.effective_user else 0
        cid = update.effective_chat.id if update and hasattr(update, 'effective_chat') and update.effective_chat else 0
        await log_action(pool, uid, cid, "System Exception", "Error", str(context.error))
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO bot_stats (date, errors) VALUES (CURRENT_DATE, 1) ON CONFLICT (date) DO UPDATE SET errors = bot_stats.errors + 1")

async def post_init_wrapper(app: Application):
    await init_db(app)
    await schedule_bday_job(app)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = post_init_wrapper
    app.add_error_handler(error_handler)

    # Background Jobs
    app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(monthly_leaderboard, datetime.time(hour=13, minute=0, tzinfo=WIB))
    app.job_queue.run_daily(weekly_quota_reset, datetime.time(hour=7, minute=0, tzinfo=WIB), days=(0,))
    app.job_queue.run_repeating(poll_cleanup, interval=3600)

    # 1. SYSTEM COMMANDS
    app.add_handler(CommandHandler("start", cmd_system.start))
    app.add_handler(CommandHandler("help", cmd_system.help_command))
    app.add_handler(CommandHandler("feedback", cmd_system.submit_feedback))
    app.add_handler(CommandHandler("gemini", cmd_system.ask_gemini))
    app.add_handler(ChatMemberHandler(cmd_system.security_track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    
    # 2. USER COMMANDS
    app.add_handler(CommandHandler("thanks", cmd_user.give_thanks))
    app.add_handler(CommandHandler("myquota", cmd_user.my_quota))
    app.add_handler(CommandHandler("mystar", cmd_user.my_star))
    app.add_handler(CommandHandler("totalstar", cmd_user.total_star))
    app.add_handler(CommandHandler("newevent", cmd_user.create_event))
    app.add_handler(CommandHandler("editevent", cmd_user.edit_event))
    app.add_handler(CommandHandler("events", cmd_user.list_events))
    app.add_handler(CommandHandler("assign", cmd_user.assign_task))
    app.add_handler(CommandHandler("complete", cmd_user.complete_task))
    app.add_handler(CommandHandler("mytasks", cmd_user.my_tasks))
    app.add_handler(CommandHandler("poll", cmd_user.create_poll))
    app.add_handler(CommandHandler("addlib", cmd_user.add_lib))
    app.add_handler(CommandHandler("editlib", cmd_user.edit_lib))
    app.add_handler(CommandHandler("getlib", cmd_user.get_lib))
    app.add_handler(CommandHandler("library", cmd_user.list_lib))
    app.add_handler(CommandHandler("away", cmd_user.set_away))
    app.add_handler(CommandHandler("back", cmd_user.set_back))

    # 3. ADMIN COMMANDS
    app.add_handler(CommandHandler("analyze_feedback", cmd_admin.analyze_feedback))
    app.add_handler(CommandHandler("setgeminiquota", cmd_admin.set_gemini_quota))
    app.add_handler(CommandHandler("checkgeminiquota", cmd_admin.check_gemini_quota))
    app.add_handler(CommandHandler("admin_gemini", cmd_admin.admin_gemini))
    app.add_handler(CommandHandler("setweeklylimit", cmd_admin.set_weekly_limit))
    app.add_handler(CommandHandler("announce", cmd_admin.announce))
    app.add_handler(CommandHandler("editannounce", cmd_admin.edit_announce))
    app.add_handler(CommandHandler("delannounce", cmd_admin.del_announce))
    app.add_handler(CommandHandler("admin_stars", cmd_admin.admin_stars))
    app.add_handler(CommandHandler("checkquota", cmd_admin.check_quota))
    app.add_handler(CommandHandler("addbday", cmd_admin.add_bday))
    app.add_handler(CommandHandler("editbday", cmd_admin.edit_bday))
    app.add_handler(CommandHandler("delbday", cmd_admin.del_bday))
    app.add_handler(CommandHandler("listbdays", cmd_admin.list_bdays))
    app.add_handler(CommandHandler("setbdaychannel", cmd_admin.set_bday_channel))
    app.add_handler(CommandHandler("setbdaytime", cmd_admin.set_bday_time))
    app.add_handler(CommandHandler("bdayconfig", cmd_admin.bday_config))
    app.add_handler(CommandHandler("addbday_batch", cmd_admin.addbday_batch))
    app.add_handler(CommandHandler("delbday_batch", cmd_admin.delbday_batch))
    app.add_handler(CommandHandler("cancelevent", cmd_admin.cancel_event))
    app.add_handler(CommandHandler("canceltask", cmd_admin.cancel_task))
    app.add_handler(CommandHandler("dellib", cmd_admin.del_lib))
    app.add_handler(CommandHandler("addlib_batch", cmd_admin.addlib_batch))
    app.add_handler(CommandHandler("dellib_batch", cmd_admin.dellib_batch))
    app.add_handler(CommandHandler("attendance", cmd_admin.attendance))
    app.add_handler(CommandHandler("grouptasks", cmd_admin.group_tasks))
    app.add_handler(CommandHandler("groupid", cmd_admin.check_group_id))
    app.add_handler(CommandHandler("listgroups", cmd_admin.check_group_id))
    app.add_handler(CommandHandler("botstatus", cmd_admin.bot_status))
    app.add_handler(CommandHandler("auditlog", cmd_admin.get_audit_log))
    app.add_handler(CommandHandler("forceback", cmd_admin.force_back))
    app.add_handler(CommandHandler("cancelpoll", cmd_admin.cancel_poll_admin))

    # 4. SUPER OWNER
    app.add_handler(CommandHandler("addadmin", cmd_admin.add_admin_req))
    app.add_handler(CommandHandler("deladmin", cmd_admin.del_admin_req))
    app.add_handler(CommandHandler("listadmins", cmd_admin.list_admins))
    app.add_handler(CommandHandler("removemember", cmd_admin.remove_member_req))
    app.add_handler(CommandHandler("graveyard", cmd_admin.graveyard))
    app.add_handler(CommandHandler("super_reset", cmd_admin.super_reset_req))

    # 5. CALLBACKS 
    app.add_handler(CallbackQueryHandler(cmd_user.poll_callback, pattern="^pollst_"))
    app.add_handler(CallbackQueryHandler(cmd_admin.super_callback, pattern="^sup_"))
    app.add_handler(CallbackQueryHandler(cmd_user.rsvp_callback, pattern="^rsvp_"))

    # 6. TRACKERS & FALLBACKS (These MUST be at the very bottom!)
    app.add_handler(MessageHandler(filters.COMMAND, cmd_system.unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_system.global_tracker))

    logger.info("Starting Enterprise bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
