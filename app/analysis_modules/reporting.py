from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


TITLE = "Equipment Health Report"


def _safe(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


def build_health_report_pdf(
    tool_id: str,
    summary: dict[str, Any],
    latest_payload: dict[str, Any] | None,
    root_cause: dict[str, str] | None,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=TITLE,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading = styles["Heading2"]
    body = styles["BodyText"]
    body.leading = 15
    small = ParagraphStyle("Small", parent=body, fontSize=9.2, leading=12)

    story = []
    story.append(Paragraph(TITLE, title_style))
    story.append(Paragraph(f"Tool: <b>{_safe(tool_id)}</b>", body))
    story.append(Spacer(1, 6 * mm))

    sev = summary.get("severity_breakdown", {})
    event_counts = summary.get("event_counts", {})
    top_issue = summary.get("dominant_fault_type") or "-"

    overview = [
        ["Metric", "Value"],
        ["Health score", _safe(summary.get("health_score"))],
        ["Average confidence", _safe(summary.get("avg_confidence"))],
        ["Fault rate", _safe(summary.get("fault_rate"))],
        ["Total events", _safe(summary.get("total_events"))],
        ["Dominant fault type", _safe(top_issue)],
        ["Critical count", _safe(sev.get("critical", 0))],
        ["Warning count", _safe(sev.get("warning", 0))],
        ["Info count", _safe(sev.get("info", 0))],
    ]

    overview_table = Table(overview, colWidths=[58 * mm, 95 * mm])
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d2dc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#eef3f8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(Paragraph("1. Health overview", heading))
    story.append(overview_table)
    story.append(Spacer(1, 5 * mm))

    if event_counts:
        issues_data = [["Fault type", "Count"]] + [[k, str(v)] for k, v in sorted(event_counts.items(), key=lambda x: x[1], reverse=True)]
        issues_table = Table(issues_data, colWidths=[100 * mm, 30 * mm])
        issues_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f6b3f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d2dc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(Paragraph("2. Issues detected", heading))
        story.append(issues_table)
        story.append(Spacer(1, 5 * mm))

    if latest_payload:
        payload_rows = [["Field", "Value"]] + [[str(k), _safe(v)] for k, v in latest_payload.items()]
        payload_table = Table(payload_rows, colWidths=[55 * mm, 98 * mm])
        payload_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7a4a00")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7d7d7")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(Paragraph("3. Latest normalized payload", heading))
        story.append(payload_table)
        story.append(Spacer(1, 5 * mm))

    if root_cause:
        story.append(Paragraph("4. Suggested root cause and fixes", heading))
        story.append(Paragraph(f"<b>Most likely cause:</b> {_safe(root_cause.get('most_likely_cause'))}", body))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(f"<b>Suggested action:</b> {_safe(root_cause.get('suggested_action'))}", body))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("This recommendation is intended as an engineering triage aid and should be validated against maintenance procedures and recent tool history.", small))

    doc.build(story)
    return buffer.getvalue()
