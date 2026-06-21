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
        
    msg = f"✅ 🌅 **Daily Diagnostic Audit Report**\nDate: {target_date.strftime('%d/%m/%Y')} | Time: {now.strftime('%H:%M')} WIB\n\n"
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

async def monthly_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    if now.day != 1:
        return 
    
    month_name = (now - datetime.timedelta(days=1)).strftime("%B")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        top_earner = await conn.fetchrow('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 1')
        groups = await conn.fetch('SELECT chat_id FROM active_groups')
        stars_channel = await conn.fetchval("SELECT value FROM config WHERE key='stars_channel'")
        
        if top_earner:
            msg = f"🏆 **Best star earner this month ({month_name}) is @{top_earner['username']}!** 🏆\n\nTotal **{top_earner['monthly_points']} RAWWY Stars** earned. Absolutely incredible work! 🌟 Keep up the amazing momentum, team!"
            
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
async def run_monthly_trivia_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    async with pool.acquire() as conn:
        target_chat_str = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''
        if not target_chat_str:
            return
        
        top_minds = await conn.fetch("SELECT username, monthly_kp FROM trivia_scores WHERE monthly_kp > 0 ORDER BY monthly_kp DESC LIMIT 3")
        await conn.execute("UPDATE trivia_scores SET monthly_kp = 0")
        
    if not top_minds:
        return
    announcement = "🏆 **NUKHBA TRIVIA MONTHLY CHAMPIONS** 🏆\n\nCongratulations to our top minds this month! Your brilliance shines supreme:\n\n"
    podiums = ["🥇", "🥈", "🥉"]
    for idx, user in enumerate(top_minds):
        announcement += f"{podiums[idx]} **@{user['username']}** — {user['monthly_kp']} Knowledge Points earned!\n"
    announcement += "\n🔄 *Monthly leaderboard stats have been reset! All-time stats remain captured.*"
    try:
        await context.bot.send_message(int(target_chat_str), announcement, parse_mode="Markdown")
    except Exception:
        pass

async def poll_cleanup(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM poll_drafts WHERE hours * 3600 < EXTRACT(EPOCH FROM NOW() - (SELECT timestamp FROM audit_logs ORDER BY timestamp DESC LIMIT 1))")
