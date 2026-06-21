# Canonical command manifest to drive both help text and Telegram menu
COMMANDS = [
    # 💬 GENERAL & AI
    {"name": "start", "desc": "Start interaction with bot", "public": True, "category": "💬 General", "emoji": "🚀"},
    {"name": "help", "desc": "View Nukhba Manual", "public": True, "category": "💬 General", "emoji": "📖"},
    {"name": "gemini", "desc": "Ask Gemini AI", "format": "`/gemini [query]`", "public": True, "category": "💬 General", "emoji": "🤖"},
    {"name": "ask", "desc": "Ask about Nukhba Bot", "format": "`/ask [query]`", "public": True, "category": "💬 General", "emoji": "🤖"},
    {"name": "wdim", "desc": "What did I miss? (Recap)", "public": True, "category": "💬 General", "emoji": "🔍"},
    {"name": "feedback", "desc": "Submit Feedback", "format": "`/feedback [details]`", "public": True, "category": "💬 General", "emoji": "💡"},

    # 📅 EVENTS
    {"name": "newevent", "desc": "Schedule an event", "format": "`/newevent [Title] , [MM/DD/YYYY HH:MM] , [RemMins]`", "public": True, "category": "📅 Events", "emoji": "📅"},
    {"name": "editevent", "desc": "Edit your event", "format": "`/editevent [ID] , [Title] , [MM/DD/YYYY HH:MM] , [RemMins]`", "public": True, "category": "📅 Events", "emoji": "✏️"},
    {"name": "events", "desc": "View upcoming events", "public": True, "category": "📅 Events", "emoji": "🗓️"},
    
    # 📊 POLLS
    {"name": "poll", "desc": "Interactive Team Poll", "format": "`/poll [Question] , [Opt1] , [Opt2]`", "public": True, "category": "📊 Polls", "emoji": "📊"},

    # ⭐ RAWWY STARS
    {"name": "thanks", "desc": "Give a Star", "format": "Reply to a message with `/thanks`", "public": True, "category": "⭐ RAWWY Stars", "emoji": "⭐"},
    {"name": "myquota", "desc": "Check Star Quota", "public": True, "category": "⭐ RAWWY Stars", "emoji": "📉"},
    {"name": "mystar", "desc": "Monthly Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌟"},
    {"name": "totalstar", "desc": "All-time Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🌠"},
    {"name": "leaderboard", "desc": "Top RAWWY Stars", "public": True, "category": "⭐ RAWWY Stars", "emoji": "🏆"},

    # 🎮 TRIVIA
    {"name": "mypoint", "desc": "View Knowledge Points", "public": True, "category": "🎮 Trivia", "emoji": "🧠"},

    # 📚 LIBRARY
    {"name": "addlib", "desc": "Save an asset", "format": "`/addlib [Name] , [Content]`", "public": True, "category": "📚 Library", "emoji": "📥"},
    {"name": "editlib", "desc": "Edit your asset", "format": "`/editlib [Name] , [Content]`", "public": True, "category": "📚 Library", "emoji": "📝"},
    {"name": "dellib", "desc": "Delete your asset", "format": "`/dellib [Name]`", "public": True, "category": "📚 Library", "emoji": "🗑️"},
    {"name": "getlib", "desc": "Retrieve an asset", "format": "`/getlib [Name]`", "public": True, "category": "📚 Library", "emoji": "📤"},
    {"name": "library", "desc": "Browse the Library", "public": True, "category": "📚 Library", "emoji": "🗂️"},

    # ⚡ TASKS
    {"name": "assign", "desc": "Assign a task", "format": "`/assign [@user] , [Mins] , [Desc]`", "public": True, "category": "⚡ Tasks", "emoji": "📌"},
    {"name": "complete", "desc": "Mark task complete", "format": "`/complete [ID]`", "public": True, "category": "⚡ Tasks", "emoji": "✅"},
    {"name": "mytasks", "desc": "View active tasks", "public": True, "category": "⚡ Tasks", "emoji": "📋"},
    
    # 🏖️ AWAY MODE
    {"name": "away", "desc": "Set away status", "format": "`/away [Reason] , [MM/DD/YYYY HH:MM]`", "public": True, "category": "🏖️ Away Mode", "emoji": "🛫"},
    {"name": "back", "desc": "Return to available", "public": True, "category": "🏖️ Away Mode", "emoji": "🛬"},

    # ⚙️ ADMIN SYSTEM CONFIG
    {"name": "botconfig", "desc": "Interactive Bot Settings", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🛠️"},
    {"name": "setchannel", "desc": "Set feature target channel", "format": "`/setchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📍"},
    {"name": "unsetchannel", "desc": "Remove feature target channel", "format": "`/unsetchannel <bday|trivia|stars|feedback>`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🔕"},
    {"name": "groupid", "desc": "Get current chat ID", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "🆔"},
    {"name": "auditlog", "desc": "Pull diagnostic logs", "format": "`/auditlog [number]`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "📑"},
    {"name": "audittime", "desc": "Set daily audit log time", "format": "`/audittime HH:MM`", "public": False, "admin": True, "category": "⚙️ System Config", "emoji": "⏰"},

    # 🎮 ADMIN TRIVIA
    {"name": "triviaconfig", "desc": "Interactive Trivia Panel", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "🎛️"},
    {"name": "forcetrivia", "desc": "Trigger standard round", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "▶️"},
    {"name": "forcesupertrivia", "desc": "Trigger super round", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "⏭️"},
    {"name": "canceltrivia", "desc": "Cancel active trivia", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "🛑"},
    {"name": "admin_kp", "desc": "Edit Knowledge Points", "format": "`/admin_kp [@user] , [set|add|sub] , [Amount]`", "public": False, "admin": True, "category": "🎮 Trivia Admin", "emoji": "💯"},

    # ⭐ ADMIN STARS & AI
    {"name": "checkquota", "desc": "Audit Star quotas", "format": "`/checkquota [all|@user]`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "🔍"},
    {"name": "admin_stars", "desc": "Modify user stars/quota", "format": "`/admin_stars [@user] , [quota|monthly|total] , [set|add|sub] , [Amount]`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "⚙️"},
    {"name": "checklimit", "desc": "Audit AI limits", "format": "`/checklimit [all|@user]`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "🔍"},
    {"name": "admin_limit", "desc": "Modify user's AI limit", "format": "`/admin_limit [@user] , [set|add|sub] , [Amount]`", "public": False, "admin": True, "category": "⭐ Stars & AI Limits", "emoji": "⚙️"},

    # 🎂 ADMIN BIRTHDAYS
    {"name": "addbday", "desc": "Add user birthday", "format": "`/addbday [@user] , [MM/DD]`", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "➕"},
    {"name": "editbday", "desc": "Edit user birthday", "format": "`/editbday [@user] , [MM/DD]`", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "✏️"},
    {"name": "delbday", "desc": "Delete user birthday", "format": "`/delbday [@user]`", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "🗑️"},
    {"name": "listbdays", "desc": "List registered birthdays", "public": False, "admin": True, "category": "🎂 Birthdays", "emoji": "📜"},

    # 🏖️ ADMIN TEAM MANAGEMENT
    {"name": "attendance", "desc": "List Away users", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "📋"},
    {"name": "forceback", "desc": "Force user back", "format": "`/forceback [@user]`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "🔙"},
    {"name": "grouptasks", "desc": "View pending tasks", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "🌍"},
    {"name": "cancelevent", "desc": "Cancel scheduled event", "format": "`/cancelevent [ID]`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "❌"},
    {"name": "canceltask", "desc": "Cancel a task", "format": "`/canceltask [ID]`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "❌"},
    {"name": "cancelpoll", "desc": "Stop a live poll", "format": "Reply to poll with `/cancelpoll`", "public": False, "admin": True, "category": "🏖️ Team Admin", "emoji": "🛑"},

    # 📢 ADMIN BROADCASTS
    {"name": "schedule", "desc": "Schedule broadcast", "format": "`/schedule [ChatID|all] , [once|daily|weekly] , [Time] , [yes|no] , [Message]`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🗓️"},
    {"name": "listschedules", "desc": "List broadcasts", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📜"},
    {"name": "delschedule", "desc": "Delete a broadcast", "format": "`/delschedule [ID]`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🗑️"},
    {"name": "announce", "desc": "Send announcement", "format": "`/announce [ChatID|all] , [Message]`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📣"},
    {"name": "editannounce", "desc": "Edit announcement", "format": "`/editannounce [ID] , [New Msg]`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "✏️"},
    {"name": "delannounce", "desc": "Delete announcement", "format": "`/delannounce [ID]`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🗑️"},
    {"name": "feedbacklist", "desc": "View recent feedback", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "📥"},
    {"name": "analyze_feedback", "desc": "Analyze feedback via AI", "format": "`/analyze_feedback [MM/DD/YYYY to MM/DD/YYYY]`", "public": False, "admin": True, "category": "📢 Broadcasts", "emoji": "🧠"},
    
    # 👑 SUPER OWNER
    {"name": "allcommandtest", "desc": "AI test for all commands", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🧪"},
    {"name": "addadmin", "desc": "Promote to Admin", "format": "`/addadmin [@user]`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⬆️"},
    {"name": "deladmin", "desc": "Demote Admin", "format": "`/deladmin [@user]`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⬇️"},
    {"name": "listadmins", "desc": "List current Admins", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "👥"},
    {"name": "removemember", "desc": "Offboard a member", "format": "`/removemember [@user]`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⛔"},
    {"name": "graveyard", "desc": "Show offboarded users", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "🪦"},
    {"name": "botstatus", "desc": "Show system status", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "📊"},
    {"name": "pause", "desc": "Pause the bot", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "⏸️"},
    {"name": "restart", "desc": "Restart the bot", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "▶️"},
    {"name": "super_reset", "desc": "Factory wipe sections", "format": "`/super_reset [stars|tasks|all]`", "public": False, "super": True, "category": "👑 Super Owner", "emoji": "☢️"}
]
