"""
cmd_events.py — /events  Unified Events & Polls Inline Hub
──────────────────────────────────────────────────────────
All flows run in DM. In a group, /events deletes the command and DMs the user.
Owner-locked inline keyboards. 120-second auto-expiry.

Menu tree:
  /events  →  Home  ─┬─ 📅 New Event   → DM flow (title → time → reminder)
                      ├─ 📊 New Poll    → DM flow (question → options → settings)
                      ├─ 📋 List Events → shown in-place (with 30-min group cooldown)
                      ├─ ✏️ Edit Event  → owner/admin can pick their event
                      └─ ❌ Cancel      → owner/admin can pick their event/poll

Callback prefix: ev_
"""

import asyncio
import datetime
import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import (
    WIB, delete_cmd, is_bot_admin,
    schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership, log_action
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
COOLDOWN_SECS   = 1800   # 30 min group cooldown for /list
KB_TIMEOUT      = 120    # keyboard auto-expire

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _safe_edit(msg, text, kb=None, md=True):
    try:
        kwargs = dict(parse_mode="Markdown") if md else {}
        if kb:
            await msg.edit_text(text, reply_markup=kb, **kwargs)
        else:
            await msg.edit_text(text, **kwargs)
    except Exception:
        pass


def _home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 New Event",   callback_data="ev_new_event"),
         InlineKeyboardButton("📊 New Poll",    callback_data="ev_new_poll")],
        [InlineKeyboardButton("📋 List Events", callback_data="ev_list"),
         InlineKeyboardButton("✏️ Edit Event",  callback_data="ev_edit_pick")],
        [InlineKeyboardButton("❌ Cancel Event/Poll", callback_data="ev_cancel_pick")],
        [InlineKeyboardButton("🚪 Close",       callback_data="ev_close")],
    ])


def _back_home_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home", callback_data="ev_home"),
        InlineKeyboardButton("🚪 Close", callback_data="ev_close"),
    ]])


# ─────────────────────────────────────────────────────────────────────────────
# DM GATE — always deliver in DM
# ─────────────────────────────────────────────────────────────────────────────

async def _send_home_dm(bot, user_id: int, username: str) -> None:
    text = (
        "📅 *Events & Polls Hub*\n\n"
        "What would you like to do?\n"
        "_(This panel closes after 120 seconds of inactivity.)_"
    )
    msg = await bot.send_message(user_id, text, reply_markup=_home_kb(), parse_mode="Markdown")
    return msg


async def eventpoll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — /eventpoll"""
    await delete_cmd(update)
    user    = update.effective_user
    pool    = context.bot_data.get("db_pool")
    user_id = user.id

    # Store origin group — auto-set when run from group, prompt in DM
    if update.effective_chat.type in ("group", "supergroup"):
        context.user_data["ev_origin_chat"] = update.effective_chat.id
        logger.info(f"Event hub: auto-set origin group {update.effective_chat.id}")
    else:
        # In DM, keep existing origin if set; user can change via menu later
        pass

    try:
        msg = await _send_home_dm(context.bot, user_id, user.username or str(user_id))
        await schedule_kb_timeout(context, user_id, msg.message_id, user_id)
    except Exception:
        # Can't DM yet — nudge in group
        if update.effective_chat.type in ("group", "supergroup"):
            bot_username = context.bot.username
            url = f"https://t.me/{bot_username}?start=open_events"
            kb  = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Open Events in DM", url=url)]])
            sent = await update.effective_chat.send_message(
                f"👋 @{user.username or user.first_name} — tap below to manage events in DM.\n"
                "_This message disappears in 30 s._",
                reply_markup=kb, parse_mode="Markdown"
            )
            if context.job_queue:
                context.job_queue.run_once(
                    lambda ctx: ctx.bot.delete_message(sent.chat_id, sent.message_id),
                    when=30, name=f"ev_nudge_{sent.message_id}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def events_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data  # e.g. "ev_new_event", "ev_home", "ev_list"
    pool = context.bot_data.get("db_pool")

    # Owner-lock: only the person who opened the panel can press buttons
    if not await check_kb_ownership(q, context):
        return await q.answer("This panel isn't yours.", show_alert=True)

    await q.answer()

    # ── Home ──────────────────────────────────────────────────────────────────
    if data == "ev_home":
        await _safe_edit(q.message,
            "📅 *Events & Polls Hub*\n\nWhat would you like to do?\n"
            "_(Panel closes after 120 s of inactivity.)_",
            _home_kb()
        )

    # ── Close ─────────────────────────────────────────────────────────────────
    elif data == "ev_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── List Events ───────────────────────────────────────────────────────────
    elif data == "ev_list":
        await _handle_list(q, context, pool)

    # ── New Event — start step 1 ───────────────────────────────────────────────
    elif data == "ev_new_event":
        context.user_data["ev_state"] = "await_event_title"
        context.user_data["ev_draft"] = {}
        await _safe_edit(q.message,
            "📅 *New Event — Step 1 of 3*\n\n"
            "Please type the *event title*:\n\n"
            "_e.g. Weekly Standup_",
            _back_home_kb()
        )

    # ── New Poll — start step 1 ────────────────────────────────────────────────
    elif data == "ev_new_poll":
        context.user_data["ev_state"] = "await_poll_question"
        context.user_data["ev_draft"] = {"type": "poll"}
        await _safe_edit(q.message,
            "📊 *New Poll — Step 1 of 2*\n\n"
            "Type the *poll question*, then on the next lines add each option:\n\n"
            "`Question\nOption 1\nOption 2\nOption 3`\n\n"
            "_Send all in one message, one per line. Minimum 2 options._",
            _back_home_kb()
        )

    # ── Edit — pick an event ───────────────────────────────────────────────────
    elif data == "ev_edit_pick":
        await _handle_edit_pick(q, context, pool)

    elif data.startswith("ev_edit_"):
        e_id = int(data.split("_")[2])
        context.user_data["ev_state"]    = "await_edit_event"
        context.user_data["ev_edit_id"]  = e_id
        await _safe_edit(q.message,
            f"✏️ *Edit Event #{e_id}*\n\n"
            "Send the updated details in this format:\n"
            "`Title , MM/DD/YYYY HH:MM , ReminderMinutes`\n\n"
            "_e.g._ `Team Sync , 06/30/2026 10:00 , 15`",
            _back_home_kb()
        )

    # ── Cancel pick ───────────────────────────────────────────────────────────
    elif data == "ev_cancel_pick":
        await _handle_cancel_pick(q, context, pool)

    elif data.startswith("ev_cancelev_"):
        e_id = int(data.split("_")[2])
        await _do_cancel_event(q, context, pool, e_id)

    elif data.startswith("ev_cancelpoll_"):
        # format: ev_cancelpoll_{chat_id}_{user_id}
        parts   = data.split("_")
        chat_id = int(parts[2])
        uid     = int(parts[3])
        await _do_cancel_poll(q, context, pool, chat_id, uid)

    # ── Poll settings toggles ──────────────────────────────────────────────────
    elif data.startswith("ev_poll_"):
        await _handle_poll_toggle(q, context, pool, data)


# ─────────────────────────────────────────────────────────────────────────────
# LIST EVENTS
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_list(q, context, pool):
    user_id = q.from_user.id
    now_ts  = datetime.datetime.now(WIB).timestamp()

    # Group cooldown: 30 minutes per group
    origin_chat = context.user_data.get("ev_origin_chat")
    if origin_chat:
        cooldowns = context.bot_data.setdefault("ev_list_cooldown", {})
        last_used = cooldowns.get(origin_chat, 0)
        elapsed   = now_ts - last_used
        if elapsed < COOLDOWN_SECS:
            remaining = int((COOLDOWN_SECS - elapsed) / 60)
            return await q.answer(
                f"⏳ List can only be shown every 30 min in the group. "
                f"Try again in {remaining} min.",
                show_alert=True
            )
        cooldowns[origin_chat] = now_ts

    async with pool.acquire() as conn:
        events = await conn.fetch(
            "SELECT id, title, event_time, created_by FROM events "
            "WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 8"
        )

    if not events:
        return await _safe_edit(q.message,
            "📋 *Upcoming Events*\n\n_No events scheduled yet._",
            _back_home_kb()
        )

    lines = ["📋 *Upcoming Events*\n"]
    for e in events:
        dt_str = e["event_time"].astimezone(WIB).strftime("%b %d, %H:%M WIB")
        lines.append(f"🔹 *{e['title']}* (#{e['id']})\n   📅 {dt_str} — by @{e['created_by']}")

    await _safe_edit(q.message, "\n".join(lines), _back_home_kb())


# ─────────────────────────────────────────────────────────────────────────────
# EDIT PICK
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_edit_pick(q, context, pool):
    username = q.from_user.username or str(q.from_user.id)
    is_adm   = await is_bot_admin(username, pool)

    async with pool.acquire() as conn:
        if is_adm:
            events = await conn.fetch(
                "SELECT id, title FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 10"
            )
        else:
            events = await conn.fetch(
                "SELECT id, title FROM events WHERE event_time > NOW() AND created_by=$1 ORDER BY event_time ASC LIMIT 10",
                username
            )

    if not events:
        return await q.answer("No events available to edit.", show_alert=True)

    rows = []
    for e in events:
        label = f"✏️ #{e['id']} {e['title'][:25]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"ev_edit_{e['id']}")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="ev_home"),
                 InlineKeyboardButton("🚪 Close", callback_data="ev_close")])

    await _safe_edit(q.message, "✏️ *Edit Event*\n\nSelect the event to edit:", InlineKeyboardMarkup(rows))


# ─────────────────────────────────────────────────────────────────────────────
# CANCEL PICK
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_cancel_pick(q, context, pool):
    username = q.from_user.username or str(q.from_user.id)
    is_adm   = await is_bot_admin(username, pool)

    rows = []

    async with pool.acquire() as conn:
        # Events
        if is_adm:
            events = await conn.fetch(
                "SELECT id, title FROM events WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 8"
            )
        else:
            events = await conn.fetch(
                "SELECT id, title FROM events WHERE event_time > NOW() AND created_by=$1 ORDER BY event_time ASC LIMIT 8",
                username
            )
        for e in events:
            label = f"📅 #{e['id']} {e['title'][:22]}"
            rows.append([InlineKeyboardButton(label, callback_data=f"ev_cancelev_{e['id']}")])

        # Active polls
        if is_adm:
            polls = await conn.fetch(
                "SELECT chat_id, user_id, end_time FROM active_polls WHERE end_time > NOW() ORDER BY end_time ASC LIMIT 5"
            )
        else:
            polls = await conn.fetch(
                "SELECT chat_id, user_id, end_time FROM active_polls WHERE end_time > NOW() AND user_id=$1 ORDER BY end_time ASC LIMIT 5",
                q.from_user.id
            )
        for p in polls:
            label = f"📊 Poll (ends {p['end_time'].astimezone(WIB).strftime('%b %d %H:%M')})"
            rows.append([InlineKeyboardButton(label, callback_data=f"ev_cancelpoll_{p['chat_id']}_{p['user_id']}")])

    if not rows:
        return await q.answer("Nothing to cancel.", show_alert=True)

    rows.append([InlineKeyboardButton("🏠 Home", callback_data="ev_home"),
                 InlineKeyboardButton("🚪 Close", callback_data="ev_close")])
    await _safe_edit(q.message, "❌ *Cancel Event / Poll*\n\nSelect what to cancel:", InlineKeyboardMarkup(rows))


# ─────────────────────────────────────────────────────────────────────────────
# DO CANCEL EVENT
# ─────────────────────────────────────────────────────────────────────────────

async def _do_cancel_event(q, context, pool, e_id: int):
    username = q.from_user.username or str(q.from_user.id)
    is_adm   = await is_bot_admin(username, pool)

    async with pool.acquire() as conn:
        ev = await conn.fetchrow("SELECT chat_id, msg_id, created_by, title FROM events WHERE id=$1", e_id)
        if not ev:
            return await q.answer("Event not found.", show_alert=True)
        if ev["created_by"] != username and not is_adm:
            return await q.answer("Only the creator or an admin can cancel this.", show_alert=True)
        await conn.execute("DELETE FROM events WHERE id=$1", e_id)

    for j in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"):
        j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name(f"event_unpin_{e_id}"):
        j.schedule_removal()
    try:
        await context.bot.unpin_chat_message(chat_id=ev["chat_id"], message_id=ev["msg_id"])
    except Exception:
        pass

    await log_action(pool, q.from_user.id, ev["chat_id"], "Event Cancelled", "Success",
                     f"#{e_id} '{ev['title']}' by @{username}")
    await _safe_edit(q.message,
        f"✅ *Event `#{e_id}` — {ev['title']}* has been cancelled and unpinned.",
        _back_home_kb()
    )


# ─────────────────────────────────────────────────────────────────────────────
# DO CANCEL POLL
# ─────────────────────────────────────────────────────────────────────────────

async def _do_cancel_poll(q, context, pool, chat_id: int, uid: int):
    username = q.from_user.username or str(q.from_user.id)
    is_adm   = await is_bot_admin(username, pool)

    if q.from_user.id != uid and not is_adm:
        return await q.answer("Only the poll creator or an admin can cancel this.", show_alert=True)

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM active_polls WHERE chat_id=$1 AND user_id=$2", chat_id, uid)

    await _safe_edit(q.message,
        "✅ *Poll cancelled.* The poll has been stopped in the group.",
        _back_home_kb()
    )


# ─────────────────────────────────────────────────────────────────────────────
# POLL SETTINGS TOGGLE
# ─────────────────────────────────────────────────────────────────────────────

def _poll_settings_kb(draft: dict) -> InlineKeyboardMarkup:
    anon_label  = f"👻 Anon: {'ON' if draft.get('anon') else 'OFF'}"
    multi_label = f"☑️ Multi-answer: {'ON' if draft.get('multi') else 'OFF'}"
    quiz_idx    = draft.get("quiz_idx", -1)
    opts        = draft.get("opts", [])
    quiz_label  = f"🧠 Quiz answer: #{quiz_idx+1}" if quiz_idx >= 0 else "🧠 Quiz: OFF"
    dur         = draft.get("hours", 24)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(anon_label,  callback_data="ev_poll_anon"),
         InlineKeyboardButton(multi_label, callback_data="ev_poll_multi")],
        [InlineKeyboardButton(quiz_label,  callback_data="ev_poll_quiz"),
         InlineKeyboardButton(f"⏳ {dur}h", callback_data="ev_poll_hrs")],
        [InlineKeyboardButton("🚀 Launch Poll", callback_data="ev_poll_send"),
         InlineKeyboardButton("❌ Cancel",      callback_data="ev_poll_cancel")],
    ])


async def _handle_poll_toggle(q, context, pool, data: str):
    draft = context.user_data.get("ev_poll_draft")
    if not draft:
        return await q.answer("Poll draft expired.", show_alert=True)

    act = data.replace("ev_poll_", "")

    if act == "anon":
        draft["anon"] = not draft.get("anon", False)
    elif act == "multi":
        draft["multi"] = not draft.get("multi", False)
        if draft["multi"]:
            draft["quiz_idx"] = -1
    elif act == "quiz":
        opts   = draft.get("opts", [])
        cur    = draft.get("quiz_idx", -1)
        nxt    = -1 if cur >= len(opts) - 1 else cur + 1
        draft["quiz_idx"] = nxt
        if nxt >= 0:
            draft["multi"] = False
    elif act == "hrs":
        cycles = [1, 6, 12, 24, 48, 72]
        cur = draft.get("hours", 24)
        draft["hours"] = cycles[(cycles.index(cur) + 1) % len(cycles)] if cur in cycles else 24
    elif act == "cancel":
        context.user_data.pop("ev_poll_draft", None)
        context.user_data.pop("ev_state", None)
        return await _safe_edit(q.message,
            "❌ Poll cancelled.",
            _back_home_kb()
        )
    elif act == "send":
        await _launch_poll(q, context, pool, draft)
        return

    context.user_data["ev_poll_draft"] = draft
    opts_text = "\n".join(f"{i+1}. {o}" for i, o in enumerate(draft["opts"]))
    await _safe_edit(q.message,
        f"📊 *Poll Settings*\n\n*Q:* {draft['question']}\n\n{opts_text}",
        _poll_settings_kb(draft)
    )


async def _launch_poll(q, context, pool, draft: dict):
    origin_chat = context.user_data.get("ev_origin_chat")
    if not origin_chat:
        return await q.answer(
            "No group target set. Start /events from your group first.",
            show_alert=True
        )
    dur = draft.get("hours", 24) * 3600
    try:
        await context.bot.send_poll(
            origin_chat,
            draft["question"],
            draft["opts"],
            is_anonymous=draft.get("anon", False),
            allows_multiple_answers=draft.get("multi", False),
            type="quiz" if draft.get("quiz_idx", -1) >= 0 else "regular",
            correct_option_id=draft.get("quiz_idx") if draft.get("quiz_idx", -1) >= 0 else None,
            open_period=min(dur, 604800),
        )
        end_time = datetime.datetime.now(WIB) + datetime.timedelta(seconds=dur)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO active_polls (chat_id, user_id, end_time) VALUES ($1, $2, $3) "
                "ON CONFLICT (chat_id, user_id) DO UPDATE SET end_time=$3",
                origin_chat, q.from_user.id, end_time
            )
        context.user_data.pop("ev_poll_draft", None)
        context.user_data.pop("ev_state", None)
        await _safe_edit(q.message, "✅ *Poll launched in the group!*", _back_home_kb())
    except Exception as e:
        logger.error(f"Poll launch error: {e}")
        await q.answer("Could not launch the poll. Make sure the bot has permission to post in the group.", show_alert=True)


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER (routes from global_text_router)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_events_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Called by global_text_router for every non-command DM message.
    Returns True if this handler consumed the message.
    """
    state = context.user_data.get("ev_state")
    if not state:
        return False

    text = (update.message.text or "").strip()
    pool = context.bot_data.get("db_pool")
    user = update.effective_user
    uid  = user.id

    # ── EVENT TITLE ────────────────────────────────────────────────────────
    if state == "await_event_title":
        if not text:
            return True
        context.user_data["ev_draft"]["title"] = text
        context.user_data["ev_state"] = "await_event_time"
        await update.message.reply_text(
            "📅 *New Event — Step 2 of 3*\n\n"
            "Enter the *event date and time*:\n`MM/DD/YYYY HH:MM`\n\n"
            "_e.g._ `06/30/2026 10:00`",
            parse_mode="Markdown"
        )
        return True

    # ── EVENT TIME ─────────────────────────────────────────────────────────
    elif state == "await_event_time":
        try:
            e_time = WIB.localize(datetime.datetime.strptime(text, "%m/%d/%Y %H:%M"))
            if e_time < datetime.datetime.now(WIB):
                raise ValueError("past")
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid date/time or it's in the past.\n"
                "Format: `MM/DD/YYYY HH:MM` (e.g. `06/30/2026 10:00`)",
                parse_mode="Markdown"
            )
            return True
        context.user_data["ev_draft"]["event_time"] = e_time
        context.user_data["ev_state"] = "await_event_reminder"
        await update.message.reply_text(
            "📅 *New Event — Step 3 of 3*\n\n"
            "How many *minutes before* should the reminder be sent?\n\n"
            "_e.g._ `15` _(for 15 minutes before the event)_",
            parse_mode="Markdown"
        )
        return True

    # ── EVENT REMINDER ─────────────────────────────────────────────────────
    elif state == "await_event_reminder":
        try:
            rem = int(text)
            if rem < 1 or rem > 1440:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Please enter a number between 1 and 1440.")
            return True

        draft  = context.user_data.get("ev_draft", {})
        title  = draft.get("title", "Event")
        e_time = draft.get("event_time")
        origin = context.user_data.get("ev_origin_chat")
        if not origin:
            await update.message.reply_text("❌ No group target. Start /events from your group first.")
            context.user_data.pop("ev_state", None)
            return True

        username = user.username or str(uid)
        async with pool.acquire() as conn:
            max_e = int(await conn.fetchval("SELECT value FROM config WHERE key='max_events'") or 5)
            if not await is_bot_admin(username, pool):
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM events WHERE created_by=$1 AND event_time > NOW()", username
                )
                if count >= max_e:
                    context.user_data.pop("ev_state", None)
                    return await update.message.reply_text(f"❌ You can only have {max_e} active events at a time.") or True

        kb  = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Going",     callback_data="rsvp_temp_Going"),
            InlineKeyboardButton("❌ Not Going", callback_data="rsvp_temp_Not"),
        ]])
        msg = await context.bot.send_message(
            origin,
            f"📅 *{title}*\n🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n\n*Attendance:*\n_None yet_",
            reply_markup=kb, parse_mode="Markdown"
        )
        try:
            await context.bot.pin_chat_message(origin, msg.message_id)
        except Exception:
            pass

        async with pool.acquire() as conn:
            e_id = await conn.fetchval(
                "INSERT INTO events (title, event_time, created_by, chat_id, msg_id) "
                "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                title, e_time, username, origin, msg.message_id
            )

        new_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Going",     callback_data=f"rsvp_{e_id}_Going"),
            InlineKeyboardButton("❌ Not Going", callback_data=f"rsvp_{e_id}_Not"),
        ]])
        try:
            await context.bot.edit_message_reply_markup(origin, msg.message_id, reply_markup=new_kb)
        except Exception:
            pass

        from cmd_admin import event_reminder as _ev_reminder, unpin_event as _unpin
        context.job_queue.run_once(
            _ev_reminder,
            when=e_time - datetime.timedelta(minutes=rem),
            chat_id=origin,
            data={"id": e_id, "title": title},
            name=f"event_rem_{e_id}"
        )
        context.job_queue.run_once(
            _unpin,
            when=e_time,
            data={"chat_id": origin, "msg_id": msg.message_id},
            name=f"event_unpin_{e_id}"
        )
        await log_action(pool, uid, origin, "Event Created", "Success",
                         f"#{e_id} '{title}' by @{username}")

        context.user_data.pop("ev_state", None)
        context.user_data.pop("ev_draft", None)
        await update.message.reply_text(
            f"✅ *Event created!*\n\n📅 *{title}*\n"
            f"🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n"
            f"⏰ Reminder: {rem} min before\n"
            f"Event ID: `#{e_id}`",
            parse_mode="Markdown"
        )
        return True

    # ── EDIT EVENT ─────────────────────────────────────────────────────────
    elif state == "await_edit_event":
        e_id = context.user_data.get("ev_edit_id")
        try:
            parts  = [p.strip() for p in text.rsplit(",", 2)]
            title  = parts[0]
            e_time = WIB.localize(datetime.datetime.strptime(parts[1], "%m/%d/%Y %H:%M"))
            rem    = int(parts[2])
        except Exception:
            await update.message.reply_text(
                "❌ Wrong format. Try:\n`Title , MM/DD/YYYY HH:MM , ReminderMins`",
                parse_mode="Markdown"
            )
            return True

        username = user.username or str(uid)
        async with pool.acquire() as conn:
            ev = await conn.fetchrow("SELECT created_by, chat_id FROM events WHERE id=$1", e_id)
            if not ev:
                await update.message.reply_text("❌ Event not found.")
                context.user_data.pop("ev_state", None)
                return True
            if ev["created_by"] != username and not await is_bot_admin(username, pool):
                await update.message.reply_text("❌ You don't have permission to edit this event.")
                context.user_data.pop("ev_state", None)
                return True
            await conn.execute("UPDATE events SET title=$1, event_time=$2 WHERE id=$3", title, e_time, e_id)

        for job in context.job_queue.get_jobs_by_name(f"event_rem_{e_id}"):
            job.schedule_removal()
        from cmd_admin import event_reminder as _ev_reminder
        context.job_queue.run_once(
            _ev_reminder,
            when=e_time - datetime.timedelta(minutes=rem),
            chat_id=ev["chat_id"],
            data={"id": e_id, "title": title},
            name=f"event_rem_{e_id}"
        )

        context.user_data.pop("ev_state", None)
        context.user_data.pop("ev_edit_id", None)
        await update.message.reply_text(
            f"✅ *Event #{e_id} updated!*\n\n📅 *{title}*\n"
            f"🕒 {e_time.strftime('%b %d at %H:%M WIB')}\n"
            f"⏰ Reminder: {rem} min before",
            parse_mode="Markdown"
        )
        return True

    # ── POLL QUESTION + OPTIONS ────────────────────────────────────────────
    elif state == "await_poll_question":
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            await update.message.reply_text(
                "❌ Need at least a question and 2 options.\n\n"
                "Format (one per line):\n`Question\nOption 1\nOption 2`",
                parse_mode="Markdown"
            )
            return True

        question = lines[0]
        opts     = lines[1:11]  # max 10 options

        context.user_data["ev_poll_draft"] = {
            "question":  question,
            "opts":      opts,
            "anon":      False,
            "multi":     False,
            "quiz_idx":  -1,
            "hours":     24,
        }
        context.user_data["ev_state"] = "await_poll_settings"

        opts_text = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opts))
        msg = await update.message.reply_text(
            f"📊 *Poll Settings*\n\n*Q:* {question}\n\n{opts_text}\n\n"
            "_Adjust settings and tap Launch when ready._",
            reply_markup=_poll_settings_kb(context.user_data["ev_poll_draft"]),
            parse_mode="Markdown"
        )
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# /listevent — quick standalone event list (no DM required)
# ─────────────────────────────────────────────────────────────────────────────

async def listevent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show upcoming events directly in-chat (30-min group cooldown)."""
    pool    = context.bot_data.get("db_pool")
    chat_id = update.effective_chat.id
    now_ts  = datetime.datetime.now(WIB).timestamp()

    if update.effective_chat.type in ("group", "supergroup"):
        cooldowns = context.bot_data.setdefault("ev_list_cooldown", {})
        elapsed   = now_ts - cooldowns.get(chat_id, 0)
        if elapsed < COOLDOWN_SECS:
            remaining = int((COOLDOWN_SECS - elapsed) / 60)
            return await update.message.reply_text(
                f"⏳ Event list was shown recently. Try again in {remaining} min."
            )
        cooldowns[chat_id] = now_ts

    async with pool.acquire() as conn:
        events = await conn.fetch(
            "SELECT id, title, event_time, created_by FROM events "
            "WHERE event_time > NOW() ORDER BY event_time ASC LIMIT 10"
        )

    if not events:
        return await update.message.reply_text("📋 No upcoming events scheduled yet.")

    lines = ["📋 *Upcoming Events*\n"]
    for e in events:
        dt_str = e["event_time"].astimezone(WIB).strftime("%b %d at %H:%M WIB")
        lines.append(f"🔹 *{e['title']}* (#{e['id']})\n   📅 {dt_str} — by @{e['created_by']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
