import datetime
import logging
import json
import re
import asyncio
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from core import WIB, GEMINI_API_KEY, is_bot_admin, is_super, delete_cmd

logger = logging.getLogger(__name__)


def escape_html(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


THEME_MAP = {
    "0": "Random", "1": "Movies & TV Shows", "2": "Gaming", "3": "Sports & Esports",
    "4": "Music", "5": "Geography", "6": "General Knowledge", "7": "History",
    "8": "Science & Technology", "9": "Food & Drink", "10": "Anime / Manga & Comics"
}


# ─────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────

async def ensure_trivia_database(pool):
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS trivia_scores (
                username VARCHAR(100) PRIMARY KEY,
                monthly_kp INT DEFAULT 0,
                all_time_kp INT DEFAULT 0
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS active_trivia (
                chat_id BIGINT PRIMARY KEY,
                message_id BIGINT,
                question TEXT,
                options TEXT,
                correct_index INT,
                explanation TEXT,
                winners TEXT DEFAULT '[]',
                answered_users TEXT DEFAULT '[]',
                is_super BOOLEAN,
                expires_at TIMESTAMP WITH TIME ZONE,
                timeout_secs INT DEFAULT 60
            )
        ''')
        await conn.execute('''
            ALTER TABLE active_trivia ADD COLUMN IF NOT EXISTS timeout_secs INT DEFAULT 60
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS trivia_config (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            )
        ''')
        defaults = {
            "trivia_theme": "Random",
            "trivia_time":  "12:00",
            "trivia_days":  "all",
            "trivia_opts":  "4",
            "trivia_reg_to": "60",
            "trivia_sup_to": "120"
        }
        for k, v in defaults.items():
            await conn.execute(
                "INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT DO NOTHING", k, v
            )


# ─────────────────────────────────────────
# TRIVIA CONFIG — /triviaconfig
# ─────────────────────────────────────────

async def trivia_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    chat_id = update.effective_chat.id
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type != "private":
        try:
            await context.bot.send_message(
                chat_id,
                "🔒 Please run `/triviaconfig` in my Direct Messages for security.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    async with pool.acquire() as conn:
        theme   = await conn.fetchval("SELECT value FROM config WHERE key='trivia_theme'") or 'Random'
        t_time  = await conn.fetchval("SELECT value FROM config WHERE key='trivia_time'")  or '12:00'
        days    = await conn.fetchval("SELECT value FROM config WHERE key='trivia_days'")  or 'all'
        opts    = await conn.fetchval("SELECT value FROM config WHERE key='trivia_opts'")  or '4'
        reg_to  = await conn.fetchval("SELECT value FROM config WHERE key='trivia_reg_to'") or '60'
        sup_to  = await conn.fetchval("SELECT value FROM config WHERE key='trivia_sup_to'") or '120'
        tgt_raw = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''

    context.user_data['tcfg_owner'] = update.effective_user.id
    context.user_data['tcfg_draft'] = {
        'theme': theme, 'run_time': t_time, 'days': days,
        'opts': opts, 'reg_to': reg_to, 'sup_to': sup_to,
        'target': tgt_raw
    }
    
    for flag in ['awaiting_tcfg_theme', 'awaiting_tcfg_time',
                 'awaiting_tcfg_reg_to', 'awaiting_tcfg_sup_to', 'awaiting_tcfg_target']:
        context.user_data.pop(flag, None)

    msg = await context.bot.send_message(
        chat_id,
        _tcfg_text(context.user_data['tcfg_draft']),
        reply_markup=_tcfg_kb(),
        parse_mode="Markdown"
    )
    context.user_data['tcfg_msg_id'] = msg.message_id


def _tcfg_text(d):
    tgt_label = f"`{d['target']}`" if d['target'] else "`Not Set`"
    return (
        "🎛️ *NUKHBA TRIVIA MASTER CONFIG*\n"
        "──────────────────────────────\n"
        f"📡 Target Chat: {tgt_label}\n"
        f"🧠 Topic Theme: `{d['theme']}`\n"
        f"⏱️ Daily Release: `{d['run_time']} WIB`\n"
        f"📅 Weekly Pattern: `{d['days']}`\n"
        f"🎯 Choice Layout: `{d['opts']} Options`\n"
        f"⏳ Regular Timeout: `{d['reg_to']}s`\n"
        f"🔥 Super Timeout: `{d['sup_to']}s`\n\n"
        "⚠️ _Nothing saves until you press ✅ Finish / Save_"
    )


def _tcfg_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Set Target Chat", callback_data="tcfg_target")],
        [InlineKeyboardButton("🧠 Topic Theme",     callback_data="tcfg_seltheme")],
        [
            InlineKeyboardButton("⏱️ −1h", callback_data="tcfg_tsub"),
            InlineKeyboardButton("⏱️ +1h", callback_data="tcfg_tadd"),
            InlineKeyboardButton("✏️ Custom Time", callback_data="tcfg_tcus"),
        ],
        [InlineKeyboardButton("📅 Toggle Days (all → weekday → weekend)", callback_data="tcfg_days")],
        [InlineKeyboardButton("🎯 Options Layout: 4 → 5 → 6", callback_data="tcfg_opts")],
        [
            InlineKeyboardButton("⏳ Reg Timeout",   callback_data="tcfg_reg_to"),
            InlineKeyboardButton("🔥 Super Timeout", callback_data="tcfg_sup_to"),
        ],
        [
            InlineKeyboardButton("✅ Finish / Save", callback_data="tcfg_save"),
            InlineKeyboardButton("❌ Cancel",        callback_data="tcfg_cancel"),
        ]
    ])


async def _tcfg_refresh(query, context):
    d = context.user_data.get('tcfg_draft')
    if not d:
        return
    try:
        await query.edit_message_text(
            _tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"tcfg refresh error: {e}")


async def _tcfg_refresh_from_input(update, context, d):
    chat_id = update.effective_chat.id
    msg_id  = context.user_data.get('tcfg_msg_id')
    try:
        if msg_id:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=_tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
            )
        else:
            msg = await context.bot.send_message(
                chat_id, _tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
            )
            context.user_data['tcfg_msg_id'] = msg.message_id
    except Exception as e:
        logger.warning(f"tcfg input refresh error: {e}")


# ─────────────────────────────────────────
# MASTER CALLBACK ROUTER
# ─────────────────────────────────────────

async def trivia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    pool = context.bot_data.get('db_pool')
    data = q.data

    if data.startswith("tcfg_"):
        if not await is_bot_admin(q.from_user.username, pool):
            return await q.answer("❌ Admins only.", show_alert=True)
        owner = context.user_data.get('tcfg_owner')
        if owner and q.from_user.id != owner:
            return await q.answer("❌ This config belongs to another admin.", show_alert=True)

        d   = context.user_data.get('tcfg_draft')
        act = data[5:]

        if act == "cancel":
            context.user_data.pop('tcfg_draft', None)
            context.user_data.pop('tcfg_owner', None)
            await q.answer("Cancelled.")
            try:
                await q.edit_message_text("❌ *Trivia config cancelled. No changes saved.*", parse_mode="Markdown")
            except Exception:
                pass
            return

        if not d:
            return await q.answer("⚠️ Session expired. Run /triviaconfig again.", show_alert=True)

        if act == "seltheme":
            await q.answer()
            buttons = [[InlineKeyboardButton(v, callback_data=f"tcfg_thm_{k}")] for k, v in THEME_MAP.items()]
            buttons.append([InlineKeyboardButton("✏️ Custom Input", callback_data="tcfg_thm_custom")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="tcfg_back")])
            try:
                await q.edit_message_text(
                    "🧠 *Select a Trivia Theme:*",
                    reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        if act.startswith("thm_"):
            val = act[4:]
            if val == "custom":
                context.user_data['awaiting_tcfg_theme'] = True
                await q.answer()
                try:
                    await q.edit_message_text(
                        "✏️ *Type your custom theme* (e.g. `Indonesian History`):\n\n_Send your reply here._",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                d['theme'] = THEME_MAP.get(val, "Random")
                await q.answer(f"Theme → {d['theme']}")
                await _tcfg_refresh(q, context)
            return

        if act == "target":
            context.user_data['awaiting_tcfg_target'] = True
            await q.answer()
            try:
                await q.edit_message_text(
                    "📡 *Set Target Chat*\n\n"
                    "Option 1: Forward any message from the target group here.\n"
                    "Option 2: Type the chat ID directly (e.g. `-1001234567890`).\n\n"
                    "_Supergroups always start with_ `-100`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        if act == "tadd":
            h, m = map(int, d['run_time'].split(":"))
            d['run_time'] = f"{(h + 1) % 24:02d}:{m:02d}"
            await q.answer(f"Time → {d['run_time']}")
            await _tcfg_refresh(q, context)
            return

        if act == "tsub":
            h, m = map(int, d['run_time'].split(":"))
            d['run_time'] = f"{(h - 1) % 24:02d}:{m:02d}"
            await q.answer(f"Time → {d['run_time']}")
            await _tcfg_refresh(q, context)
            return

        if act == "tcus":
            context.user_data['awaiting_tcfg_time'] = True
            await q.answer()
            try:
                await q.edit_message_text(
                    "⏱️ *Type the exact release time* in `HH:MM` (24-hour WIB):\n\nExample: `09:30`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        if act == "days":
            cycle = {"all": "weekday", "weekday": "weekend", "weekend": "all"}
            d['days'] = cycle.get(d['days'], "all")
            await q.answer(f"Pattern → {d['days']}")
            await _tcfg_refresh(q, context)
            return

        if act == "opts":
            curr = int(d['opts'])
            d['opts'] = str(4 if curr >= 6 else curr + 1)
            await q.answer(f"Options → {d['opts']}")
            await _tcfg_refresh(q, context)
            return

        if act == "reg_to":
            context.user_data['awaiting_tcfg_reg_to'] = True
            await q.answer()
            try:
                await q.edit_message_text(
                    "⏳ *Type Regular Trivia timeout in seconds:*\n\nExample: `60` or `90`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        if act == "sup_to":
            context.user_data['awaiting_tcfg_sup_to'] = True
            await q.answer()
            try:
                await q.edit_message_text(
                    "🔥 *Type Super Trivia timeout in seconds:*\n\nExample: `120` or `150`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        if act == "back":
            await q.answer()
            await _tcfg_refresh(q, context)
            return

        if act == "save":
            async with pool.acquire() as conn:
                for key, val in [
                    ('trivia_theme',  d['theme']),
                    ('trivia_time',   d['run_time']),
                    ('trivia_days',   d['days']),
                    ('trivia_opts',   d['opts']),
                    ('trivia_reg_to', d['reg_to']),
                    ('trivia_sup_to', d['sup_to']),
                ]:
                    await conn.execute(
                        "INSERT INTO config (key, value) VALUES ($1, $2) "
                        "ON CONFLICT (key) DO UPDATE SET value=$2",
                        key, val
                    )
                if d.get('target'):
                    await conn.execute(
                        "INSERT INTO trivia_config (key, value) VALUES ('target_chat_id', $1) "
                        "ON CONFLICT (key) DO UPDATE SET value=$1",
                        str(d['target'])
                    )
            context.user_data.pop('tcfg_draft', None)
            context.user_data.pop('tcfg_owner', None)
            context.user_data.pop('tcfg_msg_id', None)
            await q.answer("✅ Saved!")
            try:
                await q.edit_message_text(
                    "✅ *Trivia Config Saved!*\n\n"
                    f"🧠 Theme: `{d['theme']}`\n"
                    f"⏱️ Time: `{d['run_time']} WIB`\n"
                    f"📅 Days: `{d['days']}`\n"
                    f"🎯 Options: `{d['opts']}`\n"
                    f"⏳ Reg Timeout: `{d['reg_to']}s`\n"
                    f"🔥 Super Timeout: `{d['sup_to']}s`\n"
                    f"📡 Target: `{d['target'] or 'Not Set'}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        await q.answer()
        return

    if data.startswith("tcancel_"):
        if not await is_bot_admin(q.from_user.username, pool):
            return await q.answer("❌ Admins only.", show_alert=True)
        act     = data[8:]
        chat_id = update.effective_chat.id

        async with pool.acquire() as conn:
            room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)

        if act == "confirm":
            if room:
                async with pool.acquire() as conn:
                    await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
            await q.answer("Trivia cancelled.")
            try:
                await q.edit_message_text(
                    "❌ *Trivia Round Cancelled by Admin.*\nNo Knowledge Points awarded.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        if act == "retry":
            if room:
                async with pool.acquire() as conn:
                    await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
                await q.answer("Restarting trivia…")
                try:
                    await q.edit_message_text("🔄 *Restarting trivia round…*", parse_mode="Markdown")
                except Exception:
                    pass
                await deploy_trivia(context.bot, chat_id, room['is_super'], pool)
            else:
                await q.answer("No active trivia found.", show_alert=True)
            return

        await q.answer()
        return

    if data.startswith("trivans_"):
        try:
            user_choice = int(data.split("_")[1])
        except (IndexError, ValueError):
            return await q.answer("❌ Invalid answer data.", show_alert=True)

        username = q.from_user.username or str(q.from_user.id)
        chat_id  = update.effective_chat.id

        async with pool.acquire() as conn:
            room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)

        if not room:
            return await q.answer("⏱️ This round is already closed!", show_alert=True)

        answered = json.loads(room['answered_users'])
        if username in answered:
            return await q.answer("🔒 You already answered! No second chances.", show_alert=True)

        is_correct = (user_choice == room['correct_index'])
        winners = json.loads(room['winners'])
        
        if is_correct:
            pts_scale = [60, 45, 30] if room['is_super'] else [40, 25, 10]
            pts = pts_scale[len(winners)] if len(winners) < 3 else 0
            if pts > 0:
                await q.answer(f"✅ Correct! +{pts} Knowledge Points! 🧠", show_alert=True)
            else:
                await q.answer("✅ Correct! Top 3 already taken — no KP this round.", show_alert=True)
        else:
            if room['is_super']:
                await q.answer("❌ Wrong! −5 Knowledge Points penalty.", show_alert=True)
            else:
                await q.answer("❌ Wrong! Answer locked. Better luck next time!", show_alert=True)

        answered.append(username)
        should_close = False

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_trivia SET answered_users=$1 WHERE chat_id=$2",
                json.dumps(answered), chat_id
            )
            if is_correct:
                pts_scale = [60, 45, 30] if room['is_super'] else [40, 25, 10]
                pts = pts_scale[len(winners)] if len(winners) < 3 else 0
                if pts > 0:
                    winners.append({'username': username, 'pts': pts})
                    await conn.execute(
                        "UPDATE active_trivia SET winners=$1 WHERE chat_id=$2",
                        json.dumps(winners), chat_id
                    )
                    await conn.execute(
                        "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) "
                        "ON CONFLICT (username) DO UPDATE SET "
                        "monthly_kp = trivia_scores.monthly_kp + $2, "
                        "all_time_kp = trivia_scores.all_time_kp + $2",
                        username, pts
                    )
            elif room['is_super']:
                await conn.execute(
                    "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, 0, 0) "
                    "ON CONFLICT (username) DO UPDATE SET "
                    "monthly_kp = GREATEST(0, trivia_scores.monthly_kp - 5), "
                    "all_time_kp = GREATEST(0, trivia_scores.all_time_kp - 5)",
                    username
                )
            fresh = await conn.fetchrow("SELECT winners FROM active_trivia WHERE chat_id=$1", chat_id)
            if fresh:
                should_close = len(json.loads(fresh['winners'])) >= 3

        if should_close:
            await close_trivia_round(context.bot, chat_id, "🏆 Top 3 Winners Reached!", pool)
        return


# ─────────────────────────────────────────
# TEXT INPUT HANDLER
# ─────────────────────────────────────────

async def handle_trivia_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    owner   = context.user_data.get('tcfg_owner')
    chat_id = update.effective_chat.id

    if owner and user_id != owner:
        return False

    d = context.user_data.get('tcfg_draft')
    if not d:
        return False

    if context.user_data.get('awaiting_tcfg_target'):
        context.user_data.pop('awaiting_tcfg_target')
        chat_id_str = None

        if update.message:
            fo = update.message.forward_origin
            if fo:
                if hasattr(fo, 'chat') and fo.chat:
                    chat_id_str = str(fo.chat.id)
                elif hasattr(fo, 'sender_chat') and fo.sender_chat:
                    chat_id_str = str(fo.sender_chat.id)

            if not chat_id_str and getattr(update.message, 'forward_from_chat', None):
                chat_id_str = str(update.message.forward_from_chat.id)

            if not chat_id_str and update.message.text:
                raw = update.message.text.strip()
                try:
                    int(raw)
                    chat_id_str = raw
                except ValueError:
                    pass

        if chat_id_str:
            d['target'] = chat_id_str
            try:
                await update.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id,
                f"✅ Target chat set to: `{chat_id_str}`",
                parse_mode="Markdown"
            )
            await _tcfg_refresh_from_input(update, context, d)
        else:
            await context.bot.send_message(
                chat_id,
                "❌ Could not read a chat ID.\n\n"
                "Forward a message from the target group, "
                "or type the numeric chat ID (e.g. `-1001234567890`)."
            )
            context.user_data['awaiting_tcfg_target'] = True
        return True

    text = update.message.text.strip() if update.message and update.message.text else ""
    if not text:
        return False

    if context.user_data.get('awaiting_tcfg_theme'):
        context.user_data.pop('awaiting_tcfg_theme')
        d['theme'] = text
        try:
            await update.message.delete()
        except Exception:
            pass
        await _tcfg_refresh_from_input(update, context, d)
        return True

    if context.user_data.get('awaiting_tcfg_time'):
        if re.match(r'^\d{1,2}:\d{2}$', text):
            h, m = map(int, text.split(":"))
            if 0 <= h <= 23 and 0 <= m <= 59:
                context.user_data.pop('awaiting_tcfg_time')
                d['run_time'] = f"{h:02d}:{m:02d}"
                try:
                    await update.message.delete()
                except Exception:
                    pass
                await _tcfg_refresh_from_input(update, context, d)
                return True
        await context.bot.send_message(chat_id, "❌ Format must be `HH:MM` (e.g. `14:00`). Try again:", parse_mode="Markdown")
        return True

    if context.user_data.get('awaiting_tcfg_reg_to'):
        try:
            val = int(text)
            if val < 10:
                raise ValueError
            context.user_data.pop('awaiting_tcfg_reg_to')
            d['reg_to'] = str(val)
            try:
                await update.message.delete()
            except Exception:
                pass
            await _tcfg_refresh_from_input(update, context, d)
        except ValueError:
            await context.bot.send_message(chat_id, "❌ Must be a number ≥ 10 seconds. Try again:")
        return True

    if context.user_data.get('awaiting_tcfg_sup_to'):
        try:
            val = int(text)
            if val < 10:
                raise ValueError
            context.user_data.pop('awaiting_tcfg_sup_to')
            d['sup_to'] = str(val)
            try:
                await update.message.delete()
            except Exception:
                pass
            await _tcfg_refresh_from_input(update, context, d)
        except ValueError:
            await context.bot.send_message(chat_id, "❌ Must be a number ≥ 10 seconds. Try again:")
        return True

    return False


# ─────────────────────────────────────────
# TRIVIA DEPLOYMENT
# ─────────────────────────────────────────

def _safe_label(text, idx):
    text_str = str(text)
    prefix  = f"{chr(65 + idx)}. " if idx < 26 else f"{idx+1}. "
    max_len = 55 - len(prefix)
    label   = text_str[:max_len] + "…" if len(text_str) > max_len else text_str
    return prefix + label


async def deploy_trivia(bot, chat_id: int, is_super_round: bool, pool):
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT value FROM config WHERE key='status'") or 'active'
        if status != 'active':
            return

        theme   = await conn.fetchval("SELECT value FROM config WHERE key='trivia_theme'") or 'Random'
        opts    = int(await conn.fetchval("SELECT value FROM config WHERE key='trivia_opts'") or '4')
        to_key  = 'trivia_sup_to' if is_super_round else 'trivia_reg_to'
        timeout = int(await conn.fetchval(f"SELECT value FROM config WHERE key='{to_key}'") or '60')

        existing = await conn.fetchval("SELECT chat_id FROM active_trivia WHERE chat_id=$1", chat_id)
        if existing:
            return

    num_options = 6 if is_super_round else opts

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        f"Generate 1 multiple choice trivia question. Theme: {theme}. "
        f"Provide exactly {num_options} answer options. "
        f"IMPORTANT: Return ONLY a raw JSON object with NO markdown formatting, "
        f"NO code blocks, NO backticks. Just the JSON: "
        f'{"{"}"question":"...","options":["..."],"correct_index":0,"explanation":"..."{"}"}'
    )

    try:
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-2.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        raw = resp.text.strip()
        raw = re.sub(r'^
