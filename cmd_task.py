"""
cmd_task.py — /task  and  /mytask  Inline Hub
──────────────────────────────────────────────

/task behaviour:
  • In a GROUP  → shows tap-to-toggle member picker inline keyboard.
                  Tap a name to add/un-add them as assignees.
                  Status bar at top. Type task description, then Finish / Cancel.
  • In DM       → step-by-step: set group target → type task description
                  → type assignees (comma-separated) → confirm.

/mytask behaviour:
  • Always goes to DM.  Lists pending tasks with time-remaining.
  • Tap a task row to toggle Complete / Incomplete.
  • Finish button sends DM to the assigner if all assignees done.
  • Cancel button closes the panel without changes.

Callback prefix: tk_  / myt_
Owner-locked, 120-second auto-expiry.
"""

import datetime
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import (
    WIB, delete_cmd, is_bot_admin,
    schedule_kb_timeout, cancel_kb_timeout, check_kb_ownership, log_action
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_remaining(deadline) -> str:
    """Human-readable time remaining from now."""
    if deadline.tzinfo is None:
        deadline = WIB.localize(deadline)
    delta = deadline - datetime.datetime.now(WIB)
    total = int(delta.total_seconds())
    if total <= 0:
        return "⚠️ Overdue"
    if total < 3600:
        return f"{total // 60}m left"
    if total < 86400:
        h, m = divmod(total // 60, 60)
        return f"{h}h {m}m left"
    d, rem = divmod(total, 86400)
    return f"{d}d {rem // 3600}h left"


async def _ensure_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS task_assignees (
                id            SERIAL PRIMARY KEY,
                group_task_id INT NOT NULL,
                assignee      VARCHAR(100) NOT NULL,
                status        VARCHAR(20) DEFAULT 'Pending',
                completed_at  TIMESTAMP WITH TIME ZONE,
                UNIQUE(group_task_id, assignee)
            )
        """)
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS group_task_id INT DEFAULT NULL")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS total_assignees INT DEFAULT 1")
        await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_count INT DEFAULT 0")


# ─────────────────────────────────────────────────────────────────────────────
# /task — GROUP FLOW  (tap-to-toggle member picker)
# ─────────────────────────────────────────────────────────────────────────────

def _group_task_kb(members: list[str], selected: set[str], desc: str) -> InlineKeyboardMarkup:
    """
    Top status row + member toggle buttons + task desc display + Finish/Cancel.
    Selected members shown with ✅, unselected with 👤.
    """
    rows = []
    # Member buttons in pairs
    for i in range(0, len(members), 2):
        pair = []
        for m in members[i:i+2]:
            icon = "✅" if m in selected else "👤"
            pair.append(InlineKeyboardButton(f"{icon} @{m}", callback_data=f"tk_toggle_{m}"))
        rows.append(pair)

    rows.append([
        InlineKeyboardButton("✅ Finish",  callback_data="tk_finish"),
        InlineKeyboardButton("❌ Cancel",  callback_data="tk_cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _group_task_text(selected: set[str], desc: str, deadline_str: str) -> str:
    sel_list = ", ".join(f"@{m}" for m in sorted(selected)) if selected else "_None selected_"
    desc_display = f"📝 *{desc}*" if desc else "📝 _Waiting for task description…_"
    return (
        f"📋 *Assign Task*\n\n"
        f"{desc_display}\n"
        f"⏰ Due: {deadline_str}\n\n"
        f"👥 Assignees: {sel_list}\n\n"
        f"_Tap members to add/remove. Type the task description if not set yet._"
    )


async def task_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point when /task is run in a GROUP."""
    await delete_cmd(update)
    pool    = context.bot_data.get("db_pool")
    chat_id = update.effective_chat.id
    uid     = update.effective_user.id
    username = update.effective_user.username or str(uid)

    # Fetch group members from the users table (those registered in this group)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT username FROM users WHERE username IS NOT NULL AND username != $1 LIMIT 30",
            username
        )
    members = [r["username"] for r in rows]

    if not members:
        return await update.message.reply_text(
            "❌ No registered members found. Make sure members have used /start in this group."
        )

    # Default deadline: 60 min from now
    deadline = datetime.datetime.now(WIB) + datetime.timedelta(minutes=60)
    dl_str   = deadline.strftime("%b %d at %H:%M WIB")

    # Store draft in user_data
    context.user_data["tk_state"]    = "group_picking"
    context.user_data["tk_members"]  = members
    context.user_data["tk_selected"] = set()
    context.user_data["tk_desc"]     = ""
    context.user_data["tk_deadline"] = deadline
    context.user_data["tk_chat_id"]  = chat_id

    kb  = _group_task_kb(members, set(), "", )
    msg = await update.message.reply_text(
        _group_task_text(set(), "", dl_str),
        reply_markup=kb,
        parse_mode="Markdown"
    )
    context.user_data["tk_msg_id"] = msg.message_id
    await schedule_kb_timeout(context, chat_id, msg.message_id, uid)


# ─────────────────────────────────────────────────────────────────────────────
# /task — DM FLOW (step by step)
# ─────────────────────────────────────────────────────────────────────────────

async def task_dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point when /task is run in DM."""
    uid = update.effective_user.id
    pool = context.bot_data.get("db_pool")

    async with pool.acquire() as conn:
        groups = await conn.fetch(
            "SELECT DISTINCT chat_id, chat_title FROM group_settings ORDER BY chat_title ASC LIMIT 10"
        )

    context.user_data["tk_state"] = "dm_pick_group"
    context.user_data["tk_draft"] = {}

    if not groups:
        context.user_data["tk_state"] = "dm_await_group_id"
        return await update.message.reply_text(
            "📋 *Assign Task (DM)*\n\n"
            "No groups found. Type the *Group ID* to target:\n"
            "_e.g._ `-1001234567890`",
            parse_mode="Markdown"
        )

    rows = []
    for g in groups:
        rows.append([InlineKeyboardButton(
            g["chat_title"][:35],
            callback_data=f"tk_grp_{g['chat_id']}"
        )])
    rows.append([InlineKeyboardButton("🚪 Cancel", callback_data="tk_cancel")])
    msg = await update.message.reply_text(
        "📋 *Assign Task (DM)*\n\nSelect the *target group*:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown"
    )
    await schedule_kb_timeout(context, uid, msg.message_id, uid)


# ─────────────────────────────────────────────────────────────────────────────
# /task — SMART ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await task_dm_command(update, context)
    else:
        await task_group_command(update, context)


# ─────────────────────────────────────────────────────────────────────────────
# /task CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uid  = q.from_user.id
    username = q.from_user.username or str(uid)

    if not await check_kb_ownership(q, context):
        return await q.answer("This panel isn't yours.", show_alert=True)
    await q.answer()

    # ── Group picker (DM flow) ────────────────────────────────────────────────
    if data.startswith("tk_grp_"):
        chat_id = int(data[7:])
        context.user_data["tk_draft"]["chat_id"] = chat_id
        context.user_data["tk_state"] = "dm_await_desc"
        await q.message.edit_text(
            "📋 *Assign Task — Step 1 of 3*\n\n"
            "Type the *task description*:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚪 Cancel", callback_data="tk_cancel")
            ]]),
            parse_mode="Markdown"
        )

    # ── Toggle member (group flow) ────────────────────────────────────────────
    elif data.startswith("tk_toggle_"):
        member   = data[10:]
        members  = context.user_data.get("tk_members", [])
        selected = context.user_data.get("tk_selected", set())
        desc     = context.user_data.get("tk_desc", "")
        deadline = context.user_data.get("tk_deadline")
        dl_str   = deadline.strftime("%b %d at %H:%M WIB") if deadline else "TBD"

        if member in selected:
            selected.discard(member)
        else:
            selected.add(member)
        context.user_data["tk_selected"] = selected

        await q.message.edit_text(
            _group_task_text(selected, desc, dl_str),
            reply_markup=_group_task_kb(members, selected, desc),
            parse_mode="Markdown"
        )

    # ── Finish (group flow) ───────────────────────────────────────────────────
    elif data == "tk_finish":
        await _finish_group_task(q, context, pool, username)

    # ── Cancel ────────────────────────────────────────────────────────────────
    elif data == "tk_cancel":
        _clear_task_state(context)
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        try:
            await q.message.delete()
        except Exception:
            pass

    # ── Deadline quick-set ────────────────────────────────────────────────────
    elif data.startswith("tk_dl_"):
        mins     = int(data[6:])
        deadline = datetime.datetime.now(WIB) + datetime.timedelta(minutes=mins)
        context.user_data["tk_deadline"] = deadline
        dl_str   = deadline.strftime("%b %d at %H:%M WIB")
        members  = context.user_data.get("tk_members", [])
        selected = context.user_data.get("tk_selected", set())
        desc     = context.user_data.get("tk_desc", "")
        await q.message.edit_text(
            _group_task_text(selected, desc, dl_str),
            reply_markup=_group_task_kb(members, selected, desc),
            parse_mode="Markdown"
        )


async def _finish_group_task(q, context, pool, username: str):
    selected = context.user_data.get("tk_selected", set())
    desc     = context.user_data.get("tk_desc", "")
    deadline = context.user_data.get("tk_deadline")
    chat_id  = context.user_data.get("tk_chat_id")

    if not selected:
        return await q.answer("Please select at least one assignee first.", show_alert=True)
    if not desc:
        return await q.answer("Please type the task description first.", show_alert=True)

    await _ensure_tables(pool)
    assignees = list(selected)

    async with pool.acquire() as conn:
        max_t = int(await conn.fetchval("SELECT value FROM config WHERE key='max_tasks'") or 4)
        if not await is_bot_admin(username, pool):
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM tasks WHERE assigned_by=$1 AND status='Pending'", username
            )
            if count >= max_t:
                return await q.answer(f"Max {max_t} active tasks allowed.", show_alert=True)

        group_task_id = await conn.fetchval(
            "INSERT INTO tasks (assignee, task_desc, deadline, assigned_by, status, total_assignees, completed_count, group_task_id) "
            "VALUES ($1,$2,$3,$4,'Pending',$5,0,0) RETURNING id",
            assignees[0], desc, deadline, username, len(assignees)
        )
        await conn.execute("UPDATE tasks SET group_task_id=$1 WHERE id=$1", group_task_id)
        for a in assignees:
            await conn.execute(
                "INSERT INTO task_assignees (group_task_id, assignee, status) VALUES ($1,$2,'Pending') ON CONFLICT DO NOTHING",
                group_task_id, a
            )

    from cmd_admin import task_reminder
    for a in assignees:
        when = deadline - datetime.timedelta(minutes=10)
        if when > datetime.datetime.now(WIB):
            context.job_queue.run_once(
                task_reminder,
                when=when,
                data={"assignee": a, "assigner": username, "id": group_task_id, "desc": desc},
                chat_id=chat_id
            )

    # Notify each assignee by DM
    for a in assignees:
        async with pool.acquire() as conn:
            a_uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", a)
        if a_uid:
            try:
                await context.bot.send_message(
                    a_uid,
                    f"📋 *New Task Assigned!*\n\n"
                    f"📝 {desc}\n"
                    f"👤 From: @{username}\n"
                    f"⏰ Due: {deadline.strftime('%b %d at %H:%M WIB')}\n"
                    f"🔑 Task ID: `#{group_task_id}`\n\n"
                    f"_Use /mytask to mark it complete._",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await log_action(pool, q.from_user.id, chat_id, "Task Assigned", "Success",
                     f"#{group_task_id} → {', '.join(['@'+a for a in assignees])}")

    _clear_task_state(context)
    cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
    names = " ".join(f"@{a}" for a in assignees)
    await q.message.edit_text(
        f"✅ *Task `#{group_task_id}` assigned!*\n\n"
        f"📝 {desc}\n"
        f"👥 {names}\n"
        f"⏰ Due: {deadline.strftime('%b %d at %H:%M WIB')}",
        parse_mode="Markdown"
    )


def _clear_task_state(context):
    for k in ["tk_state","tk_members","tk_selected","tk_desc","tk_deadline","tk_chat_id","tk_draft","tk_msg_id"]:
        context.user_data.pop(k, None)


# ─────────────────────────────────────────────────────────────────────────────
# /task TEXT INPUT HANDLER (DM multi-step + group desc input)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("tk_state")
    if not state:
        return False

    text     = (update.message.text or "").strip()
    pool     = context.bot_data.get("db_pool")
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)

    # ── GROUP: waiting for task description ───────────────────────────────────
    if state == "group_picking" and update.effective_chat.type != "private":
        context.user_data["tk_desc"] = text
        members  = context.user_data.get("tk_members", [])
        selected = context.user_data.get("tk_selected", set())
        deadline = context.user_data.get("tk_deadline")
        dl_str   = deadline.strftime("%b %d at %H:%M WIB") if deadline else "TBD"
        chat_id  = update.effective_chat.id
        msg_id   = context.user_data.get("tk_msg_id")
        try:
            await context.bot.edit_message_text(
                _group_task_text(selected, text, dl_str),
                chat_id=chat_id, message_id=msg_id,
                reply_markup=_group_task_kb(members, selected, text),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        try:
            await update.message.delete()
        except Exception:
            pass
        return True

    # ── DM: waiting for group ID ───────────────────────────────────────────────
    if state == "dm_await_group_id" and update.effective_chat.type == "private":
        try:
            chat_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ That doesn't look like a valid Group ID. Try again:")
            return True
        context.user_data["tk_draft"]["chat_id"] = chat_id
        context.user_data["tk_state"]            = "dm_await_desc"
        await update.message.reply_text(
            "📋 *Assign Task — Step 1 of 3*\n\nType the *task description*:",
            parse_mode="Markdown"
        )
        return True

    # ── DM: waiting for task description ──────────────────────────────────────
    if state == "dm_await_desc" and update.effective_chat.type == "private":
        context.user_data["tk_draft"]["desc"] = text
        context.user_data["tk_state"]         = "dm_await_assignees"
        await update.message.reply_text(
            "📋 *Assign Task — Step 2 of 3*\n\n"
            "Type the *assignee usernames* separated by commas:\n\n"
            "_e.g._ `alice, bob, carol`",
            parse_mode="Markdown"
        )
        return True

    # ── DM: waiting for assignees ──────────────────────────────────────────────
    if state == "dm_await_assignees" and update.effective_chat.type == "private":
        assignees = [a.strip().lstrip("@").lower() for a in text.split(",") if a.strip()]
        assignees = [a for a in assignees if a != username.lower()]
        if not assignees:
            await update.message.reply_text("❌ No valid assignees. Enter usernames separated by commas:")
            return True
        context.user_data["tk_draft"]["assignees"] = assignees
        context.user_data["tk_state"]             = "dm_await_deadline"
        await update.message.reply_text(
            "📋 *Assign Task — Step 3 of 3*\n\n"
            "How many *minutes* until the deadline? (30–1440)\n\n"
            "_e.g._ `120` _(for 2 hours from now)_",
            parse_mode="Markdown"
        )
        return True

    # ── DM: waiting for deadline minutes ──────────────────────────────────────
    if state == "dm_await_deadline" and update.effective_chat.type == "private":
        try:
            mins = int(text)
            if mins < 30 or mins > 1440:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Enter a number between 30 and 1440:")
            return True

        draft    = context.user_data.get("tk_draft", {})
        desc     = draft.get("desc", "")
        chat_id  = draft.get("chat_id")
        assignees = draft.get("assignees", [])
        deadline  = datetime.datetime.now(WIB) + datetime.timedelta(minutes=mins)

        await _ensure_tables(pool)
        async with pool.acquire() as conn:
            max_t = int(await conn.fetchval("SELECT value FROM config WHERE key='max_tasks'") or 4)
            if not await is_bot_admin(username, pool):
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM tasks WHERE assigned_by=$1 AND status='Pending'", username
                )
                if count >= max_t:
                    _clear_task_state(context)
                    await update.message.reply_text(f"❌ You've hit the limit of {max_t} active tasks.")
                    return True

            group_task_id = await conn.fetchval(
                "INSERT INTO tasks (assignee, task_desc, deadline, assigned_by, status, total_assignees, completed_count, group_task_id) "
                "VALUES ($1,$2,$3,$4,'Pending',$5,0,0) RETURNING id",
                assignees[0], desc, deadline, username, len(assignees)
            )
            await conn.execute("UPDATE tasks SET group_task_id=$1 WHERE id=$1", group_task_id)
            for a in assignees:
                await conn.execute(
                    "INSERT INTO task_assignees (group_task_id, assignee, status) VALUES ($1,$2,'Pending') ON CONFLICT DO NOTHING",
                    group_task_id, a
                )

        from cmd_admin import task_reminder
        for a in assignees:
            when = deadline - datetime.timedelta(minutes=10)
            if when > datetime.datetime.now(WIB):
                context.job_queue.run_once(
                    task_reminder,
                    when=when,
                    data={"assignee": a, "assigner": username, "id": group_task_id, "desc": desc},
                    chat_id=chat_id or uid
                )
            async with pool.acquire() as conn:
                a_uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", a)
            if a_uid:
                try:
                    await context.bot.send_message(
                        a_uid,
                        f"📋 *New Task Assigned!*\n\n"
                        f"📝 {desc}\n"
                        f"👤 From: @{username}\n"
                        f"⏰ Due: {deadline.strftime('%b %d at %H:%M WIB')}\n"
                        f"🔑 Task ID: `#{group_task_id}`\n\n"
                        f"_Use /mytask to manage it._",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

        _clear_task_state(context)
        names = " ".join(f"@{a}" for a in assignees)
        await update.message.reply_text(
            f"✅ *Task `#{group_task_id}` assigned!*\n\n"
            f"📝 {desc}\n"
            f"👥 {names}\n"
            f"⏰ Due: {deadline.strftime('%b %d at %H:%M WIB')}",
            parse_mode="Markdown"
        )
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# /mytask — DM INLINE LIST
# ─────────────────────────────────────────────────────────────────────────────

async def mytask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Always sends task list to DM as inline keyboard."""
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)
    pool     = context.bot_data.get("db_pool")

    await _ensure_tables(pool)

    async with pool.acquire() as conn:
        group_tasks = await conn.fetch(
            """SELECT ta.group_task_id AS id, t.task_desc, t.deadline,
                      t.completed_count, t.total_assignees, ta.status AS my_status,
                      t.assigned_by
               FROM task_assignees ta
               JOIN tasks t ON t.id = ta.group_task_id
               WHERE LOWER(ta.assignee)=$1 AND ta.status='Pending'
               ORDER BY t.deadline""",
            username.lower()
        )
        legacy_tasks = await conn.fetch(
            "SELECT id, task_desc, deadline, assigned_by FROM tasks "
            "WHERE status='Pending' AND LOWER(assignee)=$1 AND group_task_id IS NULL ORDER BY deadline",
            username.lower()
        )

    all_tasks = list(group_tasks) + list(legacy_tasks)

    if not all_tasks:
        try:
            await context.bot.send_message(uid, "✅ *No pending tasks!* You're all caught up. 🎉", parse_mode="Markdown")
        except Exception:
            if update.message:
                await update.message.reply_text("✅ No pending tasks!")
        return

    # Store task ids in user_data for toggle callbacks
    context.user_data["myt_tasks"]   = {str(t["id"]): dict(t) for t in all_tasks}
    context.user_data["myt_toggled"] = {}   # id → True if marked complete in this session

    kb, text = _build_mytask_kb_text(all_tasks, context.user_data["myt_toggled"])
    try:
        msg = await context.bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")
        await schedule_kb_timeout(context, uid, msg.message_id, uid)
    except Exception:
        if update.message:
            await update.message.reply_text("❌ Please start a DM with me first by clicking /start.")


def _build_mytask_kb_text(tasks, toggled: dict) -> tuple:
    rows = []
    lines = ["📋 *My Pending Tasks*\n"]
    for t in tasks:
        t_id    = str(t["id"])
        is_done = toggled.get(t_id, False)
        icon    = "✅" if is_done else "🔲"
        remain  = _fmt_remaining(t["deadline"])
        prog    = f"({t['completed_count']}/{t['total_assignees']})" if t.get("total_assignees", 1) > 1 else ""
        desc    = (t["task_desc"] or "")[:40]
        lines.append(f"{icon} `#{t_id}` {desc} — _{remain}_ {prog}")
        rows.append([InlineKeyboardButton(
            f"{icon} #{t_id} {desc[:25]}",
            callback_data=f"myt_toggle_{t_id}"
        )])

    rows.append([
        InlineKeyboardButton("💾 Finish",  callback_data="myt_finish"),
        InlineKeyboardButton("🚪 Cancel",  callback_data="myt_cancel"),
    ])
    return InlineKeyboardMarkup(rows), "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# /mytask CALLBACK ROUTER
# ─────────────────────────────────────────────────────────────────────────────

async def mytask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    pool = context.bot_data.get("db_pool")
    uid  = q.from_user.id
    username = q.from_user.username or str(uid)

    if not await check_kb_ownership(q, context):
        return await q.answer("This panel isn't yours.", show_alert=True)
    await q.answer()

    # ── Toggle task complete/incomplete ───────────────────────────────────────
    if data.startswith("myt_toggle_"):
        t_id = data[11:]
        toggled = context.user_data.get("myt_toggled", {})
        toggled[t_id] = not toggled.get(t_id, False)
        context.user_data["myt_toggled"] = toggled

        tasks = list(context.user_data.get("myt_tasks", {}).values())
        kb, text = _build_mytask_kb_text(tasks, toggled)
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass

    # ── Finish — write completions to DB ─────────────────────────────────────
    elif data == "myt_finish":
        toggled  = context.user_data.get("myt_toggled", {})
        done_ids = [t_id for t_id, done in toggled.items() if done]

        if not done_ids:
            return await q.answer("No tasks marked complete yet.", show_alert=True)

        newly_finished = []
        async with pool.acquire() as conn:
            for t_id in done_ids:
                tid = int(t_id)
                # Group task path
                ta = await conn.fetchrow(
                    "SELECT id, status FROM task_assignees WHERE group_task_id=$1 AND LOWER(assignee)=$2",
                    tid, username.lower()
                )
                if ta and ta["status"] != "Completed":
                    now = datetime.datetime.now(WIB)
                    await conn.execute(
                        "UPDATE task_assignees SET status='Completed', completed_at=$1 "
                        "WHERE group_task_id=$2 AND LOWER(assignee)=$3",
                        now, tid, username.lower()
                    )
                    done_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM task_assignees WHERE group_task_id=$1 AND status='Completed'", tid
                    )
                    total = await conn.fetchval("SELECT total_assignees FROM tasks WHERE id=$1", tid)
                    await conn.execute("UPDATE tasks SET completed_count=$1 WHERE id=$2", done_count, tid)
                    if done_count >= total:
                        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", tid)
                        assigner = await conn.fetchval("SELECT assigned_by FROM tasks WHERE id=$1", tid)
                        newly_finished.append((tid, assigner))
                else:
                    # Legacy single-assignee
                    task = await conn.fetchrow("SELECT assignee, status, assigned_by, task_desc FROM tasks WHERE id=$1", tid)
                    if task and task["status"] != "Completed" and task["assignee"].lower() == username.lower():
                        await conn.execute("UPDATE tasks SET status='Completed' WHERE id=$1", tid)
                        newly_finished.append((tid, task["assigned_by"]))

        # Notify assigners of fully completed tasks
        for t_id, assigner in newly_finished:
            async with pool.acquire() as conn:
                a_uid = await conn.fetchval("SELECT user_id FROM users WHERE username=$1", assigner)
            if a_uid:
                try:
                    await context.bot.send_message(
                        a_uid,
                        f"🎉 *Task `#{t_id}` has been completed!*\n\n"
                        f"All assignees have finished.\n"
                        f"✅ Marked by @{username}",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

        n = len(done_ids)
        context.user_data.pop("myt_tasks", None)
        context.user_data.pop("myt_toggled", None)
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        await q.message.edit_text(
            f"✅ *{n} task{'s' if n>1 else ''} marked complete!*\n\n"
            f"_Your assigners have been notified._",
            parse_mode="Markdown"
        )

    # ── Cancel — close without saving ────────────────────────────────────────
    elif data == "myt_cancel":
        context.user_data.pop("myt_tasks", None)
        context.user_data.pop("myt_toggled", None)
        cancel_kb_timeout(context, q.message.chat_id, q.message.message_id)
        try:
            await q.message.delete()
        except Exception:
            pass
