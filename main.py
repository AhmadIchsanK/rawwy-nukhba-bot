import logging
import datetime
import os
from telegram import Update, BotCommand, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters, ContextTypes, PicklePersistence

# Core imports
from core import BOT_TOKEN, WIB, init_db
from commands_manifest import COMMANDS

# Module imports
import cmd_system
import cmd_user
import cmd_admin
import cmd_trivia
import cmd_command_nav
import cmd_events
import cmd_library
import cmd_away
import cmd_task
import cmd_birthday
import cmd_broadcast
import cmd_adminconfig
import cmd_manual

# Safe fallback imports for recently separated modules
try:
    import cmd_system_help
except ImportError:
    cmd_system_help = cmd_system

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# 🛡️ DYNAMIC ANTI-CRASH BINDING SYSTEM 🛡️
# ==========================================

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

async def global_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Trivia config custom input
    if await cmd_trivia.handle_trivia_text_input(update, context):
        return

    # 2. Admin config custom input
    if hasattr(cmd_admin, 'handle_admin_text_input'):
        if await cmd_admin.handle_admin_text_input(update, context):
            return

    # 3. Schedule config custom input
    if hasattr(cmd_admin, 'handle_schcfg_text_input'):
        if await cmd_admin.handle_schcfg_text_input(update, context):
            return

    # 4. /newsched interactive text input (target chat, time, message)
    # 5. Events & Polls DM text flow
    if await cmd_events.handle_events_text(update, context):
        return

    # 6b. Library DM text flow
    if await cmd_library.handle_library_text(update, context):
        return

    # 6c. Away DM text flow
    if await cmd_away.handle_away_text(update, context):
        return

    # 6d. Task DM + group text flow
    if await cmd_task.handle_task_text(update, context):
        return

    # 6e. Birthday config DM text flow
    if await cmd_birthday.handle_birthday_text(update, context):
        return

    # 6f. Broadcast DM text flow
    if await cmd_broadcast.handle_broadcast_text(update, context):
        return

    # 6g. Admin inline text flows (admin hub, userconfig, updatechange)
    if await cmd_adminconfig.handle_admin_inline_text(update, context):
        return
    if await cmd_adminconfig.handle_adminconfig_text(update, context):
        return

    # 6d. Auto-cancel away on group message
    await cmd_away.check_auto_cancel(update, context)

    # 7. System-level text handlers
    if hasattr(cmd_system, 'global_tracker'):
        await cmd_system.global_tracker(update, context)


# ==========================================
# 🚀 SYSTEM BOOT SEQUENCE 🚀
# ==========================================

async def post_init_wrapper(application: Application):
    await init_db(application)

    # Schedule birthday, KP leaderboard, and Stars leaderboard cron jobs
    try:
        from crons import schedule_bday_job, schedule_kp_job, schedule_star_job
        await schedule_bday_job(application)
        await schedule_kp_job(application)
        await schedule_star_job(application)
    except Exception as e:
        logger.warning(f"Scheduler setup failed: {e}")

    public_hints = [
        BotCommand(cmd['name'], cmd['desc'][:256])
        for cmd in COMMANDS if cmd.get('public')
    ]
    admin_hints = [
        BotCommand(cmd['name'], cmd['desc'][:256])
        for cmd in COMMANDS if cmd.get('public') or cmd.get('admin')
    ]
    super_hints = [
        BotCommand(cmd['name'], cmd['desc'][:256])
        for cmd in COMMANDS
    ]

    try:
        # Public scope — all users and groups see only public commands
        await application.bot.set_my_commands(public_hints, scope=BotCommandScopeDefault())
        await application.bot.set_my_commands(public_hints, scope=BotCommandScopeAllPrivateChats())
        await application.bot.set_my_commands(public_hints, scope=BotCommandScopeAllGroupChats())

        # Elevate admin/super DM scopes using DB
        pool = application.bot_data.get('db_pool')
        if pool:
            async with pool.acquire() as conn:
                admins = await conn.fetch("SELECT user_id FROM users u JOIN bot_admins ba ON LOWER(u.username)=LOWER(ba.username) WHERE u.user_id IS NOT NULL")
                super_row = await conn.fetchrow("SELECT user_id FROM users WHERE LOWER(username)=$1 AND user_id IS NOT NULL", SUPER_OWNER.lower())

            for row in admins:
                try:
                    await application.bot.set_my_commands(
                        admin_hints,
                        scope=BotCommandScopeChat(chat_id=row['user_id'])
                    )
                except Exception:
                    pass

            if super_row:
                try:
                    await application.bot.set_my_commands(
                        super_hints,
                        scope=BotCommandScopeChat(chat_id=super_row['user_id'])
                    )
                except Exception:
                    pass

        logger.info("✅ Telegram command menus synced (public + admin + super scopes).")
    except Exception as e:
        logger.error(f"Failed to push command menu updates: {e}")

    logger.info("🚀 Nukhba Manager Bot is online and ready.")


async def post_stop_wrapper(application: Application):
    """Gracefully close the database pool when the bot shuts down."""
    pool = application.bot_data.get('db_pool')
    if pool:
        await pool.close()
        logger.info("🛑 PostgreSQL database connection pool closed gracefully.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("⚠️ Unhandled exception during update processing:", exc_info=context.error)
    # Send user-friendly message — never expose technical details
    try:
        if update and hasattr(update, "effective_message") and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ Something went wrong on our end. Please try again in a moment.\n"
                "If the issue keeps happening, let the admin know via /feedback.",
            )
    except Exception:
        pass


# ==========================================
# 🔧 MAIN — HANDLER REGISTRATION
# ==========================================

def main():
    if not BOT_TOKEN:
        logger.error("CRITICAL: BOT_TOKEN environment variable is missing.")
        return

    # Create a persistent data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)
    
    # 💾 Initialize Persistence
    persistence = PicklePersistence(filepath="data/bot_state.pickle")

    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()
    app.post_init = post_init_wrapper
    app.post_stop = post_stop_wrapper
    app.add_error_handler(error_handler)

    # ─────────────────────────────────────────
    # 💬 GENERAL / SYSTEM COMMANDS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("start",    safe_cmd(cmd_system, "start")))
    app.add_handler(CommandHandler("help",     safe_cmd(cmd_system_help, "help_command")))
    app.add_handler(CommandHandler("command",  cmd_command_nav.command_nav))
    app.add_handler(CommandHandler("about",    safe_cmd(cmd_system, "about_command")))
    app.add_handler(CommandHandler("wdim",     safe_cmd(cmd_system, "what_did_i_miss")))
    app.add_handler(CommandHandler("feedback", safe_cmd(cmd_system, "submit_feedback")))
    app.add_handler(CommandHandler("ask",      safe_cmd(cmd_system, "ask_bot")))
    app.add_handler(CommandHandler("ai",   safe_cmd(cmd_system, "ask_ai")))

    # ─────────────────────────────────────────
    # 🔄 VERSION & UPDATE LOG
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("update",       safe_cmd(cmd_admin, "update_info")))
    app.add_handler(CommandHandler("pushupdate",   safe_cmd(cmd_admin, "push_update")))
    app.add_handler(CommandHandler("updatechange", safe_cmd(cmd_admin, "update_change")))

    # ─────────────────────────────────────────
    # 📅 EVENTS & POLLS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("eventpoll",  cmd_events.eventpoll_command))
    app.add_handler(CommandHandler("listevent",  cmd_events.listevent_command))
    # /newevent /editevent /poll /cancelevent /cancelpoll → merged into /eventpoll
    app.add_handler(CommandHandler("away",       cmd_away.away_command))
    app.add_handler(CommandHandler("back",       safe_cmd(cmd_user, "set_back")))  # /back still manual
    app.add_handler(CommandHandler("broadcast",      cmd_broadcast.broadcast_command))
    app.add_handler(CommandHandler("manual",         cmd_manual.manual_command))
    # /newsched /announce /editannounce /delannounce → merged into /broadcast
    app.add_handler(CommandHandler("admin",       cmd_adminconfig.admin_command))
    app.add_handler(CommandHandler("userconfig",  cmd_adminconfig.userconfig_command))
    app.add_handler(CommandHandler("birthdayconfig", cmd_birthday.birthday_config_command))
    # /addbday /editbday /delbday /listbdays /bulkaddbday /bulkdelbday → merged into /birthdayconfig
    app.add_handler(CommandHandler("task",       cmd_task.task_command))
    app.add_handler(CommandHandler("mytask",     cmd_task.mytask_command))
    # /assign and /complete → merged into /task and /mytask inline hubs
    # /newevent, /editevent, /poll → merged into /events inline hub

    # ─────────────────────────────────────────
    # ⭐ RAWWY STARS
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("thanks",           safe_cmd(cmd_user, "give_thanks")))
    app.add_handler(CommandHandler("myquota",          safe_cmd(cmd_user, "my_quota")))
    app.add_handler(CommandHandler("mystar",           safe_cmd(cmd_user, "my_star")))
    app.add_handler(CommandHandler("leaderboard_star", safe_cmd(cmd_user, "leaderboard_star")))

    # ─────────────────────────────────────────
    # 📚 LIBRARY
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("library", safe_cmd(cmd_user, "list_lib")))

    # ─────────────────────────────────────────
    # ⚡ TASKS & AWAY
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("assign",   safe_cmd(cmd_user, "assign_task")))
    app.add_handler(CommandHandler("complete", safe_cmd(cmd_user, "complete_task")))
    app.add_handler(CommandHandler("mytasks",  safe_cmd(cmd_user, "my_tasks")))

    # ─────────────────────────────────────────
    # 🎮 TRIVIA — USER
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("mypoint",        safe_cmd(cmd_trivia, "my_point")))
    app.add_handler(CommandHandler("leaderboard_kp", safe_cmd(cmd_trivia, "leaderboard_kp")))

    # ─────────────────────────────────────────
    # 🎮 TRIVIA — ADMIN
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("triviaconfig",    safe_cmd(cmd_trivia, "trivia_config")))
    app.add_handler(CommandHandler("forcetrivia",     safe_cmd(cmd_trivia, "force_trivia")))
    app.add_handler(CommandHandler("forcesupertrivia",safe_cmd(cmd_trivia, "force_super_trivia")))
    app.add_handler(CommandHandler("canceltrivia",    safe_cmd(cmd_trivia, "cancel_trivia")))
    app.add_handler(CommandHandler("endtrivia",       safe_cmd(cmd_trivia, "end_trivia")))
    app.add_handler(CommandHandler("triviaend",       safe_cmd(cmd_trivia, "end_trivia"))) # Alias
    app.add_handler(CommandHandler("admin_kp",        safe_cmd(cmd_trivia, "admin_kp")))

    # ─────────────────────────────────────────
    # ⚙️ ADMIN SYSTEM CONFIG
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("botconfig",   safe_cmd(cmd_admin, "bot_config")))
    app.add_handler(CommandHandler("schedconfig", safe_cmd(cmd_admin, "sched_config")))
    app.add_handler(CommandHandler("setchannel",  safe_cmd(cmd_admin, "set_channel")))
    app.add_handler(CommandHandler("unsetchannel",safe_cmd(cmd_admin, "unset_channel")))
    app.add_handler(CommandHandler("groupid",     safe_cmd(cmd_admin, "check_group_id")))
    app.add_handler(CommandHandler("registergroup", safe_cmd(cmd_admin, "register_group")))

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

    # ─────────────────────────────────────────
    # 🏖️ ADMIN TEAM MANAGEMENT
    # ─────────────────────────────────────────
    app.add_handler(CommandHandler("attendance",   safe_cmd(cmd_admin, "attendance")))
    app.add_handler(CommandHandler("forceback",    safe_cmd(cmd_admin, "force_back")))
    app.add_handler(CommandHandler("grouptasks",   safe_cmd(cmd_admin, "group_tasks")))
    # /cancelevent → merged into /events inline hub
    app.add_handler(CommandHandler("canceltask",   safe_cmd(cmd_admin, "cancel_task")))
    # /cancelpoll → merged into /events inline hub

    # ─────────────────────────────────────────
    # 📢 ADMIN BROADCASTS & SCHEDULING
    # ─────────────────────────────────────────
    # /listschedules and /delschedule merged into /broadcast
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
    app.add_handler(CallbackQueryHandler(cmd_command_nav.command_nav_callback, pattern="^cmenu_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_user,   "rsvp_callback"),    pattern="^rsvp_"))
    app.add_handler(CallbackQueryHandler(cmd_events.events_callback,              pattern="^ev_"))
    app.add_handler(CallbackQueryHandler(cmd_library.library_callback,            pattern="^lib_"))
    app.add_handler(CallbackQueryHandler(cmd_away.away_callback,                  pattern="^aw_"))
    app.add_handler(CallbackQueryHandler(cmd_task.task_callback,                  pattern="^tk_"))
    app.add_handler(CallbackQueryHandler(cmd_task.mytask_callback,                pattern="^myt_"))
    app.add_handler(CallbackQueryHandler(cmd_birthday.birthday_callback,          pattern="^bd_"))
    app.add_handler(CallbackQueryHandler(cmd_broadcast.broadcast_callback,        pattern="^bc_"))
    app.add_handler(CallbackQueryHandler(cmd_adminconfig.admin_callback,          pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(cmd_adminconfig.userconfig_callback,     pattern="^uc_"))
    app.add_handler(CallbackQueryHandler(cmd_adminconfig.admin_callback,          pattern="^adm_uc_cancel"))
    # pollst_ callbacks removed — poll settings now handled via ev_poll_ prefix
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "config_callback"),  pattern="^cfg_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "sched_config_callback"), pattern="^schcfg_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "manage_users_callback"), pattern="^mu_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_trivia, "trivia_callback"),  pattern="^tcfg_|trivans_|tcancel_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_system, "feedback_callback"),pattern="^fb_"))
    app.add_handler(CallbackQueryHandler(safe_cb(cmd_admin,  "super_callback"),   pattern="^sup_"))

    # ─────────────────────────────────────────
    # 🛡️ GLOBAL LISTENERS
    # ─────────────────────────────────────────

    # Track bot being added/removed from groups (requires ChatMemberHandler + my_chat_member updates)
    if hasattr(cmd_system, 'security_track_chats'):
        app.add_handler(ChatMemberHandler(cmd_system.security_track_chats, ChatMemberHandler.MY_CHAT_MEMBER))

    # Catch ALL non-command messages so forwarded media for target config is caught
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, global_text_router))

    if hasattr(cmd_system, 'unknown_command'):
        app.add_handler(MessageHandler(filters.COMMAND, cmd_system.unknown_command))

    # ─────────────────────────────────────────
    # ⏲️ BACKGROUND CRON SCHEDULES
    # ─────────────────────────────────────────

    if hasattr(cmd_trivia, 'trivia_timeout_sweeper'):
        app.job_queue.run_repeating(cmd_trivia.trivia_timeout_sweeper, interval=3)

    if hasattr(cmd_trivia, 'trivia_cron_job'):
        app.job_queue.run_repeating(cmd_trivia.trivia_cron_job, interval=60)

    if hasattr(cmd_admin, 'process_schedules'):
        app.job_queue.run_repeating(cmd_admin.process_schedules, interval=30)

    # run_monthly_trivia_reset is now scheduled dynamically via schedule_kp_job in post_init_wrapper

    if hasattr(cmd_admin, 'send_daily_audit_digest'):
        app.job_queue.run_daily(
            cmd_admin.send_daily_audit_digest,
            time=datetime.time(hour=23, minute=50, tzinfo=WIB)
        )

    try:
        from crons import daily_morning_log, poll_cleanup
        app.job_queue.run_daily(daily_morning_log, datetime.time(hour=7, minute=0, tzinfo=WIB))
        app.job_queue.run_repeating(poll_cleanup, interval=3600)
        # monthly_leaderboard and kp reset are now scheduled via schedule_star_job / schedule_kp_job in post_init_wrapper
    except ImportError:
        logger.warning("Optional crons.py not found — skipping daily logs and poll cleanup.")

    # Auto-flush database memory buffers — runs every 30 seconds
    if hasattr(cmd_system, 'flush_chat_buffer'):
        app.job_queue.run_repeating(cmd_system.flush_chat_buffer, interval=30)

    # 🚀 GO
    logger.info("🚀 Starting Nukhba Manager Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
