"""
cmd_manual.py — /manual  Bot User Manual Generator
────────────────────────────────────────────────────
Generates a compact, 3-language PDF manual (EN / AR / ID)
and sends it to the requesting user's DM.

Usage rules:
  • Anyone can request — but only ONCE per calendar month.
  • If they try again in the same month, the bot tells them to
    check their chat history.
  • PDF is generated on demand (not stored), kept small via
    compressed reportlab output.

Command: /manual
"""

import datetime
import io
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from core import WIB, delete_cmd

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# MANUAL CONTENT  (structured so it's easy to extend)
# ─────────────────────────────────────────────────────────────────────────────

MANUAL_SECTIONS = {
    "en": {
        "title":    "RAWWY Nukhba Manager — User Manual",
        "version":  "v1.3",
        "subtitle": "Complete command guide for all team members",
        "tip":      "Tip: Long-press any command format shown here to copy it, then paste in the group chat.",
        "sections": [
            ("⭐ RAWWY Stars — Recognise Your Teammates", [
                ("/thanks",
                 "Give a RAWWY Star to someone.\n"
                 "How: Reply to their message, then type /thanks.\n"
                 "Each star adds to their monthly and all-time tally.\n"
                 "Format: Reply to a message → /thanks"),
                ("/mystar",
                 "Check your own RAWWY Star count.\n"
                 "Shows: stars received this month + all-time total.\n"
                 "Format: /mystar"),
                ("/myquota",
                 "See how many stars you still have left to give this week.\n"
                 "Quota resets every Monday. Format: /myquota"),
                ("/leaderboard_star",
                 "View the Top 5 RAWWY Star earners — both monthly and all-time.\n"
                 "Format: /leaderboard_star"),
            ]),
            ("🎮 Trivia & Knowledge Points (KP)", [
                ("/mypoint",
                 "See your current Knowledge Point total — monthly and all-time.\n"
                 "KP is earned by answering trivia questions correctly.\n"
                 "Format: /mypoint"),
                ("/leaderboard_kp",
                 "View the Top 5 KP earners this month.\n"
                 "Format: /leaderboard_kp"),
            ]),
            ("📅 Events & Polls", [
                ("/eventpoll",
                 "Open the Events & Polls hub.\n"
                 "• In a group: automatically targets that group.\n"
                 "• In DM: you pick the group first.\n"
                 "Sub-menu options:\n"
                 "  📅 New Event → enter title, date/time, reminder minutes\n"
                 "  📊 New Poll → enter question + options (one per line), set anon/multi/quiz/duration\n"
                 "  📋 List Events → view upcoming events (30-min cooldown per group)\n"
                 "  ✏️ Edit Event → pick one of your events and update it\n"
                 "  ❌ Cancel → remove your event or poll (admins can cancel any)\n"
                 "Format: /eventpoll"),
                ("/listevent",
                 "Quick-view upcoming events in this group.\n"
                 "Format: /listevent"),
            ]),
            ("📚 Library — Team Assets", [
                ("/library",
                 "Open the Library hub in DM.\n"
                 "Sub-menu options:\n"
                 "  📂 Browse → paginated list of all public assets + your private ones\n"
                 "  🔍 Get Asset → type a name to retrieve it\n"
                 "  ➕ Add → type: Name , Content   (add ', private' to keep it private)\n"
                 "  📦 Batch Add → one entry per line: Name , Content\n"
                 "  ✏️ Edit → type: Name , New Content   (owners only)\n"
                 "  🗑️ Delete → pick from your own assets\n"
                 "Format: /library"),
            ]),
            ("📋 Tasks — Assign & Track Work", [
                ("/task",
                 "Assign a task to one or more team members.\n"
                 "• In a group: tap member names to add/remove assignees. Type the task description in chat. Press Finish.\n"
                 "• In DM: step-by-step — pick group → type description → type assignees (comma-separated) → set deadline in minutes.\n"
                 "Each assignee receives a DM notification with the task details.\n"
                 "Format: /task"),
                ("/mytask",
                 "View all tasks assigned to you — sent to DM as an inline list.\n"
                 "Each row shows: task description + time remaining.\n"
                 "Tap a task to toggle Complete ✅ / Incomplete 🔲.\n"
                 "Press Finish to save — your assigner gets a DM when all assignees complete the task.\n"
                 "Format: /mytask"),
                ("/grouptasks",
                 "View all active tasks in this group.\n"
                 "Shows: task description, who assigned it, who it's assigned to, status (Pending / Overdue / Done).\n"
                 "Also shows the last 7 completed tasks.\n"
                 "Admins running this in a group see ALL tasks across all assignees.\n"
                 "Format: /grouptasks"),
            ]),
            ("🏖️ Away Status", [
                ("/away",
                 "Open the Away hub in DM.\n"
                 "Sub-menu options:\n"
                 "  🏖️ Set Away → type reason, then return date/time (MM/DD/YYYY HH:MM)\n"
                 "  🟢 I'm Back → confirm to clear away status + receive missed mentions\n"
                 "  ⚙️ Auto-Cancel → toggle: if ON, sending any group message auto-clears your away\n"
                 "  📋 My Status → see your current reason, return time, and mention count\n"
                 "Format: /away"),
                ("/back",
                 "Mark yourself as available again — type this directly in any chat.\n"
                 "Missed mentions will be delivered to your DM.\n"
                 "Format: /back"),
            ]),
            ("🤖 AI Assistant ⚠️ Experimental", [
                ("/ai",
                 "Ask the AI assistant (powered by Groq/Llama) any question.\n"
                 "Examples: explain a concept, translate text, summarise something.\n"
                 "Format: /ai What is a KPI?"),
                ("/ask",
                 "Ask a question about this bot's features and how to use them.\n"
                 "Format: /ask How do I set an away status?"),
                ("/wdim",
                 "What Did I Miss? — Get an AI-generated recap of recent group activity.\n"
                 "Useful after returning from away.\n"
                 "Format: /wdim"),
            ]),
            ("ℹ️ General", [
                ("/start",
                 "Register yourself with the bot and open the welcome menu.\n"
                 "Run this once when you first join — required before using other features.\n"
                 "Format: /start"),
                ("/help",
                 "Show a full categorised list of all available commands.\n"
                 "Format: /help"),
                ("/command",
                 "Open an interactive inline menu to browse every command with full usage details.\n"
                 "Format: /command"),
                ("/update",
                 "See the latest bot version and changelog.\n"
                 "Format: /update"),
                ("/feedback",
                 "Send a suggestion or report directly to the admin team.\n"
                 "Format: /feedback Your message here"),
                ("/manual",
                 "Receive this full user manual as a PDF.\n"
                 "Available once every 30 days. Check your chat history to find a previous copy.\n"
                 "Format: /manual"),
            ]),
        ]
    },
    "ar": {
        "title":    "دليل مستخدم بوت Nukhba Manager",
        "version":  "v1.3",
        "subtitle": "دليل شامل لجميع أوامر المستخدم",
        "tip":      "نصيحة: اضغط مطولاً على صيغة الأمر لنسخها ثم الصقها في المجموعة.",
        "sections": [
            ("⭐ نجوم RAWWY — قدّر زملاءك", [
                ("/thanks",
                 "امنح نجمة RAWWY لشخص ما.\n"
                 "الطريقة: رُد على رسالته ثم اكتب /thanks.\n"
                 "الصيغة: الرد على رسالة ثم /thanks"),
                ("/mystar",
                 "اعرض عدد نجومك الشهرية والإجمالية.\n"
                 "الصيغة: /mystar"),
                ("/myquota",
                 "تحقق من عدد النجوم المتبقية لديك هذا الأسبوع.\n"
                 "تُجدَّد الحصة كل يوم اثنين. الصيغة: /myquota"),
                ("/leaderboard_star",
                 "اعرض أفضل 5 حاصلين على نجوم RAWWY شهرياً وإجمالاً.\n"
                 "الصيغة: /leaderboard_star"),
            ]),
            ("🎮 التريفيا ونقاط المعرفة", [
                ("/mypoint",
                 "اعرض نقاط معرفتك الشهرية والإجمالية.\n"
                 "الصيغة: /mypoint"),
                ("/leaderboard_kp",
                 "اعرض أفضل 5 حاصلين على نقاط المعرفة هذا الشهر.\n"
                 "الصيغة: /leaderboard_kp"),
            ]),
            ("📅 الفعاليات والاستطلاعات", [
                ("/eventpoll",
                 "افتح قائمة الفعاليات والاستطلاعات.\n"
                 "في المجموعة: تُضبط المجموعة تلقائياً.\n"
                 "في الرسائل الخاصة: اختر المجموعة أولاً.\n"
                 "الخيارات:\n"
                 "  📅 فعالية جديدة ← العنوان، التاريخ/الوقت، التذكير\n"
                 "  📊 استطلاع جديد ← السؤال + الخيارات\n"
                 "  📋 قائمة الفعاليات ← الفعاليات القادمة\n"
                 "  ✏️ تعديل فعالية ← تحديث بياناتها\n"
                 "  ❌ إلغاء ← حذف فعالية أو استطلاع\n"
                 "الصيغة: /eventpoll"),
                ("/listevent",
                 "اعرض الفعاليات القادمة في هذه المجموعة.\n"
                 "الصيغة: /listevent"),
            ]),
            ("📚 المكتبة — أصول الفريق", [
                ("/library",
                 "افتح قائمة المكتبة في الرسائل الخاصة.\n"
                 "الخيارات:\n"
                 "  📂 تصفّح ← قائمة مُقسَّمة بالصفحات\n"
                 "  🔍 جلب أصل ← اكتب الاسم لاسترجاعه\n"
                 "  ➕ إضافة ← الاسم , المحتوى (أضف ', private' للخصوصية)\n"
                 "  📦 إضافة مجمّعة ← سطر لكل أصل\n"
                 "  ✏️ تعديل ← الاسم , المحتوى الجديد\n"
                 "  🗑️ حذف ← من أصولك فقط\n"
                 "الصيغة: /library"),
            ]),
            ("📋 المهام", [
                ("/task",
                 "أسند مهمة لأعضاء الفريق.\n"
                 "في المجموعة: انقر على الأسماء لتحديدهم، اكتب الوصف، ثم اضغط إنهاء.\n"
                 "في الرسائل الخاصة: خطوة بخطوة.\n"
                 "الصيغة: /task"),
                ("/mytask",
                 "اعرض مهامك المعلّقة في الرسائل الخاصة.\n"
                 "انقر على المهمة لتبديل حالتها. اضغط إنهاء للحفظ.\n"
                 "الصيغة: /mytask"),
                ("/grouptasks",
                 "اعرض جميع المهام النشطة في المجموعة مع الحالة والمسؤولين.\n"
                 "الصيغة: /grouptasks"),
            ]),
            ("🏖️ حالة الغياب", [
                ("/away",
                 "افتح قائمة الغياب في الرسائل الخاصة.\n"
                 "الخيارات:\n"
                 "  🏖️ ضبط الغياب ← السبب ووقت العودة\n"
                 "  🟢 عُدت ← مسح حالة الغياب\n"
                 "  ⚙️ إلغاء تلقائي ← تبديل الخيار\n"
                 "  📋 حالتي ← عرض السبب ووقت العودة وعدد الإشعارات\n"
                 "الصيغة: /away"),
                ("/back",
                 "أعلن عودتك في أي محادثة لاستلام الإشعارات الفائتة.\n"
                 "الصيغة: /back"),
            ]),
            ("🤖 المساعد الذكي ⚠️ تجريبي", [
                ("/ai",
                 "اسأل المساعد الذكي أي سؤال.\n"
                 "مثال: /ai ما هو مؤشر الأداء الرئيسي؟"),
                ("/wdim",
                 "احصل على ملخص ذكي لما فاتك في المجموعة.\n"
                 "الصيغة: /wdim"),
            ]),
            ("ℹ️ عام", [
                ("/start",  "سجّل دخولك واستخدام البوت — مطلوب مرة واحدة."),
                ("/help",   "اعرض قائمة شاملة بجميع الأوامر مقسّمةً بالفئات."),
                ("/command","قائمة تفاعلية لاستعراض تفاصيل الأوامر."),
                ("/update", "اعرض أحدث إصدار ومحتويات التحديث."),
                ("/feedback","أرسل اقتراحاً أو بلاغاً لفريق الإدارة."),
                ("/manual", "استلم هذا الدليل بصيغة PDF — مرة كل 30 يوماً."),
            ]),
        ]
    },
    "id": {
        "title":    "Panduan Pengguna Nukhba Manager Bot",
        "version":  "v1.3",
        "subtitle": "Panduan lengkap semua perintah pengguna",
        "tip":      "Tips: Tekan lama format perintah untuk menyalinnya, lalu tempel di grup.",
        "sections": [
            ("⭐ RAWWY Stars — Apresiasi Rekan Tim", [
                ("/thanks",
                 "Beri RAWWY Star kepada seseorang.\n"
                 "Cara: Balas pesannya, lalu ketik /thanks.\n"
                 "Format: Balas pesan → /thanks"),
                ("/mystar",
                 "Lihat jumlah RAWWY Star yang kamu terima — bulanan dan sepanjang waktu.\n"
                 "Format: /mystar"),
                ("/myquota",
                 "Cek sisa jatah Star yang bisa kamu beri minggu ini. Reset setiap Senin.\n"
                 "Format: /myquota"),
                ("/leaderboard_star",
                 "Lihat Top 5 penerima RAWWY Star bulan ini dan sepanjang waktu.\n"
                 "Format: /leaderboard_star"),
            ]),
            ("🎮 Trivia & Knowledge Points (KP)", [
                ("/mypoint",
                 "Lihat total KP kamu — bulanan dan sepanjang waktu.\n"
                 "Format: /mypoint"),
                ("/leaderboard_kp",
                 "Lihat Top 5 peraih KP bulan ini.\n"
                 "Format: /leaderboard_kp"),
            ]),
            ("📅 Acara & Polling", [
                ("/eventpoll",
                 "Buka hub Acara & Polling.\n"
                 "• Di grup: grup target diset otomatis.\n"
                 "• Di DM: pilih grup terlebih dahulu.\n"
                 "Sub-menu:\n"
                 "  📅 Acara Baru → judul, tanggal/waktu, menit pengingat\n"
                 "  📊 Polling Baru → pertanyaan + pilihan (satu per baris)\n"
                 "  📋 Daftar Acara → acara yang akan datang\n"
                 "  ✏️ Edit Acara → perbarui acara milikmu\n"
                 "  ❌ Batalkan → hapus acara atau polling\n"
                 "Format: /eventpoll"),
                ("/listevent",
                 "Tampilkan acara mendatang di grup ini.\n"
                 "Format: /listevent"),
            ]),
            ("📚 Library — Aset Tim", [
                ("/library",
                 "Buka hub Library di DM.\n"
                 "Sub-menu:\n"
                 "  📂 Browse → daftar aset dengan paginasi\n"
                 "  🔍 Get Asset → ketik nama untuk mengambilnya\n"
                 "  ➕ Add → Nama , Konten  (tambah ', private' agar privat)\n"
                 "  📦 Batch Add → satu entri per baris\n"
                 "  ✏️ Edit → Nama , Konten Baru  (hanya milikmu)\n"
                 "  🗑️ Delete → pilih dari aset milikmu\n"
                 "Format: /library"),
            ]),
            ("📋 Tugas", [
                ("/task",
                 "Tugaskan pekerjaan ke anggota tim.\n"
                 "• Di grup: ketuk nama anggota, ketik deskripsi, tekan Selesai.\n"
                 "• Di DM: langkah demi langkah.\n"
                 "Format: /task"),
                ("/mytask",
                 "Lihat daftar tugasmu di DM. Ketuk untuk tandai selesai. Tekan Selesai untuk simpan.\n"
                 "Format: /mytask"),
                ("/grouptasks",
                 "Lihat semua tugas aktif di grup ini — siapa yang menugaskan, kepada siapa, dan statusnya.\n"
                 "Format: /grouptasks"),
            ]),
            ("🏖️ Status Away", [
                ("/away",
                 "Buka hub Away di DM.\n"
                 "Sub-menu:\n"
                 "  🏖️ Set Away → alasan + waktu kembali (MM/DD/YYYY HH:MM)\n"
                 "  🟢 I'm Back → hapus status away\n"
                 "  ⚙️ Auto-Cancel → jika ON, pesan di grup otomatis membatalkan away\n"
                 "  📋 My Status → lihat alasan, waktu kembali, dan jumlah mention\n"
                 "Format: /away"),
                ("/back",
                 "Tandai dirimu kembali tersedia di chat mana pun. Mention yang terlewat akan dikirim ke DM.\n"
                 "Format: /back"),
            ]),
            ("🤖 AI Assistant ⚠️ Eksperimental", [
                ("/ai",
                 "Tanya asisten AI apa pun.\n"
                 "Format: /ai Apa itu KPI?"),
                ("/wdim",
                 "Dapatkan rangkuman AI tentang aktivitas grup saat kamu away.\n"
                 "Format: /wdim"),
            ]),
            ("ℹ️ Umum", [
                ("/start",   "Daftarkan diri ke bot — wajib dilakukan sekali saat pertama bergabung."),
                ("/help",    "Tampilkan daftar lengkap perintah berdasarkan kategori."),
                ("/command", "Menu interaktif untuk menjelajahi perintah dengan detail lengkap."),
                ("/update",  "Lihat versi terbaru bot dan isi pembaruan."),
                ("/feedback","Kirim saran atau laporan ke tim admin."),
                ("/manual",  "Terima panduan ini sebagai PDF — sekali setiap 30 hari."),
            ]),
        ]
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# PDF BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_pdf() -> bytes:
    """
    Generate a compact 3-language PDF manual.
    Returns raw PDF bytes. Uses reportlab Platypus for clean layout.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm,  bottomMargin=16*mm,
        compress=True,
    )

    base    = getSampleStyleSheet()
    W, _H   = A4

    # ── Custom styles ─────────────────────────────────────────────────────────
    s_doc_title = ParagraphStyle("DocTitle",
        parent=base["Title"], fontSize=15, leading=20,
        textColor=colors.HexColor("#1a237e"), spaceAfter=2
    )
    s_version = ParagraphStyle("Version",
        parent=base["Normal"], fontSize=9, textColor=colors.grey,
        alignment=TA_CENTER, spaceAfter=6
    )
    s_subtitle = ParagraphStyle("Sub",
        parent=base["Normal"], fontSize=10, textColor=colors.HexColor("#37474f"),
        alignment=TA_CENTER, spaceAfter=10
    )
    s_lang_header = ParagraphStyle("LangH",
        parent=base["Heading1"], fontSize=13, leading=18,
        textColor=colors.HexColor("#0d47a1"),
        borderPad=4, spaceBefore=10, spaceAfter=4
    )
    s_section = ParagraphStyle("Sec",
        parent=base["Heading2"], fontSize=10, leading=14,
        textColor=colors.HexColor("#1565c0"),
        spaceBefore=8, spaceAfter=2
    )
    s_cmd = ParagraphStyle("Cmd",
        parent=base["Normal"], fontSize=9, leading=13,
        fontName="Courier-Bold", textColor=colors.HexColor("#1b5e20"),
        leftIndent=8
    )
    s_desc = ParagraphStyle("Desc",
        parent=base["Normal"], fontSize=8.5, leading=12,
        textColor=colors.HexColor("#37474f"),
        leftIndent=16, spaceAfter=5
    )
    s_tip = ParagraphStyle("Tip",
        parent=base["Normal"], fontSize=8, fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#6a1b9a"),
        borderPad=4, leftIndent=8, spaceAfter=8
    )
    s_footer = ParagraphStyle("Footer",
        parent=base["Normal"], fontSize=7.5,
        textColor=colors.grey, alignment=TA_CENTER
    )

    story = []
    divider = HRFlowable(width="100%", thickness=0.5,
                          color=colors.HexColor("#b0bec5"), spaceAfter=6, spaceBefore=4)

    # ── Cover block ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("🤖 RAWWY Nukhba Manager Bot", s_doc_title))
    story.append(Paragraph("User Manual · v1.3", s_version))
    story.append(Paragraph("English  ·  العربية  ·  Bahasa Indonesia", s_subtitle))
    story.append(divider)
    story.append(Spacer(1, 4*mm))

    lang_labels = {"en": "🇬🇧 English", "ar": "🇸🇦 العربية", "id": "🇮🇩 Bahasa Indonesia"}

    for i, (lang_code, data) in enumerate(MANUAL_SECTIONS.items()):
        # Language header
        story.append(Paragraph(lang_labels[lang_code], s_lang_header))
        story.append(Paragraph(data["subtitle"], s_subtitle))
        story.append(Paragraph(f"💡 {data['tip']}", s_tip))
        story.append(divider)

        for section_title, commands in data["sections"]:
            story.append(Paragraph(section_title, s_section))
            for cmd, desc in commands:
                story.append(Paragraph(cmd, s_cmd))
                # Replace newlines with <br/> for Paragraph
                desc_html = desc.replace("\n", "<br/>")
                story.append(Paragraph(desc_html, s_desc))
            story.append(Spacer(1, 2*mm))

        # Page break between languages (except after last)
        if i < len(MANUAL_SECTIONS) - 1:
            story.append(PageBreak())

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(divider)
    now_str = datetime.datetime.now(WIB).strftime("%B %Y")
    story.append(Paragraph(
        f"Generated {now_str} · RAWWY Nukhba Manager Bot · /manual once per month",
        s_footer
    ))

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def manual_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /manual — send the bot user manual PDF.
    Gate: once per calendar month per user. Stored in DB.
    """
    await delete_cmd(update)
    uid      = update.effective_user.id
    username = update.effective_user.username or str(uid)
    pool     = context.bot_data.get("db_pool")

    # ── Ensure tracking table exists ──────────────────────────────────────────
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS manual_requests (
                user_id   BIGINT NOT NULL,
                last_sent DATE   NOT NULL,
                PRIMARY KEY (user_id)
            )
        """)

    # ── 30-day rolling cooldown gate ─────────────────────────────────────────
    today = datetime.date.today()

    async with pool.acquire() as conn:
        last = await conn.fetchval("SELECT last_sent FROM manual_requests WHERE user_id=$1", uid)

    if last:
        days_since = (today - last).days
        if days_since < 30:
            days_left = 30 - days_since
            try:
                await context.bot.send_message(
                    uid,
                    f"📖 You received the manual *{days_since}* day(s) ago.\n\n"
                    f"📂 Check your chat history with me to find the PDF.\n"
                    f"🔄 You can request again in *{days_left} day(s)*.",
                    parse_mode="Markdown"
                )
            except Exception:
                if update.message:
                    await update.message.reply_text(
                        f"📖 You received the manual {days_since} day(s) ago. "
                        f"Check your chat history. Available again in {days_left} day(s)."
                    )
            return

    # ── Generate and send ─────────────────────────────────────────────────────
    # Send a "generating" notice
    notice = None
    try:
        notice = await context.bot.send_message(uid, "📖 Generating your manual… please wait.")
    except Exception:
        if update.message:
            await update.message.reply_text(
                "❌ Please start a DM with me first — click /start, then try /manual again."
            )
        return

    try:
        pdf_bytes = _build_pdf()
        now_str   = datetime.datetime.now(WIB).strftime("%B_%Y")
        filename  = f"Nukhba_Manager_Manual_{now_str}.pdf"

        await context.bot.send_document(
            uid,
            document=io.BytesIO(pdf_bytes),
            filename=filename,
            caption=(
                "📖 *Nukhba Manager — User Manual*\n"
                f"Version 1.3 · {datetime.datetime.now(WIB).strftime('%B %Y')}\n\n"
                "3 languages: 🇬🇧 English · 🇸🇦 Arabic · 🇮🇩 Indonesian\n\n"
                "_Use /command for interactive command browsing with full usage details._"
            ),
            parse_mode="Markdown"
        )

        # Record this month's request
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO manual_requests (user_id, last_sent) VALUES ($1, $2) "
                "ON CONFLICT (user_id) DO UPDATE SET last_sent=$2",
                uid, today
            )

        if notice:
            try:
                await notice.delete()
            except Exception:
                pass

    except Exception as e:
        logger.error(f"/manual PDF generation error for {username}: {e}")
        if notice:
            try:
                await notice.edit_text(
                    "❌ Something went wrong generating the manual. Please try again later."
                )
            except Exception:
                pass
