"""Render docs/MANUAL.md to a PDF using reportlab (no external tools needed)."""
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SRC = Path(__file__).resolve().parent / "MANUAL.md"
OUT = Path(__file__).resolve().parent / "ProofOS-Manual.pdf"

styles = getSampleStyleSheet()
title_s = ParagraphStyle("TitleS", parent=styles["Title"], fontSize=26, spaceAfter=6, textColor=colors.HexColor("#0f172a"))
subtitle_s = ParagraphStyle("SubS", parent=styles["Normal"], fontSize=12, textColor=colors.HexColor("#475569"), alignment=TA_CENTER, spaceAfter=18)
h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#065f46"))
h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#0f766e"))
body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9.5, leading=14, spaceAfter=5)
bullet = ParagraphStyle("Bullet", parent=body, leftIndent=14, bulletIndent=4, spaceAfter=2)
code = ParagraphStyle("Code", parent=styles["Code"], fontSize=8, leading=10.5, backColor=colors.HexColor("#f1f5f9"), borderPadding=5, spaceAfter=6)

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def inline(text: str) -> str:
    text = BOLD_RE.sub(r"<b>\1</b>", text)
    text = INLINE_CODE_RE.sub(r'<font face="Courier">\1</font>', text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    story = [Paragraph("ProofOS", title_s), Paragraph("Production Operations Manual — iTechSmart ProofOS", subtitle_s), Spacer(1, 6)]

    i = 0
    in_code = False
    code_buf: list[str] = []
    table_buf: list[list[str]] = []

    def flush_table():
        nonlocal table_buf
        if not table_buf:
            return
        t = Table(table_buf, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t)
        story.append(Spacer(1, 6))
        table_buf = []

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if s.startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code_buf), code))
                code_buf = []
                in_code = False
            else:
                flush_table()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if s.startswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table_buf.append([Paragraph(inline(c), ParagraphStyle("cell", parent=body, fontSize=8, leading=11)) for c in cells])
            i += 1
            continue
        else:
            flush_table()

        if not s:
            i += 1
            continue
        if s == "---":
            i += 1
            continue
        if s.startswith("### "):
            story.append(Paragraph(inline(s[4:]), h2))
        elif s.startswith("## "):
            story.append(Paragraph(inline(s[3:]), h1))
        elif s.startswith("# "):
            story.append(PageBreak())
            story.append(Paragraph(inline(s[2:]), h1))
        elif re.match(r"^\d+\.\s", s):
            story.append(Paragraph(inline(re.sub(r"^\d+\.\s", "• ", s)), bullet))
        elif s.startswith("- "):
            story.append(Paragraph(inline("• " + s[2:]), bullet))
        elif s.startswith("> "):
            story.append(Paragraph(inline(s[2:]), ParagraphStyle("note", parent=body, textColor=colors.HexColor("#334155"), leftIndent=10, borderPadding=4, backColor=colors.HexColor("#ecfdf5"))))
        else:
            story.append(Paragraph(inline(s), body))
        i += 1

    flush_table()

    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title="ProofOS Operations Manual")
    doc.build(story)
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
