"""Verify every converted standard against the source PDF and manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader


def verify(standards: Path, sources: Path) -> dict:
    manifest = json.loads((standards / "conversion-manifest.json").read_text(encoding="utf-8"))
    documents = manifest["documents"]
    corrections_path = standards / "ocr-corrections.json"
    corrections = json.loads(corrections_path.read_text(encoding="utf-8")).get("documents", {}) if corrections_path.is_file() else {}
    failures: list[str] = []
    if manifest.get('run_status') != 'complete':
        failures.append('Conversion batch is not complete')
    warnings: list[dict] = []
    seen: set[str] = set()
    total_pages = 0
    for document in documents:
        relative = document["source_pdf"]
        if relative in seen:
            failures.append(f"Duplicate source: {relative}")
        seen.add(relative)
        pdf = (sources / relative).resolve()
        md = (standards / document["markdown"]).resolve()
        if not pdf.is_relative_to(sources.resolve()) or not md.is_relative_to(standards.resolve()):
            failures.append(f"Path outside library: {relative}")
            continue
        if not pdf.is_file() or not md.is_file():
            failures.append(f"Missing PDF or Markdown: {relative}")
            continue
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        reader = PdfReader(str(pdf), strict=False)
        actual_count = len(reader.pages)
        text = md.read_text(encoding="utf-8")
        markers = [int(n) for n in re.findall(r"^## PDF 第 (\d+) 页\s*$", text, re.M)]
        chunks = re.split(r"^## PDF 第 (\d+) 页\s*$", text, flags=re.M)
        page_text = {int(chunks[i]): chunks[i + 1] for i in range(1, len(chunks) - 1, 2)}
        header = re.search(r"^- PDF 总页数：(\d+)\s*$", text, re.M)
        if digest != document["pdf_sha256"] or digest not in text[:1200]:
            failures.append(f"SHA mismatch: {relative}")
        if markers != list(range(1, actual_count + 1)):
            failures.append(f"Page markers do not match PDF: {relative}")
        if document["total_pages"] != actual_count or not header or int(header[1]) != actual_count:
            failures.append(f"Page count mismatch: {relative}")
        if not document.get("page_sequence_ok"):
            failures.append(f"Manifest page sequence failed: {relative}")
        if digest in corrections and corrections[digest].get('source_pdf') != relative:
            failures.append(f"Visual correction source differs: {relative}")
        visual_pages = corrections.get(digest, {}).get("pages", {})
        for number, correction in visual_pages.items():
            if not 1 <= int(number) <= actual_count:
                failures.append(f"Visual correction page outside PDF: {relative}, {number}")
            if re.sub(r'\s+', '', page_text.get(int(number), '')) != re.sub(r'\s+', '', correction['text']):
                failures.append(f"Visual correction was not applied: {relative}, {number}")
        for number in document.get("source_text_pages", []):
            if not 1 <= number <= actual_count:
                failures.append(f"Native page outside PDF: {relative}, {number}")
                continue
            # A page explicitly transcribed from its image can repair a corrupt
            # PDF text layer. Its exact correction text is checked above.
            if str(number) in visual_pages:
                continue
            original = (reader.pages[number - 1].extract_text() or "").replace("\x00", "")
            if re.sub(r"\s+", "", original) != re.sub(r"\s+", "", page_text.get(number, "")):
                failures.append(f"Native text differs from source page: {relative}, {number}")
        total_pages += actual_count
        if document.get("issues") or document.get("too_short_pages") or document.get("language_limitation"):
            warnings.append({"source": relative, "issues": document.get("issues", []),
                             "too_short_pages": document.get("too_short_pages", []),
                             "language_limitation": document.get("language_limitation")})
    source_set = {p.relative_to(sources).as_posix() for p in sources.rglob("*.pdf")}
    for missing in sorted(source_set - seen):
        failures.append(f"Not converted: {missing}")
    for extra in sorted(seen - source_set):
        failures.append(f"Unknown source: {extra}")
    return {"documents": len(documents), "pdf_pages": total_pages,
            "passed": not failures, "failures": failures,
            "documents_with_quality_notes": len(warnings), "quality_notes": warnings}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standards-root", type=Path, default=root / "docs/standards")
    parser.add_argument("--source-root", type=Path, default=root / "docs/standards")
    parser.add_argument("--report", type=Path)
    options = parser.parse_args()
    report = verify(options.standards_root.resolve(), options.source_root.resolve())
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "quality_notes"}, ensure_ascii=True, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
