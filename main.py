import logging
import datetime
from telegram import Update, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from core import BOT_TOKEN, DATABASE_URL, WIB, init_db, log_action
import cmd_system
import cmd_user
import cmd_admin
import cmd_trivia
import cmd_cheer
from commands_manifest import COMMANDS

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def post_init_wrapper(application: Application):
    await init_db(application)
    system_hints = [BotCommand(c['name'], c['desc']) for c in COMMANDS if c.get('public')]
    try:
        await application.bot.set_my_commands(system_hints, scope=BotCommandScopeDefault())
        await application.bot.set_my_commands(system_hints, scope=BotCommandScopeAllPrivateChats())
        await application.bot.set_my_commands(system_hints, scope=BotCommandScopeAllGroupChats())
        logger.info("✅ Menu correctly synced to commands_manifest.py absolute truth across all scopes.")
    except Exception as e:
        logger.error(f"Failed to push menu updates: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("⚠️ Exception encountered during runtime processing:", exc_info=context.error)

async def dynamic_thanks_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['thanks_command', 'give_star', 'send_star', 'cmd_thanks', 'thanks', 'give_thanks']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Star command handler configuration mismatch inside cmd_user module.")

async def dynamic_quota_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['my_quota', 'check_my_quota', 'view_my_quota', 'view_quota', 'quota_command', 'quota']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Quota command handler configuration mismatch inside cmd_user module.")

async def dynamic_mystar_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['my_stars', 'check_my_stars', 'view_my_stars', 'view_stars', 'stars_command', 'mystar', 'my_star']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Monthly star status checker mismatch inside cmd_user module.")

async def dynamic_totalstar_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['total_stars', 'check_total_stars', 'view_total_stars', 'totalstar', 'total_star']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ All-time star status checker mismatch inside cmd_user module.")

async def dynamic_leaderboard_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['leaderboard', 'view_leaderboard', 'check_leaderboard', 'cmd_leaderboard']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Leaderboard command handler configuration mismatch inside cmd_user module.")

async def dynamic_addlib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['add_lib', 'add_library', 'save_library', 'cmd_addlib']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library storage command configuration mismatch inside cmd_user module.")

async def dynamic_editlib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['edit_lib', 'edit_library', 'modify_library', 'cmd_editlib']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library modification command configuration mismatch inside cmd_user module.")

async def dynamic_dellib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['del_lib', 'delete_lib', 'del_library', 'delete_library', 'cmd_dellib']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library deletion command configuration mismatch inside cmd_user module.")

async def dynamic_getlib_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['get_lib', 'get_library', 'fetch_library', 'cmd_getlib']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Library asset retrieval configuration mismatch inside cmd_user module.")

async def dynamic_library_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['library', 'browse_library', 'list_library', 'view_library', 'cmd_library', 'list_lib']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Main library viewing layout configuration mismatch inside cmd_user module.")

async def dynamic_mytasks_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for attr in ['my_tasks', 'view_my_tasks', 'check_my_tasks', 'list_my_tasks', 'cmd_mytasks']:
        if hasattr(cmd_user, attr):
            return await getattr(cmd_user, attr)(update, context)
    await update.message.reply_text("⚠️ Pending task viewer configuration mismatch inside cmd_user module.")

def main():
    if not BOT_TOKEN:
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = post_init_wrapper
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", cmd_system.start))
    app.add_handler(CommandHandler("help", cmd_system.help_command))
    app.add_handler(CommandHandler("wdim", cmd_system.what_did_i_miss))
    app.add_handler(CommandHandler("feedback", cmd_system.submit_feedback))
    app.add_handler(CommandHandler("ask", cmd_system.ask_bot))
    app.add_handler(CommandHandler("gemini", cmd_system.ask_gemini))
    
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

    app.add_handler(CommandHandler("mypoint", cmd_trivia.my_point))
    app.add_handler(CommandHandler("triviaconfig", cmd_trivia.trivia_config))
    app.add_handler(CommandHandler("forcetrivia", cmd_trivia.force_trivia))
    app.add_handler(CommandHandler("forcesupertrivia", cmd_trivia.force_super_trivia))
    app.add_handler(CommandHandler("canceltrivia", cmd_trivia.cancel_trivia))
    app.add_handler(CommandHandler("admin_kp", cmd_trivia.admin_kp))
    
    app.add_handler(CommandHandler("botconfig", cmd_admin.bot_config))
    app.add_handler(CommandHandler("setchannel", cmd_admin.set_channel))
    app.add_handler(CommandHandler("unsetchannel", cmd_admin.unset_channel))
    
    app.add_handler(CommandHandler("addbday", cmd_admin.add_bday))
    app.add_handler(CommandHandler("editbday", cmd_admin.edit_bday))
    app.add_handler(CommandHandler("delbday", cmd_admin.del_bday))
    app.add_handler(CommandHandler("listbdays", cmd_admin.list_bdays))
    
    app.add_handler(CommandHandler("checkquota", cmd_admin.check_quota))
    app.add_handler(CommandHandler("admin_stars", cmd_admin.admin_stars))
    app.add_handler(CommandHandler("checklimit", cmd_admin.check_limit))
    app.add_handler(CommandHandler("admin_limit", cmd_admin.admin_limit))
    
    app.add_handler(CommandHandler("attendance", cmd_admin.attendance))
    app.add_handler(CommandHandler("forceback", cmd_admin.force_back))
    app.add_handler(CommandHandler("grouptasks", cmd_admin.group_tasks))
    app.add_handler(CommandHandler("cancelevent", cmd_admin.cancel_event))
    app.add_handler(CommandHandler("canceltask", cmd_admin.cancel_task))
    app.add_handler(CommandHandler("cancelpoll", cmd_admin.cancel_poll_admin))
    
    app.add_handler(CommandHandler("schedule", cmd_admin.schedule_announcement))
    app.add_handler(CommandHandler("listschedules", cmd_admin.list_schedules))
    app.add_handler(CommandHandler("delschedule", cmd_admin.del_schedule))
    app.add_handler(CommandHandler("announce", cmd_admin.announce))
    app.add_handler(CommandHandler("editannounce", cmd_admin.edit_announce))
    app.add_handler(CommandHandler("delannounce", cmd_admin.del_announce))
    app.add_handler(CommandHandler("groupid", cmd_admin.check_group_id))
    app.add_handler(CommandHandler("auditlog", cmd_admin.get_audit_log))
    app.add_handler(CommandHandler("audittime", cmd_admin.set_audit_time))
    
    app.add_handler(CommandHandler("feedbacklist", cmd_admin.feedback_list))
    app.add_handler(CommandHandler("analyze_feedback", cmd_admin.analyze_feedback))

    app.add_handler(CommandHandler("allcommandtest", cmd_admin.all_command_test))
    app.add_handler(CommandHandler("addadmin", cmd_admin.add_admin_req))
    app.add_handler(CommandHandler("deladmin", cmd_admin.del_admin_req))
    app.add_handler(CommandHandler("listadmins", cmd_admin.list_admins))
    app.add_handler(CommandHandler("removemember", cmd_admin.remove_member_req))
    app.add_handler(CommandHandler("graveyard", cmd_admin.graveyard))
    app.add_handler(CommandHandler("botstatus", cmd_admin.bot_status))
    app.add_handler(CommandHandler("pause", cmd_admin.pause_bot))
    app.add_handler(CommandHandler("restart", cmd_admin.restart_bot))
    app.add_handler(CommandHandler("super_reset", cmd_admin.super_reset_req))
    
    app.add_handler(CommandHandler("cheerme", cmd_cheer.cheer_me))
    app.add_handler(CommandHandler("setcheer", cmd_cheer.set_cheer))

    app.add_handler(CallbackQueryHandler(cmd_user.rsvp_callback, pattern="^rsvp_"))
    app.add_handler(CallbackQueryHandler(cmd_user.poll_callback, pattern="^pollst_"))
    app.add_handler(CallbackQueryHandler(cmd_admin.config_callback, pattern="^cfg_"))
    app.add_handler(CallbackQueryHandler(cmd_trivia.trivia_callback, pattern="^tcfg_|trivans_|tcancel_"))
    app.add_handler(CallbackQueryHandler(cmd_system.feedback_callback, pattern="^fb_"))
    app.add_handler(CallbackQueryHandler(cmd_admin.super_callback, pattern="^sup_"))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER, cmd_system.security_track_chats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_system.global_tracker))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_system.unknown_command))

    app.job_queue.run_repeating(cmd_trivia.trivia_timeout_sweeper, interval=3)
    app.job_queue.run_repeating(cmd_trivia.trivia_cron_job, interval=60)
    app.job_queue.run_repeating(cmd_admin.process_schedules, interval=30)
    
    try:
        from crons import daily_morning_log, poll_cleanup
        app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
        app.job_queue.run_repeating(poll_cleanup, interval=3600)
    except ImportError:
        pass
        
    app.job_queue.run_daily(cmd_trivia.run_monthly_trivia_reset, time=datetime.time(hour=13, minute=0, tzinfo=WIB))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
