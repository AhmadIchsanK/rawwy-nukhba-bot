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

# ----------------------------------------------------
# 🛡️ DYNAMIC AUTODISCOVERY FALLBACK BRIDGES (USER SUITE)
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

# ----------------------------------------------------
# 🛡️ DYNAMIC AUTODISCOVERY FALLBACK BRIDGES (ADMIN SUITE)
# ----------------------------------------------------
async def run_dynamic_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, fallback_names_list: list):
    """Iterates through matching command options inside cmd_admin to execute matching function lines securely."""
    for attr in fallback_names_list:
        if hasattr(cmd_admin, attr): return await getattr(cmd_admin, attr)(update, context)
    await update.message.reply_text("⚠️ Administrative configuration command target function resolution mismatch.")

async def adm_bday_add(u, c): await run_dynamic_admin_cmd(u, c, ['add_birthday', 'addbday', 'create_birthday', 'cmd_addbday'])
async def adm_bday_edit(u, c): await run_dynamic_admin_cmd(u, c, ['edit_birthday', 'editbday', 'modify_birthday', 'cmd_editbday'])
async def adm_bday_del(u, c): await run_dynamic_admin_cmd(u, c, ['del_birthday', 'delbday', 'delete_birthday', 'cmd_delbday'])
async def adm_bday_channel(u, c): await run_dynamic_admin_cmd(u, c, ['set_birthday_channel', 'setbdaychannel', 'bday_channel'])
async def adm_bday_time(u, c): await run_dynamic_admin_cmd(u, c, ['set_birthday_time', 'setbdaytime', 'bday_time'])
async def adm_bday_config(u, c): await run_dynamic_admin_cmd(u, c, ['view_birthday_config', 'bdayconfig', 'show_birthday_config'])
async def adm_bday_list(u, c): await run_dynamic_admin_cmd(u, c, ['list_birthdays', 'listbdays', 'show_birthdays'])
async def adm_bday_batch_add(u, c): await run_dynamic_admin_cmd(u, c, ['add_birthday_batch', 'addbday_batch', 'batch_add_birthdays'])
async def adm_bday_batch_del(u, c): await run_dynamic_admin_cmd(u, c, ['del_birthday_batch', 'delbday_batch', 'batch_del_birthdays'])

async def adm_quota_audit(u, c): await run_dynamic_admin_cmd(u, c, ['check_quota_audit', 'checkquota', 'audit_quotas'])
async def adm_stars_mod(u, c): await run_dynamic_admin_cmd(u, c, ['admin_stars_mod', 'admin_stars', 'modify_user_stars'])
async def adm_weekly_quota(u, c): await run_dynamic_admin_cmd(u, c, ['set_weekly_quota_limit', 'setweeklyquota', 'weekly_quota'])

async def adm_limit_audit(u, c): await run_dynamic_admin_cmd(u, c, ['check_limit_audit', 'checklimit', 'audit_limits'])
async def adm_limit_mod(u, c): await run_dynamic_admin_cmd(u, c, ['admin_limit_mod', 'admin_limit', 'modify_user_limits'])
async def adm_weekly_limit(u, c): await run_dynamic_admin_cmd(u, c, ['set_weekly_ai_limit', 'setweeklylimit', 'weekly_limit'])

async def adm_attendance(u, c): await run_dynamic_admin_cmd(u, c, ['view_away_attendance', 'attendance', 'show_attendance'])
async def adm_forceback(u, c): await run_dynamic_admin_cmd(u, c, ['force_back_user', 'forceback', 'cancel_away'])
async def adm_grouptasks(u, c): await run_dynamic_admin_cmd(u, c, ['view_global_tasks', 'grouptasks', 'show_group_tasks'])
async def adm_cancel_event(u, c): await run_dynamic_admin_cmd(u, c, ['cancel_event_by_id', 'cancelevent', 'delete_event'])
async def adm_cancel_task(u, c): await run_dynamic_admin_cmd(u, c, ['cancel_task_by_id', 'canceltask', 'delete_task'])
async def adm_cancel_poll(u, c): await run_dynamic_admin_cmd(u, c, ['cancel_active_poll', 'cancelpoll', 'stop_poll'])
async def adm_lib_batch_add(u, c): await run_dynamic_admin_cmd(u, c, ['add_library_batch', 'addlib_batch', 'batch_add_library'])
async def adm_lib_batch_del(u, c): await run_dynamic_admin_cmd(u, c, ['del_library_batch', 'dellib_batch', 'batch_del_library'])

async def adm_schedule(u, c): await run_dynamic_admin_cmd(u, c, ['create_schedule', 'schedule', 'add_schedule'])
async def adm_listschedules(u, c): await run_dynamic_admin_cmd(u, c, ['list_schedules', 'listschedules', 'show_schedules'])
async def adm_delschedule(u, c): await run_dynamic_admin_cmd(u, c, ['delete_schedule', 'delschedule', 'remove_schedule'])
async def adm_announce(u, c): await run_dynamic_admin_cmd(u, c, ['dispatch_broadcast', 'announce', 'broadcast'])
async def adm_editannounce(u, c): await run_dynamic_admin_cmd(u, c, ['edit_broadcast', 'editannounce', 'modify_announcement'])
async def adm_delannounce(u, c): await run_dynamic_admin_cmd(u, c, ['delete_broadcast', 'delannounce', 'remove_announcement'])
async def adm_groupid(u, c): await run_dynamic_admin_cmd(u, c, ['check_group_id', 'groupid', 'show_group_id'])
async def adm_auditlog(u, c): await run_dynamic_admin_cmd(u, c, ['pull_diagnostic_log', 'auditlog', 'get_audit_log'])

async def adm_feedbacklist(u, c): await run_dynamic_admin_cmd(u, c, ['view_feedback_log', 'feedbacklist', 'show_feedback'])
async def adm_analyze_feedback(u, c): await run_dynamic_admin_cmd(u, c, ['analyze_recent_feedback', 'analyze_feedback'])
async def adm_alltimefeedback(u, c): await run_dynamic_admin_cmd(u, c, ['review_historical_feedback', 'alltimefeedback'])

async def sup_addadmin(u, c): await run_dynamic_admin_cmd(u, c, ['promote_to_admin', 'addadmin', 'grant_admin'])
async def sup_deladmin(u, c): await run_dynamic_admin_cmd(u, c, ['demote_from_admin', 'deladmin', 'revoke_admin'])
async def sup_listadmins(u, c): await run_dynamic_admin_cmd(u, c, ['list_all_admins', 'listadmins', 'show_admins'])
async def sup_removemember(u, c): await run_dynamic_admin_cmd(u, c, ['offboard_member_records', 'removemember', 'kick_member'])
async def sup_graveyard(u, c): await run_dynamic_admin_cmd(u, c, ['view_offboarded_graveyard', 'graveyard', 'show_graveyard'])
async def sup_botstatus(u, c): await run_dynamic_admin_cmd(u, c, ['view_system_bot_status', 'botstatus', 'system_status'])
async def sup_pause(u, c): await run_dynamic_admin_cmd(u, c, ['trigger_maintenance_pause', 'pause', 'stop_bot'])
async def sup_restart(u, c): await run_dynamic_admin_cmd(u, c, ['trigger_maintenance_resume', 'restart', 'start_bot'])
async def sup_super_reset(u, c): await run_dynamic_admin_cmd(u, c, ['trigger_structural_factory_wipe', 'super_reset', 'factory_reset'])

def main():
    """Application factory loop setting up handlers, jobs, and webhook routers."""
    if not BOT_TOKEN:
        logger.critical("❌ CRITICAL ERROR: BOT_TOKEN is unconfigured in core.py environment variables!")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = post_init_wrapper
    app.add_error_handler(error_handler)

    # ----------------------------------------------------
    # 🧠 SECTION 1: TRIVIA MODULE ROUTING
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

    # ----------------------------------------------------
    # 🔐 SECTION 3: PRIVILEGED ADMINISTRATIVE ROUTING
    # ----------------------------------------------------
    app.add_handler(CommandHandler("addbday", adm_bday_add))
    app.add_handler(CommandHandler("editbday", adm_bday_edit))
    app.add_handler(CommandHandler("delbday", adm_bday_del))
    app.add_handler(CommandHandler("setbdaychannel", adm_bday_channel))
    app.add_handler(CommandHandler("setbdaytime", adm_bday_time))
    app.add_handler(CommandHandler("bdayconfig", adm_bday_config))
    app.add_handler(CommandHandler("listbdays", adm_bday_list))
    app.add_handler(CommandHandler("addbday_batch", adm_bday_batch_add))
    app.add_handler(CommandHandler("delbday_batch", adm_bday_batch_del))
    
    app.add_handler(CommandHandler("checkquota", adm_quota_audit))
    app.add_handler(CommandHandler("admin_stars", adm_stars_mod))
    app.add_handler(CommandHandler("setweeklyquota", adm_weekly_quota))
    
    app.add_handler(CommandHandler("checklimit", adm_limit_audit))
    app.add_handler(CommandHandler("admin_limit", adm_limit_mod))
    app.add_handler(CommandHandler("setweeklylimit", adm_weekly_limit))
    
    app.add_handler(CommandHandler("attendance", adm_attendance))
    app.add_handler(CommandHandler("forceback", adm_forceback))
    app.add_handler(CommandHandler("grouptasks", adm_grouptasks))
    app.add_handler(CommandHandler("cancelevent", adm_cancel_event))
    app.add_handler(CommandHandler("canceltask", adm_cancel_task))
    app.add_handler(CommandHandler("cancelpoll", adm_cancel_poll))
    app.add_handler(CommandHandler("addlib_batch", adm_lib_batch_add))
    app.add_handler(CommandHandler("dellib_batch", adm_lib_batch_del))
    
    app.add_handler(CommandHandler("schedule", adm_schedule))
    app.add_handler(CommandHandler("listschedules", adm_listschedules))
    app.add_handler(CommandHandler("delschedule", adm_delschedule))
    app.add_handler(CommandHandler("announce", adm_announce))
    app.add_handler(CommandHandler("editannounce", adm_editannounce))
    app.add_handler(CommandHandler("delannounce", adm_delannounce))
    app.add_handler(CommandHandler("groupid", adm_groupid))
    app.add_handler(CommandHandler("auditlog", adm_auditlog))
    
    app.add_handler(CommandHandler("feedbacklist", adm_feedbacklist))
    app.add_handler(CommandHandler("analyze_feedback", adm_analyze_feedback))
    app.add_handler(CommandHandler("alltimefeedback", adm_alltimefeedback))

    # ----------------------------------------------------
    # 👑 SECTION 4: SUPER OWNER STRUCTURAL EXCLUSIVES
    # ----------------------------------------------------
    app.add_handler(CommandHandler("addadmin", sup_addadmin))
    app.add_handler(CommandHandler("deladmin", sup_deladmin))
    app.add_handler(CommandHandler("listadmins", sup_listadmins))
    app.add_handler(CommandHandler("removemember", sup_removemember))
    app.add_handler(CommandHandler("graveyard", sup_graveyard))
    app.add_handler(CommandHandler("botstatus", sup_botstatus))
    app.add_handler(CommandHandler("pause", sup_pause))
    app.add_handler(CommandHandler("restart", sup_restart))
    app.add_handler(CommandHandler("super_reset", sup_super_reset))

    # ----------------------------------------------------
    # ⚙️ SECTION 5: CALLBACK & DATA CONTEXT RESOLVERS
    # ----------------------------------------------------
    app.add_handler(CallbackQueryHandler(cmd_user.rsvp_callback, pattern="^rsvp_"))
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

    logger.info("🚀 [RW] Nukhba Manager initialized. Starting event polling loops...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
