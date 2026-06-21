from core import delete_cmd, is_bot_admin
from telegram import Update
from telegram.ext import ContextTypes

# Generic mapping from keyword to config key and optional scheduled job names to cancel
UNSET_MAP = {
    'bday': {'config_key': 'bday_channel', 'jobs': ['bday_cron']},
    'trivia': {'config_key': 'target_chat_id', 'jobs': ['trivia_cron']},
    'announce': {'config_key': 'announce_channel', 'jobs': ['announcement_cron']}
}

async def unset_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    username = update.effective_user.username or str(update.effective_user.id)
    if not await is_bot_admin(username, pool):
        return
    try:
        key = context.args[0].lower()
    except Exception:
        return await context.bot.send_message(update.effective_user.id, "❌ Usage: /unsetchannel <bday|trivia|announce>")
    if key not in UNSET_MAP:
        return await context.bot.send_message(update.effective_user.id, "❌ Valid keys: bday, trivia, announce")
    conf = UNSET_MAP[key]
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM config WHERE key=$1", conf['config_key'])
    # Cancel scheduled jobs if present
    for job_name in conf.get('jobs', []):
        for job in context.application.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
    await context.bot.send_message(update.effective_user.id, f"✅ Unset {key} channel and cleared related schedules.")
