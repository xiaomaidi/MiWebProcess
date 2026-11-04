"""Server-side PDF export for data records (ReportLab, optional dependency)."""
from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.renderers import BaseRenderer

from .import_export import _content_disposition, cell_text, export_headers


def reportlab_available() -> bool:
    try:
        import reportlab  # noqa: PLC0415
    except Exception:  # pragma: no cover - optional dependency
        return False
    return True


def pdf_response(
    model,
    specs: list[dict],
    rows: list[list[Any]],
    *,
    filename: str,
    fallback: str,
    landscape_mode: bool = True,
) -> HttpResponse:
    """Build a paginated PDF table using a CJK CID font.

    Cells are converted with the same rules as CSV/XLSX and clipped to keep the
    table readable. ReportLab is optional; callers should check availability.
    """
    try:
        from reportlab.lib import colors  # noqa: PLC0415
        from reportlab.lib.pagesizes import A4, landscape  # noqa: PLC0415
        from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
        from reportlab.lib.units import mm  # noqa: PLC0415
        from reportlab.pdfbase import pdfmetrics  # noqa: PLC0415
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # noqa: PLC0415
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("服务端未安装 reportlab，暂不支持 PDF 导出") from exc

    font_name = "STSong-Light"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except Exception:
        font_name = "Helvetica"

    headers = export_headers(specs)
    page_size = landscape(A4) if landscape_mode else A4
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = _content_disposition(filename, fallback)
    response["X-Content-Type-Options"] = "nosniff"

    doc = SimpleDocTemplate(
        response,
        pagesize=page_size,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=str(getattr(model, "name", "records")),
    )
    title_style = ParagraphStyle(
        "wp-title", fontName=font_name, fontSize=15, leading=19, spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "wp-meta", fontName=font_name, fontSize=8, leading=11, textColor=colors.HexColor("#6b7280"),
    )
    cell_style = ParagraphStyle(
        "wp-cell", fontName=font_name, fontSize=7.2, leading=9.4, wordWrap="CJK",
    )
    head_style = ParagraphStyle(
        "wp-head", fontName=font_name, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#1f2329"),
    )

    def para(value: Any, style) -> Paragraph:
        text = cell_text(value)
        if len(text) > 320:
            text = text[:317] + "..."
        safe = (
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        return Paragraph(safe or "—", style)

    story = [Paragraph(str(getattr(model, "name", "记录")), title_style)]
    story.append(Paragraph(
        f"导出时间：{timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')} · 共 {len(rows)} 条记录",
        meta_style,
    ))
    story.append(Spacer(1, 6))

    if not headers:
        story.append(Paragraph("模型没有可展示的字段", meta_style))
    else:
        data = [[para(header, head_style) for header in headers]]
        for values in rows:
            data.append([para(value, cell_style) for value in values])
        available = page_size[0] - 20 * mm
        column_width = max(18 * mm, available / max(1, len(headers)))
        table = Table(data, colWidths=[column_width] * len(headers), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f2329")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9dde3")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfc")]),
        ]))
        story.append(table)
    doc.build(story)
    return response


class RecordPdfRenderer(BaseRenderer):
    """Allow DRF content negotiation for ``?format=pdf``."""

    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data
