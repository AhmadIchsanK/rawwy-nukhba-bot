from commands_manifest import COMMANDS
from telegram import Update
from telegram.ext import ContextTypes
from core import delete_cmd

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    # Build help text grouped by public/admin/super
    public = [c for c in COMMANDS if c.get('public')]
    admin = [c for c in COMMANDS if c.get('admin')]
    superc = [c for c in COMMANDS if c.get('super')]

    text = "📖 **Nukhba Bot Manual**\n\n"
    text += "**General**\n"
    for c in public:
        text += f"• /{c['name']} — {c['desc']}\n"
    if admin:
        text += "\n**Admin**\n"
        for c in admin:
            text += f"• /{c['name']} — {c['desc']}\n"
    if superc:
        text += "\n**Super Owner**\n"
        for c in superc:
            text += f"• /{c['name']} — {c['desc']}\n"
    await context.bot.send_message(update.effective_user.id, text, parse_mode="Markdown")
