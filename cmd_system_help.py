from commands_manifest import COMMANDS
from telegram import Update
from telegram.ext import ContextTypes
from core import delete_cmd

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    
    public = [c for c in COMMANDS if c.get('public')]
    admin = [c for c in COMMANDS if c.get('admin')]
    superc = [c for c in COMMANDS if c.get('super')]

    text = "📖 **[RW] Nukhba Manager Manual**\n\n"
    text += "*(If your / menu looks outdated, try logging out of Telegram or clearing your app cache — Telegram caches command lists locally!)*\n\n"
    
    text += "🟢 **USER COMMANDS**\n"
    current_cat = ""
    for c in public:
        if c.get('category') != current_cat:
            current_cat = c.get('category')
            text += f"\n*{current_cat}*\n"
        text += f"{c.get('emoji', '🔹')} `/{c['name']}` — {c['desc']}\n"
        if 'format' in c:
            text += f"   └ Format: {c['format']}\n"
            
    if admin:
        text += "\n🔐 **ADMINISTRATOR SUITE**\n"
        current_cat = ""
        for c in admin:
            if c.get('category') != current_cat:
                current_cat = c.get('category')
                text += f"\n*{current_cat}*\n"
            text += f"{c.get('emoji', '🔹')} `/{c['name']}` — {c['desc']}\n"
            if 'format' in c:
                text += f"   └ Format: {c['format']}\n"
                
    if superc:
        text += "\n👑 **SUPER OWNER EXCLUSIVES**\n"
        for c in superc:
            text += f"{c.get('emoji', '🔹')} `/{c['name']}` — {c['desc']}\n"
            if 'format' in c:
                text += f"   └ Format: {c['format']}\n"
                
    try:
        await context.bot.send_message(update.effective_user.id, text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await update.message.reply_text("✅ I have securely sent the structured manual to your Direct Messages!")
    except Exception:
        if update.effective_chat.type != "private":
            await update.message.reply_text("❌ I cannot send you a DM yet. Please start a private chat with me first!")
