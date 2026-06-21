import logging
from google import genai
from telegram import Update
from telegram.ext import ContextTypes
from core import GEMINI_API_KEY

logger = logging.getLogger(__name__)

async def ensure_cheer_profile_column(pool):
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cheer_profile TEXT;")
            logger.info("✅ Database migration: 'cheer_profile' column verified.")
        except Exception as e:
            logger.error(f"❌ Migration error: {e}")

async def set_cheer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    profile_text = " ".join(context.args).strip()
    
    if not profile_text:
        return await update.message.reply_text(
            "❌ **Format error.** Please set your vibe using:\n"
            "`/setcheer [vibe/goals/favorite cheering style]`\n\n"
            "*Example:*\n`/setcheer aggressive motivation, studying machine learning, anime hero style`",
            parse_mode="Markdown"
        )
        
    pool = context.bot_data.get('db_pool')
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (username, user_id, cheer_profile) VALUES ($1, $2, $3) "
            "ON CONFLICT (username) DO UPDATE SET cheer_profile=$3, user_id=$2",
            username, update.effective_user.id, profile_text
        )
        
    await update.message.reply_text(
        f"✅ **Cheer profile locked in!**\n"
        f"Style Profile: *\"{profile_text}\"* \n\n"
        f"Type `/cheerme` anytime to receive your hyper-personalized motivational boost!",
        parse_mode="Markdown"
    )

async def cheer_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    pool = context.bot_data.get('db_pool')
    
    async with pool.acquire() as conn:
        profile = await conn.fetchval("SELECT cheer_profile FROM users WHERE username=$1", username)
        
    if not profile:
        return await update.message.reply_text(
            "⚠️ **No cheer profile found!**\n"
            "Tell me about your vibe first so I can tailor your cheer perfectly!\n"
            "Configure it using: `/setcheer [your vibe/goals/style]`",
            parse_mode="Markdown"
        )
        
    temp_msg = await update.message.reply_text("⚡ *Charging motivation battery...* ⚡", parse_mode="Markdown")
    
    if not GEMINI_API_KEY:
        return await temp_msg.edit_text("❌ System Error: GEMINI_API_KEY is not configured in environment variables.")
        
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"Write a hyper-energetic, personalized motivational cheer or boost for the user @{username}.\n"
            f"Here is their custom personal profile:\n"
            f"\"\"\"\n{profile}\n\"\"\"\n\n"
            f"Style requirements:\n"
            f"- Align your motivation directly to their specific style/favorite genre requested in their profile.\n"
            f"- Address their listed goals or current vibe explicitly.\n"
            f"- Be extremely passionate, inspiring, and authentic. Use formatting (bolding, exclamation marks) cleanly.\n"
            f"- Keep the message safe, clean, and under 500 characters."
        )
        
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        cheer_text = response.text
        
        await temp_msg.edit_text(f"🔥 **Hey @{username}! Here is your personalized boost:**\n\n{cheer_text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error compiling cheer: {e}")
        await temp_msg.edit_text(f"❌ AI Error: Could not compile cheer at this moment. ({e})")
