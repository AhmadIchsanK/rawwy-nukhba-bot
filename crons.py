import datetime
import logging
from telegram.ext import ContextTypes, Application
from core import WIB, SUPER_OWNER

logger = logging.getLogger(__name__)

async def generate_audit_report(pool, target_date: datetime.date) -> str:
    now = datetime.datetime.now(WIB)
    start_dt = WIB.localize(datetime.datetime.combine(target_date, datetime.time.min))
    end_dt = WIB.localize(datetime.datetime.combine(target_date, datetime.time.max))
    
    async with pool.acquire() as conn:
        active_groups = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
        away_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE category='Away Status' AND status='Set' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        back_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE category='Away Status' AND status='Removed' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        events_created = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE category='Event Created' AND status='Success' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        events_updated = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE category='Event Updated' AND status='Success' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        rsvp_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE category='RSVP' AND status='Success' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        ann_sent = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE category='Announcement' AND status='Success' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        ann_failed = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE category='Announcement' AND status='Failed' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        sys_errors = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE status='Error' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        sys_warns = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE status='Warning' AND timestamp >= $1 AND timestamp <= $2", start_dt, end_dt)
        
    msg = f"✅ 🌅 **Daily Diagnostic Audit Report**\nDate: {target_date.strftime('%m/%d/%Y')} | Time: {now.strftime('%H:%M')} WIB\n\n"
    msg += f"**Groups:**\n• Total Active Groups: {active_groups}\n\n"
    msg += f"**Users:**\n• Away Count: {away_count}\n• Back Count: {back_count}\n\n"
    msg += f"**Events:**\n• Created: {events_created}\n• Updated: {events_updated}\n• RSVP Count: {rsvp_count}\n\n"
    msg += f"**Announcements:**\n• Sent: {ann_sent}\n• Failed: {ann_failed}\n\n"
    msg += f"**System:**\n• Errors: {sys_errors}\n• Warnings: {sys_warns}"
    return msg

async def daily_morning_log(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    target_date = datetime.datetime.now(WIB).date()
    try:
        msg = await generate_audit_report(pool, target_date)
        async with pool.acquire() as conn:
            admins = await conn.fetch("SELECT user_id FROM users u INNER JOIN bot_admins a ON u.username = a.username")
            super_id = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", SUPER_OWNER)
        
        admin_ids = {a['user_id'] for a in admins if a['user_id']}
        if super_id:
            admin_ids.add(super_id)
        
        for uid in admin_ids:
            try:
                await context.bot.send_message(uid, msg, parse_mode="Markdown")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to run daily morning log: {e}")

async def monthly_star_leaderboard(context):
    """Announces top RAWWY Star earner and resets monthly points. Runs on 1st of month."""
    import datetime as _dt
    now = datetime.datetime.now(WIB)
    if now.day != 1:
        return

    month_name = (now - datetime.timedelta(days=1)).strftime("%B")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        top_earner    = await conn.fetchrow('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 1')
        groups        = await conn.fetch('SELECT chat_id FROM active_groups')
        stars_channel = await conn.fetchval("SELECT value FROM config WHERE key='stars_channel'")

        if top_earner:
            msg = (
                f"\U0001f3c6 **Best RAWWY Star earner this month ({month_name}) is @{top_earner['username']}!** \U0001f3c6\n\n"
                f"Total **{top_earner['monthly_points']} RAWWY Stars** earned. Absolutely incredible work! "
                "\U0001f31f Keep up the amazing momentum, team!"
            )
            if stars_channel:
                try:
                    await context.bot.send_message(int(stars_channel), msg, parse_mode="Markdown")
                except Exception:
                    pass
            else:
                for g in groups:
                    try:
                        await context.bot.send_message(g['chat_id'], msg, parse_mode="Markdown")
                    except Exception:
                        pass
        await conn.execute("UPDATE kudos SET monthly_points = 0")

# Legacy alias so existing code that imports monthly_leaderboard still works
monthly_leaderboard = monthly_star_leaderboard


async def weekly_quota_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute("UPDATE kudos SET quota = 3")
        
        limit_str = await conn.fetchval("SELECT value FROM config WHERE key='gemini_weekly_limit'")
        limit = int(limit_str) if limit_str and limit_str.isdigit() else 20
        
        await conn.execute("UPDATE users SET gemini_quota = $1", limit)

async def schedule_bday_job(app: Application):
    pool = app.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            t_val = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'")
        
        hour, minute = 10, 0
        if t_val:
            try:
                hour, minute = map(int, t_val.split(':'))
            except Exception:
                pass
            
        for job in app.job_queue.get_jobs_by_name('bday_cron'):
            job.schedule_removal()
            
        app.job_queue.run_daily(daily_bday_announcement, datetime.time(hour=hour, minute=minute, tzinfo=WIB), name='bday_cron')
        logger.info(f"✅ Birthday alerts actively scheduled for {hour:02d}:{minute:02d} WIB.")
    except Exception as e:
        logger.error(f"Failed to schedule birthday job: {e}")

async def daily_bday_announcement(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    today_str = now.strftime("%m/%d")
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        bday_users = await conn.fetch("SELECT username FROM birthdays WHERE bday=$1", today_str)
        target_group = await conn.fetchval("SELECT value FROM config WHERE key='bday_channel'")
        
    if not bday_users or not target_group:
        return
    
    msg = "🎉🎂 **HAPPY BIRTHDAY!** 🎂🎉\n\n"
    msg += "Please join me in sending the warmest wishes to our amazing team member(s):\n"
    for u in bday_users:
        msg += f"🎈 @{u['username']}\n"
    msg += "\nWe hope you have an incredible day filled with joy, and a fantastic year ahead!"
    
    try:
        await context.bot.send_message(int(target_group), msg, parse_mode="Markdown")
    except Exception:
        pass

async def poll_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Remove poll_drafts entries whose declared duration has elapsed since they were created.
    We approximate creation time by assuming the row was inserted when the poll was created.
    Since poll_drafts has no created_at column, we delete rows where end_time has passed.
    Fall back to deleting rows older than their hours * 3600 seconds using active_polls end_time.
    """
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            # Delete active_polls records whose end_time has passed
            await conn.execute("DELETE FROM active_polls WHERE end_time < NOW()")
            # poll_drafts has no timestamp — clean up orphaned drafts with no matching active poll
            await conn.execute("DELETE FROM poll_drafts WHERE pid NOT IN (SELECT user_id FROM active_polls) AND hours IS NOT NULL AND hours < 1")
    except Exception as e:
        logger.error(f"poll_cleanup error: {e}")


async def schedule_kp_job(app):
    """Schedule (or reschedule) the monthly KP leaderboard cron based on DB config."""
    pool = app.bot_data.get('db_pool')
    hour, minute = 13, 0
    try:
        async with pool.acquire() as conn:
            t_val = await conn.fetchval("SELECT value FROM config WHERE key='kp_lb_time'")
        if t_val:
            hour, minute = map(int, t_val.split(':'))
    except Exception:
        pass

    for job in app.job_queue.get_jobs_by_name('kp_lb_cron'):
        job.schedule_removal()

    import cmd_trivia
    app.job_queue.run_daily(
        cmd_trivia.run_monthly_trivia_reset,
        datetime.time(hour=hour, minute=minute, tzinfo=WIB),
        name='kp_lb_cron'
    )
    logger.info(f"✅ KP leaderboard reset scheduled for {hour:02d}:{minute:02d} WIB.")


async def schedule_star_job(app):
    """Schedule (or reschedule) the monthly Stars leaderboard cron based on DB config."""
    pool = app.bot_data.get('db_pool')
    hour, minute = 0, 5
    try:
        async with pool.acquire() as conn:
            t_val = await conn.fetchval("SELECT value FROM config WHERE key='star_lb_time'")
        if t_val:
            hour, minute = map(int, t_val.split(':'))
    except Exception:
        pass

    for job in app.job_queue.get_jobs_by_name('star_lb_cron'):
        job.schedule_removal()

    app.job_queue.run_daily(
        monthly_star_leaderboard,
        datetime.time(hour=hour, minute=minute, tzinfo=WIB),
        name='star_lb_cron'
    )
    logger.info(f"✅ Stars leaderboard reset scheduled for {hour:02d}:{minute:02d} WIB.")
