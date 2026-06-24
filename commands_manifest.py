# Canonical command manifest — drives /help text, Telegram slash menu, and pop-out.
# Rules:
#   public=True  → shows in / pop-out for ALL users, appears in USER section of /help
#   admin=True   → ADMIN SUITE section in /help (not in public menu)
#   super=True   → SUPER OWNER section in /help (not in public menu)
# Telegram API requires command names to be 1-32 lowercase letters/digits/underscores.

COMMANDS = [
    {"name": "manual",  "emoji": "📖", "public": True,
     "category": "ℹ️ General",
     "desc": "Receive the full bot user manual as a PDF (once per month)",
     "explanation": "Generates and sends a PDF manual covering all user commands in English, Arabic, and Indonesian. You can request this once per calendar month — check your chat history if you need it again sooner.",
     "format": "/manual"},
    {"name": "broadcast", "emoji": "📢", "public": False, "admin": True,
     "category": "📢 Broadcast",
     "desc": "Post or schedule team broadcasts to groups",
     "explanation": "Opens the Broadcast hub in DM. Post immediately or schedule with recurrence (once, daily, weekday, weekly). Choose target group or all groups, set message, and optionally tag everyone.",
     "format": "/broadcast"},
    {"name": "birthdayconfig", "emoji": "🎂", "public": False, "admin": True,
     "category": "🎂 Birthday Management",
     "desc": "Manage team birthday registrations",
     "explanation": "Opens the Birthday Config hub in DM. Add, edit, delete, batch add, and batch delete birthdays — all inline. Admins only.",
     "format": "/birthdayconfig"},
    {"name": "library",  "emoji": "📚", "public": True,
     "category": "📚 Library",
     "desc": "Browse and manage team assets in the library",
     "explanation": "Opens the Library hub in DM. Browse, get, add (including batch), edit, and delete assets — all with inline buttons.",
     "format": "/library"},
    # ─────────────────────────────────────────
    # 💬 GENERAL
    # ─────────────────────────────────────────
    {"name": "start",    "desc": "Start interaction",         "public": True,  "category": "💬 General", "emoji": "🚀", "explanation": "Registers you with the bot and opens the welcome menu."},
    {"name": "help",     "desc": "View Nukhba Manual",        "public": True,  "category": "💬 General", "emoji": "📖", "explanation": "Shows a full list of all available commands by category."},
    {"name": "command",  "desc": "Interactive command browser","public": True,  "category": "💬 General", "emoji": "🗂️", "explanation": "Opens an interactive inline menu to browse and discover commands."},
    {"name": "about",    "desc": "About Nukhba Manager",      "public": True,  "category": "💬 General", "emoji": "ℹ️", "explanation": "Shows information about Nukhba Manager and its version."},
    {"name": "feedback", "desc": "Submit Feedback",           "format": "`/feedback We need a longer timer`", "public": True, "category": "💬 General", "emoji": "💡", "explanation": "Sends your feedback or suggestion directly to the admin team."},

    # ─────────────────────────────────────────
    # 📅 EVENTS & POLLS
    # ─────────────────────────────────────────
            {"name": "events",    "desc": "Upcoming events",                                                                          "public": True, "category": "📅 Events & Polls", "emoji": "🗓️", "explanation": "Lists all upcoming events scheduled in this group."},
    
    # ─────────────────────────────────────────
    # ⭐ RAWWY STARS
    # ─────────────────────────────────────────
    {"name": "thanks",           "desc": "Give a Star",         "format": "Reply to a msg with `/thanks`", "public": True, "category": "⭐ RAWWY Stars", "emoji": "⭐", "explanation": "Give a RAWWY Star to someone whose message you replied to."},
    {"name": "myquota",          "desc": "Check Star Quota",                                                "public": True, "category": "⭐ RAWWY Stars", "emoji": "📉", "explanation": "Check how many Stars you have left to give this week."},
    {"name": "mystar",           "desc": "Monthly Stars",                                                   "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌟", "explanation": "See how many Stars you have received this month and all-time."},
    {"name": "leaderboard_star", "desc": "Top RAWWY Stars",                                                 "public": True, "category": "⭐ RAWWY Stars", "emoji": "🏆", "explanation": "Shows the top 5 RAWWY Star earners this month and all-time."},

    # ─────────────────────────────────────────
    # 🎮 TRIVIA
    # ─────────────────────────────────────────
    {"name": "mypoint",        "desc": "View Knowledge Points", "public": True, "category": "🎮 Trivia", "emoji": "🧠", "explanation": "View your current Knowledge Point (KP) total from trivia."},
    {"name": "leaderboard_kp", "desc": "Top Knowledge Points",  "public": True, "category": "🎮 Trivia", "emoji": "🏅", "explanation": "Shows the top 5 Knowledge Point earners this month."},

    # ─────────────────────────────────────────
    # 📚 LIBRARY
    # ─────────────────────────────────────────
                    
    # ─────────────────────────────────────────
    # ⚡ TASKS & AWAY
    # ─────────────────────────────────────────
    {"name": "mytasks",  "desc": "Active Tasks",          "public": True, "category": "⚡ Tasks & Away", "emoji": "📋", "explanation": "View all tasks currently assigned to you, sent to your DM."},
    {"name": "assign",   "desc": "Assign a task (supports multiple users)", "format": "`/assign @user1 @user2 , 120 , Review code`", "public": True, "category": "⚡ Tasks & Away", "emoji": "📌", "explanation": "Assign a task to one or more teammates with a deadline."},
    {"name": "complete", "desc": "Mark your progress on a task", "format": "`/complete [TaskID]`",        "public": True, "category": "⚡ Tasks & Away", "emoji": "✅", "explanation": "Mark your progress on a task as done."},
    {"name": "away",     "desc": "Set away status", "format": "`/away Doctor , 10/15/2026 14:30`",       "public": True, "category": "⚡ Tasks & Away", "emoji": "🛫", "explanation": "Set yourself as Away with a reason and return time."},
    {"name": "back",     "desc": "Return to available",                                                  "public": True, "category": "⚡ Tasks & Away", "emoji": "🛬", "explanation": "Mark yourself as back and available. The bot will send you missed mentions."},

    # ─────────────────────────────────────────
    # 🤖 AI / GEMINI  ← BOTTOM of User list
    # Note added to /help: "⚠️ This is an experimental feature, don't abuse it yet"
    # ─────────────────────────────────────────
    {"name": "ai",  "desc": "Ask AI (Groq)",            "format": "`/ai Translate this: Hello`",           "public": True, "category": "🤖 AI Assistant ⚠️ Experimental", "emoji": "🤖", "experimental": True, "explanation": "Ask the AI assistant (powered by Groq) any question."},
    {"name": "ask",     "desc": "Ask about Nukhba",         "format": "`/ask How do I schedule an event?`",        "public": True, "category": "🤖 AI Assistant ⚠️ Experimental", "emoji": "🤖", "experimental": True, "explanation": "Ask about Nukhba Manager's features and how to use them."},
    {"name": "wdim",    "desc": "What did I miss? (Recap)", "public": True, "category": "🤖 AI Assistant ⚠️ Experimental", "emoji": "🔍", "experimental": True, "explanation": "Get a smart AI-generated recap of what happened in the group while you were away."},

    # ==========================================
    # 🔐 ADMIN — SYSTEM CONFIG
    # ==========================================
    {"name": "botconfig",    "desc": "All-in-One Bot Config & User Manager", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🛠️"},
    {"name": "schedconfig",  "desc": "Schedule & Reminder Config Panel",    "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🗓️"},
    {"name": "setchannel",   "desc": "Set feature target channel",          "format": "`/setchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📍"},
    {"name": "unsetchannel", "desc": "Remove feature target channel",       "format": "`/unsetchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🔕"},
    {"name": "groupid",      "desc": "Check current chat group ID",         "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🆔"},
    {"name": "registergroup","desc": "Manually register current group",     "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🏠"},

    # 👥 ADMIN — USER MANAGEMENT
    {"name": "checkquota",  "desc": "Check user star quota",                "format": "`/checkquota @user` or `all`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "🔍"},
    {"name": "admin_stars", "desc": "Manually edit user stars",             "format": "`/admin_stars @user , <quota|monthly|total> , <set|add|sub> , <amt>`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "⭐"},
    {"name": "checklimit",  "desc": "Check AI limit",                       "format": "`/checklimit @user` or `all`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "🔍"},
    {"name": "admin_limit", "desc": "Manually edit AI limit",               "format": "`/admin_limit @user , <set|add|sub> , <amt>`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "🤖"},

    # 🎂 ADMIN — BIRTHDAYS
                        
    # 🎮 ADMIN — TRIVIA
    {"name": "triviaconfig",     "desc": "Interactive Trivia Panel",         "public": False, "admin": True, "category": "🎮 Admin Trivia", "emoji": "🎛️"},
    {"name": "forcetrivia",      "desc": "Trigger standard round",           "public": False, "admin": True, "category": "🎮 Admin Trivia", "emoji": "▶️"},
    {"name": "forcesupertrivia", "desc": "Trigger super round",              "public": False, "admin": True, "category": "🎮 Admin Trivia", "emoji": "⏭️"},
    {"name": "canceltrivia",     "desc": "Cancel active trivia",             "public": False, "admin": True, "category": "🎮 Admin Trivia", "emoji": "🛑"},
    {"name": "endtrivia",        "desc": "End active trivia (calc results)", "public": False, "admin": True, "category": "🎮 Admin Trivia", "emoji": "🏁"},
    {"name": "admin_kp",         "desc": "Manually edit Knowledge Points",   "format": "`/admin_kp @user , <set|add|sub> , <amt>`", "public": False, "admin": True, "category": "🎮 Admin Trivia", "emoji": "🧠"},

    # 🏖️ ADMIN — TEAM MANAGEMENT
    {"name": "attendance",  "desc": "Check team attendance",                 "public": False, "admin": True, "category": "🏖️ Admin Team Mgmt", "emoji": "📊"},
    {"name": "forceback",   "desc": "Force user back from away",             "format": "`/forceback @user`", "public": False, "admin": True, "category": "🏖️ Admin Team Mgmt", "emoji": "🛬"},
    {"name": "grouptasks",  "desc": "View all global active tasks",          "public": False, "admin": True, "category": "🏖️ Admin Team Mgmt", "emoji": "📋"},
        {"name": "canceltask",  "desc": "Cancel a task",                         "format": "`/canceltask [ID]`",  "public": False, "admin": True, "category": "🏖️ Admin Team Mgmt", "emoji": "🛑"},
    
    # 📢 ADMIN — BROADCASTS
        {"name": "listschedules",    "desc": "List active broadcasts",            "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "📜"},
    {"name": "delschedule",      "desc": "Delete a schedule",                "format": "`/delschedule [ID]`", "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "🗑️"},
                {"name": "feedbacklist",     "desc": "View raw feedback (last 7 days)",  "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "📥"},
    {"name": "analyze_feedback", "desc": "AI summarise feedback",            "format": "`/analyze_feedback <MM/DD/YYYY> to <MM/DD/YYYY>`", "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "🤖"},

    # ==========================================
    # 👑 SUPER OWNER EXCLUSIVES
    # ==========================================
    {"name": "update",          "desc": "View latest bot version log",      "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🔄"},
    {"name": "pushupdate",      "desc": "Push auto-increment version log",  "format": "`/pushupdate Fixed bugs and UI`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🚀"},
    {"name": "updatechange",    "desc": "Set manual version and log",       "format": "`/updatechange 2.0 , Massive overhaul`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🔄"},
    {"name": "allcommandtest",  "desc": "Test all commands",                "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🧪"},
    {"name": "botstatus",       "desc": "Show system status",               "public": False, "super": True, "category": "👑 Super Owner", "emoji": "📊"},
    {"name": "addadmin",        "desc": "Promote user to Admin",            "format": "`/addadmin @user`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "👑"},
    {"name": "deladmin",        "desc": "Demote Admin",                     "format": "`/deladmin @user`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🔻"},
    {"name": "listadmins",      "desc": "List all admins",                  "public": False, "super": True, "category": "👑 Super Owner", "emoji": "📜"},
    {"name": "removemember",    "desc": "Offboard a member entirely",       "format": "`/removemember @user`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "☠️"},
    {"name": "graveyard",       "desc": "View offboarded members",          "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🪦"},
    {"name": "pause",           "desc": "Pause the bot",                    "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⏸️"},
    {"name": "restart",         "desc": "Restart the bot",                  "public": False, "super": True, "category": "👑 Super Owner", "emoji": "▶️"},
    {"name": "super_reset",     "desc": "Factory wipe data sections",       "public": False, "super": True, "category": "👑 Super Owner", "emoji": "☢️"},
]
