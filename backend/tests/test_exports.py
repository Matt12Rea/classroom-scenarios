"""Tests for the CSV and PDF exports. No database or web server needed.

    pytest -q tests/test_exports.py      (needs pytest and reportlab)
"""
import csv
import io

import pytest

from app import exports


def record(**over):
    r = {"id": 7, "scenario": "IRB review: the “Cyberball” study", "student": "Zoë Martin", "email": "zoe@demo.school",
         "course": "PSYC 310", "attempt": 2, "status": "completed", "paused": False, "outcome": "Approved",
         "outcome_type": "success", "messages_used": 2, "started_at": "2026-01-05T15:00:00+00:00",
         "completed_at": "2026-01-05T15:09:00+00:00", "flags": 1, "feedback": "Clear & specific <well done>.",
         "lines": [
             {"at": "2026-01-05T15:01:00+00:00", "scene": "The deception question", "kind": "student",
              "speaker": "Zoë Martin", "text": "Everyone gets a full debriefing.\nBefore they leave.", "hidden": False},
             {"at": "2026-01-05T15:01:04+00:00", "scene": "The deception question", "kind": "character",
              "speaker": "Dr. Miriam Adler", "text": "And if someone is upset?", "hidden": True},
             {"at": "2026-01-05T15:02:00+00:00", "scene": "The deception question", "kind": "path", "speaker": "",
              "text": "Justified the deception", "hidden": False},
             {"at": "2026-01-05T15:02:00+00:00", "scene": "The deception question", "kind": "judge_note",
              "speaker": "", "text": "The student described a debriefing.", "hidden": False}]}
    r.update(over)
    return r


def rows(data: bytes):
    assert data.startswith(b"\xef\xbb\xbf")                     # byte-order mark so Excel reads UTF-8
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def test_csv_has_one_row_per_line_with_the_conversation_details():
    out = rows(exports.conversations_csv([record()]))
    assert out[0] == exports.CONVERSATION_COLUMNS and len(out) == 5
    first = dict(zip(out[0], out[1]))
    assert first["student"] == "Zoë Martin" and first["status"] == "Completed" and first["outcome_type"] == "Success"
    assert first["line_type"] == "Student" and first["text"] == "Everyone gets a full debriefing.\nBefore they leave."
    assert dict(zip(out[0], out[2]))["hidden_by_admin"] == "yes"
    assert dict(zip(out[0], out[3]))["line_type"] == "Path taken"


def test_csv_never_lets_student_text_run_as_a_formula():
    bad = record(student="=cmd|' /C calc'!A0", lines=[
        {"kind": "student", "speaker": "x", "text": t, "scene": "s", "at": None, "hidden": False}
        for t in ('=HYPERLINK("http://evil","click")', "+1+1", "-2", "@SUM(A1)", "\tx", "plain = fine")])
    out = rows(exports.conversations_csv([bad]))
    texts = [r[out[0].index("text")] for r in out[1:]]
    assert all(t.startswith("'") for t in texts[:5]) and texts[5] == "plain = fine"
    assert out[1][out[0].index("student")].startswith("'=")


def test_csv_of_an_empty_conversation_and_of_nothing():
    out = rows(exports.conversations_csv([record(lines=[])]))
    assert len(out) == 2 and out[1][0] == "7"
    assert rows(exports.conversations_csv([])) == [exports.CONVERSATION_COLUMNS]
    assert rows(exports.results_csv([["A", "a@x", "C", 1, "completed", "Done", "success", 4, "p > q", "", ""]]))[1][0] == "A"


def test_filenames_are_header_safe():
    assert exports.safe_filename('Prairie "State": bank?\r\n', "csv") == "Prairie-State-bank.csv"
    assert exports.safe_filename("", "pdf") == "export.pdf" and exports.safe_filename("日本語", ".pdf") == "export.pdf"
    assert len(exports.safe_filename("x" * 500, "csv")) <= 64


def pdf_text(data: bytes) -> str:
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_pdf_contains_the_transcript():
    pytest.importorskip("reportlab")
    data = exports.conversations_pdf([record()], title="Conversation: IRB review", generated_by="Avery Admin")
    assert data.startswith(b"%PDF-") and len(data) > 2000
    text = pdf_text(data)
    for expected in ("Zoë Martin", "PSYC 310", "Approved (Success)", "Everyone gets a full debriefing.",
                     "Dr. Miriam Adler", "Hidden from the student", "Path taken: Justified the deception",
                     "Why the scene moved on", "Clear & specific <well done>.", "Avery Admin", "Page 1"):
        assert expected in text, expected


def test_pdf_copes_with_awkward_content():
    pytest.importorskip("reportlab")
    awkward = record(student="<b>Bobby</b> & co", scenario="", outcome=None, outcome_type=None, status="in_progress",
                     paused=True, completed_at=None, started_at="not a date", feedback="", lines=[
        {"kind": "student", "speaker": "S", "text": "emoji 😀 and 你好 and <script>alert(1)</script> & more", "scene": "A",
         "at": "garbage", "hidden": False},
        {"kind": "character", "speaker": None, "text": "x" * 9000, "scene": "A", "at": None, "hidden": False},
        {"kind": "notice", "speaker": "", "text": "", "scene": "", "at": None, "hidden": False},
        {"kind": "something-new", "speaker": "", "text": "future line type", "scene": "B", "at": None, "hidden": False}])
    data = exports.conversations_pdf([awkward, record(lines=[]), record()], title="T")
    text = pdf_text(data)
    assert "<b>Bobby</b> & co" in text and "paused for review" in text and "Not finished" in text
    assert "<script>alert(1)</script>" in text and "future line type" in text
    assert "No messages were sent" in text
    assert exports.conversations_pdf([]).startswith(b"%PDF-")          # an empty export is still a valid file


def test_pdf_reports_a_missing_library_clearly(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_reportlab(name, *a, **k):
        if name.startswith("reportlab"):
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_reportlab)
    with pytest.raises(exports.ExportUnavailable, match="reportlab"):
        exports.conversations_pdf([record()])
