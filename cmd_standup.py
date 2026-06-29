"""
cmd_standup.py — /standup  Daily Standup System
─────────────────────────────────────────────────
Full inline keyboard setup in DM. All prompts/flows in DM.

Features:
  • Manager sets up standup configs (members, schedule, timing)
  • Bot DMs members at check-in and check-out time
  • Check-in: to-do list, optional notes
  • Check-out: per-task status (Complete/Pending/Cancelled), blockers, notes
  • Manager approves or rejects each submission (with note on reject)
  • AI summary sent to manager after all members complete each session
  • Pause / Resume / Delete config controls

Callback prefix: sd_
State keys: sd_state
"""

import asyncio
import datetime
import json
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import (
    WIB, delete_cmd, is_bot_admin, is_super,
    schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership,
    schedule_text_input_timeout, cancel_text_input_timeout,
    log_action,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DB SETUP
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_standup_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS standup_configs (
                id           SERIAL PRIMARY KEY,
                manager      VARCHAR(100) NOT NULL,
                name         TEXT NOT NULL DEFAULT 'Daily Standup',
                members      TEXT NOT NULL DEFAULT '[]',
                recurrence   VARCHAR(20)  NOT NULL DEFAULT 'weekday',
                checkin_time VARCHAR(5)   NOT NULL DEFAULT '09:00',
                checkout_time VARCHAR(5)  NOT NULL DEFAULT '17:00',
                status       VARCHAR(20)  NOT NULL DEFAULT 'active',
                created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS standup_sessions (
                id          SERIAL PRIMARY KEY,
                config_id   INT NOT NULL REFERENCES standup_configs(id) ON DELETE CASCADE,
                session_date DATE NOT NULL,
                type        VARCHAR(10) NOT NULL,
                status      VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS standup_responses (
                id           SERIAL PRIMARY KEY,
                session_id   INT NOT NULL REFERENCES standup_sessions(id) ON DELETE CASCADE,
                member       VARCHAR(100) NOT NULL,
                method       VARCHAR(20)  NOT NULL DEFAULT 'bot',
                tasks        TEXT,
                notes        TEXT,
                task_statuses TEXT,
                blockers     TEXT,
                extra_notes  TEXT,
                submitted_at TIMESTAMP WITH TIME ZONE,
                approved     BOOLEAN,
                reject_note  TEXT,
                prompt_msg_id BIGINT,
                UNIQUE(session_id, member)
            )
        """)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

RECURRENCE_LABELS = {
    "weekday": "Daily (Weekdays)",
    "daily":   "Daily (All Days)",
    "weekly":  "Weekly",
    "once":    "Once",
}

def _parse_tasks(raw: str) -> list[str]:
    """Parse user task input into a list of bullet points."""
    raw = raw.strip()
    # If user used > bullets
    if ">" in raw:
        tasks = [t.strip().lstrip(">").strip() for t in raw.split("\n") if t.strip()]
    else:
        # Split on . or newline
        tasks = [t.strip() for t in re.split(r"\.\s+|\n", raw) if t.strip()]
    return [t for t in tasks if t]


def _fmt_tasks(tasks: list[str]) -> str:
    return "\n".join(f"• {t}" for t in tasks)


async def _get_user_id(pool, username: str) -> int | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT user_id FROM users WHERE LOWER(username)=$1", username.lower()
        )


async def _get_manager_name(pool, manager: str) -> str:
    return f"@{manager}"


# ─────────────────────────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────────────────────────

def _home_kb(is_manager: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if is_manager:
        rows += [
            [InlineKeyboardButton("➕ New Standup Config",  callback_data="sd_new")],
            [InlineKeyboardButton("📋 My Configs",          callback_data="sd_list"),
             InlineKeyboardButton("⚙️ Manage",              callback_data="sd_manage_pick")],
        ]
    rows += [
        [InlineKeyboardButton("📅 My Standups Today",   callback_data="sd_my_today")],
        [InlineKeyboardButton("🚪 Close",               callback_data="sd_close")],
    ]
    return InlineKeyboardMarkup(rows)


def _back_kb(home_data: str = "sd_home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Home",  callback_data=home_data),
        InlineKeyboardButton("🚪 Close", callback_data="sd_close"),
    ]])


def _manage_kb(config_id: int, status: str) -> InlineKeyboardMarkup:
    toggle = "⏸️ Pause" if status == "active" else "▶️ Resume"
    toggle_data = f"sd_pause_{config_id}" if status == "active" else f"sd_resume_{config_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit Members",    callback_data=f"sd_edit_members_{config_id}"),
         InlineKeyboardButton("⏰ Edit Timing",     callback_data=f"sd_edit_timing_{config_id}")],
        [InlineKeyboardButton(toggle,               callback_data=toggle_data),
         InlineKeyboardButton("🗑️ Delete",          callback_data=f"sd_delete_{config_id}")],
        [InlineKeyboardButton("◀️ Back",            callback_data="sd_manage_pick")],
        [InlineKeyboardButton("🚪 Close",           callback_data="sd_close")],
    ])


def _checkin_method_kb(session_id: int, manager_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Do it here (DM)",
                              callback_data=f"sd_checkin_here_{session_id}")],
        [InlineKeyboardButton(f"💬 I'll do it via Discord with {manager_name}",
                              callback_data=f"sd_checkin_discord_{session_id}")],
    ])


def _checkout_method_kb(session_id: int, manager_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Do it here (DM)",
                              callback_data=f"sd_checkout_here_{session_id}")],
        [InlineKeyboardButton(f"💬 I'll do it via Discord with {manager_name}",
                              callback_data=f"sd_checkout_discord_{session_id}")],
    ])


def _discord_reminder_kb(session_id: int, stype: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Done — submit here now",
                              callback_data=f"sd_{stype}_here_{session_id}")],
        [InlineKeyboardButton("🔄 Change to DM method",
                              callback_data=f"sd_{stype}_here_{session_id}")],
    ])


def _task_status_kb(tasks: list[str], statuses: dict, session_id: int,
                    member: str) -> tuple[str, InlineKeyboardMarkup]:
    """Build task status buttons. Each task gets its own row with 3 status buttons."""
    rows = []
    icons = {"complete": "✅", "pending": "⌛", "cancelled": "❌"}
    lines = ["📋 *Task Status*\n_Tap each status for each task, then tap Submit._\n"]

    for i, task in enumerate(tasks):
        cur = statuses.get(str(i), "")
        cur_icon = icons.get(cur, "⬜")
        lines.append(f"{cur_icon} {i+1}. {task[:60]}")
        rows.append([
            InlineKeyboardButton(
                "✅ Done"  + (" ←" if cur == "complete"  else ""),
                callback_data=f"sd_ts_{session_id}_{i}_complete"),
            InlineKeyboardButton(
                "⌛ Pending" + (" ←" if cur == "pending"   else ""),
                callback_data=f"sd_ts_{session_id}_{i}_pending"),
            InlineKeyboardButton(
                "❌ Cancel"  + (" ←" if cur == "cancelled" else ""),
                callback_data=f"sd_ts_{session_id}_{i}_cancelled"),
        ])

    all_set = all(str(i) in statuses for i in range(len(tasks)))
    rows.append([
        InlineKeyboardButton(
            "💾 Submit" if all_set else "💾 Submit (set all first)",
            callback_data=f"sd_ts_submit_{session_id}_{member}"
        )
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _approval_kb(response_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"sd_approve_{response_id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"sd_reject_{response_id}"),
    ]])


def _recurrence_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Daily (Weekdays)",  callback_data="sd_rec_weekday"),
         InlineKeyboardButton("📆 Daily (All Days)",  callback_data="sd_rec_daily")],
        [InlineKeyboardButton("🗓️ Weekly",            callback_data="sd_rec_weekly"),
         InlineKeyboardButton("1️⃣ Once",              callback_data="sd_rec_once")],
        [InlineKeyboardButton("🏠 Home", callback_data="sd_home"),
         InlineKeyboardButton("🚪 Close", callback_data="sd_close")],
    ])


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def standup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — /standup"""
    await delete_cmd(update)
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)
    pool     = context.bot_data.get("db_pool")
    await ensure_standup_tables(pool)

    is_adm = await is_bot_admin(username, pool)

    try:
        msg = await context.bot.send_message(
            uid,
            "📋 *Daily Standup Hub*\n\n"
            + ("You can create and manage standup schedules.\n" if is_adm else
               "View your standup prompts and submissions.\n") +
            "_(Panel closes after 120 s of inactivity.)_",
            reply_markup=_home_kb(is_adm),
            parse_mode="Markdown"
        )
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
        if update.message:
            await update.message.reply_text(
                "❌ Please start a DM with me first (/start), then try /standup again."
            )


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def standup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uid  = q.from_user.id
    username = q.from_user.username or str(uid)

    # Task status buttons and check-in/out method buttons are NOT owner-locked
    # (member picks their own flow, not shared panel)
    owner_locked = not any(data.startswith(p) for p in [
        "sd_ts_", "sd_checkin_", "sd_checkout_", "sd_approve_",
        "sd_reject_", "sd_discord_done_"
    ])
    if owner_locked and not await check_kb_ownership(q, context):
        return await q.answer("⛔ This panel isn't yours.", show_alert=True)

    await q.answer()

    # ── Home ─────────────────────────────────────────────────────────────────
    if data == "sd_home":
        is_adm = await is_bot_admin(username, pool)
        await q.message.edit_text(
            "📋 *Daily Standup Hub*\n\nWhat would you like to do?",
            reply_markup=_home_kb(is_adm), parse_mode="Markdown"
        )
        context.user_data.pop("sd_state", None)

    # ── Close ─────────────────────────────────────────────────────────────────
    elif data == "sd_close":
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        context.user_data.pop("sd_state", None)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── New config wizard: Step 1 — name ─────────────────────────────────────
    elif data == "sd_new":
        context.user_data["sd_state"]  = "await_name"
        context.user_data["sd_draft"]  = {"manager": username}
        context.user_data["sd_panel"]  = (q.message.chat_id, q.message.message_id)
        prompt = await q.message.edit_text(
            "➕ *New Standup Config — Step 1 of 5*\n\n"
            "Give this standup a *name*:\n_e.g. RAWWY Daily Standup_",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", "await_name",
            q.message.chat_id, q.message.message_id
        )

    # ── Recurrence picker (step 3) ────────────────────────────────────────────
    elif data.startswith("sd_rec_"):
        rec = data[7:]
        context.user_data.get("sd_draft", {})["recurrence"] = rec
        context.user_data["sd_state"] = "await_checkin_time"
        panel = context.user_data.get("sd_panel", (uid, None))
        try:
            await context.bot.edit_message_text(
                chat_id=panel[0], message_id=panel[1],
                text=(
                    f"➕ *New Standup Config — Step 4 of 5*\n\n"
                    f"Recurrence: *{RECURRENCE_LABELS[rec]}*\n\n"
                    "Type the *check-in time* (WIB):\n`HH:MM`\n_e.g. `09:00`_"
                ),
                reply_markup=_back_kb(), parse_mode="Markdown"
            )
        except Exception:
            pass
        schedule_text_input_timeout(
            context, uid, "sd_state", "await_checkin_time",
            panel[0], panel[1]
        )

    # ── List configs ──────────────────────────────────────────────────────────
    elif data == "sd_list":
        async with pool.acquire() as conn:
            configs = await conn.fetch(
                "SELECT id, name, recurrence, checkin_time, checkout_time, status, members "
                "FROM standup_configs WHERE LOWER(manager)=$1 ORDER BY id DESC",
                username.lower()
            )
        if not configs:
            await q.message.edit_text(
                "📋 *My Standup Configs*\n\n_No configs yet. Tap ➕ New to create one._",
                reply_markup=_back_kb(), parse_mode="Markdown"
            )
            return
        lines = ["📋 *My Standup Configs*\n"]
        for cfg in configs:
            members = json.loads(cfg["members"] or "[]")
            st = "✅" if cfg["status"] == "active" else "⏸️"
            lines.append(
                f"{st} *#{cfg['id']}* {cfg['name']}\n"
                f"   {RECURRENCE_LABELS.get(cfg['recurrence'], cfg['recurrence'])} | "
                f"In: {cfg['checkin_time']} · Out: {cfg['checkout_time']} WIB\n"
                f"   👥 {len(members)} member{'s' if len(members) != 1 else ''}"
            )
        rows = [[InlineKeyboardButton(f"⚙️ #{c['id']} {c['name'][:25]}",
                                       callback_data=f"sd_manage_{c['id']}")]
                for c in configs]
        rows.append([InlineKeyboardButton("🏠 Home", callback_data="sd_home"),
                     InlineKeyboardButton("🚪 Close", callback_data="sd_close")])
        await q.message.edit_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown"
        )

    # ── Manage pick ───────────────────────────────────────────────────────────
    elif data == "sd_manage_pick":
        async with pool.acquire() as conn:
            configs = await conn.fetch(
                "SELECT id, name, status FROM standup_configs WHERE LOWER(manager)=$1 ORDER BY id DESC",
                username.lower()
            )
        if not configs:
            return await q.answer("No configs to manage.", show_alert=True)
        rows = [[InlineKeyboardButton(
            f"{'✅' if c['status']=='active' else '⏸️'} #{c['id']} {c['name'][:30]}",
            callback_data=f"sd_manage_{c['id']}"
        )] for c in configs]
        rows.append([InlineKeyboardButton("🏠 Home", callback_data="sd_home"),
                     InlineKeyboardButton("🚪 Close", callback_data="sd_close")])
        await q.message.edit_text(
            "⚙️ *Manage Standup*\n\nSelect a config:",
            reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown"
        )

    # ── Manage specific config ────────────────────────────────────────────────
    elif data.startswith("sd_manage_") and not data.startswith("sd_manage_pick"):
        config_id = int(data[10:])
        async with pool.acquire() as conn:
            cfg = await conn.fetchrow(
                "SELECT * FROM standup_configs WHERE id=$1 AND LOWER(manager)=$2",
                config_id, username.lower()
            )
        if not cfg:
            return await q.answer("Config not found or not yours.", show_alert=True)
        members = json.loads(cfg["members"] or "[]")
        st = "✅ Active" if cfg["status"] == "active" else "⏸️ Paused"
        await q.message.edit_text(
            f"⚙️ *{cfg['name']}* (#{cfg['id']})\n\n"
            f"Status: {st}\n"
            f"Recurrence: {RECURRENCE_LABELS.get(cfg['recurrence'], cfg['recurrence'])}\n"
            f"Check-in: {cfg['checkin_time']} WIB\n"
            f"Check-out: {cfg['checkout_time']} WIB\n"
            f"Members ({len(members)}): {', '.join('@'+m for m in members) or '_none_'}",
            reply_markup=_manage_kb(config_id, cfg["status"]),
            parse_mode="Markdown"
        )

    # ── Pause / Resume ────────────────────────────────────────────────────────
    elif data.startswith("sd_pause_") or data.startswith("sd_resume_"):
        action    = "paused" if data.startswith("sd_pause_") else "active"
        config_id = int(data.split("_")[-1])
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE standup_configs SET status=$1 WHERE id=$2 AND LOWER(manager)=$3",
                action, config_id, username.lower()
            )
        lbl = "⏸️ Paused" if action == "paused" else "▶️ Resumed"
        await q.answer(f"{lbl} standup #{config_id}.", show_alert=True)
        # Refresh manage panel
        async with pool.acquire() as conn:
            cfg = await conn.fetchrow("SELECT * FROM standup_configs WHERE id=$1", config_id)
        if cfg:
            members = json.loads(cfg["members"] or "[]")
            st = "✅ Active" if cfg["status"] == "active" else "⏸️ Paused"
            await q.message.edit_text(
                f"⚙️ *{cfg['name']}* (#{cfg['id']})\n\nStatus: {st}\n"
                f"Recurrence: {RECURRENCE_LABELS.get(cfg['recurrence'], cfg['recurrence'])}\n"
                f"Check-in: {cfg['checkin_time']} WIB · Check-out: {cfg['checkout_time']} WIB\n"
                f"Members ({len(members)}): {', '.join('@'+m for m in members) or '_none_'}",
                reply_markup=_manage_kb(config_id, cfg["status"]),
                parse_mode="Markdown"
            )

    # ── Delete ────────────────────────────────────────────────────────────────
    elif data.startswith("sd_delete_"):
        config_id = int(data[10:])
        # Confirm prompt
        await q.message.edit_text(
            f"🗑️ *Delete standup #{config_id}?*\n\n"
            "_This will also delete all session history for this config._",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Yes, delete", callback_data=f"sd_confirmdelete_{config_id}"),
                InlineKeyboardButton("❌ Cancel",       callback_data=f"sd_manage_{config_id}"),
            ]]),
            parse_mode="Markdown"
        )

    elif data.startswith("sd_confirmdelete_"):
        config_id = int(data[17:])
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM standup_configs WHERE id=$1 AND LOWER(manager)=$2",
                config_id, username.lower()
            )
        await q.message.edit_text(
            f"✅ Standup config #{config_id} deleted.",
            reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Edit members ──────────────────────────────────────────────────────────
    elif data.startswith("sd_edit_members_"):
        config_id = int(data[16:])
        context.user_data["sd_state"]     = "await_edit_members"
        context.user_data["sd_edit_id"]   = config_id
        context.user_data["sd_panel"]     = (q.message.chat_id, q.message.message_id)
        await q.message.edit_text(
            "✏️ *Edit Members*\n\n"
            "Type usernames comma-separated:\n`@alice, @bob, @carol`",
            reply_markup=_back_kb(f"sd_manage_{config_id}"), parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", "await_edit_members",
            q.message.chat_id, q.message.message_id
        )

    # ── Edit timing ───────────────────────────────────────────────────────────
    elif data.startswith("sd_edit_timing_"):
        config_id = int(data[15:])
        context.user_data["sd_state"]   = "await_edit_timing"
        context.user_data["sd_edit_id"] = config_id
        context.user_data["sd_panel"]   = (q.message.chat_id, q.message.message_id)
        await q.message.edit_text(
            "⏰ *Edit Timing*\n\n"
            "Type check-in and check-out times (WIB):\n"
            "`HH:MM , HH:MM`\n_e.g. `09:00 , 17:00`_",
            reply_markup=_back_kb(f"sd_manage_{config_id}"), parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", "await_edit_timing",
            q.message.chat_id, q.message.message_id
        )

    # ── My standups today ─────────────────────────────────────────────────────
    elif data == "sd_my_today":
        today = datetime.date.today()
        async with pool.acquire() as conn:
            sessions = await conn.fetch(
                """SELECT ss.id, ss.type, ss.status, sc.name, sc.manager
                   FROM standup_sessions ss
                   JOIN standup_configs sc ON ss.config_id = sc.id
                   WHERE ss.session_date=$1
                   AND sc.members LIKE $2
                   ORDER BY ss.type""",
                today, f"%{username}%"
            )
        if not sessions:
            await q.message.edit_text(
                "📅 *My Standups Today*\n\n_No standup sessions scheduled for today._",
                reply_markup=_back_kb(), parse_mode="Markdown"
            )
            return
        lines = [f"📅 *My Standups Today ({today.strftime('%b %d')})*\n"]
        for s in sessions:
            type_label = "Check-in 🌅" if s["type"] == "checkin" else "Check-out 🌇"
            status_icon = {"pending": "⏳", "submitted": "📤", "approved": "✅",
                           "rejected": "❌"}.get(s["status"], "⏳")
            lines.append(f"{status_icon} {type_label} — {s['name']} (by @{s['manager']})")
        await q.message.edit_text(
            "\n".join(lines), reply_markup=_back_kb(), parse_mode="Markdown"
        )

    # ── Skip checkin notes (inline button) ──────────────────────────────────────
    elif data.startswith("sd_skip_notes_"):
        session_id = int(data[14:])
        cancel_text_input_timeout(context, uid, "sd_state")
        panel = context.user_data.get("sd_panel", (uid, None))
        context.user_data.pop("sd_state", None)
        await _submit_checkin(context, pool, session_id, username, uid, None, panel)

    # ── Task status buttons ───────────────────────────────────────────────────
    elif data.startswith("sd_ts_") and not data.startswith("sd_ts_submit"):
        # format: sd_ts_{session_id}_{task_idx}_{status}
        parts     = data[6:].split("_")
        session_id = int(parts[0])
        task_idx   = int(parts[1])
        status     = parts[2]

        key = f"sd_ts_{session_id}"
        statuses = context.user_data.get(key, {})
        statuses[str(task_idx)] = status
        context.user_data[key] = statuses

        # Rebuild task status keyboard
        tasks_raw = context.user_data.get(f"sd_tasks_{session_id}", [])
        if not tasks_raw:
            async with pool.acquire() as conn:
                resp = await conn.fetchrow(
                    "SELECT tasks FROM standup_responses WHERE session_id=$1 AND LOWER(member)=$2",
                    session_id, username.lower()
                )
                tasks_raw = json.loads(resp["tasks"]) if resp and resp["tasks"] else []
                context.user_data[f"sd_tasks_{session_id}"] = tasks_raw

        text, kb = _task_status_kb(tasks_raw, statuses, session_id, username)
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass

    # ── Task status submit ────────────────────────────────────────────────────
    elif data.startswith("sd_ts_submit_"):
        parts      = data[13:].split("_", 1)
        session_id = int(parts[0])
        member     = parts[1] if len(parts) > 1 else username

        key      = f"sd_ts_{session_id}"
        statuses = context.user_data.get(key, {})
        tasks    = context.user_data.get(f"sd_tasks_{session_id}", [])

        if len(statuses) < len(tasks):
            return await q.answer(
                f"Please set status for all {len(tasks)} tasks first.", show_alert=True
            )

        # Save statuses, prompt for blockers
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE standup_responses SET task_statuses=$1 WHERE session_id=$2 AND LOWER(member)=$3",
                json.dumps(statuses), session_id, member.lower()
            )

        context.user_data["sd_state"]      = f"await_blockers_{session_id}"
        context.user_data["sd_panel"]      = (q.message.chat_id, q.message.message_id)
        await q.message.edit_text(
            "🚧 *Any blockers?* _(optional)_\n\n"
            "Describe anything that blocked your tasks, or type `none` to skip.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭️ Skip", callback_data=f"sd_skip_blockers_{session_id}")
            ]]),
            parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", f"await_blockers_{session_id}",
            q.message.chat_id, q.message.message_id
        )

    # ── Skip blockers ─────────────────────────────────────────────────────────
    elif data.startswith("sd_skip_blockers_"):
        session_id = int(data[17:])
        context.user_data["sd_state"] = f"await_extra_notes_{session_id}"
        context.user_data["sd_panel"] = (q.message.chat_id, q.message.message_id)
        await q.message.edit_text(
            "📝 *Additional notes?* _(optional)_\n\n"
            "Any notes for teammates or tomorrow's standup. Type `none` to skip.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭️ Skip", callback_data=f"sd_skip_extranotes_{session_id}")
            ]]),
            parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", f"await_extra_notes_{session_id}",
            q.message.chat_id, q.message.message_id
        )

    # ── Skip extra notes ──────────────────────────────────────────────────────
    elif data.startswith("sd_skip_extranotes_"):
        session_id = int(data[19:])
        await _submit_checkout(q, context, pool, session_id, username, blockers=None, extra=None)

    # ── Check-in method choice ────────────────────────────────────────────────
    elif data.startswith("sd_checkin_here_"):
        session_id = int(data[16:])
        context.user_data["sd_state"] = f"await_tasks_{session_id}"
        context.user_data["sd_panel"] = (q.message.chat_id, q.message.message_id)
        await q.message.edit_text(
            "🌅 *Check-in — Step 1 of 2*\n\n"
            "📝 *List your to-do tasks for today:*\n\n"
            "One task per line (or separate with `.`)\n"
            "Example:\n`> Review PR from Ahmad\n> Write meeting notes\n> Update dashboard`",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚪 Cancel", callback_data="sd_close")
            ]]),
            parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", f"await_tasks_{session_id}",
            q.message.chat_id, q.message.message_id
        )

    elif data.startswith("sd_checkin_discord_"):
        session_id = int(data[19:])
        async with pool.acquire() as conn:
            sess = await conn.fetchrow(
                "SELECT sc.manager FROM standup_sessions ss "
                "JOIN standup_configs sc ON ss.config_id=sc.id WHERE ss.id=$1",
                session_id
            )
        manager = sess["manager"] if sess else "your manager"
        await q.message.edit_text(
            f"💬 Got it! Please complete your check-in with @{manager} on Discord.\n\n"
            "I'll remind you in 1 hour if it's not submitted.",
            reply_markup=_discord_reminder_kb(session_id, "checkin"),
            parse_mode="Markdown"
        )
        # Schedule 1-hour reminder
        context.job_queue.run_once(
            _discord_reminder_job,
            when=3600,
            data={"session_id": session_id, "member": username,
                  "type": "checkin", "user_id": uid},
            name=f"sd_discord_{session_id}_{username}"
        )

    # ── Check-out method choice ───────────────────────────────────────────────
    elif data.startswith("sd_checkout_here_"):
        session_id = int(data[17:])
        # Load their check-in tasks
        async with pool.acquire() as conn:
            resp = await conn.fetchrow(
                "SELECT tasks FROM standup_responses WHERE session_id=$1 AND LOWER(member)=$2",
                session_id, username.lower()
            )
        tasks = json.loads(resp["tasks"]) if resp and resp["tasks"] else []
        context.user_data[f"sd_tasks_{session_id}"] = tasks
        context.user_data[f"sd_ts_{session_id}"]    = {}

        if not tasks:
            # No check-in tasks found — ask them to list tasks directly
            context.user_data["sd_state"] = f"await_checkout_tasks_{session_id}"
            context.user_data["sd_panel"] = (q.message.chat_id, q.message.message_id)
            await q.message.edit_text(
                "🌇 *Check-out*\n\n"
                "No check-in tasks found. List the tasks you worked on today:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🚪 Cancel", callback_data="sd_close")
                ]]),
                parse_mode="Markdown"
            )
            schedule_text_input_timeout(
                context, uid, "sd_state", f"await_checkout_tasks_{session_id}",
                q.message.chat_id, q.message.message_id
            )
            return

        text, kb = _task_status_kb(tasks, {}, session_id, username)
        await q.message.edit_text(
            "🌇 *Check-out — Mark your task statuses:*\n\n" + text,
            reply_markup=kb, parse_mode="Markdown"
        )

    elif data.startswith("sd_checkout_discord_"):
        session_id = int(data[20:])
        async with pool.acquire() as conn:
            sess = await conn.fetchrow(
                "SELECT sc.manager FROM standup_sessions ss "
                "JOIN standup_configs sc ON ss.config_id=sc.id WHERE ss.id=$1",
                session_id
            )
        manager = sess["manager"] if sess else "your manager"
        await q.message.edit_text(
            f"💬 Got it! Please complete your check-out with @{manager} on Discord.\n\n"
            "I'll remind you in 1 hour if it's not submitted.",
            reply_markup=_discord_reminder_kb(session_id, "checkout"),
            parse_mode="Markdown"
        )
        context.job_queue.run_once(
            _discord_reminder_job,
            when=3600,
            data={"session_id": session_id, "member": username,
                  "type": "checkout", "user_id": uid},
            name=f"sd_discord_{session_id}_{username}"
        )

    # ── Approval ──────────────────────────────────────────────────────────────
    elif data.startswith("sd_approve_"):
        response_id = int(data[11:])
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE standup_responses SET approved=TRUE WHERE id=$1", response_id
            )
            resp = await conn.fetchrow("SELECT * FROM standup_responses WHERE id=$1", response_id)
            sess = await conn.fetchrow(
                "SELECT ss.*, sc.name, sc.manager, sc.members FROM standup_sessions ss "
                "JOIN standup_configs sc ON ss.config_id=sc.id WHERE ss.id=$1",
                resp["session_id"]
            )
        await q.answer("✅ Approved!", show_alert=True)
        try:
            await q.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        # Notify member
        member_uid = await _get_user_id(pool, resp["member"])
        if member_uid:
            stype = "Check-in" if sess["type"] == "checkin" else "Check-out"
            try:
                await context.bot.send_message(
                    member_uid,
                    f"✅ Your *{stype}* standup has been approved by @{sess['manager']}!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        # Check if all members done → trigger AI summary
        await _check_all_done(context, pool, resp["session_id"], sess)

    # ── Rejection ─────────────────────────────────────────────────────────────
    elif data.startswith("sd_reject_"):
        response_id = int(data[10:])
        context.user_data["sd_state"]       = f"await_reject_note_{response_id}"
        context.user_data["sd_panel"]       = (q.message.chat_id, q.message.message_id)
        await q.message.edit_text(
            "❌ *Reject Standup*\n\nType a note explaining why (will be sent to the member):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚪 Cancel", callback_data=f"sd_approve_{response_id}")
            ]]),
            parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", f"await_reject_note_{response_id}",
            q.message.chat_id, q.message.message_id
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEXT INPUT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_standup_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("sd_state")
    if not state:
        return False
    if update.effective_chat.type != "private":
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)
    panel    = context.user_data.get("sd_panel", (uid, None))

    async def _reshow(panel_text: str, kb: InlineKeyboardMarkup, err: str = None):
        """Show an error then re-render the panel guide."""
        if err:
            await update.message.reply_text(f"❌ {err}")
        if panel[1]:
            try:
                await context.bot.edit_message_text(
                    chat_id=panel[0], message_id=panel[1],
                    text=panel_text, reply_markup=kb, parse_mode="Markdown"
                )
            except Exception:
                pass

    # ── Step 1: Name ──────────────────────────────────────────────────────────
    if state == "await_name":
        if not text:
            await _reshow(
                "➕ *New Standup Config — Step 1 of 5*\n\nGive this standup a *name*:",
                _back_kb(), "Name cannot be empty."
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        context.user_data["sd_draft"]["name"] = text
        context.user_data["sd_state"] = "await_members"
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=(
                f"➕ *New Standup Config — Step 2 of 5*\n\n"
                f"Name: *{text}*\n\n"
                "Type the *member usernames* (comma-separated):\n"
                "`@alice, @bob, @carol`"
            ),
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", "await_members", panel[0], panel[1]
        )
        return True

    # ── Step 2: Members ───────────────────────────────────────────────────────
    elif state == "await_members":
        members = [m.strip().lstrip("@").lower()
                   for m in text.replace(",", " ").split() if m.strip()]
        if not members:
            await _reshow(
                "➕ *Step 2 of 5*\n\nType member usernames (comma-separated):",
                _back_kb(), "Please enter at least one member username."
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        context.user_data["sd_draft"]["members"] = members
        context.user_data["sd_state"] = "await_recurrence"
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=(
                f"➕ *New Standup Config — Step 3 of 5*\n\n"
                f"Members: {', '.join('@'+m for m in members)}\n\n"
                "Choose the *recurrence*:"
            ),
            reply_markup=_recurrence_kb(), parse_mode="Markdown"
        )
        return True

    # ── Step 4: Check-in time ─────────────────────────────────────────────────
    elif state == "await_checkin_time":
        if not re.match(r"^\d{1,2}:\d{2}$", text):
            await _reshow(
                "➕ *Step 4 of 5*\n\nType the *check-in time* (WIB):\n`HH:MM`",
                _back_kb(), "Invalid time format. Use HH:MM, e.g. `09:00`"
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        context.user_data["sd_draft"]["checkin_time"] = text.zfill(5)
        context.user_data["sd_state"] = "await_checkout_time"
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=(
                f"➕ *New Standup Config — Step 5 of 5*\n\n"
                f"Check-in: *{text} WIB*\n\n"
                "Type the *check-out time* (WIB):\n`HH:MM`"
            ),
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", "await_checkout_time", panel[0], panel[1]
        )
        return True

    # ── Step 5: Check-out time → Save config ──────────────────────────────────
    elif state == "await_checkout_time":
        if not re.match(r"^\d{1,2}:\d{2}$", text):
            await _reshow(
                "➕ *Step 5 of 5*\n\nType the *check-out time* (WIB):\n`HH:MM`",
                _back_kb(), "Invalid time format. Use HH:MM, e.g. `17:00`"
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        draft = context.user_data.pop("sd_draft", {})
        draft["checkout_time"] = text.zfill(5)

        async with pool.acquire() as conn:
            config_id = await conn.fetchval(
                "INSERT INTO standup_configs "
                "(manager, name, members, recurrence, checkin_time, checkout_time, status) "
                "VALUES ($1,$2,$3,$4,$5,$6,'active') RETURNING id",
                draft.get("manager", username),
                draft.get("name", "Standup"),
                json.dumps(draft.get("members", [])),
                draft.get("recurrence", "weekday"),
                draft.get("checkin_time", "09:00"),
                draft.get("checkout_time", "17:00"),
            )

        context.user_data.pop("sd_state", None)
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=(
                f"✅ *Standup Config #{config_id} Created!*\n\n"
                f"📛 Name: {draft['name']}\n"
                f"👥 Members: {', '.join('@'+m for m in draft.get('members', []))}\n"
                f"🔁 Recurrence: {RECURRENCE_LABELS.get(draft['recurrence'], draft['recurrence'])}\n"
                f"🌅 Check-in: {draft['checkin_time']} WIB\n"
                f"🌇 Check-out: {draft['checkout_time']} WIB\n\n"
                "_The bot will DM members at the scheduled times._"
            ),
            reply_markup=_back_kb(), parse_mode="Markdown"
        )
        return True

    # ── Edit members ──────────────────────────────────────────────────────────
    elif state == "await_edit_members":
        members = [m.strip().lstrip("@").lower()
                   for m in text.replace(",", " ").split() if m.strip()]
        if not members:
            await _reshow(
                "✏️ *Edit Members*\n\nType usernames comma-separated:\n`@alice, @bob`",
                _back_kb(), "Please enter at least one username."
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        config_id = context.user_data.pop("sd_edit_id", None)
        context.user_data.pop("sd_state", None)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE standup_configs SET members=$1 WHERE id=$2",
                json.dumps(members), config_id
            )
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=f"✅ Members updated: {', '.join('@'+m for m in members)}",
            reply_markup=_back_kb(f"sd_manage_{config_id}"), parse_mode="Markdown"
        )
        return True

    # ── Edit timing ───────────────────────────────────────────────────────────
    elif state == "await_edit_timing":
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 2 or not all(re.match(r"^\d{1,2}:\d{2}$", p) for p in parts):
            await _reshow(
                "⏰ *Edit Timing*\n\nFormat: `HH:MM , HH:MM`\n_e.g. `09:00 , 17:00`_",
                _back_kb(), "Invalid format. Use: `HH:MM , HH:MM`"
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        config_id = context.user_data.pop("sd_edit_id", None)
        context.user_data.pop("sd_state", None)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE standup_configs SET checkin_time=$1, checkout_time=$2 WHERE id=$3",
                parts[0].zfill(5), parts[1].zfill(5), config_id
            )
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=f"✅ Timing updated: Check-in {parts[0]} · Check-out {parts[1]} WIB",
            reply_markup=_back_kb(f"sd_manage_{config_id}"), parse_mode="Markdown"
        )
        return True

    # ── Check-in tasks ────────────────────────────────────────────────────────
    elif state.startswith("await_tasks_"):
        session_id = int(state.split("_")[-1])
        tasks = _parse_tasks(text)
        if not tasks:
            await _reshow(
                "🌅 *Check-in — Step 1 of 2*\n\n📝 List your to-do tasks (one per line or separated by `.`):",
                InlineKeyboardMarkup([[InlineKeyboardButton("🚪 Cancel", callback_data="sd_close")]]),
                "No tasks found. Please list at least one task."
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO standup_responses (session_id, member, tasks, method, submitted_at) "
                "VALUES ($1,$2,$3,'bot',NULL) ON CONFLICT (session_id, member) DO UPDATE SET tasks=$3",
                session_id, username, json.dumps(tasks)
            )
        context.user_data["sd_state"] = f"await_checkin_notes_{session_id}"
        context.user_data[f"sd_tasks_{session_id}"] = tasks
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=(
                f"🌅 *Check-in — Step 2 of 2*\n\n"
                f"Tasks logged:\n{_fmt_tasks(tasks)}\n\n"
                "📝 *Any notes for the team?* _(optional — type `none` to skip)_"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭️ Skip", callback_data=f"sd_skip_notes_{session_id}")
            ]]),
            parse_mode="Markdown"
        )
        schedule_text_input_timeout(
            context, uid, "sd_state", f"await_checkin_notes_{session_id}",
            panel[0], panel[1]
        )
        return True

    # ── Check-in notes ────────────────────────────────────────────────────────
    elif state.startswith("await_checkin_notes_"):
        session_id = int(state.split("_")[-1])
        notes = None if text.lower() in ("none", "skip", "-") else text
        cancel_text_input_timeout(context, uid, "sd_state")
        await _submit_checkin(context, pool, session_id, username, uid, notes, panel)
        context.user_data.pop("sd_state", None)
        return True

    # ── Skip check-in notes (via text "none") ─────────────────────────────────
    # Handled by button sd_skip_notes_ in callback — but also handle typed "none"
    elif state.startswith("await_checkin_notes_") and text.lower() in ("none", "skip"):
        session_id = int(state.split("_")[-1])
        cancel_text_input_timeout(context, uid, "sd_state")
        await _submit_checkin(context, pool, session_id, username, uid, None, panel)
        context.user_data.pop("sd_state", None)
        return True

    # ── Check-out tasks (no prior check-in) ───────────────────────────────────
    elif state.startswith("await_checkout_tasks_"):
        session_id = int(state.split("_")[-1])
        tasks = _parse_tasks(text)
        if not tasks:
            await _reshow(
                "🌇 *Check-out*\n\nList the tasks you worked on today:",
                InlineKeyboardMarkup([[InlineKeyboardButton("🚪 Cancel", callback_data="sd_close")]]),
                "No tasks found. Please list at least one task."
            )
            return True
        cancel_text_input_timeout(context, uid, "sd_state")
        context.user_data[f"sd_tasks_{session_id}"] = tasks
        context.user_data[f"sd_ts_{session_id}"]    = {}
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO standup_responses (session_id, member, tasks, method) "
                "VALUES ($1,$2,$3,'bot') ON CONFLICT (session_id, member) DO UPDATE SET tasks=$3",
                session_id, username, json.dumps(tasks)
            )
        text_msg, kb = _task_status_kb(tasks, {}, session_id, username)
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text="🌇 *Check-out — Mark your task statuses:*\n\n" + text_msg,
            reply_markup=kb, parse_mode="Markdown"
        )
        context.user_data.pop("sd_state", None)
        return True

    # ── Blockers ──────────────────────────────────────────────────────────────
    elif state.startswith("await_blockers_"):
        session_id = int(state.split("_")[-1])
        blockers = None if text.lower() in ("none", "skip", "-") else text
        cancel_text_input_timeout(context, uid, "sd_state")
        context.user_data["sd_state"] = f"await_extra_notes_{session_id}"
        await context.bot.edit_message_text(
            chat_id=panel[0], message_id=panel[1],
            text=(
                "📝 *Additional notes?* _(optional)_\n\n"
                "Notes for teammates or tomorrow's standup. Type `none` to skip."
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭️ Skip", callback_data=f"sd_skip_extranotes_{session_id}")
            ]]),
            parse_mode="Markdown"
        )
        context.user_data[f"sd_blockers_{session_id}"] = blockers
        schedule_text_input_timeout(
            context, uid, "sd_state", f"await_extra_notes_{session_id}",
            panel[0], panel[1]
        )
        return True

    # ── Extra notes ───────────────────────────────────────────────────────────
    elif state.startswith("await_extra_notes_"):
        session_id = int(state.split("_")[-1])
        extra    = None if text.lower() in ("none", "skip", "-") else text
        blockers = context.user_data.pop(f"sd_blockers_{session_id}", None)
        cancel_text_input_timeout(context, uid, "sd_state")
        await _submit_checkout(
            update, context, pool, session_id, username, blockers, extra, panel=panel
        )
        context.user_data.pop("sd_state", None)
        return True

    # ── Reject note ───────────────────────────────────────────────────────────
    elif state.startswith("await_reject_note_"):
        response_id = int(state.split("_")[-1])
        cancel_text_input_timeout(context, uid, "sd_state")
        context.user_data.pop("sd_state", None)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE standup_responses SET approved=FALSE, reject_note=$1 WHERE id=$2",
                text, response_id
            )
            resp = await conn.fetchrow("SELECT * FROM standup_responses WHERE id=$1", response_id)
            sess = await conn.fetchrow(
                "SELECT ss.*, sc.name, sc.manager FROM standup_sessions ss "
                "JOIN standup_configs sc ON ss.config_id=sc.id WHERE ss.id=$1",
                resp["session_id"]
            )
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=panel[0], message_id=panel[1], reply_markup=None
            )
        except Exception:
            pass
        # Notify member to redo
        member_uid = await _get_user_id(pool, resp["member"])
        if member_uid:
            stype = "Check-in" if sess["type"] == "checkin" else "Check-out"
            tasks_text = ""
            if resp["tasks"]:
                tasks_text = (
                    f"\n\n_Your previous response (for easy copy-paste):_\n"
                    f"{_fmt_tasks(json.loads(resp['tasks']))}"
                )
            try:
                msg = await context.bot.send_message(
                    member_uid,
                    f"❌ *Your {stype} standup was rejected by @{sess['manager']}.*\n\n"
                    f"📝 Reason: _{text}_\n\n"
                    f"Please redo your {stype} standup.{tasks_text}",
                    reply_markup=_checkin_method_kb(sess["id"], sess["manager"])
                    if stype == "Check-in" else
                    _checkout_method_kb(sess["id"], sess["manager"]),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        await update.message.reply_text(f"❌ Standup rejected. @{resp['member']} has been notified.")
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# SKIP CALLBACKS (from inline "Skip" buttons)
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_skip_callbacks(q, context, pool, data, username, uid):
    """Handle sd_skip_notes_ callbacks from the check-in notes step."""
    if data.startswith("sd_skip_notes_"):
        session_id = int(data[14:])
        cancel_text_input_timeout(context, uid, "sd_state")
        panel = context.user_data.get("sd_panel", (uid, None))
        await _submit_checkin(context, pool, session_id, username, uid, None, panel)
        context.user_data.pop("sd_state", None)
        try:
            await q.message.delete()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# SUBMIT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _submit_checkin(context, pool, session_id: int, member: str,
                           uid: int, notes: str | None, panel: tuple):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE standup_responses SET notes=$1, submitted_at=NOW() WHERE session_id=$2 AND LOWER(member)=$3",
            notes, session_id, member.lower()
        )
        resp = await conn.fetchrow(
            "SELECT sr.id, sr.tasks FROM standup_responses sr WHERE sr.session_id=$1 AND LOWER(sr.member)=$2",
            session_id, member.lower()
        )
        sess = await conn.fetchrow(
            "SELECT ss.*, sc.name, sc.manager FROM standup_sessions ss "
            "JOIN standup_configs sc ON ss.config_id=sc.id WHERE ss.id=$1",
            session_id
        )

    tasks = json.loads(resp["tasks"]) if resp and resp["tasks"] else []
    manager = sess["manager"] if sess else "manager"

    # Update panel
    if panel[1]:
        try:
            await context.bot.edit_message_text(
                chat_id=panel[0], message_id=panel[1],
                text=(
                    "✅ *Check-in submitted!*\n\n"
                    f"📝 Tasks:\n{_fmt_tasks(tasks)}\n\n"
                    + (f"💬 Notes: _{notes}_\n\n" if notes else "") +
                    "_Waiting for manager approval…_"
                ),
                reply_markup=None, parse_mode="Markdown"
            )
        except Exception:
            pass

    # Notify manager
    manager_uid = await _get_user_id(pool, manager)
    if manager_uid and resp:
        notes_line = f"\n💬 Notes: _{notes}_" if notes else ""
        try:
            await context.bot.send_message(
                manager_uid,
                f"📥 *Check-in from @{member}*\n"
                f"📛 Standup: {sess['name']}\n"
                f"🕒 {datetime.datetime.now(WIB).strftime('%H:%M WIB')}\n\n"
                f"📋 Tasks:\n{_fmt_tasks(tasks)}{notes_line}",
                reply_markup=_approval_kb(resp["id"]),
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def _submit_checkout(source, context, pool, session_id: int, member: str,
                            blockers: str | None, extra: str | None, panel: tuple = None):
    """Finalise checkout — save and notify manager."""
    key      = f"sd_ts_{session_id}"
    statuses = context.user_data.pop(key, {})
    tasks    = context.user_data.pop(f"sd_tasks_{session_id}", [])

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO standup_responses "
            "(session_id, member, task_statuses, blockers, extra_notes, submitted_at, method) "
            "VALUES ($1,$2,$3,$4,$5,NOW(),'bot') "
            "ON CONFLICT (session_id, member) DO UPDATE SET "
            "task_statuses=$3, blockers=$4, extra_notes=$5, submitted_at=NOW()",
            session_id, member, json.dumps(statuses), blockers, extra
        )
        resp = await conn.fetchrow(
            "SELECT id FROM standup_responses WHERE session_id=$1 AND LOWER(member)=$2",
            session_id, member.lower()
        )
        sess = await conn.fetchrow(
            "SELECT ss.*, sc.name, sc.manager FROM standup_sessions ss "
            "JOIN standup_configs sc ON ss.config_id=sc.id WHERE ss.id=$1",
            session_id
        )

    icons = {"complete": "✅", "pending": "⌛", "cancelled": "❌"}
    task_lines = "\n".join(
        f"{icons.get(statuses.get(str(i), ''), '⬜')} {t}"
        for i, t in enumerate(tasks)
    ) if tasks else "_No tasks_"

    if panel and panel[1]:
        try:
            await context.bot.edit_message_text(
                chat_id=panel[0], message_id=panel[1],
                text=(
                    "✅ *Check-out submitted!*\n\n"
                    f"📋 Tasks:\n{task_lines}\n\n"
                    + (f"🚧 Blockers: _{blockers}_\n" if blockers else "") +
                    (f"📝 Notes: _{extra}_\n" if extra else "") +
                    "\n_Waiting for manager approval…_"
                ),
                reply_markup=None, parse_mode="Markdown"
            )
        except Exception:
            pass

    manager = sess["manager"] if sess else "manager"
    manager_uid = await _get_user_id(pool, manager)
    if manager_uid and resp:
        try:
            await context.bot.send_message(
                manager_uid,
                f"📥 *Check-out from @{member}*\n"
                f"📛 Standup: {sess['name']}\n"
                f"🕒 {datetime.datetime.now(WIB).strftime('%H:%M WIB')}\n\n"
                f"📋 Task statuses:\n{task_lines}\n"
                + (f"🚧 Blockers: _{blockers}_\n" if blockers else "") +
                (f"📝 Notes: _{extra}_\n" if extra else ""),
                reply_markup=_approval_kb(resp["id"]),
                parse_mode="Markdown"
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ALL-DONE CHECK + AI SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

async def _check_all_done(context, pool, session_id: int, sess):
    """If all members approved, send AI summary to manager."""
    try:
        members_raw = sess["members"]
    except (KeyError, IndexError):
        members_raw = "[]"
    members = json.loads(members_raw or "[]")
    if not members:
        return

    async with pool.acquire() as conn:
        approved = await conn.fetch(
            "SELECT * FROM standup_responses WHERE session_id=$1 AND approved=TRUE",
            session_id
        )

    if len(approved) < len(members):
        return  # not all done yet

    stype = "Check-in" if sess["type"] == "checkin" else "Check-out"
    manager_uid = await _get_user_id(pool, sess["manager"])
    if not manager_uid:
        return

    # Build AI prompt
    lines = [f"You are summarising a team {stype} standup for the manager @{sess['manager']}."]
    lines.append(f"Standup: {sess['name']} | Date: {datetime.date.today().strftime('%b %d, %Y')}")
    lines.append(f"Session type: {stype}\n")
    for r in approved:
        tasks    = json.loads(r["tasks"] or "[]")
        statuses = json.loads(r["task_statuses"] or "{}")
        icons    = {"complete": "✅", "pending": "⌛", "cancelled": "❌"}
        task_text = "\n".join(
            f"  {icons.get(statuses.get(str(i),''),'⬜')} {t}"
            for i, t in enumerate(tasks)
        ) or "  (no tasks)"
        lines.append(
            f"@{r['member']}:\n{task_text}"
            + (f"\n  Notes: {r['notes']}" if r.get("notes") else "")
            + (f"\n  Blockers: {r['blockers']}" if r.get("blockers") else "")
            + (f"\n  Extra: {r['extra_notes']}" if r.get("extra_notes") else "")
        )

    if stype == "Check-in":
        lines.append(
            "\nProvide: (1) a quick overview of what the team will accomplish today, "
            "(2) any connected tasks between members, "
            "(3) action items or reminders for the manager. "
            "Keep it under 250 words. Use emojis. Plain text only."
        )
    else:
        lines.append(
            "\nProvide: (1) what the team accomplished today vs planned, "
            "(2) pending or blocked items needing manager attention, "
            "(3) suggestions for tomorrow based on today's blockers. "
            "Keep it under 250 words. Use emojis. Plain text only."
        )

    prompt  = "\n".join(lines)
    summary = None
    try:
        from cmd_system import _generate_content_with_retry
        resp    = await _generate_content_with_retry(None, prompt)
        summary = resp.text.strip()
    except Exception as e:
        logger.warning(f"Standup AI summary failed: {e}")

    if not summary:
        summary = (
            f"📊 *{stype} Summary — {sess['name']}*\n\n"
            f"All {len(members)} members have submitted their {stype.lower()}.\n"
            "AI summary unavailable — check individual submissions above."
        )

    try:
        await context.bot.send_message(
            manager_uid,
            f"🤖 *AI {stype} Summary — {sess['name']}*\n\n{summary}",
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD REMINDER JOB
# ─────────────────────────────────────────────────────────────────────────────

async def _discord_reminder_job(context):
    job  = context.job
    data = job.data
    uid  = data["user_id"]
    stype    = data["type"]
    session_id = data["session_id"]
    member   = data["member"]

    async with context.bot_data["db_pool"].acquire() as conn:
        resp = await conn.fetchrow(
            "SELECT submitted_at FROM standup_responses WHERE session_id=$1 AND LOWER(member)=$2",
            session_id, member.lower()
        )
        sess = await conn.fetchrow(
            "SELECT sc.manager FROM standup_sessions ss "
            "JOIN standup_configs sc ON ss.config_id=sc.id WHERE ss.id=$1",
            session_id
        )

    if resp and resp["submitted_at"]:
        return  # already submitted

    manager = sess["manager"] if sess else "your manager"
    stype_label = "check-in" if stype == "checkin" else "check-out"
    try:
        await context.bot.send_message(
            uid,
            f"⏰ *Reminder:* You haven't submitted your {stype_label} yet!\n\n"
            f"Would you like to do it here now instead?",
            reply_markup=_checkin_method_kb(session_id, manager)
            if stype == "checkin" else
            _checkout_method_kb(session_id, manager),
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULED DISPATCH (called by cron jobs)
# ─────────────────────────────────────────────────────────────────────────────

async def dispatch_standup_prompts(context, session_type: str):
    """
    Called by the cron job every minute. Sends check-in or check-out prompts
    to all members whose standup config matches the current time + day.
    session_type: 'checkin' or 'checkout'
    """
    pool = context.bot_data.get("db_pool")
    if not pool:
        return

    now      = datetime.datetime.now(WIB)
    cur_time = now.strftime("%H:%M")
    today    = now.date()
    weekday  = now.weekday()  # 0=Mon … 6=Sun

    async with pool.acquire() as conn:
        configs = await conn.fetch(
            "SELECT * FROM standup_configs WHERE status='active'"
        )

    for cfg in configs:
        trigger_time = cfg["checkin_time"] if session_type == "checkin" else cfg["checkout_time"]
        if trigger_time != cur_time:
            continue

        rec = cfg["recurrence"]
        if rec == "weekday" and weekday >= 5:
            continue
        if rec == "weekly" and weekday != 0:  # only Monday
            continue

        members = json.loads(cfg["members"] or "[]")
        if not members:
            continue

        async with pool.acquire() as conn:
            # Create session if not exists
            session_id = await conn.fetchval(
                "SELECT id FROM standup_sessions WHERE config_id=$1 AND session_date=$2 AND type=$3",
                cfg["id"], today, session_type
            )
            if not session_id:
                session_id = await conn.fetchval(
                    "INSERT INTO standup_sessions (config_id, session_date, type, status) "
                    "VALUES ($1,$2,$3,'pending') RETURNING id",
                    cfg["id"], today, session_type
                )

        manager_name = cfg["manager"]
        stype_label  = "Check-in 🌅" if session_type == "checkin" else "Check-out 🌇"

        for member in members:
            uid = await _get_user_id(pool, member)
            if not uid:
                continue

            # Check if already submitted
            async with pool.acquire() as conn:
                existing = await conn.fetchrow(
                    "SELECT submitted_at FROM standup_responses WHERE session_id=$1 AND LOWER(member)=$2",
                    session_id, member.lower()
                )
            if existing and existing["submitted_at"]:
                continue

            try:
                msg = await context.bot.send_message(
                    uid,
                    f"📋 *It's time for your {stype_label}!*\n\n"
                    f"Standup: _{cfg['name']}_\n\n"
                    f"Will you do it here with me via chat, "
                    f"or directly with @{manager_name} via Discord?",
                    reply_markup=_checkin_method_kb(session_id, manager_name)
                    if session_type == "checkin" else
                    _checkout_method_kb(session_id, manager_name),
                    parse_mode="Markdown"
                )

                # Auto-delete the prompt at checkout time (for check-in)
                # or 6 hours after for checkout
                if session_type == "checkin":
                    # Delete at checkout time
                    h, m = map(int, cfg["checkout_time"].split(":"))
                    checkout_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    delay = max(60, (checkout_dt - now).total_seconds())
                else:
                    delay = 6 * 3600  # 6 hours

                context.job_queue.run_once(
                    _auto_expire_prompt,
                    when=delay,
                    data={"chat_id": uid, "msg_id": msg.message_id,
                          "session_id": session_id, "member": member,
                          "type": session_type, "manager": manager_name,
                          "config_name": cfg["name"]},
                    name=f"sd_expire_{session_id}_{member}"
                )

                # Store prompt msg id
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO standup_responses (session_id, member, prompt_msg_id) "
                        "VALUES ($1,$2,$3) ON CONFLICT (session_id, member) DO UPDATE SET prompt_msg_id=$3",
                        session_id, member, msg.message_id
                    )
            except Exception as e:
                logger.warning(f"Failed to send standup prompt to @{member}: {e}")


async def _auto_expire_prompt(context):
    """Delete prompt if member never responded and notify manager."""
    job  = context.job
    data = job.data
    pool = context.bot_data.get("db_pool")

    async with pool.acquire() as conn:
        resp = await conn.fetchrow(
            "SELECT submitted_at FROM standup_responses WHERE session_id=$1 AND LOWER(member)=$2",
            data["session_id"], data["member"].lower()
        )

    if resp and resp["submitted_at"]:
        return  # submitted fine

    # Delete the prompt message
    try:
        await context.bot.delete_message(
            chat_id=data["chat_id"], message_id=data["msg_id"]
        )
    except Exception:
        pass

    # Notify manager of failure
    manager_uid = await _get_user_id(pool, data["manager"])
    stype = "check-in" if data["type"] == "checkin" else "check-out"
    if manager_uid:
        try:
            await context.bot.send_message(
                manager_uid,
                f"⚠️ *Missed {stype}!*\n\n"
                f"@{data['member']} did not submit their {stype} "
                f"for *{data['config_name']}*.\n"
                f"📅 {datetime.date.today().strftime('%b %d, %Y')}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
