"""Small reusable PDF helpers for Nexora read-only exports."""

import re
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def slugify_filename_part(value, fallback="export"):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _paragraph(value, style):
    text = "—" if value is None or value == "" else str(value)
    return Paragraph(escape(text), style)


def build_report_pdf(title, subtitle="", sections=None, footer_note="", landscape_mode=False):
    """Return a compact branded PDF assembled from key/value and table sections."""
    buffer = BytesIO()
    page_size = landscape(letter) if landscape_mode else letter
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=str(title or "Nexora Report"),
        author="Nexora",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "NexoraTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "NexoraSubtitle",
        parent=styles["BodyText"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "NexoraHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#1d4ed8"),
        spaceBefore=7,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "NexoraBody",
        parent=styles["BodyText"],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    label_style = ParagraphStyle(
        "NexoraLabel",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#475569"),
    )
    footer_style = ParagraphStyle(
        "NexoraFooter",
        parent=body_style,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748b"),
        spaceBefore=10,
    )

    story = [Paragraph(escape(str(title or "Nexora Report")), title_style)]
    if subtitle:
        story.append(Paragraph(escape(str(subtitle)), subtitle_style))

    for section in sections or []:
        heading = section.get("heading") or ""
        if heading:
            story.append(Paragraph(escape(str(heading)), heading_style))

        rows = section.get("rows") or []
        if rows:
            data = [[_paragraph(label, label_style), _paragraph(value, body_style)] for label, value in rows]
            table = Table(data, colWidths=[1.65 * inch, None], hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.extend([table, Spacer(1, 7)])

        headers = section.get("headers") or []
        table_rows = section.get("table") or []
        if headers and table_rows:
            table_data = [[_paragraph(item, label_style) for item in headers]]
            for row in table_rows:
                table_data.append([_paragraph(item, body_style) for item in row])
            table = Table(table_data, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.extend([table, Spacer(1, 7)])

        note = section.get("note") or ""
        if note:
            story.append(Paragraph(escape(str(note)), body_style))
            story.append(Spacer(1, 7))

    if footer_note:
        story.append(Paragraph(escape(str(footer_note)), footer_style))

    doc.build(story)
    return buffer.getvalue()
