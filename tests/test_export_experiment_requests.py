"""Read the evaluation workbook's editable prompt cells."""

from __future__ import annotations

import zipfile

import pytest

from tools.export_experiment_requests import PROMPT_IDS, extract_requests


@pytest.mark.parametrize("sheet_name", ["프롬프트", "입력과실험조건"])
def test_extract_requests_uses_editable_cells_instead_of_cached_json(
    tmp_path, sheet_name: str
) -> None:
    workbook = tmp_path / "prompts.xlsx"
    rows = []
    for index, scenario_id in enumerate(PROMPT_IDS, 7):
        values = (
            f"{scenario_id} · Scenario",
            "Pixel Art",
            "Fantasy",
            "플랫포머",
            "사이드뷰",
            f"Current condition for {scenario_id}",
            '{"condition":"stale cached value"}',
        )
        cells = "".join(
            f'<c r="{column}{index}" t="inlineStr"><is><t>{value}</t></is></c>'
            for column, value in zip("ABCDEFG", values, strict=True)
        )
        rows.append(f'<row r="{index}">{cells}</row>')
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(rows)}</sheetData></worksheet>",
        )

    requests = extract_requests(workbook)

    assert list(requests) == list(PROMPT_IDS)
    assert requests["P01"]["condition"] == "Current condition for P01"
    assert "stale cached value" not in requests["P01"]["condition"]
