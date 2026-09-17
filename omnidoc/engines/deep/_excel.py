"""Excel (.xls/.xlsx) builder (ported from ``docconvert.converters.excel``).

Preserves the full merged-cell -> Markdown table pipeline verbatim:
:class:`MergeInfo`, :meth:`_build_merged_map`,
:meth:`_filter_merges_for_dropped_rows`, :meth:`_remap_merged_rows` and the
standard / enhanced Markdown generators. The only structural change is that
this builder *produces content* (string or dict) instead of writing files;
the engine decides whether to serialise in-memory or persist to ``output_dir``.
"""

from __future__ import annotations

import html as html_mod
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from openpyxl import load_workbook

from omnidoc.engines.deep._logger import get_logger
from omnidoc.engines.deep._models import MergeInfo
from omnidoc.engines.deep._utils import (
    clean_filename,
    escape_md_cell,
    get_excel_sheet_names,
    html_to_md,
    safe_str,
    unique_cleaned_suffixes,
)


class _XlsMergeRange:
    """Mimics openpyxl's merged cell range for use with _build_merged_map."""

    def __init__(self, min_col: int, min_row: int, max_col: int, max_row: int):
        self.bounds = (min_col, min_row, max_col, max_row)


class ExcelBuilder:
    def __init__(self):
        self.logger = get_logger()

    # ── loading ────────────────────────────────────────────────

    def load_sheets(
        self, input_path: str, sheets: Optional[list[str]] = None
    ) -> dict[str, pd.DataFrame]:
        ext = Path(input_path).suffix.lower()
        engine = "xlrd" if ext == ".xls" else "openpyxl"
        if ext == ".xls":
            try:
                import xlrd  # noqa: F401
            except ImportError:
                raise RuntimeError("需安装 xlrd 库以处理 .xls 文件")
        if sheets is not None:
            all_names = get_excel_sheet_names(input_path, ext)
            existing = [sn for sn in sheets if sn in all_names]
            if not existing:
                return {}
            all_sheets = pd.read_excel(input_path, sheet_name=existing, engine=engine, header=None)
            if not isinstance(all_sheets, dict):
                all_sheets = {existing[0]: all_sheets}
            return all_sheets
        return pd.read_excel(input_path, sheet_name=None, engine=engine, header=None)

    @staticmethod
    def _get_all_sheet_names(input_path: str, ext: str) -> list[str]:
        return get_excel_sheet_names(input_path, ext)

    @staticmethod
    def _load_merged_cache_xls(input_path: str, sheet_names: list[str]) -> dict[str, list]:
        import xlrd

        wb = xlrd.open_workbook(input_path, formatting_info=True)
        try:
            cache: dict[str, list] = {}
            for sn in sheet_names:
                try:
                    ws = wb.sheet_by_name(sn)
                except (KeyError, xlrd.XLRDError):
                    cache[sn] = []
                    continue
                merged = []
                for rlo, rhi, clo, chi in ws.merged_cells:
                    merged.append(_XlsMergeRange(clo + 1, rlo + 1, chi, rhi))
                cache[sn] = merged
            return cache
        finally:
            wb.release_resources()

    def _load_merged_cache(
        self, input_path: str, ext: str, sheet_names: list[str]
    ) -> Optional[dict[str, list]]:
        if ext == ".xls":
            return self._load_merged_cache_xls(input_path, sheet_names)
        if ext != ".xlsx":
            return None
        try:
            wb = load_workbook(input_path, data_only=True)
        except Exception as e:
            self.logger.warning("打开工作簿失败： %s", e)
            return None
        try:
            cache: dict[str, list] = {}
            for sn in sheet_names:
                try:
                    cache[sn] = list(wb[sn].merged_cells.ranges)
                except (KeyError, AttributeError) as e:
                    self.logger.debug("工作表 '%s' 合并单元格读取失败： %s", sn, e)
                    cache[sn] = []
            return cache
        except Exception as e:
            self.logger.warning("合并单元格读取失败： %s", e)
            return None
        finally:
            wb.close()

    # ── merge-cell algorithm (preserved verbatim) ─────────────

    def _build_merged_map(self, merged_ranges: list) -> dict:
        merged_map = {}
        for merged in merged_ranges:
            min_col, min_row, max_col, max_row = merged.bounds
            for row in range(min_row, max_row + 1):
                for col in range(min_col, max_col + 1):
                    key = (row, col)
                    if key not in merged_map:
                        merged_map[key] = MergeInfo(
                            rowspan=max_row - min_row + 1,
                            colspan=max_col - min_col + 1,
                            is_master=(row == min_row and col == min_col),
                            is_merged=True,
                            min_row=min_row,
                            min_col=min_col,
                            max_row=max_row,
                            max_col=max_col,
                        )
                    else:
                        merged_map[key].is_master = False
        return merged_map

    def _df_to_rows(self, df: pd.DataFrame) -> list[list[str]]:
        # With header=None, all rows are data rows (including the original
        # "header" row of the sheet). df.values.tolist() returns every row
        # directly; no column-name reconstruction needed.
        rows_data = []
        for row in df.values.tolist():
            rows_data.append([safe_str(v) for v in row])
        return rows_data

    @staticmethod
    def _filter_merges_for_dropped_rows(merged_ranges: list, dropped_df_indices: set) -> list:
        # With header=None, DataFrame index i corresponds to workbook row i+1.
        # A merge spans dropped rows if any of its workbook rows (1-indexed)
        # maps to a dropped DataFrame index.
        filtered: list = []
        for merged in merged_ranges:
            min_col, min_row, max_col, max_row = merged.bounds
            spans_dropped = any(
                (row - 1) in dropped_df_indices
                for row in range(min_row, max_row + 1)
            )
            if not spans_dropped:
                filtered.append(merged)
        return filtered

    @staticmethod
    def _remap_merged_rows(merged_ranges: list, df: pd.DataFrame) -> list:
        # With header=None, DataFrame index i = workbook row i+1 (identity).
        # After dropna, some rows are removed; the surviving rows shift up.
        # Build workbook-row → rendered-row map: workbook row (i+1) →
        # rendered position (2 + i) when row 1 is the header-like first row,
        # or simply (i+1) for all rows including the first.
        # In this codebase the first rendered row (index 0 in rows_data) is
        # treated as the header row (tag="th"), so rendered position of
        # DataFrame index i is (i + 1).
        wb_to_rendered = {orig_idx + 1: orig_idx + 1 for orig_idx in df.index}
        remapped: list = []
        for merged in merged_ranges:
            min_col, min_row, max_col, max_row = merged.bounds
            if min_row not in wb_to_rendered or max_row not in wb_to_rendered:
                continue
            remapped.append(
                _XlsMergeRange(
                    min_col,
                    wb_to_rendered[min_row],
                    max_col,
                    wb_to_rendered[max_row],
                )
            )
        return remapped

    @staticmethod
    def _iter_merge_legs(info):
        for row in range(info.min_row, info.max_row + 1):
            for col in range(info.min_col, info.max_col + 1):
                yield (row, col)

    # ── content builders ───────────────────────────────────────

    def _prepare(
        self, df: pd.DataFrame, merged_ranges: Optional[list]
    ) -> tuple:
        """Return ``(rows_data, merged_map, max_cols)`` for one sheet."""
        if df.empty:
            raise ValueError("工作表为空")

        all_nan_mask = df.isna().all(axis=1)
        dropped_df_indices = set(df.index[all_nan_mask].tolist())
        if merged_ranges and dropped_df_indices:
            merged_ranges = self._filter_merges_for_dropped_rows(
                merged_ranges, dropped_df_indices
            )

        df = df.dropna(how="all")
        if df.empty:
            raise ValueError("工作表为空")

        rows_data = self._df_to_rows(df)
        max_cols = len(df.columns)
        merged_map = {}
        if merged_ranges:
            merged_ranges = self._remap_merged_rows(merged_ranges, df)
            merged_map = self._build_merged_map(merged_ranges)
            mc = max((key[1] for key in merged_map), default=0)
            max_cols = max(max_cols, mc)
            # Bug guard: a merge whose legs extend past the available rows
            # would render a rowspan no tbody row covers, so the browser
            # silently clamps it. Drop the merge entirely in that case.
            rows_after_dropna = len(rows_data)
            for key, info in list(merged_map.items()):
                if info.max_row > rows_after_dropna:
                    master_key = (info.min_row, info.min_col)
                    for leg in self._iter_merge_legs(info):
                        merged_map.pop(leg, None)
                    merged_map.pop(master_key, None)
        return rows_data, merged_map, max_cols, df

    def _md_content(
        self,
        df: pd.DataFrame,
        rows_data: list,
        merged_map: dict,
        max_cols: int,
        sheet_name: str,
        source_name: str,
        enhanced: bool,
    ) -> str:
        if enhanced:
            md = self._generate_md_via_html(rows_data, merged_map, max_cols, sheet_name)
        else:
            md = self._generate_md_standard(rows_data, max_cols)
        return (
            f"<!-- source: {source_name} | sheet: {sheet_name}"
            f" | rows: {len(rows_data) - 1} | cols: {max_cols} -->\n\n{md}"
        )

    def _generate_md_standard(self, rows_data: list, max_cols: int) -> str:
        # Build the table directly from rows_data (row 1 = <thead>, the rest
        # = <tbody>) instead of the DataFrame, whose column labels are
        # integer/``Unnamed`` under header=None and must never be rendered.
        def _cell(v: Any, tag: str) -> str:
            text = html_mod.escape(escape_md_cell(safe_str(v)))
            return f"<{tag}>&nbsp;</{tag}>" if text == "" else f"<{tag}>{text}</{tag}>"

        head = rows_data[0] if rows_data else []
        head_cells = "".join(_cell(head[c] if c < len(head) else "", "th") for c in range(max_cols))
        html_rows = [f"<tr>{head_cells}</tr>"]
        for row_data in rows_data[1:]:
            cells = "".join(_cell(row_data[c] if c < len(row_data) else "", "td") for c in range(max_cols))
            html_rows.append(f"<tr>{cells}</tr>")
        html_content = "<table>" + "\n".join(html_rows) + "</table>"
        return html_to_md(self._escape_table_cells(html_content))

    @staticmethod
    def _escape_table_cells(html_content: str) -> str:
        from bs4 import BeautifulSoup, Tag

        soup = BeautifulSoup(html_content, "html.parser")
        for cell in soup.find_all(["th", "td"]):
            if not isinstance(cell, Tag):
                continue
            current = cell.get_text()
            unescaped = current.replace(chr(92) + chr(110), chr(10))
            escaped = escape_md_cell(unescaped)
            if escaped != current:
                cell.string = escaped
        return str(soup)

    def _generate_md_via_html(
        self, rows_data: list, merged_map: dict, max_cols: int, sheet_name: str,
    ) -> str:
        row_spans: dict = {}
        html_rows = ["<table>"]
        for row_idx, row_data in enumerate(rows_data, start=1):
            cells = []
            for col in range(1, max_cols + 1):
                span_val = row_spans.get((row_idx, col))
                if span_val is not None:
                    cells.append(span_val)
                    continue
                value = row_data[col - 1] if col <= len(row_data) else ""
                key = (row_idx, col)
                cell_info = merged_map.get(key)
                tag = "th" if row_idx == 1 else "td"
                if cell_info and not cell_info.is_master:
                    cells.append(f"<{tag}>&nbsp;</{tag}>")
                    continue
                if cell_info and cell_info.is_master:
                    if value is not None and str(value).strip() != "":
                        cell_value = html_mod.escape(escape_md_cell(str(value)))
                    else:
                        cell_value = "&nbsp;"
                    cells.append(f"<{tag}>{cell_value}</{tag}>")
                    for r in range(cell_info.rowspan):
                        for c in range(cell_info.colspan):
                            if r == 0 and c == 0:
                                continue
                            row_spans[(row_idx + r, col + c)] = f"<{tag}>{cell_value}</{tag}>"
                else:
                    if value is not None and str(value).strip() != "":
                        cell_value = html_mod.escape(escape_md_cell(str(value)))
                    else:
                        cell_value = "&nbsp;"
                    cells.append(f"<{tag}>{cell_value}</{tag}>")
            html_rows.append("<tr>" + "".join(cells) + "</tr>")
        html_rows.append("</table>")
        return html_to_md("\n".join(html_rows))

    # ── HTML / JSON builders ───────────────────────────────────

    def _build_html_table(
        self, rows_data: list, merged_map: dict, max_cols: int,
        sheet_name: str, source_name: str,
    ) -> str:
        header_row = rows_data[0] if rows_data else []
        html_rows = []
        header_cells = []
        header_covered: dict = {}

        for col_pos in range(1, max_cols + 1):
            h = header_row[col_pos - 1] if col_pos <= len(header_row) else ""
            key = (1, col_pos)
            cell_info = merged_map.get(key)
            if cell_info and cell_info.is_master:
                if cell_info.max_row > 1:
                    for r in range(1, cell_info.rowspan):
                        for c in range(cell_info.colspan):
                            header_covered[(1 + r, col_pos + c)] = True
                    span = (
                        f' colspan="{cell_info.colspan}"'
                        f' data-colspan="{cell_info.colspan}"'
                        if cell_info.colspan > 1 else ""
                    )
                    cell_value = html_mod.escape(str(h)) if h is not None and str(h).strip() != "" else "&nbsp;"
                    header_cells.append(f'<th scope="col" data-row="1" data-col="{col_pos}"{span}>{cell_value}</th>')
                else:
                    attrs = self._cell_attrs(1, col_pos, cell_info)
                    cell_value = html_mod.escape(str(h)) if h is not None and str(h).strip() != "" else "&nbsp;"
                    header_cells.append(f"<th{attrs}>{cell_value}</th>")
            elif cell_info and not cell_info.is_master:
                continue
            else:
                cell_value = html_mod.escape(str(h)) if h is not None and str(h).strip() != "" else "&nbsp;"
                header_cells.append(f'<th scope="col" data-row="1" data-col="{col_pos}">{cell_value}</th>')
        html_rows.append('<tr data-row="1">' + "".join(header_cells) + "</tr>")

        row_spans: dict = {}
        for row_idx, row_data in enumerate(rows_data[1:], start=2):
            cells = []
            for col in range(1, max_cols + 1):
                if header_covered.get((row_idx, col)):
                    cells.append("<td>&nbsp;</td>")
                    continue
                if row_spans.get((row_idx, col), False):
                    continue
                value = row_data[col - 1] if col <= len(row_data) else ""
                key = (row_idx, col)
                cell_info = merged_map.get(key)
                if cell_info and not cell_info.is_master:
                    continue
                if cell_info and cell_info.is_master:
                    attrs = self._cell_attrs(row_idx, col, cell_info)
                    for r in range(1, cell_info.rowspan):
                        for c in range(cell_info.colspan):
                            row_spans[(row_idx + r, col + c)] = True
                    cell_value = html_mod.escape(str(value)) if value is not None and str(value).strip() != "" else "&nbsp;"
                    cells.append(f"<td{attrs}>{cell_value}</td>")
                else:
                    cell_value = html_mod.escape(str(value)) if value is not None and str(value).strip() != "" else "&nbsp;"
                    cells.append(f"<td>{cell_value}</td>")
            html_rows.append(f'<tr data-row="{row_idx}">' + "".join(cells) + "</tr>")

        source_name = html_mod.escape(source_name)
        return (
            f'<table border="1" class="excel-data" id="data-table" '
            f'data-sheet="{html_mod.escape(sheet_name)}"'
            f' data-source="{source_name}">\n<thead>\n{html_rows[0]}\n</thead>\n<tbody>\n'
            + "\n".join(html_rows[1:]) + "\n</tbody>\n</table>"
        )

    @staticmethod
    def _cell_attrs(row_idx: int, col_idx: int, info: MergeInfo) -> str:
        parts = [f'data-row="{row_idx}"', f'data-col="{col_idx}"']
        if info.rowspan > 1:
            parts.append(f'rowspan="{info.rowspan}"')
            parts.append(f'data-rowspan="{info.rowspan}"')
        if info.colspan > 1:
            parts.append(f'colspan="{info.colspan}"')
            parts.append(f'data-colspan="{info.colspan}"')
        return " " + " ".join(parts)

    # ── public entry point ─────────────────────────────────────

    def build(
        self,
        input_path: str,
        output_fmt: str = "md",
        enhanced_md: bool = False,
        sheets: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Build raw content for every sheet in the workbook.

        Returns a dict with per-sheet entries (``sheet``, ``sn_clean``,
        ``content``) plus any per-sheet ``errors`` and workbook-level
        ``metadata``. ``content`` is a string for md/html and a dict for json.
        """
        ext = Path(input_path).suffix.lower()
        source_name = Path(input_path).name
        stem = clean_filename(Path(input_path).stem)

        all_sheets = self.load_sheets(input_path, sheets)
        if not all_sheets:
            return {"sheets": [], "errors": [], "metadata": {}, "stem": stem}

        sheet_names = list(all_sheets.keys())
        merged_cache = self._load_merged_cache(input_path, ext, sheet_names)
        sn_overrides = dict(zip(sheet_names, unique_cleaned_suffixes(sheet_names)))

        out_sheets: list[dict[str, Any]] = []
        errors: list[tuple] = []
        for sn in sheet_names:
            try:
                df = all_sheets.get(sn)
                if df is None:
                    errors.append((sn, "工作表不存在"))
                    continue
                mr = merged_cache.get(sn) if merged_cache else None
                rows_data, merged_map, max_cols, df_clean = self._prepare(df, mr)
                sn_clean = sn_overrides.get(sn) or clean_filename(sn)
                content = self._sheet_content(
                    output_fmt, df_clean, rows_data, merged_map, max_cols, sn,
                    source_name, enhanced_md,
                )
                out_sheets.append({
                    "sheet": sn,
                    "sn_clean": sn_clean,
                    "content": content,
                    "rows": len(rows_data) - 1,
                    "cols": max_cols,
                })
            except Exception as e:  # per-sheet isolation: one bad sheet never aborts the batch
                self.logger.error("工作表转换失败 [%s]: %s", sn, str(e))
                errors.append((sn, str(e)))

        return {
            "sheets": out_sheets,
            "errors": errors,
            "stem": stem,
            "source_name": source_name,
            "metadata": {
                "source": source_name,
                "format": ext.lstrip("."),
                "sheet_count": len(out_sheets),
            },
        }

    def _sheet_content(
        self, output_fmt, df, rows_data, merged_map, max_cols, sheet_name,
        source_name, enhanced_md,
    ):
        if output_fmt == "md":
            return self._md_content(
                df, rows_data, merged_map, max_cols, sheet_name, source_name, enhanced_md
            )
        if output_fmt == "html":
            return _html_document(
                self._build_html_table(rows_data, merged_map, max_cols, sheet_name, source_name),
                sheet_name,
            )
        if output_fmt == "json":
            return _generate_json_data(rows_data, merged_map, sheet_name)
        raise ValueError(f"不支持的输出格式： {output_fmt}")


# ── Module-level helpers ─────────────────────────────────────────


def _html_document(table_html: str, sheet_name: str) -> str:
    return (
        f'<!DOCTYPE html>\n<html lang="zh-CN" data-exported-by="OmniDoc" '
        f'data-sheet-name="{html_mod.escape(sheet_name)}">\n'
        f'<head>\n    <meta charset="UTF-8">\n    '
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'    <title>{html_mod.escape(sheet_name)}</title>\n'
        f'    <style>\n'
        f'        body {{ font-family: Arial, sans-serif; margin: 20px; }}\n'
        f'        table {{ border-collapse: collapse; width: 100%; }}\n'
        f'        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; white-space: pre-wrap; }}\n'
        f'        th {{ background-color: #4CAF50; color: white; }}\n'
        f'        tr:nth-child(even) {{ background-color: #f2f2f2; }}\n'
        f'        tbody tr {{ cursor: pointer; }}\n'
        f'        tbody tr:hover {{ background-color: #e0e0e0; }}\n'
        f'    </style>\n</head>\n<body>\n{table_html}\n</body>\n</html>'
    )


def _generate_json_data(rows_data: list, merged_map: dict, sheet_name: str) -> dict:
    if not rows_data or len(rows_data) < 2:
        return {
            "metadata": {"sheet": sheet_name, "total_rows": 0, "total_columns": 0, "headers": [], "merged_cells": []},
            "data": [],
        }

    headers = list(rows_data[0])
    for c in range(len(headers)):
        if not headers[c]:
            for r in range(1, len(rows_data)):
                if c < len(rows_data[r]) and rows_data[r][c]:
                    headers[c] = rows_data[r][c]
                    break

    # header=None treats the first row as plain data, so pandas may name the
    # columns ``0, 1, 2`` or ``Unnamed: N`` when the first row has blanks.
    # Sanitise the header list: replace anything that matches those patterns
    # with a stable ``col_{n}`` placeholder so downstream JSON keys stay clean.
    import re
    _col_re = re.compile(r'^(Unnamed:\s*\d+|\d+)$')
    for i, h in enumerate(headers, start=1):
        if _col_re.match(str(h)):
            headers[i - 1] = f"col_{i}"

    merged_cells_info = [
        {"row": k[0], "col": k[1], "rowspan": v.rowspan, "colspan": v.colspan}
        for k, v in merged_map.items() if v.is_master
    ]

    records = []
    for row_idx, row_data in enumerate(rows_data[1:], start=2):
        record: dict = {"_row": row_idx, "_cells": {}}
        for col_idx, value in enumerate(row_data, start=1):
            key = (row_idx, col_idx)
            cell_info = merged_map.get(key)
            header_name = headers[col_idx - 1] if col_idx <= len(headers) else f"col_{col_idx}"

            if cell_info and not cell_info.is_master:
                mr, mc = cell_info.min_row, cell_info.min_col
                value = rows_data[mr - 1][mc - 1] if mr <= len(rows_data) and mc <= len(rows_data[mr - 1]) else ""

            cell_data: dict = {"value": value, "col": col_idx, "header": header_name}
            if cell_info and cell_info.is_master:
                cell_data.update(rowspan=cell_info.rowspan, colspan=cell_info.colspan, merged=True)
            elif cell_info and not cell_info.is_master:
                cell_data.update(merged=True, skipped=True)
            else:
                cell_data["merged"] = False
            record["_cells"][str(col_idx)] = cell_data
            record[f"{header_name}_col{col_idx}"] = value
        records.append(record)

    return {
        "metadata": {
            "sheet": sheet_name,
            "total_rows": len(records),
            "total_columns": len(headers),
            "headers": headers,
            "merged_cells": merged_cells_info,
        },
        "data": records,
    }
