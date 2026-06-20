import logging, datetime
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters, ContextTypes
from core import BOT_TOKEN, WIB, init_db, log_action
from crons import daily_morning_log, monthly_leaderboard, weekly_quota_reset, poll_cleanup, schedule_bday_job
import commands

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
    app.job_queue.run_daily(weekly_quota_reset, datetime.time(hour=0, minute=0, tzinfo=WIB), days=(0,))
    app.job_queue.run_repeating(poll_cleanup, interval=3600)

    # Core
    app.add_handler(CommandHandler("start", commands.start))
    app.add_handler(CommandHandler("help", commands.help_command))
    app.add_handler(CommandHandler("bugreport", commands.report_bug))
    app.add_handler(ChatMemberHandler(commands.security_track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    
    # User Commands
    app.add_handler(CommandHandler("gemini", commands.ask_gemini))
    app.add_handler(CommandHandler("thanks", commands.give_thanks))
    app.add_handler(CommandHandler("myquota", commands.my_quota))
    app.add_handler(CommandHandler("mystar", commands.my_star))
    app.add_handler(CommandHandler("totalstar", commands.total_star))
    app.add_handler(CommandHandler("newevent", commands.create_event))
    app.add_handler(CommandHandler("editevent", commands.edit_event))
    app.add_handler(CommandHandler("events", commands.list_events))
    app.add_handler(CommandHandler("assign", commands.assign_task))
    app.add_handler(CommandHandler("complete", commands.complete_task))
    app.add_handler(CommandHandler("mytasks", commands.my_tasks))
    app.add_handler(CommandHandler("poll", commands.create_poll))
    app.add_handler(CommandHandler("addlib", commands.add_lib))
    app.add_handler(CommandHandler("editlib", commands.edit_lib))
    app.add_handler(CommandHandler("getlib", commands.get_lib))
    app.add_handler(CommandHandler("library", commands.list_lib))
    app.add_handler(CommandHandler("away", commands.set_away))
    app.add_handler(CommandHandler("back", commands.set_back))

    # Admin Commands
    app.add_handler(CommandHandler("setgeminiquota", commands.set_gemini_quota))
    app.add_handler(CommandHandler("announce", commands.announce))
    app.add_handler(CommandHandler("editannounce", commands.edit_announce))
    app.add_handler(CommandHandler("delannounce", commands.del_announce))
    app.add_handler(CommandHandler("admin_stars", commands.admin_stars))
    app.add_handler(CommandHandler("checkquota", commands.check_quota))
    app.add_handler(CommandHandler("addbday", commands.add_bday))
    app.add_handler(CommandHandler("editbday", commands.edit_bday))
    app.add_handler(CommandHandler("delbday", commands.del_bday))
    app.add_handler(CommandHandler("listbdays", commands.list_bdays))
    app.add_handler(CommandHandler("setbdaychannel", commands.set_bday_channel))
    app.add_handler(CommandHandler("setbdaytime", commands.set_bday_time))
    app.add_handler(CommandHandler("bdayconfig", commands.bday_config))
    app.add_handler(CommandHandler("addbday_batch", commands.addbday_batch))
    app.add_handler(CommandHandler("delbday_batch", commands.delbday_batch))
    app.add_handler(CommandHandler("cancelevent", commands.cancel_event))
    app.add_handler(CommandHandler("canceltask", commands.cancel_task))
    app.add_handler(CommandHandler("dellib", commands.del_lib))
    app.add_handler(CommandHandler("addlib_batch", commands.addlib_batch))
    app.add_handler(CommandHandler("dellib_batch", commands.dellib_batch))
    app.add_handler(CommandHandler("attendance", commands.attendance))
    app.add_handler(CommandHandler("grouptasks", commands.group_tasks))
    app.add_handler(CommandHandler("groupid", commands.check_group_id))
    app.add_handler(CommandHandler("listgroups", commands.check_group_id))
    app.add_handler(CommandHandler("botstatus", commands.bot_status))
    app.add_handler(CommandHandler("auditlog", commands.get_audit_log))
    app.add_handler(CommandHandler("forceback", commands.force_back))
    app.add_handler(CommandHandler("cancelpoll", commands.cancel_poll_admin))

    # Super Owner
    app.add_handler(CommandHandler("addadmin", commands.add_admin_req))
    app.add_handler(CommandHandler("deladmin", commands.del_admin_req))
    app.add_handler(CommandHandler("listadmins", commands.list_admins))
    app.add_handler(CommandHandler("removemember", commands.remove_member_req))
    app.add_handler(CommandHandler("graveyard", commands.graveyard))
    app.add_handler(CommandHandler("super_reset", commands.super_reset_req))

    # Callbacks & Trackers
    app.add_handler(CallbackQueryHandler(commands.poll_callback, pattern="^pollst_"))
    app.add_handler(CallbackQueryHandler(commands.super_callback, pattern="^sup_"))
    app.add_handler(CallbackQueryHandler(commands.rsvp_callback, pattern="^rsvp_"))
    app.add_handler(MessageHandler(filters.COMMAND, commands.unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, commands.global_tracker))

    logger.info("Starting Enterprise bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
