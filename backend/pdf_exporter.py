"""
ADAPTFIT PDF Export Module (FR-12)
==================================
Generates publication-quality, self-contained PDF evaluation reports
for climate adaptation transferability assessments using ReportLab.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def generate_assessment_pdf(data: Dict[str, Any]) -> bytes:
    """
    Generate a complete, professionally formatted PDF report for an assessment.
    Returns the PDF as raw bytes.
    """
    buffer = io.BytesIO()

    # Setup document with 0.5-inch margins for spacious tabular layout
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    primary_color = colors.HexColor("#124e2c")
    text_dark = colors.HexColor("#0f172a")
    text_muted = colors.HexColor("#475569")

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=primary_color,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=text_muted,
    )
    section_h2 = ParagraphStyle(
        "SectionH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=primary_color,
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "BodyTextCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12.5,
        textColor=text_dark,
    )
    bold_style = ParagraphStyle(
        "BodyBoldCustom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12.5,
        textColor=text_dark,
    )
    mono_style = ParagraphStyle(
        "MonoStyle",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8.5,
        leading=11,
        textColor=text_dark,
    )
    th_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1e293b"),
    )
    disclaimer_style = ParagraphStyle(
        "Disclaimer",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#334155"),
    )

    story = []

    # 1. Header Banner
    header_data = [
        [
            Paragraph("<b>ADAPTFIT</b> – Climate Adaptation Decision Support", title_style),
            Paragraph(f"<b>Assessment #{data.get('assessment_id', 'N/A')}</b>", ParagraphStyle("RightH", parent=title_style, alignment=2, fontSize=12, textColor=text_muted)),
        ],
        [
            Paragraph("Explainable Transferability Feasibility Screening &bull; Prototype", subtitle_style),
            Paragraph(f"Adaptation: <b>{data.get('adaptation_name', 'Rain Garden')}</b>", ParagraphStyle("RightSub", parent=subtitle_style, alignment=2)),
        ],
    ]
    header_table = Table(header_data, colWidths=[360, 160])
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(header_table)
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceBefore=0, spaceAfter=8))

    # 2. Executive Status Box
    status = data.get("status", "insufficient_data")
    score = data.get("score")
    score_display = f"{int(round(score * 100))}% ({score:.2f})" if score is not None else "N/A"

    status_theme = {
        "suitable": {
            "title": "SUITABLE FOR TRANSFER",
            "bg": colors.HexColor("#d1fae5"),
            "border": colors.HexColor("#10b981"),
            "text": colors.HexColor("#064e3b"),
            "desc": "All documented environmental criteria appear met at the target site with no fatal blockers identified.",
        },
        "conditional": {
            "title": "CONDITIONAL TRANSFER",
            "bg": colors.HexColor("#fef3c7"),
            "border": colors.HexColor("#f59e0b"),
            "text": colors.HexColor("#78350f"),
            "desc": "Transfer requires engineering modifications or field verification of highlighted factors / transfer risks.",
        },
        "unsuitable": {
            "title": "UNSUITABLE",
            "bg": colors.HexColor("#fee2e2"),
            "border": colors.HexColor("#ef4444"),
            "text": colors.HexColor("#7f1d1d"),
            "desc": "One or more critical documented requirements are not met at the candidate target site.",
        },
        "insufficient_data": {
            "title": "INSUFFICIENT DATA",
            "bg": colors.HexColor("#f1f5f9"),
            "border": colors.HexColor("#94a3b8"),
            "text": colors.HexColor("#1e293b"),
            "desc": "Missing critical measurements or missing factor weight exceeds threshold. Feasibility unconfirmed.",
        },
    }.get(
        status,
        {
            "title": status.upper(),
            "bg": colors.HexColor("#f1f5f9"),
            "border": colors.HexColor("#94a3b8"),
            "text": colors.HexColor("#1e293b"),
            "desc": "Assessment status evaluated.",
        },
    )

    box_style = ParagraphStyle(
        "StatusBoxTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=status_theme["text"],
    )
    box_desc = ParagraphStyle(
        "StatusBoxDesc",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=status_theme["text"],
    )

    status_row = [
        [
            Paragraph(f"<b>STATUS: {status_theme['title']}</b>", box_style),
            Paragraph(f"<b>Viability Score: {score_display}</b>", ParagraphStyle("ScoreP", parent=box_style, alignment=2)),
        ],
        [
            Paragraph(status_theme["desc"], box_desc),
            Paragraph(f"Provenance: {data.get('data_badge_label', 'Demo data')}", ParagraphStyle("ProvP", parent=box_desc, alignment=2, fontSize=8)),
        ],
    ]
    status_table = Table(status_row, colWidths=[350, 170])
    status_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), status_theme["bg"]),
            ("BOX", (0, 0), (-1, -1), 1.2, status_theme["border"]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(status_table)
    story.append(Spacer(1, 8))

    # 3. Location Summary Table
    ref_loc = data.get("reference_location") or data.get("location_a") or {}
    tgt_loc = data.get("target_location") or data.get("location_b") or {}

    ref_name = ref_loc.get("name", "Location A")
    ref_lat = ref_loc.get("latitude")
    ref_lon = ref_loc.get("longitude")
    ref_coords = f"{ref_lat:.4f}, {ref_lon:.4f}" if ref_lat is not None and ref_lon is not None else "Unknown"

    tgt_name = tgt_loc.get("name", "Location B")
    tgt_lat = tgt_loc.get("latitude")
    tgt_lon = tgt_loc.get("longitude")
    tgt_coords = f"{tgt_lat:.4f}, {tgt_lon:.4f}" if tgt_lat is not None and tgt_lon is not None else "Unknown"

    loc_summary_data = [
        [
            Paragraph("<b>Reference Site (Location A)</b>", bold_style),
            Paragraph(f"{ref_name} &bull; <font face='Courier' size=8>{ref_coords}</font>", body_style),
        ],
        [
            Paragraph("<b>Target Candidate (Location B)</b>", bold_style),
            Paragraph(f"{tgt_name} &bull; <font face='Courier' size=8>{tgt_coords}</font>", body_style),
        ],
    ]
    loc_table = Table(loc_summary_data, colWidths=[160, 360])
    loc_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(loc_table)
    story.append(Spacer(1, 8))

    # 4. Environmental Factor Comparison Table
    story.append(Paragraph("<b>Factor-by-Factor Evaluation Matrix</b>", section_h2))

    factors = data.get("factors", [])
    matrix_rows = [
        [
            Paragraph("Factor", th_style),
            Paragraph("Criteria", th_style),
            Paragraph("Ref (A)", th_style),
            Paragraph("Target (B)", th_style),
            Paragraph("Status", th_style),
            Paragraph("Source / Resolution", th_style),
        ]
    ]

    for f in factors:
        factor_name = f.get("factor", "").replace("_", " ").title()
        req = f.get("requirement", "n/a")
        a_val = str(f.get("a_value")) if f.get("a_value") is not None else "Unknown"
        b_val = str(f.get("b_value")) if f.get("b_value") is not None else "Unknown"
        status_raw = f.get("factor_status", "unknown").upper()
        if f.get("transfer_risk"):
            status_raw += " (RISK)"

        b_src = f.get("b_source") or f.get("source") or "Demo"
        b_res = f.get("b_resolution") or f.get("resolution") or "n/a"
        src_res = f"{b_src} ({b_res})"

        matrix_rows.append([
            Paragraph(factor_name, bold_style),
            Paragraph(req, body_style),
            Paragraph(a_val, mono_style),
            Paragraph(b_val, mono_style),
            Paragraph(status_raw, bold_style),
            Paragraph(src_res, ParagraphStyle("SrcP", parent=body_style, fontSize=7.5, leading=10)),
        ])

    factor_table = Table(matrix_rows, colWidths=[90, 105, 55, 55, 75, 140])
    factor_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#94a3b8")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    story.append(factor_table)
    story.append(Spacer(1, 8))

    # 5. Decision Factors (Limiting, Supporting, Suggested Checks)
    limiting = data.get("limiting_factors", [])
    supporting = data.get("supporting_factors", [])
    suggested = data.get("suggested_checks", [])

    analysis_rows = []
    if limiting:
        analysis_rows.append([Paragraph(f"<b>Limiting Factors &amp; Transfer Risks:</b> {', '.join(limiting)}", body_style)])
    else:
        analysis_rows.append([Paragraph("<b>Limiting Factors:</b> None identified &bull; All criteria satisfied.", body_style)])

    if supporting:
        analysis_rows.append([Paragraph(f"<b>Supporting Factors:</b> {', '.join(supporting)}", body_style)])

    if suggested:
        analysis_rows.append([Paragraph(f"<b>Suggested Field Checks:</b> {'; '.join(suggested)}", body_style)])

    warnings = data.get("data_quality_warnings", [])
    if warnings:
        warn_text = "<br/>&bull; ".join(warnings)
        analysis_rows.append([Paragraph(f"<b>Data Quality Warnings:</b><br/>&bull; {warn_text}", ParagraphStyle("WarnP", parent=body_style, textColor=colors.HexColor("#b45309")))])

    analysis_box = Table(analysis_rows, colWidths=[520])
    analysis_box.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(analysis_box)
    story.append(Spacer(1, 8))

    # 6. Official PRD §13 Disclaimer Box
    disclaimer_text = data.get(
        "disclaimer",
        "ADAPTFIT is a preliminary, explainable decision-support prototype. "
        "It compares documented adaptation requirements with available environmental "
        "data for reference and target locations. Results depend on data coverage, "
        "spatial resolution and the quality of the requirements; they are not a "
        "guarantee of implementation success.",
    )
    disclaimer_table = Table(
        [
            [
                Paragraph(
                    f"<b>Official Decision-Support Notice (PRD §13):</b><br/>{disclaimer_text}",
                    disclaimer_style,
                )
            ]
        ],
        colWidths=[520],
    )
    disclaimer_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(disclaimer_table)

    # Build PDF
    doc.build(story)
    return buffer.getvalue()
