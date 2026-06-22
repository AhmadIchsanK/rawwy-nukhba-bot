# Canonical command manifest — drives /help text, Telegram slash menu, and pop-out.
# Rules:
#   public=True  → shows in / pop-out for ALL users, appears in USER section of /help
#   admin=True   → ADMIN SUITE section in /help (not in public menu)
#   super=True   → SUPER OWNER section in /help (not in public menu)
# Telegram API requires command names to be 1-32 lowercase letters/digits/underscores.

COMMANDS = [
    # ─────────────────────────────────────────
    # 💬 GENERAL
    # ─────────────────────────────────────────
    {"name": "start",    "desc": "Start interaction",         "public": True,  "category": "💬 General", "emoji": "🚀"},
    {"name": "help",     "desc": "View Nukhba Manual",        "public": True,  "category": "💬 General", "emoji": "📖"},
    {"name": "command",  "desc": "Interactive command browser","public": True,  "category": "💬 General", "emoji": "🗂️"},
    {"name": "about",    "desc": "About Nukhba Manager",      "public": True,  "category": "💬 General", "emoji": "ℹ️"},
    {"name": "feedback", "desc": "Submit Feedback",           "format": "`/feedback We need a longer timer`", "public": True, "category": "💬 General", "emoji": "💡"},

    # ─────────────────────────────────────────
    # 📅 EVENTS & POLLS
    # ─────────────────────────────────────────
    {"name": "newevent",  "desc": "Schedule an event",  "format": "`/newevent Title , MM/DD/YYYY HH:MM , RemMins`",          "public": True, "category": "📅 Events & Polls", "emoji": "📅"},
    {"name": "editevent", "desc": "Edit an event",      "format": "`/editevent ID , Title , MM/DD/YYYY HH:MM , RemMins`",    "public": True, "category": "📅 Events & Polls", "emoji": "✏️"},
    {"name": "events",    "desc": "Upcoming events",                                                                          "public": True, "category": "📅 Events & Polls", "emoji": "🗓️"},
    {"name": "poll",      "desc": "Interactive Team Poll", "format": "`/poll Where to eat? , Pizza , Sushi`",                "public": True, "category": "📅 Events & Polls", "emoji": "📊"},

    # ─────────────────────────────────────────
    # ⭐ RAWWY STARS
    # ─────────────────────────────────────────
    {"name": "thanks",           "desc": "Give a Star",         "format": "Reply to a msg with `/thanks`", "public": True, "category": "⭐ RAWWY Stars", "emoji": "⭐"},
    {"name": "myquota",          "desc": "Check Star Quota",                                                "public": True, "category": "⭐ RAWWY Stars", "emoji": "📉"},
    {"name": "mystar",           "desc": "Monthly Stars",                                                   "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌟"},
    {"name": "totalstar",        "desc": "All-time Stars",                                                  "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌠"},
    {"name": "leaderboard_star", "desc": "Top RAWWY Stars",                                                 "public": True, "category": "⭐ RAWWY Stars", "emoji": "🏆"},

    # ─────────────────────────────────────────
    # 🎮 TRIVIA
    # ─────────────────────────────────────────
    {"name": "mypoint",        "desc": "View Knowledge Points", "public": True, "category": "🎮 Trivia", "emoji": "🧠"},
    {"name": "leaderboard_kp", "desc": "Top Knowledge Points",  "public": True, "category": "🎮 Trivia", "emoji": "🏅"},

    # ─────────────────────────────────────────
    # 📚 LIBRARY
    # ─────────────────────────────────────────
    {"name": "library", "desc": "Browse Library",    "public": True, "category": "📚 Library", "emoji": "🗂️"},
    {"name": "getlib",  "desc": "Retrieve an asset", "format": "`/getlib Logo`",                "public": True, "category": "📚 Library", "emoji": "📤"},
    {"name": "addlib",  "desc": "Save an asset",     "format": "`/addlib Logo , content`",      "public": True, "category": "📚 Library", "emoji": "📥"},
    {"name": "editlib", "desc": "Edit an asset",     "format": "`/editlib Logo , <new content>`", "public": True, "category": "📚 Library", "emoji": "✏️"},
    {"name": "dellib",  "desc": "Delete an asset",   "format": "`/dellib Logo`",                "public": True, "category": "📚 Library", "emoji": "🗑️"},

    # ─────────────────────────────────────────
    # ⚡ TASKS & AWAY
    # ─────────────────────────────────────────
    {"name": "mytasks",  "desc": "Active Tasks",          "public": True, "category": "⚡ Tasks & Away", "emoji": "📋"},
    {"name": "assign",   "desc": "Assign a task",   "format": "`/assign @user , 120 , Review code`",    "public": True, "category": "⚡ Tasks & Away", "emoji": "📌"},
    {"name": "complete", "desc": "Complete a task", "format": "`/complete [TaskID]`",                    "public": True, "category": "⚡ Tasks & Away", "emoji": "✅"},
    {"name": "away",     "desc": "Set away status", "format": "`/away Doctor , 10/15/2026 14:30`",       "public": True, "category": "⚡ Tasks & Away", "emoji": "🛫"},
    {"name": "back",     "desc": "Return to available",                                                  "public": True, "category": "⚡ Tasks & Away", "emoji": "🛬"},

    # ─────────────────────────────────────────
    # 🤖 AI / GEMINI  ← BOTTOM of User list
    # Note added to /help: "⚠️ This is an experimental feature, don't abuse it yet"
    # ─────────────────────────────────────────
    {"name": "gemini",  "desc": "Ask Gemini AI",            "format": "`/gemini Translate this: Hello`",           "public": True, "category": "🤖 AI / Gemini ⚠️ Experimental", "emoji": "🤖", "experimental": True},
    {"name": "ask",     "desc": "Ask about Nukhba",         "format": "`/ask How do I schedule an event?`",        "public": True, "category": "🤖 AI / Gemini ⚠️ Experimental", "emoji": "🤖", "experimental": True},
    {"name": "wdim",    "desc": "What did I miss? (Recap)", "public": True, "category": "🤖 AI / Gemini ⚠️ Experimental", "emoji": "🔍", "experimental": True},
    {"name": "cheerme", "desc": "Get a personalised cheer", "public": True, "category": "🤖 AI / Gemini ⚠️ Experimental", "emoji": "🎉", "experimental": True},
    {"name": "setcheer","desc": "Set your cheer profile",   "format": "`/setcheer <text>`",                        "public": True, "category": "🤖 AI / Gemini ⚠️ Experimental", "emoji": "💬", "experimental": True},

    # ==========================================
    # 🔐 ADMIN — SYSTEM CONFIG
    # ==========================================
    {"name": "botconfig",    "desc": "Interactive Bot Settings Panel",      "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🛠️"},
    {"name": "schedconfig",  "desc": "Schedule & Reminder Config Panel",    "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🗓️"},
    {"name": "setchannel",   "desc": "Set feature target channel",          "format": "`/setchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📍"},
    {"name": "unsetchannel", "desc": "Remove feature target channel",       "format": "`/unsetchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🔕"},
    {"name": "groupid",      "desc": "Check current chat group ID",         "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🆔"},
    {"name": "registergroup","desc": "Manually register current group",     "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🏠"},
    {"name": "auditlog",     "desc": "Pull diagnostic logs",                "format": "`/auditlog 15`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📑"},
    {"name": "audittime",    "desc": "Set daily audit digest time",         "format": "`/audittime 23:50`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "⏰"},

    # 👥 ADMIN — USER MANAGEMENT
    {"name": "manageusers", "desc": "Interactive User Manager",             "public": False, "admin": True, "category": "👥 User Management", "emoji": "🎛️"},
    {"name": "checkquota",  "desc": "Check user star quota",                "format": "`/checkquota @user` or `all`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "🔍"},
    {"name": "admin_stars", "desc": "Manually edit user stars",             "format": "`/admin_stars @user , <quota|monthly|total> , <set|add|sub> , <amt>`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "⭐"},
    {"name": "checklimit",  "desc": "Check AI limit",                       "format": "`/checklimit @user` or `all`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "🔍"},
    {"name": "admin_limit", "desc": "Manually edit AI limit",               "format": "`/admin_limit @user , <set|add|sub> , <amt>`", "public": False, "admin": True, "category": "👥 User Management", "emoji": "🤖"},

    # 🎂 ADMIN — BIRTHDAYS
    {"name": "listbdays",   "desc": "List registered birthdays",            "public": False, "admin": True, "category": "🎂 Admin Birthdays", "emoji": "📋"},
    {"name": "addbday",     "desc": "Add a birthday",                       "format": "`/addbday @user , MM/DD`", "public": False, "admin": True, "category": "🎂 Admin Birthdays", "emoji": "➕"},
    {"name": "editbday",    "desc": "Edit a birthday",                      "format": "`/editbday @user , MM/DD`", "public": False, "admin": True, "category": "🎂 Admin Birthdays", "emoji": "✏️"},
    {"name": "delbday",     "desc": "Delete a birthday",                    "format": "`/delbday @user`", "public": False, "admin": True, "category": "🎂 Admin Birthdays", "emoji": "🗑️"},
    {"name": "bulkaddbday", "desc": "Bulk-add birthdays",                   "format": "`/bulkaddbday @user1 MM/DD , @user2 MM/DD`", "public": False, "admin": True, "category": "🎂 Admin Birthdays", "emoji": "📥"},
    {"name": "bulkdelbday", "desc": "Bulk-delete birthdays",                "format": "`/bulkdelbday @user1 , @user2 , @user3`", "public": False, "admin": True, "category": "🎂 Admin Birthdays", "emoji": "🗑️"},

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
    {"name": "cancelevent", "desc": "Cancel an event",                       "format": "`/cancelevent [ID]`", "public": False, "admin": True, "category": "🏖️ Admin Team Mgmt", "emoji": "🛑"},
    {"name": "canceltask",  "desc": "Cancel a task",                         "format": "`/canceltask [ID]`",  "public": False, "admin": True, "category": "🏖️ Admin Team Mgmt", "emoji": "🛑"},
    {"name": "cancelpoll",  "desc": "Cancel a poll (reply to poll msg)",     "public": False, "admin": True, "category": "🏖️ Admin Team Mgmt", "emoji": "🛑"},

    # 📢 ADMIN — BROADCASTS
    {"name": "newsched",         "desc": "Interactive Broadcast Scheduler",  "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "🗓️"},
    {"name": "listschedules",    "desc": "List active broadcasts",            "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "📜"},
    {"name": "delschedule",      "desc": "Delete a schedule",                "format": "`/delschedule [ID]`", "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "🗑️"},
    {"name": "announce",         "desc": "Send announcement now",            "format": "`/announce <chat_id|all> , <Message>`", "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "📣"},
    {"name": "editannounce",     "desc": "Edit sent announcement",           "format": "`/editannounce [ID] , <New Message>`", "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "✏️"},
    {"name": "delannounce",      "desc": "Delete sent announcement",         "format": "`/delannounce [ID]`", "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "🗑️"},
    {"name": "feedbacklist",     "desc": "View raw feedback (last 7 days)",  "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "📥"},
    {"name": "analyze_feedback", "desc": "AI summarise feedback",            "format": "`/analyze_feedback <MM/DD/YYYY> to <MM/DD/YYYY>`", "public": False, "admin": True, "category": "📢 Admin Broadcasts", "emoji": "🤖"},

    # ==========================================
    # 👑 SUPER OWNER EXCLUSIVES
    # ==========================================
    {"name": "update",          "desc": "View latest bot version log",      "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🔄"},
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
