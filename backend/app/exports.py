"""Turning logged conversations into files: CSV (for spreadsheets) and PDF (for
reading, printing and filing).

Plain functions over plain dictionaries: no database or web imports, so they can
be tested on their own (tests/test_exports.py). transcripts.conversation_record()
builds the dictionaries; the routers send the bytes.

A conversation record looks like:

{"id": 12, "scenario": "IRB review", "student": "Maya Chen", "email": "maya@…",
 "course": "PSYC 310", "attempt": 1, "status": "completed", "paused": False,
 "outcome": "Approved", "outcome_type": "success", "messages_used": 6,
 "started_at": "2026-01-05T15:00:00+00:00", "completed_at": "...", "flags": 0,
 "feedback": "…",
 "lines": [{"at": "2026-01-05T15:01:00+00:00", "scene": "The deception question",
            "kind": "student|character|path|judge_note|feedback|notice",
            "speaker": "Maya Chen", "text": "…", "hidden": False}]}
"""
import csv
import io
import re
from datetime import datetime, timezone

MAX_PDF_CONVERSATIONS = 200
MAX_CSV_CONVERSATIONS = 2000

KIND_LABEL = {"student": "Student", "character": "Character", "path": "Path taken",
              "judge_note": "Why the scene moved on", "feedback": "Instructor's note", "notice": "System notice"}
STATUS_LABEL = {"in_progress": "In progress", "completed": "Completed", "abandoned": "Restarted"}
OUTCOME_LABEL = {"success": "Success", "partial": "Partial", "fail": "Didn't succeed"}


class ExportUnavailable(Exception):
    """The export can't be produced on this server (e.g. the PDF library is missing)."""


def safe_filename(name: str, ext: str) -> str:
    """An ASCII file name that is safe in a Content-Disposition header."""
    base = re.sub(r"[^A-Za-z0-9]+", "-", str(name or "")).strip("-")[:60] or "export"
    return f"{base}.{ext.lstrip('.')}"


def _cell(value) -> str:
    """Spreadsheet-safe text. Excel and Sheets run a cell that starts with = + - or @
    as a formula; student-typed text must never be executable, so those get a leading
    apostrophe (shown as plain text)."""
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if text[:1] in ("=", "+", "-", "@", "\t"):
        text = "'" + text
    return text


def csv_bytes(header: list[str], rows) -> bytes:
    """UTF-8 CSV with a byte-order mark so Excel opens accented names correctly."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    for row in rows:
        w.writerow([_cell(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")


CONVERSATION_COLUMNS = ["conversation_id", "scenario", "student", "email", "course", "attempt", "status",
                        "outcome", "outcome_type", "time_utc", "scene", "line_type", "speaker", "text",
                        "hidden_by_admin"]


def conversations_csv(records: list[dict]) -> bytes:
    """One row per line of every conversation, so it can be filtered and pivoted."""
    def rows():
        for r in records:
            lines = r.get("lines") or [{}]            # a conversation with no lines still gets a row
            for ln in lines:
                yield [r.get("id"), r.get("scenario"), r.get("student"), r.get("email"), r.get("course"),
                       r.get("attempt"), STATUS_LABEL.get(r.get("status"), r.get("status")),
                       r.get("outcome") or "", OUTCOME_LABEL.get(r.get("outcome_type"), ""),
                       ln.get("at") or "", ln.get("scene") or "", KIND_LABEL.get(ln.get("kind"), ln.get("kind") or ""),
                       ln.get("speaker") or "", ln.get("text") or "", "yes" if ln.get("hidden") else ""]
    return csv_bytes(CONVERSATION_COLUMNS, rows())


SUMMARY_COLUMNS = ["student", "email", "course", "attempt", "status", "outcome", "outcome_type", "messages",
                   "paths_taken", "started_utc", "completed_utc"]


def results_csv(rows: list[list]) -> bytes:
    """The per-attempt results table (one row per attempt)."""
    return csv_bytes(SUMMARY_COLUMNS, rows)


# ---------------------------------------------------------------------- PDF --
def _when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError):
        return str(iso)


def _clock(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M") if iso else ""
    except (TypeError, ValueError):
        return ""


def _fonts():
    """Register the Unicode fonts bundled with reportlab (Bitstream Vera). Falls back
    to the built-in Helvetica if they can't be loaded. Returns (regular, bold, italic,
    can_draw) where can_draw(ch) says whether the font has that character."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        if "AICSS" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("AICSS", "Vera.ttf"))
            pdfmetrics.registerFont(TTFont("AICSS-Bold", "VeraBd.ttf"))
            pdfmetrics.registerFont(TTFont("AICSS-Italic", "VeraIt.ttf"))
            pdfmetrics.registerFontFamily("AICSS", normal="AICSS", bold="AICSS-Bold", italic="AICSS-Italic",
                                          boldItalic="AICSS-Bold")
        cmap = pdfmetrics.getFont("AICSS").face.charToGlyph
        return "AICSS", "AICSS-Bold", "AICSS-Italic", lambda ch: ord(ch) in cmap
    except Exception:                       # font files missing from this reportlab build
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", lambda ch: ord(ch) < 256


_PUNCT = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
          "…": "...", " ": " ", "→": "->", "•": "*"}


def _para(text, can_draw) -> str:
    """Text made safe for a reportlab Paragraph: characters the font can't draw are
    replaced (never dropped silently as black boxes), markup characters escaped, and
    line breaks kept."""
    out = []
    for ch in "" if text is None else str(text):
        if ch == "\n":
            out.append("\n")
        elif ch == "\t":
            out.append("    ")
        elif ord(ch) < 32:
            continue
        elif can_draw(ch):
            out.append(ch)
        else:
            out.append(_PUNCT.get(ch, "?"))
    s = "".join(out).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace("\n", "<br/>")


def conversations_pdf(records: list[dict], title: str = "Conversation export", generated_by: str = "",
                      generated_at: str | None = None) -> bytes:
    """A readable transcript of one or more conversations, one per section."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                        TableStyle)
    except ImportError as e:
        raise ExportUnavailable("PDF export needs the “reportlab” package. Run "
                                "pip install -r requirements.txt on the server, or export CSV instead.") from e

    regular, bold, italic, can_draw = _fonts()
    P = lambda text: _para(text, can_draw)          # noqa: E731
    green, brass, ink, muted, rule = (colors.HexColor(c) for c in
                                      ("#1e3a31", "#7f6127", "#1c2522", "#5a6560", "#d3d8d0"))
    tint = colors.HexColor("#eef3ef")

    def style(name, **kw):
        base = dict(fontName=regular, fontSize=10, leading=14, textColor=ink, alignment=TA_LEFT)
        base.update(kw)
        return ParagraphStyle(name, **base)

    s_title = style("title", fontName=bold, fontSize=18, leading=22, textColor=green, spaceAfter=2)
    s_sub = style("sub", fontSize=9, leading=12, textColor=muted, spaceAfter=10)
    s_h = style("h", fontName=bold, fontSize=13, leading=17, textColor=green, spaceBefore=4, spaceAfter=4)
    s_meta = style("meta", fontSize=9, leading=12.5)
    s_scene = style("scene", fontName=bold, fontSize=10.5, leading=14, textColor=brass, spaceBefore=10, spaceAfter=3)
    s_who = style("who", fontName=bold, fontSize=9, leading=13, textColor=muted)
    s_who_you = style("whoyou", fontName=bold, fontSize=9, leading=13, textColor=green)
    s_said = style("said", fontSize=10, leading=14)
    s_note = style("note", fontName=italic, fontSize=9, leading=12.5, textColor=muted)
    s_path = style("path", fontName=bold, fontSize=9.5, leading=13, textColor=green)

    generated_at = generated_at or datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    # Plain text for the page footer (drawn directly, so no markup escaping).
    footer_text = "".join(ch if can_draw(ch) else _PUNCT.get(ch, "?")
                          for ch in f"Confidential student record  |  {title}  |  Generated {generated_at}")

    def footer(canvas, doc):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(muted)
        page = f"Page {doc.page}"
        room = doc.width - stringWidth(page, regular, 7.5) - 18      # never run into the page number
        text = footer_text
        while text and stringWidth(text, regular, 7.5) > room:
            text = text[:-4].rstrip() + "..." if len(text) > 4 else ""
        canvas.drawString(doc.leftMargin, 0.5 * inch, text)
        canvas.drawRightString(LETTER[0] - doc.rightMargin, 0.5 * inch, page)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.85 * inch, rightMargin=0.85 * inch,
                            topMargin=0.8 * inch, bottomMargin=0.85 * inch, title=str(title)[:120],
                            author="Classroom Scenarios")
    width = doc.width
    story = [Paragraph(P(title), s_title),
             Paragraph(P(f"{len(records)} conversation{'' if len(records) == 1 else 's'}. Generated {generated_at}"
                         + (f" by {generated_by}" if generated_by else "") + "."), s_sub)]
    if not records:
        story.append(Paragraph("No conversations match this export.", s_said))

    for i, r in enumerate(records):
        if i:
            story.append(PageBreak())
        story.append(Paragraph(P(r.get("scenario") or "Scenario"), s_h))
        outcome = r.get("outcome")
        if outcome and r.get("outcome_type"):
            outcome = f"{outcome} ({OUTCOME_LABEL.get(r['outcome_type'], r['outcome_type'])})"
        status = STATUS_LABEL.get(r.get("status"), r.get("status") or "")
        if r.get("paused"):
            status += ", paused for review"
        facts = [("Student", f"{r.get('student') or 'Unknown'}" + (f" ({r['email']})" if r.get("email") else "")),
                 ("Course", r.get("course") or "-"),
                 ("Attempt", f"{r.get('attempt') or 1}, {r.get('messages_used') or 0} student message(s)"),
                 ("Status", status),
                 ("Outcome", outcome or "Not finished"),
                 ("Started", _when(r.get("started_at")) or "-"),
                 ("Finished", _when(r.get("completed_at")) or "-"),
                 ("Safety flags", str(r.get("flags") or 0))]
        t = Table([[Paragraph(P(k), s_who), Paragraph(P(v), s_meta)] for k, v in facts],
                  colWidths=[1.1 * inch, width - 1.1 * inch])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("LINEBELOW", (0, -1), (-1, -1), 0.75, rule)]))
        story += [t, Spacer(1, 6)]

        scene = None
        for ln in r.get("lines") or []:
            if ln.get("scene") and ln["scene"] != scene and ln.get("kind") in ("student", "character"):
                scene = ln["scene"]
                story.append(Paragraph(P(f"Scene: {scene}"), s_scene))
            kind, text = ln.get("kind"), ln.get("text") or ""
            if ln.get("hidden"):
                text = f"[Hidden from the student by an administrator] {text}"
            if kind in ("student", "character") and len(text) > 2500:
                # Too long to keep in one table row (a row can't break across pages).
                story.append(Paragraph(f"<b>{P(ln.get('speaker') or 'Speaker')}</b>: {P(text)}", s_said))
            elif kind in ("student", "character"):
                you = kind == "student"
                who = Paragraph(P(ln.get("speaker") or ("Student" if you else "Character"))
                                + f'<br/><font size="7.5" color="#5a6560">{_clock(ln.get("at"))}</font>',
                                s_who_you if you else s_who)
                row = Table([[who, Paragraph(P(text), s_said)]], colWidths=[1.35 * inch, width - 1.35 * inch])
                row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                                         ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                         ("BACKGROUND", (0, 0), (-1, -1), tint if you else colors.white),
                                         ("LINEBELOW", (0, 0), (-1, -1), 0.4, rule)]))
                row.splitByRow = 1
                story.append(row)
            elif kind == "path":
                story.append(KeepTogether([Spacer(1, 5), Paragraph("Path taken: " + P(text), s_path)]))
            else:
                label = KIND_LABEL.get(kind, "Note")
                story.append(Paragraph(f"{P(label)}: {P(text)}", s_note))
        if not r.get("lines"):
            story.append(Paragraph("No messages were sent in this conversation.", s_note))
        if r.get("feedback"):
            story += [Spacer(1, 8), Paragraph("Feedback shown to the student", s_scene),
                      Paragraph(P(r["feedback"]), s_said)]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
