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
        "version":  "v1.2",
        "subtitle": "A complete guide to all user commands",
        "tip":      "Tip: Long-press any command format to copy it, then paste in the group.",
        "sections": [
            ("⭐ RAWWY Stars", [
                ("/thanks",      "Reply to any message with /thanks to give that person a RAWWY Star."),
                ("/mystar",      "See your monthly and all-time RAWWY Stars received."),
                ("/myquota",     "Check how many Stars you have left to give this week."),
            ]),
            ("🎮 Trivia & Knowledge Points", [
                ("/trivia",      "Start a trivia session in the group (admin-triggered automatically)."),
                ("/mypoint",     "Check your current Knowledge Point (KP) total."),
            ]),
            ("📅 Events & Polls", [
                ("/events",      "Open the Events & Polls hub in DM. Create events, polls, edit or cancel — all inline.\n"
                                 "Format: /events  →  tap New Event or New Poll in the menu."),
            ]),
            ("📚 Library", [
                ("/library",     "Open the Library hub in DM. Browse, get, add, batch-add, edit, and delete assets.\n"
                                 "Format: /library  →  use inline menu."),
            ]),
            ("📋 Tasks", [
                ("/task",        "Assign a task.\n"
                                 "• In a group: tap members to add/remove, type description, press Finish.\n"
                                 "• In DM: step-by-step — pick group → description → assignees → deadline."),
                ("/mytask",      "View your pending tasks in DM. Tap a task to mark complete. Press Finish to save."),
            ]),
            ("🏖️ Away Status", [
                ("/away",        "Open the Away hub in DM. Set away reason + return time via inline menu."),
                ("/back",        "Type /back in any chat to mark yourself as available and receive missed mentions."),
            ]),
            ("🤖 AI Assistant", [
                ("/ai",          "Ask the AI assistant (Groq/Llama) any question.\n"
                                 "Format: /ai What is a KPI?"),
                ("/ask",         "Ask about the bot's features.\n"
                                 "Format: /ask How do I set my away status?"),
                ("/wdim",        "Get an AI recap of what happened in the group while you were away."),
            ]),
            ("ℹ️ General", [
                ("/start",       "Register with the bot and open the welcome menu."),
                ("/help",        "Show a full list of commands by category."),
                ("/command",     "Open an interactive menu to browse commands with full usage details."),
                ("/update",      "See the latest changelog and bot version."),
                ("/feedback",    "Send a suggestion or report to the admin team."),
                ("/manual",      "Receive this user manual (once per month)."),
            ]),
        ]
    },
    "ar": {
        "title":    "دليل مستخدم بوت Nukhba Manager",
        "version":  "v1.2",
        "subtitle": "دليل شامل لجميع أوامر المستخدم",
        "tip":      "نصيحة: اضغط مطولاً على أي أمر لنسخه ولصقه في المجموعة.",
        "sections": [
            ("⭐ نجوم RAWWY", [
                ("/thanks",   "رُد على أي رسالة بـ /thanks لمنح صاحبها نجمة RAWWY."),
                ("/mystar",   "اعرض نجومك الشهرية والكلية."),
                ("/myquota",  "تحقق من عدد النجوم المتبقية لديك هذا الأسبوع."),
            ]),
            ("🎮 التريفيا ونقاط المعرفة", [
                ("/mypoint",  "اعرض مجموع نقاط المعرفة الخاصة بك."),
            ]),
            ("📅 الفعاليات والاستطلاعات", [
                ("/events",   "افتح قائمة الفعاليات في الرسائل الخاصة. أنشئ فعاليات واستطلاعات وعدّلها أو ألغِها بالقائمة المضمّنة."),
            ]),
            ("📚 المكتبة", [
                ("/library",  "افتح قائمة المكتبة في الرسائل الخاصة. تصفّح وأضف وعدّل وحذف الأصول."),
            ]),
            ("📋 المهام", [
                ("/task",     "أسند مهمة. في المجموعة: انقر على الأعضاء لاختيارهم، اكتب الوصف ثم اضغط إنهاء.\nفي الرسائل الخاصة: خطوة بخطوة."),
                ("/mytask",   "اعرض مهامك المعلّقة في الرسائل الخاصة. انقر للإكمال ثم اضغط إنهاء."),
            ]),
            ("🏖️ حالة الغياب", [
                ("/away",     "افتح قائمة الغياب في الرسائل الخاصة. حدّد سبب الغياب ووقت العودة."),
                ("/back",     "اكتب /back في أي محادثة للإشارة إلى عودتك واستقبال الإشعارات الفائتة."),
            ]),
            ("🤖 المساعد الذكي", [
                ("/ai",       "اسأل المساعد الذكي أي سؤال.\nالصيغة: /ai ما هو مؤشر الأداء الرئيسي؟"),
                ("/wdim",     "احصل على ملخص ذكي لما جرى في المجموعة أثناء غيابك."),
            ]),
            ("ℹ️ عام", [
                ("/start",    "سجّل في البوت وافتح قائمة الترحيب."),
                ("/help",     "اعرض قائمة كاملة بجميع الأوامر."),
                ("/command",  "افتح قائمة تفاعلية للتصفّح بين الأوامر."),
                ("/feedback", "أرسل اقتراحاً أو بلاغاً إلى فريق الإدارة."),
                ("/manual",   "استلم هذا الدليل (مرة واحدة شهرياً)."),
            ]),
        ]
    },
    "id": {
        "title":    "Panduan Pengguna Nukhba Manager Bot",
        "version":  "v1.2",
        "subtitle": "Panduan lengkap semua perintah pengguna",
        "tip":      "Tips: Tekan lama format perintah untuk menyalinnya, lalu tempel di grup.",
        "sections": [
            ("⭐ RAWWY Stars", [
                ("/thanks",   "Balas pesan siapa pun dengan /thanks untuk memberinya RAWWY Star."),
                ("/mystar",   "Lihat RAWWY Star bulanan dan sepanjang waktu yang kamu terima."),
                ("/myquota",  "Cek sisa jatah Star yang bisa kamu beri minggu ini."),
            ]),
            ("🎮 Trivia & Knowledge Points", [
                ("/mypoint",  "Lihat total Knowledge Point (KP) kamu saat ini."),
            ]),
            ("📅 Acara & Polling", [
                ("/events",   "Buka hub Acara & Polling di DM. Buat acara, polling, edit, atau batalkan — semua lewat menu inline."),
            ]),
            ("📚 Perpustakaan", [
                ("/library",  "Buka hub Perpustakaan di DM. Jelajahi, tambah, edit, dan hapus aset tim."),
            ]),
            ("📋 Tugas", [
                ("/task",     "Tugaskan pekerjaan.\n"
                              "• Di grup: ketuk anggota untuk memilih, ketik deskripsi, tekan Selesai.\n"
                              "• Di DM: langkah demi langkah — pilih grup → deskripsi → penerima → tenggat."),
                ("/mytask",   "Lihat tugas yang belum selesai di DM. Ketuk tugas untuk menandai selesai, lalu tekan Selesai."),
            ]),
            ("🏖️ Status Away", [
                ("/away",     "Buka hub Away di DM. Atur alasan dan waktu kembali lewat menu inline."),
                ("/back",     "Ketik /back di chat mana pun untuk menandai dirimu kembali dan menerima mention yang terlewat."),
            ]),
            ("🤖 Asisten AI", [
                ("/ai",       "Tanya asisten AI (Groq/Llama) apa pun.\nFormat: /ai Apa itu KPI?"),
                ("/wdim",     "Dapatkan rangkuman AI tentang apa yang terjadi di grup saat kamu away."),
            ]),
            ("ℹ️ Umum", [
                ("/start",    "Daftarkan diri ke bot dan buka menu selamat datang."),
                ("/help",     "Tampilkan daftar lengkap perintah berdasarkan kategori."),
                ("/command",  "Buka menu interaktif untuk menjelajahi perintah beserta panduan lengkapnya."),
                ("/feedback", "Kirim saran atau laporan ke tim admin."),
                ("/manual",   "Terima panduan ini (sekali per bulan)."),
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
    story.append(Paragraph("User Manual · v1.2", s_version))
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

    # ── Monthly gate ──────────────────────────────────────────────────────────
    today       = datetime.date.today()
    first_of_m  = today.replace(day=1)

    async with pool.acquire() as conn:
        last = await conn.fetchval("SELECT last_sent FROM manual_requests WHERE user_id=$1", uid)

    if last and last >= first_of_m:
        next_m = (first_of_m + datetime.timedelta(days=32)).replace(day=1)
        try:
            await context.bot.send_message(
                uid,
                f"📖 You already received the manual this month!\n\n"
                f"Check your chat history with me — scroll up to find the PDF.\n"
                f"You can request again from *{next_m.strftime('%B %d, %Y')}*.",
                parse_mode="Markdown"
            )
        except Exception:
            if update.message:
                await update.message.reply_text(
                    "📖 You already received the manual this month! "
                    "Check your chat history with this bot."
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
                f"Version 1.2 · {datetime.datetime.now(WIB).strftime('%B %Y')}\n\n"
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
