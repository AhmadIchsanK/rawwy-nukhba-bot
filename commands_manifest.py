# Canonical command manifest to drive both help text and Telegram menu
COMMANDS = [
    # 🟢 GENERAL & AI
    {"name": "start", "desc": "Start interaction with bot", "category": "General", "access": "public", "public": True},
    {"name": "help", "desc": "View Nukhba Manual", "category": "General", "access": "public", "public": True},
    {"name": "gemini", "desc": "Ask Gemini AI any question", "category": "General", "access": "public", "public": True},
    {"name": "ask", "desc": "Ask about Nukhba Bot features", "category": "General", "access": "public", "public": True},
    {"name": "wdim", "desc": "What did I miss? (Recap)", "category": "General", "access": "public", "public": True},
    
    # 📅 EVENTS & POLLS
    {"name": "newevent", "desc": "Schedule a pinned event", "category": "Events & Polls", "access": "public", "public": True},
    {"name": "editevent", "desc": "Modify a scheduled event", "category": "Events & Polls", "access": "public", "public": True},
    {"name": "events", "desc": "View upcoming events", "category": "Events & Polls", "access": "public", "public": True},
    {"name": "poll", "desc": "Launch an interactive poll", "category": "Events & Polls", "access": "public", "public": True},
    
    # 🌟 RAWWY STARS
    {"name": "thanks", "desc": "Give a Star (Reply)", "category": "Stars", "access": "public", "public": True},
    {"name": "myquota", "desc": "Check Star Quota left", "category": "Stars", "access": "public", "public": True},
    {"name": "mystar", "desc": "Monthly Stars earned", "category": "Stars", "access": "public", "public": True},
    {"name": "totalstar", "desc": "All-time Stars earned", "category": "Stars", "access": "public", "public": True},
    {"name": "leaderboard", "desc": "Top RAWWY Stars", "category": "Stars", "access": "public", "public": True},
    
    # 🧠 TRIVIA
    {"name": "mypoint", "desc": "View your Trivia Points (DM)", "category": "Trivia", "access": "public", "public": True},
    
    # 📚 LIBRARY
    {"name": "addlib", "desc": "Save a library asset", "category": "Library", "access": "public", "public": True},
    {"name": "editlib", "desc": "Edit your asset", "category": "Library", "access": "public", "public": True},
    {"name": "dellib", "desc": "Delete your asset", "category": "Library", "access": "public", "public": True},
    {"name": "getlib", "desc": "Retrieve an asset", "category": "Library", "access": "public", "public": True},
    {"name": "library", "desc": "Browse the Library", "category": "Library", "access": "public", "public": True},
    
    # ⚡ TASKS & AWAY
    {"name": "assign", "desc": "Assign a task", "category": "Tasks & Away", "access": "public", "public": True},
    {"name": "complete", "desc": "Mark task complete", "category": "Tasks & Away", "access": "public", "public": True},
    {"name": "mytasks", "desc": "View your active tasks", "category": "Tasks & Away", "access": "public", "public": True},
    {"name": "away", "desc": "Set away status", "category": "Tasks & Away", "access": "public", "public": True},
    {"name": "back", "desc": "Return to available", "category": "Tasks & Away", "access": "public", "public": True},
    
    # 💡 EXTRAS
    {"name": "feedback", "desc": "Submit Feedback to dev", "category": "Extras", "access": "public", "public": True},

    # 🔐 ADMIN SUITE
    {"name": "botconfig", "desc": "Interactive Bot Settings", "category": "Admin", "access": "admin", "admin": True},
    {"name": "setchannel", "desc": "Set channel <bday|trivia|stars>", "category": "Admin", "access": "admin", "admin": True},
    {"name": "unsetchannel", "desc": "Unset channel <bday|trivia|stars>", "category": "Admin", "access": "admin", "admin": True},
    
    {"name": "triviaconfig", "desc": "Interactive Trivia Settings", "category": "Admin", "access": "admin", "admin": True},
    {"name": "forcetrivia", "desc": "Trigger standard trivia now", "category": "Admin", "access": "admin", "admin": True},
    {"name": "forcesupertrivia", "desc": "Trigger super trivia now", "category": "Admin", "access": "admin", "admin": True},
    {"name": "canceltrivia", "desc": "Force drop live trivia", "category": "Admin", "access": "admin", "admin": True},
    {"name": "admin_kp", "desc": "Edit trivia scores manually", "category": "Admin", "access": "admin", "admin": True},
    
    {"name": "addbday", "desc": "Add a user birthday", "category": "Admin", "access": "admin", "admin": True},
    {"name": "editbday", "desc": "Edit a user birthday", "category": "Admin", "access": "admin", "admin": True},
    {"name": "delbday", "desc": "Delete a user birthday", "category": "Admin", "access": "admin", "admin": True},
    {"name": "listbdays", "desc": "List registered birthdays", "category": "Admin", "access": "admin", "admin": True},

    {"name": "checkquota", "desc": "Audit Star quotas", "category": "Admin", "access": "admin", "admin": True},
    {"name": "admin_stars", "desc": "Modify user stars/quota", "category": "Admin", "access": "admin", "admin": True},
    {"name": "checklimit", "desc": "Audit weekly AI limits", "category": "Admin", "access": "admin", "admin": True},
    {"name": "admin_limit", "desc": "Modify a user's AI limit", "category": "Admin", "access": "admin", "admin": True},

    {"name": "attendance", "desc": "List currently Away users", "category": "Admin", "access": "admin", "admin": True},
    {"name": "forceback", "desc": "Force user back from Away", "category": "Admin", "access": "admin", "admin": True},
    {"name": "grouptasks", "desc": "View pending tasks globally", "category": "Admin", "access": "admin", "admin": True},
    {"name": "cancelevent", "desc": "Cancel a scheduled event", "category": "Admin", "access": "admin", "admin": True},
    {"name": "canceltask", "desc": "Cancel a task", "category": "Admin", "access": "admin", "admin": True},
    {"name": "cancelpoll", "desc": "Stop a live poll (Reply)", "category": "Admin", "access": "admin", "admin": True},

    {"name": "schedule", "desc": "Schedule an announcement", "category": "Admin", "access": "admin", "admin": True},
    {"name": "listschedules", "desc": "List announcements", "category": "Admin", "access": "admin", "admin": True},
    {"name": "delschedule", "desc": "Delete a schedule", "category": "Admin", "access": "admin", "admin": True},
    {"name": "announce", "desc": "Send an announcement", "category": "Admin", "access": "admin", "admin": True},
    {"name": "editannounce", "desc": "Edit an announcement", "category": "Admin", "access": "admin", "admin": True},
    {"name": "delannounce", "desc": "Delete an announcement", "category": "Admin", "access": "admin", "admin": True},
    {"name": "groupid", "desc": "Get current chat ID", "category": "Admin", "access": "admin", "admin": True},
    {"name": "auditlog", "desc": "Pull diagnostic logs", "category": "Admin", "access": "admin", "admin": True},

    {"name": "feedbacklist", "desc": "View recent feedback", "category": "Admin", "access": "admin", "admin": True},
    {"name": "analyze_feedback", "desc": "Analyze feedback via AI", "category": "Admin", "access": "admin", "admin": True},
    
    # 👑 SUPER OWNER
    {"name": "addadmin", "desc": "Promote a user to Admin", "category": "Super", "access": "super", "super": True},
    {"name": "deladmin", "desc": "Demote an Admin", "category": "Super", "access": "super", "super": True},
    {"name": "listadmins", "desc": "List current Admins", "category": "Super", "access": "super", "super": True},
    {"name": "removemember", "desc": "Offboard a member", "category": "Super", "access": "super", "super": True},
    {"name": "graveyard", "desc": "Show offboarded users", "category": "Super", "access": "super", "super": True},
    {"name": "botstatus", "desc": "Show system status", "category": "Super", "access": "super", "super": True},
    {"name": "pause", "desc": "Pause the bot", "category": "Super", "access": "super", "super": True},
    {"name": "restart", "desc": "Restart the bot", "category": "Super", "access": "super", "super": True},
    {"name": "super_reset", "desc": "Factory wipe sections", "category": "Super", "access": "super", "super": True}
]
