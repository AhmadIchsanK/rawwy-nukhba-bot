import datetime, logging
from telegram.ext import ContextTypes, Application
from core import WIB, SUPER_OWNER

logger = logging.getLogger(__name__)

async def generate_audit_report(pool, target_date: datetime.date) -> str:
    now = datetime.datetime.now(WIB)
    start_dt = WIB.localize(datetime.datetime.combine(target_date, datetime.time.min))
    end_dt = WIB.localize(datetime.datetime.combine(target_date, datetime.time.max))
    
    async with pool.acquire() as conn:
        active_groups = await conn.fetchval("SELECT COUNT(*) FROM active_groups")
        away_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Away Status' AND status='Set' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        back_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Away Status' AND status='Removed' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        events_created = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Event Created' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        events_updated = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Event Updated' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        rsvp_count = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='RSVP' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        ann_sent = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Announcement' AND status='Success' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        ann_failed = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE action_type='Announcement' AND status='Failed' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        sys_errors = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE status='Error' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        sys_warns = await conn.fetchval("SELECT COUNT(*) FROM audit_logs WHERE status='Warning' AND created_at >= $1 AND created_at <= $2", start_dt, end_dt)
        
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
        
        admin_ids = {a['user_id'] for a in admins}
        if super_id: admin_ids.add(super_id)
        
        for uid in admin_ids:
            try: await context.bot.send_message(uid, msg, parse_mode="Markdown")
            except: pass
    except Exception as e:
        logger.error(f"Failed to run daily morning log: {e}")

async def monthly_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now(WIB)
    if now.day != 1: return 
    
    month_name = (now - datetime.timedelta(days=1)).strftime("%B")
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        top_earner = await conn.fetchrow('SELECT username, monthly_points FROM kudos WHERE monthly_points > 0 ORDER BY monthly_points DESC LIMIT 1')
        groups = await conn.fetch('SELECT chat_id FROM active_groups')
        
        if top_earner:
            msg = f"🏆 **Best star earner this month ({month_name}) is @{top_earner['username']}!** 🏆\n\nTotal **{top_earner['monthly_points']} RAWWY Stars** earned. Absolutely incredible work! 🌟 Keep up the amazing momentum, team!"
            for g in groups:
                try: await context.bot.send_message(g['chat_id'], msg, parse_mode="Markdown")
                except: pass
        await conn.execute("UPDATE kudos SET monthly_points = 0")

async def weekly_quota_reset(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn: 
        await conn.execute("UPDATE kudos SET quota = 3")
        await conn.execute("UPDATE users SET gemini_quota = 20")

async def schedule_bday_job(app: Application):
    pool = app.bot_data.get('db_pool')
    try:
        async with pool.acquire() as conn:
            t_val = await conn.fetchval("SELECT value FROM config WHERE key='bday_time'")
        
        hour, minute = 10, 0
        if t_val:
            try: hour, minute = map(int, t_val.split(':'))
            except: pass
            
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
        
    if not bday_users or not target_group: return
    
    msg = "🎉🎂 **HAPPY BIRTHDAY!** 🎂🎉\n\n"
    msg += "Please join me in sending the warmest wishes to our amazing team member(s):\n"
    for u in bday_users: msg += f"🎈 @{u['username']}\n"
    msg += "\nWe hope you have an incredible day filled with joy, and a fantastic year ahead!"
    
    try: await context.bot.send_message(int(target_group), msg, parse_mode="Markdown")
    except: pass

async def poll_cleanup(context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_polls WHERE end_time < NOW()")
