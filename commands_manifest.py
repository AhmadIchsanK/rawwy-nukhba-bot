# Canonical command manifest to drive both help text and Telegram menu
COMMANDS = [
    # 🟢 GENERAL & AI
    {"name": "start", "desc": "Start interaction with bot", "public": True},
    {"name": "help", "desc": "View Nukhba Manual", "public": True},
    {"name": "gemini", "desc": "Ask Gemini AI any question", "public": True},
    {"name": "ask", "desc": "Ask about Nukhba Bot features", "public": True},
    {"name": "wdim", "desc": "What did I miss? (Recap)", "public": True},
    
    # 📅 EVENTS & POLLS
    {"name": "newevent", "desc": "Schedule a pinned event", "public": True},
    {"name": "editevent", "desc": "Modify a scheduled event", "public": True},
    {"name": "events", "desc": "View upcoming events", "public": True},
    {"name": "poll", "desc": "Launch an interactive poll", "public": True},
    
    # 🌟 RAWWY STARS
    {"name": "thanks", "desc": "Give a Star (Reply)", "public": True},
    {"name": "myquota", "desc": "Check Star Quota left", "public": True},
    {"name": "mystar", "desc": "Monthly Stars earned", "public": True},
    {"name": "totalstar", "desc": "All-time Stars earned", "public": True},
    {"name": "leaderboard", "desc": "Top RAWWY Stars", "public": True},
    
    # 🧠 TRIVIA
    {"name": "mypoint", "desc": "View your Trivia Points (DM)", "public": True},
    
    # 📚 LIBRARY
    {"name": "addlib", "desc": "Save a library asset", "public": True},
    {"name": "editlib", "desc": "Edit your asset", "public": True},
    {"name": "dellib", "desc": "Delete your asset", "public": True},
    {"name": "getlib", "desc": "Retrieve an asset", "public": True},
    {"name": "library", "desc": "Browse the Library", "public": True},
    
    # ⚡ TASKS & AWAY
    {"name": "assign", "desc": "Assign a task", "public": True},
    {"name": "complete", "desc": "Mark task complete", "public": True},
    {"name": "mytasks", "desc": "View your active tasks", "public": True},
    {"name": "away", "desc": "Set away status", "public": True},
    {"name": "back", "desc": "Return to available", "public": True},
    
    # 💡 EXTRAS
    {"name": "feedback", "desc": "Submit Feedback to dev", "public": True},

    # 🔐 ADMIN SUITE
    {"name": "botconfig", "desc": "Interactive Bot Settings", "public": False, "admin": True},
    {"name": "setchannel", "desc": "Set channel <bday|trivia|stars>", "public": False, "admin": True},
    {"name": "unsetchannel", "desc": "Unset channel <bday|trivia|stars>", "public": False, "admin": True},
    
    {"name": "triviaconfig", "desc": "Interactive Trivia Settings", "public": False, "admin": True},
    {"name": "forcetrivia", "desc": "Trigger standard trivia now", "public": False, "admin": True},
    {"name": "forcesupertrivia", "desc": "Trigger super trivia now", "public": False, "admin": True},
    {"name": "canceltrivia", "desc": "Force drop live trivia", "public": False, "admin": True},
    {"name": "admin_kp", "desc": "Edit trivia scores manually", "public": False, "admin": True},
    
    {"name": "addbday", "desc": "Add a user birthday", "public": False, "admin": True},
    {"name": "editbday", "desc": "Edit a user birthday", "public": False, "admin": True},
    {"name": "delbday", "desc": "Delete a user birthday", "public": False, "admin": True},
    {"name": "listbdays", "desc": "List registered birthdays", "public": False, "admin": True},

    {"name": "checkquota", "desc": "Audit Star quotas", "public": False, "admin": True},
    {"name": "admin_stars", "desc": "Modify user stars/quota", "public": False, "admin": True},
    {"name": "checklimit", "desc": "Audit weekly AI limits", "public": False, "admin": True},
    {"name": "admin_limit", "desc": "Modify a user's AI limit", "public": False, "admin": True},

    {"name": "attendance", "desc": "List currently Away users", "public": False, "admin": True},
    {"name": "forceback", "desc": "Force user back from Away", "public": False, "admin": True},
    {"name": "grouptasks", "desc": "View pending tasks globally", "public": False, "admin": True},
    {"name": "cancelevent", "desc": "Cancel a scheduled event", "public": False, "admin": True},
    {"name": "canceltask", "desc": "Cancel a task", "public": False, "admin": True},
    {"name": "cancelpoll", "desc": "Stop a live poll (Reply)", "public": False, "admin": True},

    {"name": "schedule", "desc": "Schedule an announcement", "public": False, "admin": True},
    {"name": "listschedules", "desc": "List announcements", "public": False, "admin": True},
    {"name": "delschedule", "desc": "Delete a schedule", "public": False, "admin": True},
    {"name": "announce", "desc": "Send an announcement", "public": False, "admin": True},
    {"name": "editannounce", "desc": "Edit an announcement", "public": False, "admin": True},
    {"name": "delannounce", "desc": "Delete an announcement", "public": False, "admin": True},
    {"name": "groupid", "desc": "Get current chat ID", "public": False, "admin": True},
    {"name": "auditlog", "desc": "Pull diagnostic logs", "public": False, "admin": True},

    {"name": "feedbacklist", "desc": "View recent feedback", "public": False, "admin": True},
    {"name": "analyze_feedback", "desc": "Analyze feedback via AI", "public": False, "admin": True},
    
    # 👑 SUPER OWNER
    {"name": "addadmin", "desc": "Promote a user to Admin", "public": False, "super": True},
    {"name": "deladmin", "desc": "Demote an Admin", "public": False, "super": True},
    {"name": "listadmins", "desc": "List current Admins", "public": False, "super": True},
    {"name": "removemember", "desc": "Offboard a member", "public": False, "super": True},
    {"name": "graveyard", "desc": "Show offboarded users", "public": False, "super": True},
    {"name": "botstatus", "desc": "Show system status", "public": False, "super": True},
    {"name": "pause", "desc": "Pause the bot", "public": False, "super": True},
    {"name": "restart", "desc": "Restart the bot", "public": False, "super": True},
    {"name": "super_reset", "desc": "Factory wipe sections", "public": False, "super": True}
]
