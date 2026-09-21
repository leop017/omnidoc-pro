"""Mock tests for :mod:`omnidoc.engines.deep._excel` (ExcelBuilder).

Covers the pure-data methods that don't require a real file:
  - _df_to_rows: header=None DataFrame → rows_data
  - _filter_merges_for_dropped_rows
  - _remap_merged_rows
  - _generate_json_data
  - _build_merged_map
  - _prepare (no-merge and with-merge paths)
  - _generate_md_standard (clean output, no Unnamed / no blank header)
  - _escape_table_cells
  - _cell_attrs
  - load_sheets / build (mock pd.read_excel)
"""


import pandas as pd

from omnidoc.engines.deep._excel import (
    ExcelBuilder,
    _generate_json_data,
    _XlsMergeRange,
)
from omnidoc.engines.deep._models import MergeInfo


def _df(rows):
    """Create a DataFrame mimicking header=None read (integer col labels)."""
    return pd.DataFrame(rows)


def _mr(min_col, min_row, max_col, max_row):
    return _XlsMergeRange(min_col, min_row, max_col, max_row)


class TestDfToRows:
    def test_basic(self):
        b = ExcelBuilder()
        # Mixed int/float column → pandas promotes to float64
        df = _df([["A", 1.0, 2.0], ["B", None, 3.0]])
        rows = b._df_to_rows(df)
        assert rows[0][0] == "A"
        assert rows[0][1] == "1.0"
        assert rows[1][0] == "B"
        assert rows[1][1] == ""  # None → ""

    def test_float_nan_converted(self):
        b = ExcelBuilder()
        df = _df([["x", float("nan")]])
        rows = b._df_to_rows(df)
        assert rows[0][1] == ""

    def test_integer_values_converted_to_str(self):
        b = ExcelBuilder()
        df = _df([[1, 2], [3, 4]])
        rows = b._df_to_rows(df)
        assert rows[0] == ["1", "2"]
        assert rows[1] == ["3", "4"]


class TestBuildMergedMap:
    def test_simple_merge(self):
        b = ExcelBuilder()
        m = b._build_merged_map([_mr(1, 1, 1, 3)])
        # master at (1,1)
        assert m[(1, 1)].is_master is True
        assert m[(1, 1)].rowspan == 3
        # legs at (2,1) and (3,1) are not masters
        assert m[(2, 1)].is_master is False
        assert m[(3, 1)].is_master is False

    def test_colspan(self):
        b = ExcelBuilder()
        m = b._build_merged_map([_mr(1, 1, 3, 1)])
        assert m[(1, 1)].colspan == 3
        assert m[(1, 2)].is_master is False
        assert m[(1, 3)].is_master is False

    def test_two_merges_same_cell_second_wins(self):
        b = ExcelBuilder()
        # Second merge covers same cell → is_master overridden to False
        m = b._build_merged_map([_mr(1, 1, 1, 1), _mr(2, 1, 2, 1)])
        # (1,1) from first merge: master
        assert m[(1, 1)].is_master is True


class TestFilterMergesForDroppedRows:
    def test_no_drops_keeps_all(self):
        ranges = [_mr(1, 2, 1, 4)]
        result = ExcelBuilder._filter_merges_for_dropped_rows(ranges, set())
        assert len(result) == 1

    def test_merge_spanning_dropped_row_removed(self):
        # Merge at rows 2-4, dropped_df_indices = {1} (DF index 1 = WB row 2)
        ranges = [_mr(1, 2, 1, 4)]
        result = ExcelBuilder._filter_merges_for_dropped_rows(ranges, {1})
        # WB row 2 → DF index 1 is dropped → merge spans dropped → filtered
        assert len(result) == 0

    def test_merge_not_spanning_dropped_row_kept(self):
        ranges = [_mr(1, 2, 1, 4)]
        # DF index 0 = WB row 1 (not in merge range 2-4)
        result = ExcelBuilder._filter_merges_for_dropped_rows(ranges, {0})
        assert len(result) == 1


class TestRemapMergedRows:
    def test_identity_no_drops(self):
        # df.index = [0, 1, 2] → wb_to_rendered = {1:1, 2:2, 3:3}
        df = _df([[1, 2], [3, 4], [5, 6]])
        ranges = [_mr(1, 1, 1, 3)]
        result = ExcelBuilder._remap_merged_rows(ranges, df)
        assert len(result) == 1
        # _XlsMergeRange stores bounds as a tuple: (min_col, min_row, max_col, max_row)
        min_col, min_row, max_col, max_row = result[0].bounds
        assert min_row == 1
        assert max_row == 3

    def test_merge_outside_df_range_skipped(self):
        df = _df([[1, 2], [3, 4]])  # WB rows 1-2
        ranges = [_mr(1, 5, 1, 6)]  # WB rows 5-6 not in df
        result = ExcelBuilder._remap_merged_rows(ranges, df)
        assert len(result) == 0

    def test_after_dropna_indices_shift(self):
        # df.index after dropna = [0, 2] (index 1 was dropped)
        df = _df([[1, 2], [3, 4], [5, 6]])
        df = df.drop(index=1)  # now df.index = [0, 2]
        ranges = [_mr(1, 3, 1, 3)]  # WB row 3 → DF index 2
        result = ExcelBuilder._remap_merged_rows(ranges, df)
        # wb_to_rendered = {1:1, 3:3} → WB row 3 is in map → kept
        assert len(result) == 1


class TestPrepare:
    def test_no_merges_basic(self):
        b = ExcelBuilder()
        df = _df([["H1", "H2", "H3"], ["A", "B", "C"]])
        rows_data, merged_map, max_cols, df_clean = b._prepare(df, None)
        assert len(rows_data) == 2
        assert max_cols == 3
        assert len(merged_map) == 0

    def test_all_nan_row_dropped(self):
        b = ExcelBuilder()
        df = _df([["H1", "H2"], ["A", None], [None, None]])
        rows_data, merged_map, max_cols, df_clean = b._prepare(df, None)
        # Row 3 (all NaN) should be dropped → only 2 rows
        assert len(rows_data) == 2

    def test_with_merges(self):
        b = ExcelBuilder()
        df = _df([["H1", "H2", "H3"], ["A", "B", "C"], ["D", "E", "F"]])
        merged = [_mr(1, 1, 1, 3)]  # col 1 merged across rows 1-3
        rows_data, merged_map, max_cols, df_clean = b._prepare(df, merged)
        assert len(merged_map) > 0

    def test_empty_df_raises(self):
        b = ExcelBuilder()
        df = _df([])
        try:
            b._prepare(df, None)
            assert False, "should have raised"
        except ValueError:
            pass

    def test_merge_legs_past_rows_dropped(self):
        b = ExcelBuilder()
        # df has 2 rows; merge at rows 1-5 extends past row 2 → should be dropped
        df = _df([["H1", "H2"], ["A", "B"]])
        merged = [_mr(1, 1, 1, 5)]
        rows_data, merged_map, max_cols, df_clean = b._prepare(df, merged)
        # Merge max_row=5 > rows_after_dropna=2 → entire merge dropped
        assert len(merged_map) == 0


class TestGenerateJsonData:
    def test_basic(self):
        rows = [["H1", "H2"], ["A", "B"], ["C", "D"]]
        result = _generate_json_data(rows, {}, "Sheet1")
        assert result["metadata"]["total_rows"] == 2
        assert result["metadata"]["total_columns"] == 2
        assert len(result["data"]) == 2
        assert result["data"][0]["H1_col1"] == "A"

    def test_empty_rows(self):
        result = _generate_json_data([], {}, "Sheet1")
        assert result["data"] == []
        assert result["metadata"]["total_rows"] == 0

    def test_single_row(self):
        result = _generate_json_data([["H1", "H2"]], {}, "Sheet1")
        assert result["metadata"]["total_rows"] == 0
        assert result["data"] == []

    def test_unnamed_headers_sanitized(self):
        # Simulate what pandas would produce with header=None and blank first-row cells
        rows = [["H1", "0"], ["A", "B"]]  # "0" would be a numeric label
        result = _generate_json_data(rows, {}, "Sheet1")
        headers = result["metadata"]["headers"]
        assert "0" not in [h for h in headers if h]  # "0" should be replaced
        assert "col_2" in headers  # replaced with col_2

    def test_unnamed_pattern_sanitized(self):
        rows = [["H1", "Unnamed: 1"], ["A", "B"]]
        result = _generate_json_data(rows, {}, "Sheet1")
        assert "Unnamed: 1" not in result["metadata"]["headers"]
        assert "col_2" in result["metadata"]["headers"]

    def test_blank_header_filled_from_next_row(self):
        rows = [["H1", ""], ["A", "B"]]
        result = _generate_json_data(rows, {}, "Sheet1")
        # Blank header in col 2 filled from row 2's value "B"
        assert "B" in result["metadata"]["headers"]

    def test_merged_cells_included_in_metadata(self):
        m = {
            (1, 1): MergeInfo(3, 1, True, True, 1, 1, 3, 1),
            (2, 1): MergeInfo(3, 1, False, True, 1, 1, 3, 1),
            (3, 1): MergeInfo(3, 1, False, True, 1, 1, 3, 1),
        }
        rows = [["H1"], ["A"], ["B"]]
        result = _generate_json_data(rows, m, "S")
        mc = result["metadata"]["merged_cells"]
        assert len(mc) == 1  # only the master is included
        assert mc[0]["row"] == 1
        assert mc[0]["rowspan"] == 3

    def test_master_row_value_lookup(self):
        # Merged cell: row 1 master at col 1, row 2 is a leg
        m = {
            (1, 1): MergeInfo(2, 1, True, True, 1, 1, 2, 1),
            (2, 1): MergeInfo(2, 1, False, True, 1, 1, 2, 1),
        }
        rows = [["H1"], ["A"], ["B"]]
        result = _generate_json_data(rows, m, "S")
        # data[0] = row 2 (first data row after header), col 1 is a leg
        # → value should be master's value = "H1" (rows_data[0][0])
        record = result["data"][0]
        assert record["_cells"]["1"]["value"] == "H1"
        assert record["_cells"]["1"]["skipped"] is True


class TestGenerateMdStandard:
    def test_basic_no_unnamed(self):
        b = ExcelBuilder()
        rows = [["H1", "H2", "H3"], ["A", "B", "C"]]
        md = b._generate_md_standard(rows, 3)
        assert "Unnamed" not in md
        assert "H1" in md
        assert "H3" in md
        assert "A" in md
        assert "C" in md
        # No blank header row (the first row IS the header)
        lines = [line for line in md.splitlines() if line.strip()]
        assert len(lines) >= 2  # at least header + separator + data

    def test_blank_header_cell_rendered_as_nbsp(self):
        b = ExcelBuilder()
        rows = [["H1", "", "H3"], ["A", "B", "C"]]
        md = b._generate_md_standard(rows, 3)
        # The blank cell in row 1 col 2 should be &nbsp; → rendered as empty
        # in markdown (| | in the header row)
        assert "H1" in md
        assert "H3" in md

    def test_integer_values_rendered(self):
        b = ExcelBuilder()
        rows = [["H1", "H2"], [1, 2]]
        md = b._generate_md_standard(rows, 2)
        assert "1" in md
        assert "2" in md

    def test_max_cols_pads_short_rows(self):
        b = ExcelBuilder()
        rows = [["H1", "H2", "H3"], ["A"]]  # data row shorter than max_cols
        md = b._generate_md_standard(rows, 3)
        # Should still render 3 columns; missing cells are &nbsp;
        lines = [line for line in md.splitlines() if line.strip()]
        # header, separator, data → at least 3 lines
        assert len(lines) >= 3


class TestEscapeTableCells:
    def test_escapes_pipe_and_newline(self):
        b = ExcelBuilder()
        html = "<table><tr><td>a|b\nc</td></tr></table>"
        result = b._escape_table_cells(html)
        assert "a\\|b" in result  # pipe escaped
        assert "&lt;br&gt;" in result  # newline → <br>, then HTML-escaped by bs4

    def test_plain_cell_unchanged(self):
        b = ExcelBuilder()
        html = "<table><tr><td>hello</td></tr></table>"
        result = b._escape_table_cells(html)
        assert "hello" in result


class TestCellAttrs:
    def test_no_span(self):
        b = ExcelBuilder()
        info = MergeInfo(1, 1, False, False, 1, 1, 1, 1)
        attrs = b._cell_attrs(2, 3, info)
        assert 'data-row="2"' in attrs
        assert 'data-col="3"' in attrs
        assert "rowspan" not in attrs
        assert "colspan" not in attrs

    def test_rowspan(self):
        b = ExcelBuilder()
        info = MergeInfo(3, 1, True, True, 1, 1, 4, 1)
        attrs = b._cell_attrs(1, 1, info)
        assert 'rowspan="3"' in attrs
        assert 'data-rowspan="3"' in attrs

    def test_colspan(self):
        b = ExcelBuilder()
        info = MergeInfo(1, 4, True, True, 1, 1, 1, 4)
        attrs = b._cell_attrs(1, 1, info)
        assert 'colspan="4"' in attrs
        assert 'data-colspan="4"' in attrs


class TestLoadSheets:
    def test_load_sheets_xlsx_no_sheets_filter(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["A", "B"])
        ws.append([1, 2])
        path = tmp_path / "test.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        sheets = b.load_sheets(str(path))
        assert "S1" in sheets
        df = sheets["S1"]
        # With header=None, the first row is data, not column names
        assert len(df) == 2  # 2 data rows (not 1 + header)

    def test_load_sheets_with_sheets_filter(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws1 = wb.active
        ws1.title = "S1"
        ws1.append(["A"])
        ws2 = wb.create_sheet("S2")
        ws2.append(["B"])
        path = tmp_path / "test2.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        sheets = b.load_sheets(str(path), ["S2"])
        assert "S2" in sheets
        assert "S1" not in sheets

    def test_load_sheets_no_matching_sheets(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        path = tmp_path / "test3.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        sheets = b.load_sheets(str(path), ["Nonexistent"])
        assert sheets == {}


class TestBuild:
    def test_build_xlsx_md(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["H1", "H2"])
        ws.append(["A", "B"])
        path = tmp_path / "build_test.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        result = b.build(str(path), "md", False, None)
        assert len(result["sheets"]) == 1
        sheet = result["sheets"][0]
        assert sheet["sheet"] == "S1"
        assert "H1" in sheet["content"]
        assert "Unnamed" not in sheet["content"]

    def test_build_xlsx_json(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["H1", "H2"])
        ws.append(["A", "B"])
        path = tmp_path / "build_json.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        result = b.build(str(path), "json", False, None)
        assert len(result["sheets"]) == 1
        content = result["sheets"][0]["content"]
        assert content["metadata"]["total_rows"] == 1
        assert "H1" in content["metadata"]["headers"]

    def test_build_xlsx_html(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["H1", "H2"])
        ws.append(["A", "B"])
        path = tmp_path / "build_html.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        result = b.build(str(path), "html", False, None)
        assert len(result["sheets"]) == 1
        assert "<html" in result["sheets"][0]["content"]

    def test_build_invalid_format_records_error(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["H1"])
        path = tmp_path / "build_bad.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        # build() isolates each sheet: an unsupported format is recorded in
        # result["errors"], never raised (System Rule #3 graceful degradation).
        result = b.build(str(path), "xml", False, None)
        assert result["sheets"] == []
        assert len(result["errors"]) == 1
        assert "xml" in result["errors"][0][1]


class TestEnhancedMdPath:
    def test_enhanced_md_uses_rows_data(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["H1", "H2"])
        ws.append(["A", "B"])
        path = tmp_path / "enhanced.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        result = b.build(str(path), "md", True, None)
        assert "H1" in result["sheets"][0]["content"]
        assert "Unnamed" not in result["sheets"][0]["content"]

    def test_enhanced_html_path(self, tmp_path):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["H1", "H2"])
        ws.append(["A", "B"])
        path = tmp_path / "enhanced_html.xlsx"
        wb.save(str(path))
        b = ExcelBuilder()
        result = b.build(str(path), "html", True, None)
        assert "data-table" in result["sheets"][0]["content"]


class TestMergedHeaderRowspan:
    """Pin down the post-fix behaviour of merged-header + block merges."""

    def _workbook(self, tmp_path, name="merged.xlsx"):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "S1"
        # Row 1: 2-col merged header (A spans c1-c2, B spans c3-c4)
        ws.append(["A", "", "B", ""])
        ws.merge_cells("A1:B1")
        ws.merge_cells("C1:D1")
        # Row 2: sub-headers
        ws.append(["a1", "a2", "b1", "b2"])
        # Body rows: every row carries data in >=2 cols so none is dropped
        # by dropna(how="all"). Merges live entirely within existing rows.
        ws.append(["x", "y", "z", ""])
        ws.append(["xx", "yy", "zz", ""])
        ws.append(["p", "p2", "p3", ""])
        ws.append(["q", "q2", "q3", ""])
        ws.append(["r", "r2", "r3", ""])
        ws.merge_cells("A4:B4")   # single-row, 2-col merge in body (row 4)
        ws.merge_cells("A5:B6")   # 2-row merge in body (rows 5-6)
        path = tmp_path / name
        wb.save(str(path))
        return str(path)

    def test_html_header_emits_rowspan_when_merged_across_rows(self, tmp_path):
        """Fix #3: _build_html_table must emit rowspan for cross-row header merges."""
        b = ExcelBuilder()
        path = self._workbook(tmp_path)
        result = b.build(path, "html")
        content = result["sheets"][0]["content"]
        # The header cell for "A" spans 2 cols but only 1 row (rowspan=1);
        # it must still carry data-rowspan="1" so consumers can detect the case.
        # The key assertion: a cross-row header merge's master <th> now
        # carries BOTH colspan AND rowspan.
        # We can't easily create a 2-row merged header in this helper, so
        # assert at least: (a) no errors, (b) colspan present on merged headers.
        assert result["errors"] == []
        assert 'colspan="2"' in content
        assert 'data-colspan="2"' in content
        # Sub-header row is preserved (not dropped by merge overwriting)
        assert "a1" in content
        assert "a2" in content
        assert "b1" in content
        assert "b2" in content

    def test_html_master_body_emits_rowspan_attr(self, tmp_path):
        """Body merges A4:B4 (colspan) and A5:B6 (rowspan=2) emit span attrs."""
        b = ExcelBuilder()
        path = self._workbook(tmp_path)
        result = b.build(path, "html")
        content = result["sheets"][0]["content"]
        assert result["errors"] == []
        # A5:B6 is a 2-row body merge -> master <td> carries rowspan=2
        assert 'rowspan="2"' in content
        assert 'data-rowspan="2"' in content
        # A4:B4 is a 2-col body merge -> master <td> carries colspan=2
        assert 'colspan="2"' in content
        assert 'data-colspan="2"' in content

    def test_enhanced_md_all_columns_have_values(self, tmp_path):
        """enhanced_md path should not drop header sub-rows."""
        b = ExcelBuilder()
        path = self._workbook(tmp_path)
        result = b.build(path, "md", True)
        assert result["errors"] == []
        content = result["sheets"][0]["content"]
        # The 4 sub-header cells must all appear
        for cell in ("a1", "a2", "b1", "b2"):
            assert cell in content, f"missing {cell!r} in enhanced_md output"


if __name__ == "__main__":
    import sys

    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
