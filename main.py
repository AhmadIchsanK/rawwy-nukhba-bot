import logging
import datetime
from telegram import Update, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Core imports
from core import BOT_TOKEN, WIB, init_db
from commands_manifest import COMMANDS

# Module imports
import cmd_system
import cmd_user
import cmd_admin
import cmd_trivia

# Safe fallback imports for recently separated modules
try:
    import cmd_system_help
except ImportError:
    cmd_system_help = cmd_system

try:
    import cmd_cheer
except ImportError:
    cmd_cheer = None

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# 🛡️ DYNAMIC ANTI-CRASH BINDING SYSTEM 🛡️
# ==========================================
# If a function is missing from a module, binds a safe fallback instead of crashing.

def safe_cmd(module, func_name):
    if module and hasattr(module, func_name):
        return getattr(module, func_name)

    async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                f"⚠️ The command `{func_name}` is currently unavailable. Please try again later.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    return fallback

def safe_cb(module, func_name):
    if module and hasattr(module, func_name):
        return getattr(module, func_name)

    async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await update.callback_query.answer(
                "⚠️ This button is temporarily unavailable. Try again shortly.", show_alert=True
            )
        except Exception:
            pass
    return fallback


# ==========================================
# 🌐 GLOBAL TEXT INPUT ROUTER 🌐
# ==========================================
# Routes plain-text messages to whichever feature is currently awaiting input.
# Priority order: trivia config → system (feedback, wdim, etc.) → general tracker.

async def global_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Trivia config custom input (theme, time, target, timeouts)
    if await cmd_trivia.handle_trivia_text_input(update, context):
        return

    # 2. Admin config custom input (botconfig inline keyboard text fields)
    if hasattr(cmd_admin, 'handle_admin_text_input'):
        if await cmd_admin.handle_admin_text_input(update, context):
            return

    # 3. System-level text handlers (feedback drafts, wdim, etc.)
    if hasattr(cmd_system, 'global_tracker'):
        await cmd_system.global_tracker(update, context)


# ==========================================
# 🚀 SYSTEM BOOT SEQUENCE 🚀
# ==========================================

async def post_init_wrapper(application: Application):
    await init_db(application)

    # Push public commands to Telegram menus
    # Only 'public: True' commands appear in the slash menu for regular users
    public_hints = [(c['name'], c['desc']) for c in COMMANDS if c.get('public')]
    try:
        await application.bot.set_my_commands(public_hints, scope=BotCommandScopeDefault())
        await application.bot.set_my_commands(public_hints, scope=BotCommandScopeAllPrivateChats())
        await application.bot.set_my_commands(public_hints, scope=BotCommandScopeAllGroupChats())
        logger.info("✅ Telegram command menus synced from commands_manifest.")
    except Exception as e:
        logger.error(f"Failed to push command menu updates: {e}")

    logger.info("🚀 Nukhba Manager Bot is online and ready.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("⚠️ Unhandled exception during update processing:", exc_info=context.error)


# ==========================================
# 🔧 MAIN — HANDLER REGISTRATION
# ==========================================

def main():
    if not BOT_TOKEN:
        logger.error("CRITICAL: BOT_TOKEN environment variable is missing.")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = post_init_wrapper
    app.add_error_handler(error_handler)

    # ─────────────────────────────────────────
    # 💬 GENERAL / SYSTEM COMMANDS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("start",    safe_cmd(cmd_system, "start")))
    app.add_handler(CommandHandler("help",     safe_cmd(cmd_system_help, "help_command")))
    app.add_handler(CommandHandler("about",    safe_cmd(cmd_system, "about_command")))
    app.add_handler(CommandHandler("wdim",     safe_cmd(cmd_system, "what_did_i_miss")))
    app.add_handler(CommandHandler("feedback", safe_cmd(cmd_system, "submit_feedback")))
    app.add_handler(CommandHandler("ask",      safe_cmd(cmd_system, "ask_bot")))
    app.add_handler(CommandHandler("gemini",   safe_cmd(cmd_system, "ask_gemini")))

    # ─────────────────────────────────────────
    # 🔄 VERSION & UPDATE LOG
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("updateinfo",   safe_cmd(cmd_admin, "update_info")))
    app.add_handler(CommandHandler("pushupdate",   safe_cmd(cmd_admin, "push_update")))
    app.add_handler(CommandHandler("updatechange", safe_cmd(cmd_admin, "update_change")))

    # ─────────────────────────────────────────
    # 📅 EVENTS & POLLS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("newevent",   safe_cmd(cmd_user, "create_event")))
    app.add_handler(CommandHandler("editevent",  safe_cmd(cmd_user, "edit_event")))
    app.add_handler(CommandHandler("events",     safe_cmd(cmd_user, "list_events")))
    app.add_handler(CommandHandler("poll",       safe_cmd(cmd_user, "create_poll")))

    # ─────────────────────────────────────────
    # ⭐ RAWWY STARS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("thanks",      safe_cmd(cmd_user, "give_thanks")))
    app.add_handler(CommandHandler("myquota",     safe_cmd(cmd_user, "my_quota")))
    app.add_handler(CommandHandler("mystar",      safe_cmd(cmd_user, "my_star")))
    app.add_handler(CommandHandler("totalstar",   safe_cmd(cmd_user, "total_star")))
    app.add_handler(CommandHandler("leaderboard", safe_cmd(cmd_user, "leaderboard")))

    # ─────────────────────────────────────────
    # 📚 LIBRARY
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("addlib",  safe_cmd(cmd_user, "add_lib")))
    app.add_handler(CommandHandler("editlib", safe_cmd(cmd_user, "edit_lib")))
    app.add_handler(CommandHandler("dellib",  safe_cmd(cmd_user, "del_lib")))
    app.add_handler(CommandHandler("getlib",  safe_cmd(cmd_user, "get_lib")))
    app.add_handler(CommandHandler("library", safe_cmd(cmd_user, "list_lib")))

    # ─────────────────────────────────────────
    # ⚡ TASKS & AWAY
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("assign",   safe_cmd(cmd_user, "assign_task")))
    app.add_handler(CommandHandler("complete", safe_cmd(cmd_user, "complete_task")))
    app.add_handler(CommandHandler("mytasks",  safe_cmd(cmd_user, "my_tasks")))
    app.add_handler(CommandHandler("away",     safe_cmd(cmd_user, "set_away")))
    app.add_handler(CommandHandler("back",     safe_cmd(cmd_user, "set_back")))

    # ─────────────────────────────────────────
    # 🥳 MOTIVATIONAL CHEERS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("cheerme",  safe_cmd(cmd_cheer, "cheer_me")))
    app.add_handler(CommandHandler("setcheer", safe_cmd(cmd_cheer, "set_cheer")))

    # ─────────────────────────────────────────
    # 🎮 TRIVIA — USER
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("mypoint", safe_cmd(cmd_trivia, "my_point")))

    # ─────────────────────────────────────────
    # 🎮 TRIVIA — ADMIN
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("triviaconfig",    safe_cmd(cmd_trivia, "trivia_config")))
    app.add_handler(CommandHandler("forcetrivia",     safe_cmd(cmd_trivia, "force_trivia")))
    app.add_handler(CommandHandler("forcesupertrivia",safe_cmd(cmd_trivia, "force_super_trivia")))
    app.add_handler(CommandHandler("canceltrivia",    safe_cmd(cmd_trivia, "cancel_trivia")))
    app.add_handler(CommandHandler("endtrivia",       safe_cmd(cmd_trivia, "end_trivia")))
    app.add_handler(CommandHandler("admin_kp",        safe_cmd(cmd_trivia, "admin_kp")))

    # ─────────────────────────────────────────
    # ⚙️ ADMIN SYSTEM CONFIG
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("botconfig",   safe_cmd(cmd_admin, "bot_config")))
    app.add_handler(CommandHandler("setchannel",  safe_cmd(cmd_admin, "set_channel")))
    app.add_handler(CommandHandler("unsetchannel",safe_cmd(cmd_admin, "unset_channel")))
    app.add_handler(CommandHandler("groupid",     safe_cmd(cmd_admin, "check_group_id")))
    app.add_handler(CommandHandler("auditlog",    safe_cmd(cmd_admin, "get_audit_log")))
    app.add_handler(CommandHandler("audittime",   safe_cmd(cmd_admin, "set_audit_time")))

    # ─────────────────────────────────────────
    # 👥 USER MANAGEMENT
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("manageusers", safe_cmd(cmd_admin, "manage_users")))

    # ─────────────────────────────────────────
    # ⭐ ADMIN STARS & AI LIMITS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("checkquota",  safe_cmd(cmd_admin, "check_quota")))
    app.add_handler(CommandHandler("admin_stars", safe_cmd(cmd_admin, "admin_stars")))
    app.add_handler(CommandHandler("checklimit",  safe_cmd(cmd_admin, "check_limit")))
    app.add_handler(CommandHandler("admin_limit", safe_cmd(cmd_admin, "admin_limit")))

    # ─────────────────────────────────────────
    # 🎂 ADMIN BIRTHDAYS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("addbday",   safe_cmd(cmd_admin, "add_bday")))
    app.add_handler(CommandHandler("editbday",  safe_cmd(cmd_admin, "edit_bday")))
    app.add_handler(CommandHandler("delbday",   safe_cmd(cmd_admin, "del_bday")))
    app.add_handler(CommandHandler("listbdays", safe_cmd(cmd_admin, "list_bdays")))

    # ─────────────────────────────────────────
    # 🏖️ ADMIN TEAM MANAGEMENT
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("attendance",   safe_cmd(cmd_admin, "attendance")))
    app.add_handler(CommandHandler("forceback",    safe_cmd(cmd_admin, "force_back")))
    app.add_handler(CommandHandler("grouptasks",   safe_cmd(cmd_admin, "group_tasks")))
    app.add_handler(CommandHandler("cancelevent",  safe_cmd(cmd_admin, "cancel_event")))
    app.add_handler(CommandHandler("canceltask",   safe_cmd(cmd_admin, "cancel_task")))
    app.add_handler(CommandHandler("cancelpoll",   safe_cmd(cmd_admin, "cancel_poll_admin")))

    # ─────────────────────────────────────────
    # 📢 ADMIN BROADCASTS & SCHEDULING
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("newsched",      safe_cmd(cmd_admin, "new_schedule")))
    app.add_handler(CommandHandler("listschedules", safe_cmd(cmd_admin, "list_schedules")))
    app.add_handler(CommandHandler("delschedule",   safe_cmd(cmd_admin, "del_schedule")))
    app.add_handler(CommandHandler("announce",      safe_cmd(cmd_admin, "announce")))
    app.add_handler(CommandHandler("editannounce",  safe_cmd(cmd_admin, "edit_announce")))
    app.add_handler(CommandHandler("delannounce",   safe_cmd(cmd_admin, "del_announce")))
    app.add_handler(CommandHandler("feedbacklist",  safe_cmd(cmd_admin, "feedback_list")))
    app.add_handler(CommandHandler("analyze_feedback", safe_cmd(cmd_admin, "analyze_feedback")))

    # ─────────────────────────────────────────
    # 👑 SUPER OWNER EXCLUSIVES
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("allcommandtest", safe_cmd(cmd_admin, "all_command_test")))
    app.add_handler(CommandHandler("addadmin",       safe_cmd(cmd_admin, "add_admin_req")))
    app.add_handler(CommandHandler("deladmin",       safe_cmd(cmd_admin, "del_admin_req")))
    app.add_handler(CommandHandler("listadmins",     safe_cmd(cmd_admin, "list_admins")))
    app.add_handler(CommandHandler("removemember",   safe_cmd(cmd_admin, "remove_member_req")))
    app.add_handler(CommandHandler("graveyard",      safe_cmd(cmd_admin, "graveyard")))
    app.add_handler(CommandHandler("botstatus",      safe_cmd(cmd_admin, "bot_status")))
    app.add_handler(CommandHandler("pause",          safe_cmd(cmd_admin, "pause_bot")))
    app.add_handler(CommandHandler("restart",        safe_cmd(cmd_admin, "restart_bot")))
    app.add_handler(CommandHandler("super_reset",    safe_cmd(cmd_admin, "super_reset_req")))

    # ─────────────────────────────────────────
    # 🖱️ INTERACTIVE CALLBACK ROUTERS
    # ─────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_user,   "rsvp_callback"),    pattern="^rsvp_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_user,   "poll_callback"),    pattern="^pollst_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "config_callback"),  pattern="^cfg_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "manage_users_callback"), pattern="^mu_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "newsched_callback"), pattern="^nsched_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_trivia, "trivia_callback"),  pattern="^tcfg_|trivans_|tcancel_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_system, "feedback_callback"),pattern="^fb_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "super_callback"),   pattern="^sup_"))

    # ─────────────────────────────────────────
    # 🛡️ GLOBAL LISTENERS
    # ─────────────────────────────────────────

    # Track members joining/leaving
    if hasattr(cmd_system, 'security_track_chats'):
        app.add_handler(MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
            cmd_system.security_track_chats
        ))

    # Main text router — handles all plain-text messages in priority order:
    # trivia config input → admin config input → system tracker
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_router))

    # Unknown command fallback
    if hasattr(cmd_system, 'unknown_command'):
        app.add_handler(MessageHandler(filters.COMMAND, cmd_system.unknown_command))

    # ─────────────────────────────────────────
    # ⏲️ BACKGROUND CRON SCHEDULES
    # ─────────────────────────────────────────

    # Trivia countdown sweeper — runs every 3 seconds
    if hasattr(cmd_trivia, 'trivia_timeout_sweeper'):
        app.job_queue.run_repeating(cmd_trivia.trivia_timeout_sweeper, interval=3)

    # Daily trivia scheduler — checks every 60 seconds
    if hasattr(cmd_trivia, 'trivia_cron_job'):
        app.job_queue.run_repeating(cmd_trivia.trivia_cron_job, interval=60)

    # Broadcast/schedule processor — runs every 30 seconds
    if hasattr(cmd_admin, 'process_schedules'):
        app.job_queue.run_repeating(cmd_admin.process_schedules, interval=30)

    # Monthly trivia KP reset — runs at 13:00 WIB daily (only acts on 1st of month)
    if hasattr(cmd_trivia, 'run_monthly_trivia_reset'):
        app.job_queue.run_daily(
            cmd_trivia.run_monthly_trivia_reset,
            time=datetime.time(hour=13, minute=0, tzinfo=WIB)
        )

    # Audit log daily digest
    if hasattr(cmd_admin, 'send_daily_audit_digest'):
        app.job_queue.run_daily(
            cmd_admin.send_daily_audit_digest,
            time=datetime.time(hour=23, minute=50, tzinfo=WIB)
        )

    # Optional cron jobs from crons.py
    try:
        from crons import daily_morning_log, poll_cleanup
        app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
        app.job_queue.run_repeating(poll_cleanup, interval=3600)
    except ImportError:
        logger.warning("Optional crons.py not found — skipping daily logs and poll cleanup.")

    # 🚀 GO
    logger.info("🚀 Starting Nukhba Manager Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
