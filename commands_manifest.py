# Canonical command manifest to drive both help text and Telegram menu
# Each entry: name, description, public (shows in menu), admin (requires bot admin), super (requires SUPER_OWNER)
COMMANDS = [
    {"name": "start", "desc": "Start interaction with bot", "public": True},
    {"name": "help", "desc": "View Nukhba Manual", "public": True},
    {"name": "gemini", "desc": "Ask Gemini AI", "public": True},
    {"name": "ask", "desc": "Ask about Nukhba Bot", "public": True},

    {"name": "newevent", "desc": "Schedule an event", "public": True},
    {"name": "editevent", "desc": "Edit your event", "public": True},
    {"name": "events", "desc": "View upcoming events", "public": True},

    {"name": "poll", "desc": "Interactive Team Poll", "public": True},
    {"name": "thanks", "desc": "Give a Star (Reply)", "public": True},
    {"name": "myquota", "desc": "Check Star Quota left", "public": True},
    {"name": "mystar", "desc": "Monthly Stars earned", "public": True},
    {"name": "totalstar", "desc": "All-time Stars earned", "public": True},
    {"name": "leaderboard", "desc": "Top RAWWY Stars", "public": True},

    {"name": "mypoint", "desc": "View your Trivia Points", "public": True},
    {"name": "addlib", "desc": "Save a library asset", "public": True},
    {"name": "editlib", "desc": "Edit your asset", "public": True},
    {"name": "dellib", "desc": "Delete your asset", "public": True},
    {"name": "getlib", "desc": "Retrieve an asset", "public": True},
    {"name": "library", "desc": "Browse the Library", "public": True},

    {"name": "assign", "desc": "Assign a task", "public": True},
    {"name": "complete", "desc": "Mark task complete", "public": True},
    {"name": "mytasks", "desc": "View your active tasks", "public": True},
    {"name": "away", "desc": "Set away status", "public": True},
    {"name": "back", "desc": "Return to available", "public": True},
    {"name": "feedback", "desc": "Submit Feedback", "public": True},

    # Trivia consolidated command (entry point)
    {"name": "trivia", "desc": "Trivia configuration & controls", "public": False, "admin": True},

    # Admin-only commands (appear in admin help, not public menu)
    {"name": "setbdaychannel", "desc": "Set Birthday channel (run inside group)", "public": False, "admin": True},
    {"name": "setbdaytime", "desc": "Set daily birthday time (WIB)", "public": False, "admin": True},
    {"name": "bdayconfig", "desc": "Show birthday configuration", "public": False, "admin": True},
    {"name": "listbdays", "desc": "List registered birthdays", "public": False, "admin": True},
    {"name": "addbday", "desc": "Add a birthday entry", "public": False, "admin": True},
    {"name": "editbday", "desc": "Edit a birthday entry", "public": False, "admin": True},
    {"name": "delbday", "desc": "Delete a birthday entry", "public": False, "admin": True},

    {"name": "checkquota", "desc": "Audit Star quotas", "public": False, "admin": True},
    {"name": "admin_stars", "desc": "Modify user stars or quota", "public": False, "admin": True},
    {"name": "setweeklyquota", "desc": "Set default weekly Star Quota", "public": False, "admin": True},

    {"name": "checklimit", "desc": "Audit weekly AI limits", "public": False, "admin": True},
    {"name": "admin_limit", "desc": "Modify a user's AI limit", "public": False, "admin": True},
    {"name": "setweeklylimit", "desc": "Set default weekly AI limit", "public": False, "admin": True},

    {"name": "attendance", "desc": "List currently Away users", "public": False, "admin": True},
    {"name": "forceback", "desc": "Force a user back from Away", "public": False, "admin": True},
    {"name": "grouptasks", "desc": "View pending tasks globally", "public": False, "admin": True},

    {"name": "cancelevent", "desc": "Cancel a scheduled event", "public": False, "admin": True},
    {"name": "canceltask", "desc": "Cancel a task", "public": False, "admin": True},
    {"name": "cancelpoll", "desc": "Stop a live poll", "public": False, "admin": True},

    {"name": "schedule", "desc": "Schedule an announcement", "public": False, "admin": True},
    {"name": "listschedules", "desc": "List scheduled announcements", "public": False, "admin": True},
    {"name": "delschedule", "desc": "Delete a schedule", "public": False, "admin": True},
    {"name": "announce", "desc": "Send an announcement", "public": False, "admin": True},
    {"name": "editannounce", "desc": "Edit an announcement", "public": False, "admin": True},
    {"name": "delannounce", "desc": "Delete an announcement", "public": False, "admin": True},

    {"name": "feedbacklist", "desc": "View recent feedback", "public": False, "admin": True},
    {"name": "analyze_feedback", "desc": "Analyze feedback via AI", "public": False, "admin": True},
    {"name": "alltimefeedback", "desc": "All-time feedback", "public": False, "admin": True},

    # Super owner commands
    {"name": "addadmin", "desc": "Promote a user to Admin", "public": False, "super": True},
    {"name": "deladmin", "desc": "Demote an Admin", "public": False, "super": True},
    {"name": "listadmins", "desc": "List current Admins", "public": False, "super": True},
    {"name": "removemember", "desc": "Offboard a member", "public": False, "super": True},
    {"name": "graveyard", "desc": "Show offboarded users", "public": False, "super": True},
    {"name": "botstatus", "desc": "Show system status", "public": False, "super": True},
    {"name": "pause", "desc": "Pause the bot (maintenance)", "public": False, "super": True},
    {"name": "restart", "desc": "Restart the bot (resume)", "public": False, "super": True},
    {"name": "super_reset", "desc": "Factory wipe sections", "public": False, "super": True},

    # Utility: unset channel (generic)
    {"name": "unsetchannel", "desc": "Unset a configured channel: /unsetchannel <bday|trivia|announce>", "public": False, "admin": True},
]
