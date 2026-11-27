"""Export the evaluation workbook's prompt rows as headless request JSON files."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
PROMPT_IDS = ("P01", "P02", "P03", "P04", "T01", "T02", "T03", "S01", "S02", "S03")


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    namespace = {"m": MAIN_NS}
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", namespace))
    value = cell.find("m:v", namespace)
    if value is None or value.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        return strings[int(value.text)]
    return value.text


def extract_requests(workbook_path: Path) -> dict[str, dict[str, str]]:
    """Read user inputs B:F, avoiding the cached formula output in column G."""

    namespace = {"m": MAIN_NS}
    with zipfile.ZipFile(workbook_path) as workbook:
        workbook_xml = ET.fromstring(workbook.read("xl/workbook.xml"))
        sheets = workbook_xml.findall("m:sheets/m:sheet", namespace)
        prompt_sheet = next(
            (
                sheet
                for sheet in sheets
                if sheet.attrib.get("name") in {"프롬프트", "입력과실험조건"}
            ),
            None,
        )
        if prompt_sheet is None:
            raise ValueError("Workbook has no prompt worksheet (프롬프트/입력과실험조건)")
        relationship_id = prompt_sheet.attrib[f"{{{OFFICE_REL_NS}}}id"]
        relationships = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        target = next(
            (
                item.attrib["Target"]
                for item in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
                if item.attrib.get("Id") == relationship_id
            ),
            None,
        )
        if target is None:
            raise ValueError("Prompt worksheet relationship is missing")
        sheet_path = target.lstrip("/")
        if not sheet_path.startswith("xl/"):
            sheet_path = "xl/" + sheet_path
        sheet_xml = ET.fromstring(workbook.read(sheet_path))

        strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            string_xml = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            strings = [
                "".join(node.text or "" for node in item.findall(".//m:t", namespace))
                for item in string_xml.findall("m:si", namespace)
            ]

        requests: dict[str, dict[str, str]] = {}
        for row in sheet_xml.findall("m:sheetData/m:row", namespace):
            cells = {
                re.match(r"[A-Z]+", cell.attrib["r"]).group(): _cell_text(cell, strings)
                for cell in row.findall("m:c", namespace)
            }
            match = re.match(r"^(P\d{2}|T\d{2}|S\d{2})\b", cells.get("A", ""))
            if match is None:
                continue
            scenario_id = match.group(1)
            if scenario_id in requests:
                raise ValueError(f"Duplicate scenario ID: {scenario_id}")
            request = dict(
                zip(
                    ("image_style", "mood_style", "genre", "viewpoint", "condition"),
                    (cells.get(column, "").strip() for column in "BCDEF"),
                    strict=True,
                )
            )
            if not all(request.values()):
                raise ValueError(f"Incomplete prompt row: {scenario_id}")
            requests[scenario_id] = request
    missing = set(PROMPT_IDS) - requests.keys()
    if missing:
        raise ValueError(f"Missing evaluation prompts: {', '.join(sorted(missing))}")
    return {scenario_id: requests[scenario_id] for scenario_id in PROMPT_IDS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    requests = extract_requests(args.workbook)
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error("output directory is not empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    for scenario_id, request in requests.items():
        path = output_dir / f"{scenario_id}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
