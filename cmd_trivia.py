import datetime
import logging
import json
import asyncio
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from core import WIB, GEMINI_API_KEY, is_bot_admin, is_super, delete_cmd

logger = logging.getLogger(__name__)

THEME_MAP = {
    "0": "Random", "1": "Movies & TV Shows", "2": "Gaming", "3": "Sports & Esports",
    "4": "Music", "5": "Geography", "6": "General Knowledge", "7": "History",
    "8": "Science & Technology", "9": "Food & Drink", "10": "Anime / Manga & Comics"
}

# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

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
                expires_at TIMESTAMP WITH TIME ZONE
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS trivia_config (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            )
        ''')
        defaults = {
            "trivia_theme": "Random",
            "trivia_time": "12:00",
            "trivia_days": "all",
            "trivia_opts": "4",
            "trivia_reg_to": "60",
            "trivia_sup_to": "120"
        }
        for k, v in defaults.items():
            await conn.execute(
                "INSERT INTO config (key, value) VALUES ($1, $2) ON CONFLICT DO NOTHING", k, v
            )


# ─────────────────────────────────────────────
# TRIVIA CONFIG — /triviaconfig
# ─────────────────────────────────────────────

async def trivia_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return
    if update.effective_chat.type != "private":
        try:
            await update.message.reply_text(
                "🔒 For security, please run `/triviaconfig` in my Direct Messages.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    async with pool.acquire() as conn:
        theme    = await conn.fetchval("SELECT value FROM config WHERE key='trivia_theme'") or 'Random'
        t_time   = await conn.fetchval("SELECT value FROM config WHERE key='trivia_time'")  or '12:00'
        days     = await conn.fetchval("SELECT value FROM config WHERE key='trivia_days'")  or 'all'
        opts     = await conn.fetchval("SELECT value FROM config WHERE key='trivia_opts'")  or '4'
        reg_to   = await conn.fetchval("SELECT value FROM config WHERE key='trivia_reg_to'") or '60'
        sup_to   = await conn.fetchval("SELECT value FROM config WHERE key='trivia_sup_to'") or '120'
        tgt_raw  = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''

    # Store who triggered this — only they can interact
    context.user_data['tcfg_owner'] = update.effective_user.id
    context.user_data['tcfg_draft'] = {
        'theme': theme, 'run_time': t_time, 'days': days,
        'opts': opts, 'reg_to': reg_to, 'sup_to': sup_to,
        'target': tgt_raw
    }
    # Clear any pending input flags
    context.user_data.pop('awaiting_tcfg_theme', None)
    context.user_data.pop('awaiting_tcfg_time', None)
    context.user_data.pop('awaiting_tcfg_reg_to', None)
    context.user_data.pop('awaiting_tcfg_sup_to', None)

    msg = await update.message.reply_text(
        _tcfg_text(context.user_data['tcfg_draft']),
        reply_markup=_tcfg_kb(),
        parse_mode="Markdown"
    )
    context.user_data['tcfg_msg_id'] = msg.message_id


def _tcfg_text(d):
    tgt_label = f"`{d['target']}`" if d['target'] else "`Not Set`"
    return (
        "🎛️ **NUKHBA TRIVIA MASTER CONFIG**\n"
        "──────────────────────────────\n"
        f"📡 Target Chat: {tgt_label}\n"
        f"🧠 Topic Theme: `{d['theme']}`\n"
        f"⏱️ Daily Release: `{d['run_time']} WIB`\n"
        f"📅 Weekly Pattern: `{d['days']}`\n"
        f"🎯 Choice Layout: `{d['opts']} Options`\n"
        f"⏳ Regular Timeout: `{d['reg_to']}s`\n"
        f"🔥 Super Timeout: `{d['sup_to']}s`\n\n"
        "⚠️ *Nothing saves until you press ✅ Finish / Save*"
    )


def _tcfg_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Set Target Chat", callback_data="tcfg_target")],
        [InlineKeyboardButton("🧠 Topic Theme", callback_data="tcfg_seltheme")],
        [
            InlineKeyboardButton("⏱️ −1h", callback_data="tcfg_tsub"),
            InlineKeyboardButton("⏱️ +1h", callback_data="tcfg_tadd"),
            InlineKeyboardButton("✏️ Custom Time", callback_data="tcfg_tcus"),
        ],
        [InlineKeyboardButton("📅 Toggle Days (all/weekday/weekend)", callback_data="tcfg_days")],
        [
            InlineKeyboardButton("🎯 Options: 4/5/6", callback_data="tcfg_opts"),
        ],
        [
            InlineKeyboardButton("⏳ Reg Timeout", callback_data="tcfg_reg_to"),
            InlineKeyboardButton("🔥 Super Timeout", callback_data="tcfg_sup_to"),
        ],
        [
            InlineKeyboardButton("✅ Finish / Save", callback_data="tcfg_save"),
            InlineKeyboardButton("❌ Cancel", callback_data="tcfg_cancel"),
        ]
    ])


async def _tcfg_refresh(query, context):
    """Edit the existing config message with updated state."""
    d = context.user_data.get('tcfg_draft')
    if not d:
        return
    try:
        await query.edit_message_text(
            _tcfg_text(d),
            reply_markup=_tcfg_kb(),
            parse_mode="Markdown"
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"tcfg refresh edit error: {e}")


# ─────────────────────────────────────────────
# MASTER CALLBACK ROUTER
# ─────────────────────────────────────────────

async def trivia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    pool = context.bot_data.get('db_pool')
    data = q.data

    # ── TRIVIA CONFIG callbacks (tcfg_) ──────────────────────────────
    if data.startswith("tcfg_"):
        # Verify admin
        if not await is_bot_admin(q.from_user.username, pool):
            return await q.answer("❌ Admins only.", show_alert=True)
        # Verify it's the same user who opened the config
        owner = context.user_data.get('tcfg_owner')
        if owner and q.from_user.id != owner:
            return await q.answer("❌ This config was opened by another admin.", show_alert=True)

        d = context.user_data.get('tcfg_draft')
        act = data[5:]  # strip "tcfg_"

        # ── CANCEL ──
        if act == "cancel":
            context.user_data.pop('tcfg_draft', None)
            context.user_data.pop('tcfg_owner', None)
            await q.answer("Cancelled.")
            try:
                await q.edit_message_text("❌ **Trivia config cancelled. No changes saved.**", parse_mode="Markdown")
            except Exception:
                pass
            return

        if not d:
            return await q.answer("⚠️ Session expired. Run /triviaconfig again.", show_alert=True)

        # ── THEME SELECTION MENU ──
        if act == "seltheme":
            await q.answer()
            buttons = [
                [InlineKeyboardButton(v, callback_data=f"tcfg_thm_{k}")]
                for k, v in THEME_MAP.items()
            ]
            buttons.append([InlineKeyboardButton("✏️ Custom Input", callback_data="tcfg_thm_custom")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="tcfg_back")])
            try:
                await q.edit_message_text(
                    "🧠 **Select a Trivia Theme:**",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        # ── THEME VALUE SET ──
        if act.startswith("thm_"):
            val = act[4:]  # strip "thm_"
            if val == "custom":
                await q.answer()
                context.user_data['awaiting_tcfg_theme'] = True
                try:
                    await q.edit_message_text(
                        "✏️ **Type your custom theme now** (e.g. `Indonesian History`):\n\n"
                        "_Send your reply in this chat._",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                return
            else:
                d['theme'] = THEME_MAP.get(val, "Random")
                await q.answer(f"Theme set to {d['theme']}")
                return await _tcfg_refresh(q, context)

        # ── TARGET CHAT ──
        if act == "target":
            await q.answer()
            context.user_data['awaiting_tcfg_target'] = True
            try:
                await q.edit_message_text(
                    "📡 **Set Target Chat ID**\n\n"
                    "Forward any message from the target group to me, "
                    "or type the chat ID manually (e.g. `-1001234567890`):",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        # ── TIME BUTTONS ──
        if act == "tadd":
            h, m = map(int, d['run_time'].split(":"))
            d['run_time'] = f"{(h + 1) % 24:02d}:{m:02d}"
            await q.answer(f"Time → {d['run_time']}")
            return await _tcfg_refresh(q, context)

        if act == "tsub":
            h, m = map(int, d['run_time'].split(":"))
            d['run_time'] = f"{(h - 1) % 24:02d}:{m:02d}"
            await q.answer(f"Time → {d['run_time']}")
            return await _tcfg_refresh(q, context)

        if act == "tcus":
            await q.answer()
            context.user_data['awaiting_tcfg_time'] = True
            try:
                await q.edit_message_text(
                    "⏱️ **Type the exact release time** in `HH:MM` (24-hour WIB):\n\n"
                    "Example: `09:30`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        # ── DAYS TOGGLE ──
        if act == "days":
            cycle = {"all": "weekday", "weekday": "weekend", "weekend": "all"}
            d['days'] = cycle.get(d['days'], "all")
            await q.answer(f"Pattern → {d['days']}")
            return await _tcfg_refresh(q, context)

        # ── OPTIONS COUNT ──
        if act == "opts":
            curr = int(d['opts'])
            d['opts'] = str(4 if curr >= 6 else curr + 1)
            await q.answer(f"Options → {d['opts']}")
            return await _tcfg_refresh(q, context)

        # ── REGULAR TIMEOUT ──
        if act == "reg_to":
            await q.answer()
            context.user_data['awaiting_tcfg_reg_to'] = True
            try:
                await q.edit_message_text(
                    "⏳ **Type Regular Trivia timeout in seconds:**\n\n"
                    "Example: `60` or `90`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        # ── SUPER TIMEOUT ──
        if act == "sup_to":
            await q.answer()
            context.user_data['awaiting_tcfg_sup_to'] = True
            try:
                await q.edit_message_text(
                    "🔥 **Type Super Trivia timeout in seconds:**\n\n"
                    "Example: `120` or `150`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        # ── BACK ──
        if act == "back":
            await q.answer()
            return await _tcfg_refresh(q, context)

        # ── SAVE ──
        if act == "save":
            async with pool.acquire() as conn:
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_theme'", d['theme'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_time'",  d['run_time'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_days'",  d['days'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_opts'",  d['opts'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_reg_to'", d['reg_to'])
                await conn.execute("UPDATE config SET value=$1 WHERE key='trivia_sup_to'", d['sup_to'])
                if d.get('target'):
                    await conn.execute(
                        "INSERT INTO trivia_config (key, value) VALUES ('target_chat_id', $1) "
                        "ON CONFLICT (key) DO UPDATE SET value=$1",
                        str(d['target'])
                    )
            context.user_data.pop('tcfg_draft', None)
            context.user_data.pop('tcfg_owner', None)
            await q.answer("✅ Saved!")
            try:
                await q.edit_message_text(
                    "✅ **Trivia Config Saved & Applied!**\n\n"
                    f"🧠 Theme: `{d['theme']}`\n"
                    f"⏱️ Time: `{d['run_time']} WIB`\n"
                    f"📅 Days: `{d['days']}`\n"
                    f"🎯 Options: `{d['opts']}`\n"
                    f"⏳ Reg Timeout: `{d['reg_to']}s`\n"
                    f"🔥 Super Timeout: `{d['sup_to']}s`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return

        await q.answer()
        return

    # ── CANCEL TRIVIA callbacks (tcancel_) ────────────────────────────
    if data.startswith("tcancel_"):
        if not await is_bot_admin(q.from_user.username, pool):
            return await q.answer("❌ Admins only.", show_alert=True)
        act = data[8:]  # strip "tcancel_"
        chat_id = update.effective_chat.id

        async with pool.acquire() as conn:
            room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
            if act == "confirm":
                if room:
                    await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
                await q.answer("Trivia cancelled.")
                try:
                    await q.message.delete()
                except Exception:
                    pass
                try:
                    await q.message.reply_text(
                        "❌ **Trivia Round Cancelled by Admin.**\n"
                        "No Knowledge Points awarded.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                return

            elif act == "retry":
                if room:
                    await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
                    await q.answer("Restarting trivia…")
                    try:
                        await q.message.delete()
                    except Exception:
                        pass
                    await deploy_trivia(q.message.bot, chat_id, room['is_super'], pool)
                else:
                    await q.answer("No active trivia found.", show_alert=True)
                return

        await q.answer()
        return

    # ── ANSWER callbacks (trivans_) ────────────────────────────────────
    if data.startswith("trivans_"):
        user_choice = int(data.split("_")[1])
        username    = q.from_user.username or str(q.from_user.id)
        chat_id     = update.effective_chat.id

        async with pool.acquire() as conn:
            room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
            if not room:
                return await q.answer("⏱️ This round is already closed!", show_alert=True)

            answered = json.loads(room['answered_users'])
            winners  = json.loads(room['winners'])

            # Already answered
            if username in answered:
                return await q.answer(
                    "🔒 You already locked in your answer. No second chances!",
                    show_alert=True
                )

            # Record this user as answered
            answered.append(username)
            await conn.execute(
                "UPDATE active_trivia SET answered_users=$1 WHERE chat_id=$2",
                json.dumps(answered), chat_id
            )

            is_correct = (user_choice == room['correct_index'])

            if is_correct:
                pts_scale = [60, 45, 30] if room['is_super'] else [40, 25, 10]
                pts = pts_scale[len(winners)] if len(winners) < 3 else 0

                if pts > 0:
                    winners.append({'username': username, 'pts': pts})
                    await conn.execute(
                        "UPDATE active_trivia SET winners=$1 WHERE chat_id=$2",
                        json.dumps(winners), chat_id
                    )
                    # Update leaderboard immediately
                    await conn.execute(
                        "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) "
                        "ON CONFLICT (username) DO UPDATE SET "
                        "monthly_kp = trivia_scores.monthly_kp + $2, "
                        "all_time_kp = trivia_scores.all_time_kp + $2",
                        username, pts
                    )
                    await q.answer(
                        f"✅ Correct! You earned {pts} Knowledge Points! 🧠",
                        show_alert=True
                    )
                else:
                    await q.answer(
                        "✅ Correct! But the top 3 spots are already taken.",
                        show_alert=True
                    )
            else:
                # Super trivia penalty
                if room['is_super']:
                    await conn.execute(
                        "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, 0, 0) "
                        "ON CONFLICT (username) DO UPDATE SET "
                        "monthly_kp = GREATEST(0, trivia_scores.monthly_kp - 5), "
                        "all_time_kp = GREATEST(0, trivia_scores.all_time_kp - 5)",
                        username
                    )
                    await q.answer("❌ Wrong! −5 Knowledge Points penalty applied.", show_alert=True)
                else:
                    await q.answer("❌ Wrong! Answer locked. Better luck next time!", show_alert=True)

            # Re-fetch winners after write to avoid race condition
            fresh_room = await conn.fetchrow("SELECT winners FROM active_trivia WHERE chat_id=$1", chat_id)

        # Check end condition outside the lock
        if fresh_room:
            fresh_winners = json.loads(fresh_room['winners'])
            if len(fresh_winners) >= 3:
                await close_trivia_round(q.message.bot, chat_id, "🏆 Top 3 Winners Reached!", pool)
        return


# ─────────────────────────────────────────────
# CUSTOM TEXT INPUT HANDLER
# Called from cmd_system.py global_tracker or message handler in main.py
# ─────────────────────────────────────────────

async def handle_trivia_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Processes any pending trivia config text input.
    Returns True if the message was consumed, False otherwise.
    Call this from the global message handler BEFORE other processing.
    """
    pool = context.bot_data.get('db_pool')
    user_id = update.effective_user.id
    owner   = context.user_data.get('tcfg_owner')

    # Only the user who opened the config can submit text
    if owner and user_id != owner:
        return False

    d = context.user_data.get('tcfg_draft')
    text = update.message.text.strip() if update.message and update.message.text else ""

    if not text or not d:
        return False

    # ── Custom Theme ──
    if context.user_data.get('awaiting_tcfg_theme'):
        context.user_data.pop('awaiting_tcfg_theme')
        d['theme'] = text
        try:
            await update.message.delete()
        except Exception:
            pass
        try:
            chat_id = update.effective_chat.id
            msg_id  = context.user_data.get('tcfg_msg_id')
            if msg_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=_tcfg_text(d),
                    reply_markup=_tcfg_kb(),
                    parse_mode="Markdown"
                )
            else:
                msg = await update.message.reply_text(
                    _tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
                )
                context.user_data['tcfg_msg_id'] = msg.message_id
        except Exception as e:
            logger.warning(f"tcfg theme refresh error: {e}")
        return True

    # ── Custom Time ──
    if context.user_data.get('awaiting_tcfg_time'):
        context.user_data.pop('awaiting_tcfg_time')
        import re
        if re.match(r'^\d{1,2}:\d{2}$', text):
            h, m = map(int, text.split(":"))
            if 0 <= h <= 23 and 0 <= m <= 59:
                d['run_time'] = f"{h:02d}:{m:02d}"
            else:
                await update.message.reply_text("❌ Invalid time. Use HH:MM (e.g. `09:30`)", parse_mode="Markdown")
                context.user_data['awaiting_tcfg_time'] = True
                return True
        else:
            await update.message.reply_text("❌ Format must be HH:MM (e.g. `14:00`)", parse_mode="Markdown")
            context.user_data['awaiting_tcfg_time'] = True
            return True
        try:
            await update.message.delete()
        except Exception:
            pass
        try:
            chat_id = update.effective_chat.id
            msg_id  = context.user_data.get('tcfg_msg_id')
            if msg_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=_tcfg_text(d),
                    reply_markup=_tcfg_kb(),
                    parse_mode="Markdown"
                )
            else:
                msg = await update.message.reply_text(
                    _tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
                )
                context.user_data['tcfg_msg_id'] = msg.message_id
        except Exception as e:
            logger.warning(f"tcfg time refresh error: {e}")
        return True

    # ── Custom Target Chat ──
    if context.user_data.get('awaiting_tcfg_target'):
        context.user_data.pop('awaiting_tcfg_target')
        # Accept forwarded message (grab chat_id) or raw typed ID
        if update.message.forward_origin or update.message.forward_from_chat:
            fwd_chat = getattr(update.message.forward_from_chat, 'id', None)
            if fwd_chat:
                d['target'] = str(fwd_chat)
            else:
                await update.message.reply_text("❌ Could not read chat ID from forwarded message.")
                context.user_data['awaiting_tcfg_target'] = True
                return True
        else:
            try:
                int(text)  # validate it's a number
                d['target'] = text
            except ValueError:
                await update.message.reply_text("❌ Invalid chat ID. Must be a number like `-1001234567890`")
                context.user_data['awaiting_tcfg_target'] = True
                return True
        try:
            await update.message.delete()
        except Exception:
            pass
        try:
            chat_id = update.effective_chat.id
            msg_id  = context.user_data.get('tcfg_msg_id')
            if msg_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=_tcfg_text(d),
                    reply_markup=_tcfg_kb(),
                    parse_mode="Markdown"
                )
            else:
                msg = await update.message.reply_text(
                    _tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
                )
                context.user_data['tcfg_msg_id'] = msg.message_id
        except Exception as e:
            logger.warning(f"tcfg target refresh error: {e}")
        return True

    # ── Regular Timeout ──
    if context.user_data.get('awaiting_tcfg_reg_to'):
        context.user_data.pop('awaiting_tcfg_reg_to')
        try:
            val = int(text)
            if val < 10:
                raise ValueError
            d['reg_to'] = str(val)
        except ValueError:
            await update.message.reply_text("❌ Must be a number ≥ 10 (seconds)")
            context.user_data['awaiting_tcfg_reg_to'] = True
            return True
        try:
            await update.message.delete()
        except Exception:
            pass
        try:
            chat_id = update.effective_chat.id
            msg_id  = context.user_data.get('tcfg_msg_id')
            if msg_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=_tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
                )
        except Exception:
            pass
        return True

    # ── Super Timeout ──
    if context.user_data.get('awaiting_tcfg_sup_to'):
        context.user_data.pop('awaiting_tcfg_sup_to')
        try:
            val = int(text)
            if val < 10:
                raise ValueError
            d['sup_to'] = str(val)
        except ValueError:
            await update.message.reply_text("❌ Must be a number ≥ 10 (seconds)")
            context.user_data['awaiting_tcfg_sup_to'] = True
            return True
        try:
            await update.message.delete()
        except Exception:
            pass
        try:
            chat_id = update.effective_chat.id
            msg_id  = context.user_data.get('tcfg_msg_id')
            if msg_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=_tcfg_text(d), reply_markup=_tcfg_kb(), parse_mode="Markdown"
                )
        except Exception:
            pass
        return True

    return False


# ─────────────────────────────────────────────
# TRIVIA DEPLOYMENT
# ─────────────────────────────────────────────

async def deploy_trivia(bot, chat_id: int, is_super_round: bool, pool):
    """Generate and send a trivia question to the target chat."""
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT value FROM config WHERE key='status'") or 'active'
        if status != 'active':
            return

        theme   = await conn.fetchval("SELECT value FROM config WHERE key='trivia_theme'") or 'Random'
        opts    = int(await conn.fetchval("SELECT value FROM config WHERE key='trivia_opts'") or '4')
        to_key  = 'trivia_sup_to' if is_super_round else 'trivia_reg_to'
        timeout = int(await conn.fetchval(f"SELECT value FROM config WHERE key='{to_key}'") or '60')

        # Check no active trivia already running
        existing = await conn.fetchval("SELECT chat_id FROM active_trivia WHERE chat_id=$1", chat_id)
        if existing:
            return  # Already running

    num_options = 6 if is_super_round else opts

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        f"Generate 1 multiple choice trivia question. Theme: {theme}. "
        f"Provide exactly {num_options} answer options. "
        f"Return ONLY valid JSON with no extra text: "
        f"{{\"question\":\"...\",\"options\":[\"...\"],\"correct_index\":0,\"explanation\":\"...\"}}"
    )

    try:
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-2.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        raw = resp.text.strip()
        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Trivia AI generation failed: {e}")
        try:
            await bot.send_message(chat_id, "⚠️ Trivia generation failed. Please try again.")
        except Exception:
            pass
        return

    expires_at = datetime.datetime.now(WIB) + datetime.timedelta(seconds=timeout)

    # Build answer keyboard — truncate long options safely
    def safe_label(text, idx):
        prefix = f"{['A','B','C','D','E','F'][idx]}. "
        max_len = 60 - len(prefix)
        label = text[:max_len] + "…" if len(text) > max_len else text
        return prefix + label

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(safe_label(opt, idx), callback_data=f"trivans_{idx}")]
        for idx, opt in enumerate(data['options'])
    ])

    title  = "🚨 **WEEKLY SUPER TRIVIA** 🚨" if is_super_round else "🧠 **DAILY TRIVIA** 🧠"
    footer = "⚡ *Super Trivia: −5 KP for wrong answers!*\n" if is_super_round else ""
    msg_text = (
        f"{title}\n\n"
        f"❓ {data['question']}\n\n"
        f"⏱️ **Time Remaining:** `{timeout}s`\n"
        f"{footer}"
        f"🔒 *Answers lock instantly. No second chances!*"
    )

    try:
        sent = await bot.send_message(chat_id, msg_text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send trivia message: {e}")
        return

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)
        await conn.execute(
            "INSERT INTO active_trivia "
            "(chat_id, message_id, question, options, correct_index, explanation, is_super, expires_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            chat_id, sent.message_id,
            data['question'], json.dumps(data['options']),
            data['correct_index'], data['explanation'],
            is_super_round, expires_at
        )


# ─────────────────────────────────────────────
# TRIVIA CLOSE / END ROUND
# ─────────────────────────────────────────────

async def close_trivia_round(bot, chat_id: int, reason: str, pool):
    """End a trivia round, post results and explanation."""
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM active_trivia WHERE chat_id=$1", chat_id)
        if not room:
            return
        await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", chat_id)

    opts    = json.loads(room['options'])
    correct = opts[room['correct_index']]
    winners = json.loads(room['winners'])

    podiums = ["🥇", "🥈", "🥉"]
    if winners:
        board = "🏆 **Top Winners:**\n" + "".join(
            f"{podiums[i]} @{w['username']} — +{w['pts']} Knowledge Points\n"
            for i, w in enumerate(winners)
        )
    else:
        board = "📭 *No one answered correctly this round.*"

    result_text = (
        f"🏁 **TRIVIA CLOSED** — {reason}\n"
        "──────────────────────────────\n"
        f"❓ *{room['question']}*\n\n"
        f"✅ **Correct Answer:** {correct}\n\n"
        f"💡 **Explanation:**\n{room['explanation']}\n\n"
        f"{board}"
    )

    # Try editing original message first; fall back to new message
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=room['message_id'],
            text=result_text,
            parse_mode="Markdown"
        )
    except BadRequest as e:
        if "Message to edit not found" in str(e) or "too old" in str(e).lower() or "can't be edited" in str(e).lower():
            try:
                await bot.send_message(chat_id, result_text, parse_mode="Markdown")
            except Exception as send_err:
                logger.error(f"Failed to send trivia result: {send_err}")
        elif "Message is not modified" not in str(e):
            logger.warning(f"close_trivia_round edit error: {e}")
    except Exception as e:
        logger.error(f"close_trivia_round unexpected error: {e}")
        try:
            await bot.send_message(chat_id, result_text, parse_mode="Markdown")
        except Exception:
            pass


# ─────────────────────────────────────────────
# CRON JOBS
# ─────────────────────────────────────────────

async def trivia_timeout_sweeper(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 3 seconds. Updates countdown timer and closes expired rounds."""
    pool = context.bot_data.get('db_pool')
    if not pool:
        return
    now = datetime.datetime.now(WIB)

    async with pool.acquire() as conn:
        rooms = await conn.fetch("SELECT * FROM active_trivia")

    for r in rooms:
        expires = r['expires_at'].astimezone(WIB)
        rem = int((expires - now).total_seconds())

        if rem <= 0:
            await close_trivia_round(context.bot, r['chat_id'], "⏱️ Time Limit Reached", pool)
            continue

        # Update the countdown on the message
        opts    = json.loads(r['options'])
        winners = json.loads(r['winners'])
        is_super_round = r['is_super']

        def safe_label(text, idx):
            prefix = f"{['A','B','C','D','E','F'][idx]}. "
            max_len = 60 - len(prefix)
            label = text[:max_len] + "…" if len(text) > max_len else text
            return prefix + label

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(safe_label(opt, idx), callback_data=f"trivans_{idx}")]
            for idx, opt in enumerate(opts)
        ])

        title  = "🚨 **WEEKLY SUPER TRIVIA** 🚨" if is_super_round else "🧠 **DAILY TRIVIA** 🧠"
        footer = "⚡ *Super Trivia: −5 KP for wrong answers!*\n" if is_super_round else ""

        # Build timer bar
        total_secs = int((expires - (now - datetime.timedelta(seconds=rem + 3))).total_seconds()) or 1
        filled = max(0, min(10, int((rem / max(total_secs, 1)) * 10)))
        timer_bar = "▓" * filled + "░" * (10 - filled)

        updated_text = (
            f"{title}\n\n"
            f"❓ {r['question']}\n\n"
            f"⏱️ **Time Remaining:** `{rem}s` [{timer_bar}]\n"
            f"✅ Correct so far: {len(winners)}/3\n"
            f"{footer}"
            f"🔒 *Answers lock instantly. No second chances!*"
        )

        try:
            await context.bot.edit_message_text(
                chat_id=r['chat_id'],
                message_id=r['message_id'],
                text=updated_text,
                reply_markup=kb,
                parse_mode="Markdown"
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass  # Ignore — content was identical, no real error
            elif "Message to edit not found" in str(e):
                # Message was deleted externally; clean up DB
                async with pool.acquire() as conn:
                    await conn.execute("DELETE FROM active_trivia WHERE chat_id=$1", r['chat_id'])
            else:
                logger.warning(f"Sweeper edit error for chat {r['chat_id']}: {e}")
        except Exception as e:
            logger.warning(f"Sweeper unexpected error: {e}")


async def trivia_cron_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 60 seconds. Fires daily/weekly trivia at the configured time."""
    pool = context.bot_data.get('db_pool')
    if not pool:
        return

    now          = datetime.datetime.now(WIB)
    current_date = now.strftime('%Y-%m-%d')
    day_name     = now.strftime('%A').lower()
    is_weekend   = day_name in ['saturday', 'sunday']

    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT value FROM config WHERE key='status'") or 'active'
        if status != 'active':
            return

        last_run     = await conn.fetchval("SELECT value FROM config WHERE key='last_run_date'") or ''
        if last_run == current_date:
            return

        run_time_str  = await conn.fetchval("SELECT value FROM config WHERE key='trivia_time'") or '12:00'
        target_raw    = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''
        days_mode     = await conn.fetchval("SELECT value FROM config WHERE key='trivia_days'") or 'all'

    if not target_raw:
        return
    try:
        target_chat_id = int(target_raw)
    except ValueError:
        return

    if days_mode == 'weekday' and is_weekend:
        return
    if days_mode == 'weekend' and not is_weekend:
        return
    if now.strftime('%H:%M') != run_time_str:
        return

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config (key, value) VALUES ('last_run_date', $1) "
            "ON CONFLICT (key) DO UPDATE SET value=$1",
            current_date
        )

    is_super_day = (day_name == 'sunday')
    context.application.create_task(
        deploy_trivia(context.bot, target_chat_id, is_super_day, pool)
    )


async def run_monthly_trivia_reset(context: ContextTypes.DEFAULT_TYPE):
    """Runs on the 1st of each month. Posts leaderboard and resets monthly KP."""
    pool = context.bot_data.get('db_pool')
    if not pool:
        return

    async with pool.acquire() as conn:
        target_raw = await conn.fetchval("SELECT value FROM trivia_config WHERE key='target_chat_id'") or ''
        if not target_raw:
            return
        top_minds = await conn.fetch(
            "SELECT username, monthly_kp FROM trivia_scores WHERE monthly_kp > 0 "
            "ORDER BY monthly_kp DESC LIMIT 3"
        )
        await conn.execute("UPDATE trivia_scores SET monthly_kp = 0")

    try:
        target_chat_id = int(target_raw)
    except ValueError:
        return

    if not top_minds:
        return

    podiums      = ["🥇", "🥈", "🥉"]
    announcement = (
        "🏆 **NUKHBA TRIVIA — MONTHLY CHAMPIONS** 🏆\n"
        "──────────────────────────────\n"
        "Congratulations to our top minds this month!\n\n"
    )
    for idx, user in enumerate(top_minds):
        announcement += f"{podiums[idx]} **@{user['username']}** — {user['monthly_kp']} Knowledge Points\n"
    announcement += "\n🔄 *Monthly stats reset. All-time stats preserved!*"

    try:
        await context.bot.send_message(target_chat_id, announcement, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Monthly trivia reset announcement failed: {e}")


# ─────────────────────────────────────────────
# ADMIN COMMANDS
# ─────────────────────────────────────────────

async def force_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return await update.message.reply_text("❌ Admins only.")
    await deploy_trivia(context.bot, update.effective_chat.id, False, pool)


async def force_super_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return await update.message.reply_text("❌ Admins only.")
    await deploy_trivia(context.bot, update.effective_chat.id, True, pool)


async def cancel_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return await update.message.reply_text("❌ Admins only.")

    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT chat_id FROM active_trivia WHERE chat_id=$1", update.effective_chat.id)

    if not room:
        return await update.message.reply_text("ℹ️ No active trivia round in this chat.")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Retry Round", callback_data="tcancel_retry"),
        InlineKeyboardButton("❌ Confirm Cancel", callback_data="tcancel_confirm")
    ]])
    await update.message.reply_text(
        "⚠️ **Cancel Active Trivia?**\n\n"
        "This will end the round immediately with **no Knowledge Points awarded**.\n\n"
        "Choose an option:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def end_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force-end trivia immediately and show results. Admin only."""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return await update.message.reply_text("❌ Admins only.")

    chat_id = update.effective_chat.id
    async with pool.acquire() as conn:
        room = await conn.fetchrow("SELECT chat_id FROM active_trivia WHERE chat_id=$1", chat_id)

    if not room:
        return await update.message.reply_text("ℹ️ No active trivia round in this chat.")

    await close_trivia_round(context.bot, chat_id, "🛑 Ended by Admin", pool)


async def admin_kp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually adjust a user's Knowledge Points. Admin only."""
    await delete_cmd(update)
    pool = context.bot_data.get('db_pool')
    if not await is_bot_admin(update.effective_user.username, pool):
        return await update.message.reply_text("❌ Admins only.")

    try:
        raw   = " ".join(context.args)
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        user   = parts[0].replace("@", "")
        op     = parts[1].lower()
        amount = int(parts[2])
    except Exception:
        return await update.message.reply_text(
            "❌ **Usage:**\n"
            "`` /admin_kp @username , set|add|sub , amount ``",
            parse_mode="Markdown"
        )

    async with pool.acquire() as conn:
        if op == 'set':
            await conn.execute(
                "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) "
                "ON CONFLICT (username) DO UPDATE SET monthly_kp=$2, all_time_kp=$2",
                user, amount
            )
        elif op == 'add':
            await conn.execute(
                "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, $2, $2) "
                "ON CONFLICT (username) DO UPDATE SET "
                "monthly_kp=trivia_scores.monthly_kp+$2, all_time_kp=trivia_scores.all_time_kp+$2",
                user, amount
            )
        elif op == 'sub':
            await conn.execute(
                "INSERT INTO trivia_scores (username, monthly_kp, all_time_kp) VALUES ($1, 0, 0) "
                "ON CONFLICT (username) DO UPDATE SET "
                "monthly_kp=GREATEST(0, trivia_scores.monthly_kp-$2), "
                "all_time_kp=GREATEST(0, trivia_scores.all_time_kp-$2)",
                user, amount
            )
        else:
            return await update.message.reply_text("❌ Op must be `set`, `add`, or `sub`", parse_mode="Markdown")

    await update.message.reply_text(
        f"✅ Knowledge Points updated for **@{user}** (`{op}` {amount} KP).",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
# USER COMMANDS
# ─────────────────────────────────────────────

async def my_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    username = update.effective_user.username or str(update.effective_user.id)
    pool     = context.bot_data.get('db_pool')

    async with pool.acquire() as conn:
        scores = await conn.fetchrow(
            "SELECT monthly_kp, all_time_kp FROM trivia_scores WHERE username=$1", username
        )

    monthly  = scores['monthly_kp']  if scores else 0
    all_time = scores['all_time_kp'] if scores else 0

    text = (
        "🧠 **Your Knowledge Point Summary**\n"
        "──────────────────────────────\n"
        f"📅 Monthly KP:  `{monthly}`\n"
        f"🏆 All-Time KP: `{all_time}`\n\n"
        "Keep exercising your mind — trivia runs daily! 💡"
    )

    try:
        await context.bot.send_message(update.effective_user.id, text, parse_mode="Markdown")
        if update.effective_chat.type != "private":
            await update.message.reply_text("✅ Your Knowledge Points have been sent to your DMs!")
    except Exception:
        await update.message.reply_text(
            "❌ Couldn't DM you. Please start a chat with me first, then try again."
        )


# ─────────────────────────────────────────────
# LEGACY FALLBACKS (prevent import crashes)
# ─────────────────────────────────────────────

async def _legacy_redirect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Please use the unified `/triviaconfig` panel instead.")

set_trivia_channel  = _legacy_redirect
set_trivia_theme    = _legacy_redirect
set_trivia_time     = _legacy_redirect
set_trivia_days     = _legacy_redirect
set_trivia_opts     = _legacy_redirect
set_trivia_timeout  = _legacy_redirect
set_super_timeout   = _legacy_redirect
pause_trivia        = _legacy_redirect
resume_trivia       = _legacy_redirect
