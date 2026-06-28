"""
commands_manifest.py — Single source of truth for ALL commands.
Drives: /help text, Telegram slash-menu, /command browser, /manual PDF.

Keys:
  public=True  → shown in / pop-out for ALL users, USER section in /help
  admin=True   → ADMIN section in /help only
  super=True   → SUPER OWNER section in /help only
  experimental → shown with ⚠️ warning
  subcommands  → list of sub-features shown in /command detail card
"""

COMMANDS = [
    # ════════════════════════════════════════
    # 💬 GENERAL
    # ════════════════════════════════════════
    {"name": "start",    "emoji": "🚀", "public": True,  "category": "💬 General",
     "desc": "Register and open welcome menu",
     "explanation": "Registers you with the bot. Required once before using any features.",
     "format": "/start"},

    {"name": "help",     "emoji": "📖", "public": True,  "category": "💬 General",
     "desc": "View all available commands",
     "explanation": "Shows a full categorised list of every command available to you.",
     "format": "/help"},

    {"name": "command",  "emoji": "🗂️", "public": True,  "category": "💬 General",
     "desc": "Interactive command browser",
     "explanation": "Opens an inline menu to browse commands with full usage details and copyable formats.",
     "format": "/command"},

    {"name": "manual",   "emoji": "📖", "public": True,  "category": "💬 General",
     "desc": "Receive the full user manual as PDF (30-day cooldown)",
     "explanation": "Generates a PDF guide in 3 languages (English, Arabic, Indonesian) with detailed usage for every command. Once every 30 days — check your chat history if you need it sooner.",
     "format": "/manual"},

    {"name": "update",   "emoji": "🔄", "public": True,  "category": "💬 General",
     "desc": "View latest bot version and changelog",
     "explanation": "Shows the current version number and what changed in recent updates.",
     "format": "/update"},

    {"name": "about",    "emoji": "ℹ️", "public": True,  "category": "💬 General",
     "desc": "About Nukhba Manager bot",
     "explanation": "Shows bot info, version, and credits.",
     "format": "/about"},

    {"name": "feedback", "emoji": "💡", "public": True,  "category": "💬 General",
     "desc": "Send a suggestion or report to admin",
     "explanation": "Your message goes directly to the admin team. Be specific!",
     "format": "/feedback Your message here"},

    # ════════════════════════════════════════
    # ⭐ RAWWY STARS
    # ════════════════════════════════════════
    {"name": "thanks",           "emoji": "⭐", "public": True, "category": "⭐ RAWWY Stars",
     "desc": "Give a RAWWY Star (reply to a message)",
     "explanation": "Reply to any message and type /thanks to give that person a RAWWY Star.",
     "format": "Reply to a message → /thanks"},

    {"name": "mystar",           "emoji": "🌟", "public": True, "category": "⭐ RAWWY Stars",
     "desc": "See your monthly and all-time RAWWY Stars",
     "explanation": "Shows stars received this month and your all-time total in one message.",
     "format": "/mystar"},

    {"name": "myquota",          "emoji": "📉", "public": True, "category": "⭐ RAWWY Stars",
     "desc": "Check how many Stars you can still give this week",
     "explanation": "Your giving quota resets every Monday.",
     "format": "/myquota"},

    {"name": "leaderboard_star", "emoji": "🏆", "public": True, "category": "⭐ RAWWY Stars",
     "desc": "Top 5 RAWWY Star earners (monthly + all-time)",
     "explanation": "Leaderboard resets monthly. All-time is cumulative.",
     "format": "/leaderboard_star"},

    # ════════════════════════════════════════
    # 🎮 TRIVIA & KP
    # ════════════════════════════════════════
    {"name": "mypoint",        "emoji": "🧠", "public": True, "category": "🎮 Trivia & KP",
     "desc": "View your Knowledge Points (monthly + all-time)",
     "explanation": "KP is earned by answering trivia correctly. Monthly KP resets on the 1st.",
     "format": "/mypoint"},

    {"name": "leaderboard_kp", "emoji": "🏅", "public": True, "category": "🎮 Trivia & KP",
     "desc": "Top 5 KP earners this month",
     "explanation": "Shows this month's trivia champions.",
     "format": "/leaderboard_kp"},

    # ════════════════════════════════════════
    # 📅 EVENTS & POLLS
    # ════════════════════════════════════════
    {"name": "eventpoll", "emoji": "📅", "public": True, "category": "📅 Events & Polls",
     "desc": "Create and manage events and polls (inline hub)",
     "explanation": "Opens the Events & Polls hub in DM. Auto-targets the group when run from a group.",
     "format": "/eventpoll",
     "subcommands": [
         "📅 New Event → title, date/time (MM/DD/YYYY HH:MM), reminder minutes",
         "📊 New Poll → question + options (one per line), anon/multi/quiz/duration settings",
         "📋 List Events → upcoming events (30-min cooldown per group)",
         "✏️ Edit Event → update your event's title, time, or reminder",
         "❌ Cancel → remove your event or poll (admins can cancel any)",
     ]},

    {"name": "listevent",  "emoji": "📋", "public": True, "category": "📅 Events & Polls",
     "desc": "Quick-view upcoming events in this group",
     "explanation": "Shows upcoming events directly in chat. 30-minute cooldown per group.",
     "format": "/listevent"},

    # ════════════════════════════════════════
    # 📚 LIBRARY
    # ════════════════════════════════════════
    {"name": "library", "emoji": "📚", "public": True, "category": "📚 Library",
     "desc": "Browse and manage team assets (opens inline hub in DM)",
     "explanation": "Opens the Library hub in DM with all asset operations in one place.",
     "format": "/library",
     "subcommands": [
         "📂 Browse → paginated list (your private + all public assets)",
         "🔍 Get Asset → type name to retrieve content",
         "➕ Add → Name , Content  (add ', private' to keep it private)",
         "📦 Batch Add → one entry per line: Name , Content",
         "✏️ Edit → Name , New Content  (owners only)",
         "🗑️ Delete → pick from your own assets",
         "🗑️📦 Batch Delete → names comma-separated or one per line",
     ]},

    # ════════════════════════════════════════
    # 📋 TASKS
    # ════════════════════════════════════════
    {"name": "task",      "emoji": "📌", "public": True, "category": "📋 Tasks",
     "desc": "Assign a task to team members (group or DM)",
     "explanation": "In a group: tap members to assign, type description, press Finish. In DM: step-by-step with group picker.",
     "format": "/task",
     "subcommands": [
         "Group: tap member names → type task description → Finish",
         "DM: pick group → type description → type assignees (comma-separated) → set deadline in minutes",
     ]},

    {"name": "mytask",    "emoji": "✅", "public": True, "category": "📋 Tasks",
     "desc": "View and complete your assigned tasks (inline DM list)",
     "explanation": "Tap a task to toggle Complete/Incomplete. Press Finish to save — assigner is notified when all done.",
     "format": "/mytask"},

    {"name": "grouptask", "emoji": "📋", "public": True, "category": "📋 Tasks",
     "desc": "View active tasks and last 7 completed tasks in this group",
     "explanation": "Shows status (Pending/Overdue/Done), assigner, and assignees. Admins see all tasks.",
     "format": "/grouptask"},

    # ════════════════════════════════════════
    # 🏖️ AWAY STATUS
    # ════════════════════════════════════════
    {"name": "away", "emoji": "🛫", "public": True, "category": "🏖️ Away Status",
     "desc": "Open Away hub — set status, reason, return time (inline DM)",
     "explanation": "Opens the Away hub in DM. All away options in one inline menu.",
     "format": "/away",
     "subcommands": [
         "🏖️ Set Away → type reason, then return date/time (MM/DD/YYYY HH:MM)",
         "🟢 I'm Back → confirm to clear away + receive missed mentions",
         "⚙️ Auto-Cancel → if ON, any group message auto-clears your away status",
         "📋 My Status → view reason, return time, and pending mention count",
     ]},

    {"name": "back",  "emoji": "🛬", "public": True, "category": "🏖️ Away Status",
     "desc": "Mark yourself as available (type in any chat)",
     "explanation": "Clears your away status. Missed mentions will be delivered to your DM.",
     "format": "/back"},

    # ════════════════════════════════════════
    # 🤖 AI ASSISTANT
    # ════════════════════════════════════════
    {"name": "ai",   "emoji": "🤖", "public": True, "category": "🤖 AI Assistant ⚠️ Experimental",
     "desc": "Ask the AI assistant anything (Groq/Llama)",
     "explanation": "Powered by Groq's fast Llama model. Ask questions, translate, summarise, etc.",
     "experimental": True,
     "format": "/ai Your question here"},

    {"name": "ask",  "emoji": "💬", "public": True, "category": "🤖 AI Assistant ⚠️ Experimental",
     "desc": "Ask about this bot's features",
     "explanation": "Ask how to use any command or feature of Nukhba Manager.",
     "experimental": True,
     "format": "/ask How do I set an away status?"},

    {"name": "wdim", "emoji": "🔍", "public": True, "category": "🤖 AI Assistant ⚠️ Experimental",
     "desc": "What Did I Miss? — AI recap of group activity",
     "explanation": "Get an AI-generated summary of what happened in the group while you were away.",
     "experimental": True,
     "format": "/wdim"},

    # ════════════════════════════════════════
    # 🔐 ADMIN CONFIG  (combined category)
    # ════════════════════════════════════════
    {"name": "broadcast",      "emoji": "📢", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Post or schedule team broadcasts (inline hub in DM)",
     "explanation": "Post now or schedule with recurrence. Choose group target, tag members, and set message inline.",
     "format": "/broadcast",
     "subcommands": [
         "📤 Post Now → target → tag all? → message → confirm",
         "📅 Schedule → target → recurrence (once/daily/weekday/weekly) → date/time → tag → message → confirm",
         "📋 List Schedules → paginated list with delete buttons",
         "🗑️ Delete Schedule → tap to remove",
     ]},

    {"name": "birthdayconfig", "emoji": "🎂", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Manage team birthday registrations (inline hub in DM)",
     "format": "/birthdayconfig",
     "subcommands": [
         "📋 List → paginated birthday registry",
         "➕ Add → @username , MM/DD",
         "✏️ Edit → pick member → type new date",
         "🗑️ Delete → pick member",
         "📥 Batch Add → one per line: @user , MM/DD",
         "🗑️📥 Batch Delete → usernames comma-separated or one per line",
     ]},

    {"name": "admin",          "emoji": "👑", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Manage bot admins — add, remove, list (Super Owner only, inline DM)",
     "format": "/admin",
     "subcommands": [
         "➕ Add Admin → type @username",
         "➖ Remove Admin → tap from list",
         "📋 List Admins → all current admins",
     ]},

    {"name": "userconfig",     "emoji": "👥", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "User management hub — quota, stars, limits, graveyard (inline DM)",
     "format": "/userconfig",
     "subcommands": [
         "👥 Registered Users → paginated list with user IDs",
         "🪦 Graveyard → offboarded members list",
         "🔍 Check Quota → @user or 'all'",
         "⭐ Admin Stars → @user , quota|monthly|total , set|add|sub , amount",
         "🤖 Check AI Limit → @user or 'all'",
         "🔧 Set AI Limit → @user , set|add|sub , amount",
         "☠️ Remove Member → permanently offboard (Super Owner only)",
     ]},

    {"name": "botconfig",      "emoji": "🛠️", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "All-in-one bot config panel",
     "format": "/botconfig"},

    {"name": "schedconfig",    "emoji": "🗓️", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Schedule and reminder configuration",
     "format": "/schedconfig"},

    {"name": "triviaconfig",   "emoji": "🎛️", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Interactive trivia panel",
     "format": "/triviaconfig"},

    {"name": "setchannel",     "emoji": "📍", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Set feature target channel",
     "format": "/setchannel bday|trivia|stars|feedback"},

    {"name": "unsetchannel",   "emoji": "🔕", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Remove feature target channel",
     "format": "/unsetchannel bday|trivia|stars|feedback"},

    {"name": "groupid",        "emoji": "🆔", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Check current chat group ID",
     "format": "/groupid"},

    {"name": "registergroup",  "emoji": "🏠", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Manually register current group with the bot",
     "format": "/registergroup"},

    {"name": "grouptasks",     "emoji": "📋", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "View all global active tasks (admin view)",
     "format": "/grouptasks"},

    {"name": "attendance",     "emoji": "📊", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Check team attendance",
     "format": "/attendance"},

    {"name": "forceback",      "emoji": "🛬", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Force a user back from away",
     "format": "/forceback @user"},

    {"name": "canceltask",     "emoji": "🛑", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Cancel a task by ID",
     "format": "/canceltask [TaskID]"},

    {"name": "feedbacklist",   "emoji": "📥", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "View raw feedback (last 7 days)",
     "format": "/feedbacklist"},

    {"name": "analyze_feedback","emoji": "🤖", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "AI summarise feedback by date range",
     "format": "/analyze_feedback MM/DD/YYYY to MM/DD/YYYY"},

    {"name": "forcetrivia",    "emoji": "▶️", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Trigger a standard trivia round",
     "format": "/forcetrivia"},

    {"name": "forcesupertrivia","emoji": "⏭️", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Trigger a super trivia round",
     "format": "/forcesupertrivia"},

    {"name": "canceltrivia",   "emoji": "🛑", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Cancel the active trivia session",
     "format": "/canceltrivia"},

    {"name": "endtrivia",      "emoji": "🏁", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "End trivia and calculate results",
     "format": "/endtrivia"},

    {"name": "admin_kp",       "emoji": "🧠", "public": False, "admin": True, "category": "🔐 Admin Config",
     "desc": "Manually edit Knowledge Points",
     "format": "/admin_kp @user , set|add|sub , amount"},

    # ════════════════════════════════════════
    # 👑 SUPER OWNER
    # ════════════════════════════════════════
    {"name": "updatechange",   "emoji": "🔄", "public": False, "super": True, "category": "👑 Super Owner",
     "desc": "Edit current version and changelog via inline panel",
     "format": "/updatechange"},

    {"name": "pushupdate",     "emoji": "🚀", "public": False, "super": True, "category": "👑 Super Owner",
     "desc": "Push auto-increment version log to all groups",
     "format": "/pushupdate Your changelog message here"},

    {"name": "allcommandtest", "emoji": "🧪", "public": False, "super": True, "category": "👑 Super Owner",
     "desc": "Test all registered commands",
     "format": "/allcommandtest"},

    {"name": "botstatus",      "emoji": "📊", "public": False, "super": True, "category": "👑 Super Owner",
     "desc": "Show full system status",
     "format": "/botstatus"},

    {"name": "pause",          "emoji": "⏸️", "public": False, "super": True, "category": "👑 Super Owner",
     "desc": "Pause the bot",
     "format": "/pause"},

    {"name": "restart",        "emoji": "▶️", "public": False, "super": True, "category": "👑 Super Owner",
     "desc": "Restart the bot",
     "format": "/restart"},

    {"name": "super_reset",    "emoji": "☢️", "public": False, "super": True, "category": "👑 Super Owner",
     "desc": "Factory wipe selected data sections",
     "format": "/super_reset"},
]
