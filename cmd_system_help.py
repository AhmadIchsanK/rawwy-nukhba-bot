from commands_manifest import COMMANDS
from telegram import Update
from telegram.ext import ContextTypes
from core import delete_cmd


async def send_md_chunks(bot, chat_id, text):
    limit = 3800
    chunks = []
    current_chunk = ""
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > limit:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk)

    for chunk in chunks:
        if chunk.strip():
            try:
                await bot.send_message(chat_id, chunk, parse_mode="Markdown")
            except Exception:
                await bot.send_message(chat_id, chunk)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)

    public = [c for c in COMMANDS if c.get('public')]
    admin  = [c for c in COMMANDS if c.get('admin') and not c.get('super')]
    superc = [c for c in COMMANDS if c.get('super')]

    text  = "📖 **[RW] Nukhba Manager Manual**\n\n"
    text += "*(If your `/` menu looks outdated, log out of Telegram and back in, or clear the app cache — Telegram caches command lists locally!)*\n\n"

    # ── USER COMMANDS ──────────────────────────────────────────────────────
    text += "🟢 **USER COMMANDS**\n"
    current_cat = ""
    experimental_banner_shown = False

    for c in public:
        cat = c.get('category', '')
        if cat != current_cat:
            current_cat = cat
            text += f"\n*{current_cat}*\n"
            # Show the experimental disclaimer once, right under the AI category header
            if c.get('experimental') and not experimental_banner_shown:
                text += "⚠️ _(This is an experimental feature, don't abuse it yet)_\n"
                experimental_banner_shown = True
        text += f"{c.get('emoji', '🔹')} `/{c['name']}` — {c['desc']}\n"
        if 'format' in c:
            text += f"   └ Format: {c['format']}\n"

    # ── ADMIN SUITE ────────────────────────────────────────────────────────
    if admin:
        text += "\n🔐 **ADMINISTRATOR SUITE**\n"
        current_cat = ""
        for c in admin:
            cat = c.get('category', '')
            if cat != current_cat:
                current_cat = cat
                text += f"\n*{current_cat}*\n"
            text += f"{c.get('emoji', '🔹')} `/{c['name']}` — {c['desc']}\n"
            if 'format' in c:
                text += f"   └ Format: {c['format']}\n"

    # ── SUPER OWNER ────────────────────────────────────────────────────────
    if superc:
        text += "\n👑 **SUPER OWNER EXCLUSIVES**\n"
        for c in superc:
            text += f"{c.get('emoji', '🔹')} `/{c['name']}` — {c['desc']}\n"
            if 'format' in c:
                text += f"   └ Format: {c['format']}\n"

    try:
        await send_md_chunks(context.bot, update.effective_user.id, text)
        if update.effective_chat.type != "private":
            await update.message.reply_text("✅ I have sent the full manual to your DMs!")
    except Exception:
        if update.effective_chat.type != "private":
            await update.message.reply_text("❌ I cannot DM you yet. Please start a private chat with me first!")
