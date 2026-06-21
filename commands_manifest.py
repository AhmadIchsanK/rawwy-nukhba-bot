# Canonical command manifest to drive both help text and Telegram menu
COMMANDS = [
    # 💬 GENERAL & AI
    {"name": "start", "desc": "Start interaction with bot", "public": True, "category": "💬 General", "emoji": "🚀"},
    {"name": "help", "desc": "View Nukhba Manual", "public": True, "category": "💬 General", "emoji": "📖"},
    {"name": "gemini", "desc": "Ask Gemini AI", "format": "`/gemini Translate this to French: Hello`", "public": True, "category": "💬 General", "emoji": "🤖"},
    {"name": "ask", "desc": "Ask about Nukhba Bot", "format": "`/ask How do I schedule an event?`", "public": True, "category": "💬 General", "emoji": "🤖"},
    {"name": "wdim", "desc": "What did I miss? (Recap)", "public": True, "category": "💬 General", "emoji": "🔍"},
    {"name": "feedback", "desc": "Submit Feedback", "format": "`/feedback We need a longer trivia timer`", "public": True, "category": "💬 General", "emoji": "💡"},

    # 📅 EVENTS & POLLS
    {"name": "newevent", "desc": "Schedule an event", "format": "`/newevent Team Meeting , 12/25/2026 14:00 , 30`", "public": True, "category": "📅 Events & Polls", "emoji": "📅"},
    {"name": "editevent", "desc": "Edit your event", "format": "`/editevent 5 , Team Sync , 12/26/2026 15:00 , 15`", "public": True, "category": "📅 Events & Polls", "emoji": "✏️"},
    {"name": "events", "desc": "View upcoming events", "public": True, "category": "📅 Events & Polls", "emoji": "🗓️"},
    {"name": "poll", "desc": "Interactive Team Poll", "format": "`/poll Where should we eat? , Pizza , Sushi , Burgers`", "public": True, "category": "📅 Events & Polls", "emoji": "📊"},

    # ⭐ RAWWY STARS
    {"name": "thanks", "desc": "Give a Star", "format": "Reply to a message with `/thanks`", "public": True, "category": "⭐ RAWWY Stars", "emoji": "⭐"},
    {"name": "myquota", "desc": "Check Star Quota", "public": True, "category": "⭐ RAWWY Stars", "emoji": "📉"},
    {"name": "mystar", "desc": "Monthly Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌟"},
    {"name": "totalstar", "desc": "All-time Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌠"},
    {"name": "leaderboard", "desc": "Top RAWWY Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🏆"},

    # 🎮 TRIVIA
    {"name": "mypoint", "desc": "View Knowledge Points", "public": True, "category": "🎮 Trivia", "emoji": "🧠"},

    # 📚 LIBRARY
    {"name": "addlib", "desc": "Save an asset", "format": "`/addlib Logo , https://link.com/logo.png`", "public": True, "category": "📚 Library", "emoji": "📥"},
    {"name": "editlib", "desc": "Edit your asset", "format": "`/editlib Logo , https://link.com/new_logo.png`", "public": True, "category": "📚 Library", "emoji": "📝"},
    {"name": "dellib", "desc": "Delete your asset", "format": "`/dellib Logo`", "public": True, "category": "📚 Library", "emoji": "🗑️"},
    {"name": "getlib", "desc": "Retrieve an asset", "format": "`/getlib Logo`", "public": True, "category": "📚 Library", "emoji": "📤"},
    {"name": "library", "desc": "Browse the Library", "public": True, "category": "📚 Library", "emoji": "🗂️"},

    # ⚡ TASKS & AWAY
    {"name": "assign", "desc": "Assign a task", "format": "`/assign @username , 120 , Review the Q3 report`", "public": True, "category": "⚡ Tasks & Away", "emoji": "📌"},
    {"name": "complete", "desc": "Mark task complete", "format": "`/complete 12`", "public": True, "category": "⚡ Tasks & Away", "emoji": "✅"},
    {"name": "mytasks", "desc": "View active tasks", "public": True, "category": "⚡ Tasks & Away", "emoji": "📋"},
    {"name": "away", "desc": "Set away status", "format": "`/away Doctor Appointment , 10/15/2026 14:30`", "public": True, "category": "⚡ Tasks & Away", "emoji": "🛫"},
    {"name": "back", "desc": "Return to available", "public": True, "category": "⚡ Tasks & Away", "emoji": "🛬"},

    # ⚙️ ADMIN SYSTEM CONFIG
    {"name": "botconfig", "desc": "Interactive Bot Settings", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🛠️"},
    {"name": "setchannel", "desc": "Set feature target channel", "format": "`/setchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📍"},
    {"name": "unsetchannel", "desc": "Remove feature target channel", "format": "`/unsetchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🔕"},
    {"name": "groupid", "desc": "Get current chat ID", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🆔"},
    {"name": "auditlog", "desc": "Pull diagnostic logs", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📑"},

    # 🎮 ADMIN TRIVIA
    {"name": "triviaconfig", "desc": "Interactive Trivia Panel", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "🎛️"},
    {"name": "forcetrivia", "desc": "Trigger standard round", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "▶️"},
    {"name": "forcesupertrivia", "desc": "Trigger super round", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "⏭️"},
    {"name": "canceltrivia", "desc": "Cancel active trivia", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "🛑"},
    {"name": "admin_kp", "desc": "Edit Knowledge Points", "format": "`/admin_kp @username , add , 50`", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "💯"},

    # ⭐ ADMIN STARS & AI
    {"name": "checkquota", "desc": "Audit Star quotas", "format": "`/checkquota @username`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "🔍"},
    {"name": "admin_stars", "desc": "Modify user stars/quota", "format": "`/admin_stars @username , monthly , set , 10`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "⚙️"},
    {"name": "checklimit", "desc": "Audit AI limits", "format": "`/checklimit all`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "🔍"},
    {"name": "admin_limit", "desc": "Modify user's AI limit", "format": "`/admin_limit @username , add , 10`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "⚙️"},

    # 🎂 ADMIN BIRTHDAYS
    {"name": "addbday", "desc": "Add user birthday", "format": "`/addbday @username , 12/25`", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "➕"},
    {"name": "editbday", "desc": "Edit user birthday", "format": "`/editbday @username , 01/01`", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "✏️"},
    {"name": "delbday", "desc": "Delete user birthday", "format": "`/delbday @username`", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "🗑️"},
    {"name": "listbdays", "desc": "List registered birthdays", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "📜"},

    # 🏖️ ADMIN TEAM MANAGEMENT
    {"name": "attendance", "desc": "List Away users", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "📋"},
    {"name": "forceback", "desc": "Force user back", "format": "`/forceback @username`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "🔙"},
    {"name": "grouptasks", "desc": "View pending tasks", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "🌍"},
    {"name": "cancelevent", "desc": "Cancel scheduled event", "format": "`/cancelevent 5`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "❌"},
    {"name": "canceltask", "desc": "Cancel a task", "format": "`/canceltask 12`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "❌"},
    {"name": "cancelpoll", "desc": "Stop a live poll", "format": "Reply to poll with `/cancelpoll`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "🛑"},

    # 📢 ADMIN BROADCASTS
    {"name": "schedule", "desc": "Schedule broadcast", "format": "`/schedule all , daily , 09:00 , yes , Good Morning!`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🗓️"},
    {"name": "listschedules", "desc": "List broadcasts", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📜"},
    {"name": "delschedule", "desc": "Delete a broadcast", "format": "`/delschedule 3`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🗑️"},
    {"name": "announce", "desc": "Send announcement", "format": "`/announce all , Server maintenance at 2AM.`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📣"},
    {"name": "editannounce", "desc": "Edit announcement", "format": "`/editannounce 8 , Server maintenance at 3AM.`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "✏️"},
    {"name": "delannounce", "desc": "Delete announcement", "format": "`/delannounce 8`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🗑️"},
    {"name": "feedbacklist", "desc": "View recent feedback", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📥"},
    {"name": "analyze_feedback", "desc": "Analyze feedback via AI", "format": "`/analyze_feedback 01/01/2026 to 01/31/2026`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🧠"},
    
    # 👑 SUPER OWNER
    {"name": "addadmin", "desc": "Promote to Admin", "format": "`/addadmin @username`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⬆️"},
    {"name": "deladmin", "desc": "Demote Admin", "format": "`/deladmin @username`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⬇️"},
    {"name": "listadmins", "desc": "List current Admins", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "👥"},
    {"name": "removemember", "desc": "Offboard a member", "format": "`/removemember @username`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⛔"},
    {"name": "graveyard", "desc": "Show offboarded users", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🪦"},
    {"name": "botstatus", "desc": "Show system status", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "📊"},
    {"name": "pause", "desc": "Pause the bot", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⏸️"},
    {"name": "restart", "desc": "Restart the bot", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "▶️"},
    {"name": "super_reset", "desc": "Factory wipe sections", "format": "`/super_reset stars`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "☢️"}
]
