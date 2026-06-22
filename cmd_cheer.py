import logging
import asyncio
from google import genai
from telegram import Update
from telegram.ext import ContextTypes
from core import GEMINI_API_KEY
from cmd_system import _generate_content_with_retry

logger = logging.getLogger(__name__)

async def cheer_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates customized high-energy motivational cheers using Gemini."""
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        profile = await conn.fetchval("SELECT cheer_profile FROM users WHERE username = $1", username)
        
    if not profile:
        return await update.message.reply_text("👋 You haven't set a profile yet! Tell me your vibe first using `/setcheer [your vibe]`")
        
    await update.message.reply_text("📣 *Preparing your dynamic motivation boost...*")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"Write a highly personal, hyper-energetic motivational cheer or pep-talk for @{username} based on their profile: {profile}."
        response = await _generate_content_with_retry(client, prompt)
        await update.message.reply_text(response.text)
    except Exception as e:
        await update.message.reply_text(f"❌ Could not generate motivation right now: {e}")

async def ensure_cheer_profile_column(pool):
    """Safely upgrades the users table column schema at startup."""
    async with pool.acquire() as conn:
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cheer_profile TEXT;")
