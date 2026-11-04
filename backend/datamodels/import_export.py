"""记录导入解析 / 导出渲染工具。

本模块只负责「文件 ↔ 行数据 ↔ 响应」的转换，不处理权限与数据库写入：
- 导入：CSV（UTF-8/GBK，带 BOM 亦可）与 XLSX（openpyxl 可选）；
- 导出：CSV（UTF-8 BOM）、XLSX（openpyxl 可选）、打印友好 HTML。

`format` 是 DRF 的保留查询参数（内容协商），因此导出视图通过自定义
renderer 声明 ``format``，避免 ``?format=xlsx`` 被 DRF 当作未知渲染器 404。
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, time
from typing import Any

from django.http import HttpResponse
from django.utils.html import escape
from rest_framework.renderers import BaseRenderer

from .services import visible_data

MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_IMPORT_ROWS = 5000
SUPPORTED_IMPORT_EXTENSIONS = (".csv", ".xlsx")

# 导入时按类型做单元格转换；这些类型统一按文本处理。
_TEXT_TYPES = {
    "string", "longtext", "richtext", "email", "phone", "url", "password",
    "image", "file", "signature", "barcode", "color", "select", "auto_number",
}
_NUMBER_TYPES = {"number", "decimal", "money", "percent", "rating"}
_ID_TYPES = {"reference", "user", "department"}
_LIST_TYPES = {"references", "multiselect", "tags", "attachments"}
_JSON_TYPES = {"json", "geolocation"}
_COMPUTED_TYPES = {"formula", "created_at", "updated_at"}


class ImportFileError(Exception):
    """文件级错误：内容可直接展示给用户（格式 / 大小 / 表头等）。"""


# ---------------------------------------------------------------- openpyxl


def openpyxl_module():
    """返回 openpyxl 模块；未安装时返回 None（不自动安装依赖）。"""
    try:
        import openpyxl  # noqa: PLC0415
    except Exception:  # pragma: no cover - 依赖缺失时降级
        return None
    return openpyxl


def xlsx_supported() -> bool:
    return openpyxl_module() is not None


# ---------------------------------------------------------------- 导入解析


def parse_import_file(uploaded, model) -> tuple[list[dict], int]:
    """解析上传文件，返回 ``(rows, blank_rows)``。

    rows: ``[{"row": 文件行号(表头为1), "values": {字段: 值}, "id": 记录id或None}]``
    blank_rows: 整行为空、被跳过的数据行数量。
    文件级问题抛 ``ImportFileError``；单元格级问题留给 validate_data 逐行报错。
    """
    if uploaded is None:
        raise ImportFileError("请上传 CSV 或 XLSX 文件")
    name = str(getattr(uploaded, "name", "") or "")
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in SUPPORTED_IMPORT_EXTENSIONS:
        raise ImportFileError("仅支持 .csv 或 .xlsx 文件")

    _check_file_size(uploaded)
    raw_rows = _read_csv(uploaded) if ext == ".csv" else _read_xlsx(uploaded)
    if not raw_rows:
        raise ImportFileError("文件内容为空")

    header_pos = next((i for i, row in enumerate(raw_rows) if not _is_blank_row(row)), None)
    if header_pos is None:
        raise ImportFileError("文件内容为空")
    header = raw_rows[header_pos]
    mapping = resolve_headers(model, header)

    specs = model.field_map()
    rows: list[dict] = []
    blank_rows = 0
    # 文件行号从表头所在行 + 1 开始（表头通常是第 1 行）。
    for file_row, raw in enumerate(raw_rows[header_pos + 1:], start=header_pos + 2):
        if file_row - header_pos - 1 > MAX_IMPORT_ROWS:
            raise ImportFileError(f"单次最多导入 {MAX_IMPORT_ROWS} 行，请拆分文件后重试")
        values: dict[str, Any] = {}
        record_id = None
        for column, field_name in mapping.items():
            if column >= len(raw):
                continue
            cell = raw[column]
            if field_name == "__id__":
                record_id = _to_int(cell)
                continue
            value = coerce_cell(cell, specs.get(field_name) or {})
            if value is not None:
                values[field_name] = value
        if not values:
            blank_rows += 1
            continue
        rows.append({"row": file_row, "values": values, "id": record_id})
    if not rows and not blank_rows:
        raise ImportFileError("文件没有数据行")
    return rows, blank_rows


def resolve_headers(model, header_row) -> dict[int, str]:
    """表头 → 字段名映射；字段名与中文 label 均可，未知/重复列直接报错。"""
    specs = model.field_map()
    lookup: dict[str, str] = {}
    for name in specs:
        lookup[str(name).lower()] = name
    for name, spec in specs.items():
        label = str(spec.get("label") or "").strip()
        if label:
            lookup.setdefault(label.lower(), name)
    lookup.setdefault("id", "__id__")
    lookup.setdefault("记录id", "__id__")
    lookup.setdefault("记录 id", "__id__")

    mapping: dict[int, str] = {}
    seen: dict[str, str] = {}
    unknown: list[str] = []
    for column, raw in enumerate(header_row):
        text = _cell_text(raw).strip()
        if not text:
            continue
        field_name = lookup.get(text.lower())
        if field_name is None:
            unknown.append(text)
            continue
        if field_name in seen:
            raise ImportFileError(f"列「{text}」与「{seen[field_name]}」重复对应字段 {field_name}")
        seen[field_name] = text
        mapping[column] = field_name
    if unknown:
        sample = "、".join(unknown[:8])
        more = " 等" if len(unknown) > 8 else ""
        raise ImportFileError(f"无法识别的列：{sample}{more}。请使用模型字段名或中文标签作为表头")
    if not mapping:
        raise ImportFileError("未找到可识别的字段列，请检查表头")
    return mapping


def _read_csv(uploaded) -> list[list[Any]]:
    raw = uploaded.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ImportFileError("CSV 编码无法识别，请另存为 UTF-8 或 GBK 编码后重试") from exc
    if not text.strip():
        raise ImportFileError("文件内容为空")
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[list[Any]] = []
    for row in reader:
        rows.append(row)
        if len(rows) > MAX_IMPORT_ROWS + 2:
            raise ImportFileError(f"单次最多导入 {MAX_IMPORT_ROWS} 行，请拆分文件后重试")
    return rows


def _read_xlsx(uploaded) -> list[list[Any]]:
    openpyxl = openpyxl_module()
    if openpyxl is None:
        raise ImportFileError("服务端未安装 openpyxl，暂不支持 .xlsx 导入，请改用 CSV 文件")
    try:
        workbook = openpyxl.load_workbook(uploaded, read_only=True, data_only=True)
    except Exception as exc:
        raise ImportFileError("无法解析 Excel 文件，请确认是有效的 .xlsx（不支持旧版 .xls）") from exc
    try:
        sheet = workbook.active
        if sheet is None:
            raise ImportFileError("Excel 文件没有工作表")
        rows: list[list[Any]] = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(list(row))
            if len(rows) > MAX_IMPORT_ROWS + 2:
                raise ImportFileError(f"单次最多导入 {MAX_IMPORT_ROWS} 行，请拆分文件后重试")
        return rows
    finally:
        try:
            workbook.close()
        except Exception:  # noqa: BLE001 - 关闭失败不影响解析结果
            pass


def _check_file_size(uploaded) -> None:
    size = getattr(uploaded, "size", None)
    if size is None:
        try:
            uploaded.seek(0, io.SEEK_END)
            size = uploaded.tell()
            uploaded.seek(0)
        except Exception:  # noqa: BLE001 - 取不到大小则跳过限制
            return
    if int(size) > MAX_IMPORT_BYTES:
        raise ImportFileError(
            f"文件大小 {int(size) / 1024 / 1024:.1f}MB 超过 {MAX_IMPORT_BYTES // 1024 // 1024}MB 限制"
        )


def coerce_cell(value, spec: dict) -> Any:
    """把 CSV/XLSX 单元格转换为模型字段期望的类型。空值返回 None。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    ftype = str(spec.get("type") or "string")

    if isinstance(value, (datetime, date, time)):
        if ftype == "date":
            return value.strftime("%Y-%m-%d")
        if ftype == "time":
            return value.strftime("%H:%M:%S")
        return value.isoformat()

    if ftype in _COMPUTED_TYPES:
        return value
    if ftype in _TEXT_TYPES or ftype in ("duration",):
        return _cell_text(value)
    if ftype in _NUMBER_TYPES:
        number = _to_number(value)
        return number if number is not None else value
    if ftype == "integer":
        number = _to_number(value)
        if number is not None and float(number).is_integer():
            return int(number)
        return value
    if ftype == "boolean":
        boolean = _to_bool(value)
        return boolean if boolean is not None else value
    if ftype in ("date", "datetime"):
        return _normalize_datetime(value, date_only=ftype == "date")
    if ftype == "time":
        return _normalize_time(value)
    if ftype in _JSON_TYPES:
        return _parse_json(value)
    if ftype in _LIST_TYPES:
        return _to_list(value, integer=ftype == "references")
    if ftype in _ID_TYPES:
        return _to_int(value) if _to_int(value) is not None else value
    return value


def _is_blank_row(row) -> bool:
    return all(value is None or (isinstance(value, str) and not value.strip()) for value in (row or []))


def _cell_text(value) -> str:
    """单元格 → 文本（避免 Excel 数字 1001.0 变成 "1001.0"）。"""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value).strip()


def _to_number(value) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    text = str(value).strip()
    for token in ("，", ",", "¥", "￥", "$", "€", "%", " "):
        text = text.replace(token, "")
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if not (number == number) or number in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return int(number) if number.is_integer() else number


def _to_int(value) -> int | None:
    number = _to_number(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def _to_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _cell_text(value).lower()
    if text in ("1", "true", "yes", "y", "on", "是", "对", "启用"):
        return True
    if text in ("0", "false", "no", "n", "off", "否", "错", "停用"):
        return False
    return None


def _parse_json(value) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = _cell_text(value)
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return value


def _to_list(value, *, integer: bool = False) -> Any:
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        text = _cell_text(value)
        if not text:
            return None
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = parsed
                else:
                    items = [text]
            except (TypeError, ValueError):
                items = re.split(r"[,，;；\n]", text)
        else:
            items = re.split(r"[,，;；\n]", text)
    out = []
    for item in items:
        if isinstance(item, str) and not item.strip():
            continue
        if integer:
            number = _to_int(item)
            if number is None:
                return value
            out.append(number)
        else:
            out.append(_cell_text(item) if not isinstance(item, (int, float)) else item)
    if not out and not isinstance(value, str):
        return []
    return out or None


def _normalize_datetime(value, *, date_only: bool) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date().isoformat() if date_only else parsed.isoformat()
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date().isoformat() if date_only else parsed.isoformat()
        except ValueError:
            continue
    return value


def _normalize_time(value) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time().isoformat()
        except ValueError:
            continue
    return value


# ---------------------------------------------------------------- 导出


def export_field_specs(model, role: str | None, *, admin: bool = False) -> list[dict]:
    """按字段 read_roles 过滤可导出字段；admin 不受限制（与列表读取一致）。"""
    specs: list[dict] = []
    for spec in model.fields or []:
        if not isinstance(spec, dict) or not spec.get("name"):
            continue
        read_roles = spec.get("read_roles")
        if not admin and isinstance(read_roles, list) and read_roles and role not in read_roles:
            continue
        specs.append(spec)
    return specs


def export_headers(specs: list[dict]) -> list[str]:
    return [str(spec.get("label") or spec.get("name")) for spec in specs]


def export_rows(model, specs: list[dict], rows: list[dict], role: str | None, *, admin: bool = False) -> list[list[Any]]:
    out: list[list[Any]] = []
    names = [str(spec.get("name")) for spec in specs]
    for row in rows:
        data = visible_data(model, row.get("data") or {}, role, admin=admin)
        out.append([data.get(name) for name in names])
    return out


def cell_text(value) -> str:
    """导出单元格文本：列表用中文逗号连接，对象转 JSON，布尔转是/否。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "，".join(cell_text(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _formula_guard(value, text: str) -> str:
    """防 CSV / XLSX 公式注入：仅对文本值加前缀，数字（含负数）保持原样。"""
    if isinstance(value, str) and text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def csv_response(filename: str, fallback: str, headers: list[str], rows: list[list[Any]]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = _content_disposition(filename, fallback)
    response["X-Content-Type-Options"] = "nosniff"
    response.write("\ufeff")  # UTF-8 BOM，Excel 直接双击不乱码
    writer = csv.writer(response)
    writer.writerow(headers)
    for values in rows:
        line = []
        for value in values:
            line.append(_formula_guard(value, cell_text(value)))
        writer.writerow(line)
    return response


def xlsx_response(filename: str, fallback: str, headers: list[str], rows: list[list[Any]], *, sheet_title: str = "记录"):
    """openpyxl 生成 XLSX；未安装时抛 ImportFileError（由视图转为友好 400）。"""
    openpyxl = openpyxl_module()
    if openpyxl is None:
        raise ImportFileError("服务端未安装 openpyxl，暂不支持 Excel 导出，请改用 CSV")
    from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    workbook = openpyxl.Workbook()
    try:
        sheet = workbook.active
        sheet.title = _safe_sheet_title(sheet_title)
        for column, header in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="F2F3F5")
            cell.alignment = Alignment(vertical="center")
            sheet.column_dimensions[get_column_letter(column)].width = max(10, min(40, len(str(header)) + 6))
        widths = [max(10, min(40, len(str(header)) + 6)) for header in headers]
        for row_index, values in enumerate(rows, start=2):
            for column, value in enumerate(values, start=1):
                text = _formula_guard(value, cell_text(value))
                sheet.cell(row=row_index, column=column, value=text)
                if column - 1 < len(widths):
                    widths[column - 1] = max(widths[column - 1], min(40, len(text) + 2))
        for column, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(column)].width = width
        sheet.freeze_panes = "A2"
        if headers:
            sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = _content_disposition(filename, fallback)
        response["X-Content-Type-Options"] = "nosniff"
        workbook.save(response)
        return response
    finally:
        try:
            workbook.close()
        except Exception:  # noqa: BLE001
            pass


def _content_disposition(filename: str, fallback: str) -> str:
    from urllib.parse import quote  # noqa: PLC0415

    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _safe_sheet_title(title: str) -> str:
    value = re.sub(r"[\[\]:*?/\\]", "-", str(title or "记录")).strip() or "记录"
    return value[:31]


# ---------------------------------------------------------------- 打印 HTML

_PRINT_STYLE = """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; background: #fff; color: #1f2329;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 13px;
}
.print-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 14px; }
.print-head h1 { margin: 0 0 6px; font-size: 20px; }
.print-meta { color: #6b7280; font-size: 12px; line-height: 1.7; }
.print-hint { color: #9ca3af; font-size: 12px; margin: 0 0 12px; }
table { width: 100%; border-collapse: collapse; table-layout: auto; }
thead { display: table-header-group; }
th, td { border: 1px solid #d9dde3; padding: 6px 8px; text-align: left; vertical-align: top; word-break: break-word; }
th { background: #f2f3f5; font-weight: 600; white-space: nowrap; }
tbody tr:nth-child(even) { background: #fafbfc; }
.empty { padding: 40px; text-align: center; color: #9ca3af; border: 1px dashed #d9dde3; }
@page { size: A4 landscape; margin: 12mm; }
@media print {
  body { padding: 0; }
  .print-hint { display: none; }
  th, td { padding: 4px 6px; }
  tr { page-break-inside: avoid; }
}
"""


def print_html_response(
    model,
    specs: list[dict],
    rows: list[dict],
    role: str | None,
    *,
    admin: bool = False,
    filters: dict | None = None,
) -> HttpResponse:
    """生成可直接浏览器打印 / 另存 PDF 的 HTML；所有动态文本均转义。"""
    from django.utils import timezone  # noqa: PLC0415

    headers = export_headers(specs)
    body = export_rows(model, specs, rows, role, admin=admin)
    now = timezone.localtime(timezone.now())
    model_name = escape(str(model.name))
    filter_text = _filter_summary(filters or {})

    lines: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        f"<title>{model_name} - 记录打印</title>",
        f"<style>{_PRINT_STYLE}</style>",
        "</head>",
        "<body>",
        '<div class="print-head">',
        "<div>",
        f"<h1>{model_name} · 记录</h1>",
        f'<div class="print-meta">共 {len(body)} 条记录{("；" + escape(filter_text)) if filter_text else ""}</div>',
        "</div>",
        f'<div class="print-meta">生成时间：{now.strftime("%Y-%m-%d %H:%M:%S")}</div>',
        "</div>",
        '<p class="print-hint">使用浏览器打印（Ctrl/Cmd + P）可另存为 PDF。</p>',
    ]
    if not headers:
        lines.append('<div class="empty">模型没有可展示的字段</div>')
    elif not body:
        lines.append('<div class="empty">没有匹配的记录</div>')
    else:
        lines.append("<table>")
        lines.append("<thead><tr>")
        for header in headers:
            lines.append(f"<th>{escape(header)}</th>")
        lines.append("</tr></thead>")
        lines.append("<tbody>")
        for values in body:
            lines.append("<tr>")
            for value in values:
                lines.append(f"<td>{escape(cell_text(value))}</td>")
            lines.append("</tr>")
        lines.append("</tbody>")
        lines.append("</table>")
    lines.extend(["</body>", "</html>"])
    response = HttpResponse("\n".join(lines), content_type="text/html; charset=utf-8")
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _filter_summary(filters: dict) -> str:
    if not filters:
        return ""
    parts = []
    for key, value in filters.items():
        if key in ("page", "size", "page_size", "format"):
            continue
        text = str(value if value is not None else "").strip()
        if text:
            parts.append(f"{key}={text}")
    return "筛选条件：" + "，".join(parts) if parts else ""


# ---------------------------------------------------------------- DRF renderer


class RecordCsvRenderer(BaseRenderer):
    """让 DRF 接受 ``?format=csv``（实际响应由视图直接返回 HttpResponse）。"""

    media_type = "text/csv"
    format = "csv"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):  # noqa: D102
        return data


class RecordXlsxRenderer(BaseRenderer):
    """让 DRF 接受 ``?format=xlsx``（避免被内容协商当成未知格式 404）。"""

    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    format = "xlsx"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):  # noqa: D102
        return data
