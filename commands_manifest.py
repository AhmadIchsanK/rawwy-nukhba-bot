# Canonical command manifest to drive both help text and Telegram menu
COMMANDS = [
    # 💬 GENERAL & AI
    {"name": "start", "desc": "Start interaction", "public": True, "category": "💬 General", "emoji": "🚀"},
    {"name": "help", "desc": "View Nukhba Manual", "public": True, "category": "💬 General", "emoji": "📖"},
    {"name": "feedback", "desc": "Submit Feedback", "format": "`/feedback We need a longer timer`", "public": True, "category": "💬 General", "emoji": "💡"},
    {"name": "update", "desc": "View latest bot version log", "public": True, "category": "💬 General", "emoji": "🔄"},

    # 🤖 AI / GEMINI
    {"name": "gemini", "desc": "Ask Gemini AI", "format": "`/gemini Translate this: Hello`", "public": True, "category": "🤖 AI / Gemini", "emoji": "🤖"},
    {"name": "ask", "desc": "Ask about Nukhba", "format": "`/ask How do I schedule an event?`", "public": True, "category": "🤖 AI / Gemini", "emoji": "🤖"},
    {"name": "wdim", "desc": "What did I miss? (Recap)", "public": True, "category": "🤖 AI / Gemini", "emoji": "🔍"},

    # 📅 EVENTS & POLLS
    {"name": "newevent", "desc": "Schedule an event", "format": "`/newevent Team Sync , 12/25/2026 14:00 , 30`", "public": True, "category": "📅 Events & Polls", "emoji": "📅"},
    {"name": "events", "desc": "Interactive Event Manager", "public": True, "category": "📅 Events & Polls", "emoji": "🗓️"},
    {"name": "poll", "desc": "Interactive Team Poll", "format": "`/poll Where to eat? , Pizza , Sushi`", "public": True, "category": "📅 Events & Polls", "emoji": "📊"},

    # ⭐ RAWWY STARS
    {"name": "thanks", "desc": "Give a Star", "format": "Reply to a msg with `/thanks`", "public": True, "category": "⭐ RAWWY Stars", "emoji": "⭐"},
    {"name": "myquota", "desc": "Check Star Quota", "public": True, "category": "⭐ RAWWY Stars", "emoji": "📉"},
    {"name": "mystar", "desc": "Monthly Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌟"},
    {"name": "totalstar", "desc": "All-time Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌠"},
    {"name": "leaderboard", "desc": "Top RAWWY Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🏆"},

    # 🎮 TRIVIA
    {"name": "mypoint", "desc": "View Knowledge Points", "public": True, "category": "🎮 Trivia", "emoji": "🧠"},

    # 📚 LIBRARY
    {"name": "addlib", "desc": "Save an asset", "format": "`/addlib Logo , https://link.com/logo.png`", "public": True, "category": "📚 Library", "emoji": "📥"},
    {"name": "getlib", "desc": "Retrieve an asset", "format": "`/getlib Logo`", "public": True, "category": "📚 Library", "emoji": "📤"},
    {"name": "library", "desc": "Browse Library", "public": True, "category": "📚 Library", "emoji": "🗂️"},

    # ⚡ TASKS & AWAY
    {"name": "assign", "desc": "Assign a task", "format": "`/assign @user , 120 , Review code`", "public": True, "category": "⚡ Tasks & Away", "emoji": "📌"},
    {"name": "mytasks", "desc": "Interactive Task Manager", "public": True, "category": "⚡ Tasks & Away", "emoji": "📋"},
    {"name": "away", "desc": "Set away status", "format": "`/away Doctor , 10/15/2026 14:30`", "public": True, "category": "⚡ Tasks & Away", "emoji": "🛫"},
    {"name": "back", "desc": "Return to available", "public": True, "category": "⚡ Tasks & Away", "emoji": "🛬"},

    # ⚙️ ADMIN SYSTEM CONFIG
    {"name": "botconfig", "desc": "Interactive Bot Settings", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🛠️"},
    {"name": "setchannel", "desc": "Set feature target channel", "format": "`/setchannel <bday|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📍"},
    {"name": "unsetchannel", "desc": "Remove feature target channel", "format": "`/unsetchannel <bday|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🔕"},
    {"name": "auditlog", "desc": "Pull diagnostic logs", "format": "`/auditlog 15`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📑"},
    {"name": "audittime", "desc": "Set daily audit log time", "format": "`/audittime 23:50`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "⏰"},

    # 👥 USER MANAGEMENT
    {"name": "manageusers", "desc": "Interactive User Manager (Limits/Stars/KP)", "public": False, "admin": True, "category": "👥 User Management", "emoji": "🎛️"},

    # 🎮 ADMIN TRIVIA
    {"name": "triviaconfig", "desc": "Interactive Trivia Panel", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "🎛️"},
    {"name": "forcetrivia", "desc": "Trigger standard round", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "▶️"},
    {"name": "forcesupertrivia", "desc": "Trigger super round", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "⏭️"},
    {"name": "canceltrivia", "desc": "Cancel active trivia", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "🛑"},

    # 📢 BROADCASTS
    {"name": "newsched", "desc": "Interactive Broadcast Scheduler", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🗓️"},
    {"name": "listschedules", "desc": "List broadcasts", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📜"},
    {"name": "announce", "desc": "Send announcement", "format": "`/announce all , Server maintenance at 2AM.`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📣"},
    
    # 👑 SUPER OWNER
    {"name": "pushupdate", "desc": "Push auto-increment version log", "format": "`/pushupdate Fixed bugs and UI`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🚀"},
    {"name": "updatechange", "desc": "Set manual version and log", "format": "`/updatechange 2.0 , Massive overhaul`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🔄"},
    {"name": "allcommandtest", "desc": "AI test for all commands", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🧪"},
    {"name": "botstatus", "desc": "Show system status", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "📊"},
    {"name": "pause", "desc": "Pause the bot", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⏸️"},
    {"name": "restart", "desc": "Restart the bot", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "▶️"},
    {"name": "super_reset", "desc": "Factory wipe sections", "format": "`/super_reset stars`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "☢️"}
]
