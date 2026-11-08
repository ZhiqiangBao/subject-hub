#!/usr/bin/env python3
"""Convert curriculum-standard PDFs into page-addressable UTF-8 Markdown."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader, __version__ as PYPDF_VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = REPO_ROOT / "docs" / "standards"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "docs" / "standards"
OCR_HELPER = Path(__file__).with_name("ocr_standards.ps1")
OCR_DPI = 180
OCR_SCALE_TO = 2800
OCR_RENDER_CHUNK_PAGES = 32
SHORT_PAGE_THRESHOLD = 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def clean_page_text(text: str) -> str:
    """Clean OCR/PDF text spacing without gluing Latin or formula tokens."""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cjk = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    cjk_punctuation = r"，。！？；：、（）《》〈〉「」『』【】〔〕…—·"
    horizontal_space = r"[\t \u00a0\u2000-\u200a]+"
    text = re.sub(rf"(?<=[{cjk}{cjk_punctuation}]){horizontal_space}(?=[{cjk}{cjk_punctuation}])", "", text)
    text = re.sub(rf"(?<=[{cjk}]){horizontal_space}(?=[0-9])", "", text)
    text = re.sub(rf"(?<=[0-9]){horizontal_space}(?=[{cjk}])", "", text)
    return text


def abnormal_counts(text: str) -> dict[str, int]:
    replacement = text.count("\ufffd")
    nul = text.count("\x00")
    private_use = sum(1 for char in text if "\ue000" <= char <= "\uf8ff")
    question_runs = len(re.findall(r"\?{3,}|□{2,}|�{2,}", text))
    return {
        "replacement_characters": replacement,
        "nul_characters": nul,
        "private_use_characters": private_use,
        "suspicious_placeholder_runs": question_runs,
    }


class OcrClient:
    """A single persistent Windows PowerShell/WinRT process with JSONL I/O."""

    def __init__(self, helper: Path = OCR_HELPER) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("Windows PowerShell was not found; OCR pages cannot be processed.")
        if not helper.is_file():
            raise RuntimeError(f"OCR helper is missing: {helper}")
        self.process = subprocess.Popen(
            [powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        ready = self._read_response()
        if not ready.get("ready"):
            self.close()
            raise RuntimeError(f"WinRT OCR helper failed to start: {ready}")
        self.ready = ready
        self.counter = 0

    def _read_response(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            stderr = b""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read(8192)
            raise RuntimeError(
                "WinRT OCR helper exited before returning JSON. "
                + stderr.decode("utf-8", errors="replace")
            )
        try:
            return json.loads(line.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"WinRT OCR helper returned invalid JSON: {line[:300]!r}") from exc

    def recognize(self, image_path: Path, language: str = "zh-Hans-CN") -> dict[str, Any]:
        if self.process.poll() is not None:
            raise RuntimeError(f"WinRT OCR helper exited with status {self.process.returncode}.")
        self.counter += 1
        request_id = str(self.counter)
        assert self.process.stdin is not None
        request = {"request_id": request_id, "path": str(image_path.resolve()), "language": language}
        self.process.stdin.write((json.dumps(request, ensure_ascii=True) + "\n").encode("ascii"))
        self.process.stdin.flush()
        response = self._read_response()
        if response.get("request_id") != request_id:
            raise RuntimeError(f"WinRT OCR response ID mismatch: expected {request_id}, got {response}")
        if not response.get("ok"):
            raise RuntimeError(
                f"WinRT OCR failed at {response.get('stage', 'unknown stage')}: "
                f"{response.get('error', 'Unknown WinRT OCR error')}"
            )
        return response

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is None:
            return
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stderr:
            process.stderr.close()
        if process.stdout:
            process.stdout.close()

    def __enter__(self) -> "OcrClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class TesseractOcrClient:
    """Persistent Node.js/tesseract.js JSONL client for multilingual pages."""

    def __init__(self, languages: str, cache_path: Path) -> None:
        node = shutil.which("node.exe") or shutil.which("node")
        if not node:
            raise RuntimeError("Node.js was not found; Tesseract.js OCR cannot be started.")
        helper = REPO_ROOT / "scripts" / "ocr_multilingual.cjs"
        if not helper.is_file():
            raise RuntimeError(f"Tesseract.js JSONL helper is missing: {helper}")
        module_dir = os.environ.get(
            "SUBJECT_HUB_TESSERACT_MODULE",
            r"C:\Users\33013\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\tesseract.js",
        )
        environment = os.environ.copy()
        environment["SUBJECT_HUB_TESSERACT_MODULE"] = module_dir
        self.process = subprocess.Popen(
            [
                node,
                str(helper),
                "--languages",
                languages,
                "--cache-path",
                str(cache_path.resolve()),
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        ready = self._read_response()
        if not ready.get("ready"):
            self.close()
            raise RuntimeError(f"Tesseract.js OCR helper failed to start: {ready}")
        self.ready = ready
        self.counter = 0

    def _read_response(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            stderr = b""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read(8192)
            raise RuntimeError(
                "Tesseract.js helper exited before returning JSON. "
                + stderr.decode("utf-8", errors="replace")
            )
        try:
            return json.loads(line.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Tesseract.js helper returned invalid JSON: {line[:300]!r}") from exc

    def recognize(self, image_path: Path, _language: str | None = None) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise RuntimeError(f"Tesseract.js helper exited with status {self.process.returncode}.")
        self.counter += 1
        request_id = str(self.counter)
        assert self.process.stdin is not None
        request = {"request_id": request_id, "path": str(image_path.resolve())}
        self.process.stdin.write((json.dumps(request, ensure_ascii=True) + "\n").encode("ascii"))
        self.process.stdin.flush()
        response = self._read_response()
        if response.get("request_id") != request_id:
            raise RuntimeError(f"Tesseract.js response ID mismatch: expected {request_id}, got {response}")
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "Unknown Tesseract.js OCR error"))
        return response

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is None:
            return
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stderr:
            process.stderr.close()
        if process.stdout:
            process.stdout.close()


def make_ocr_client(language: str, temp_root: Path) -> Any:
    if language.startswith("tesseract:"):
        languages = language.split(":", 1)[1]
        return TesseractOcrClient(languages, temp_root.parent / "ocr-languages")
    return OcrClient()


def ocr_engine_name(result: dict[str, Any]) -> str:
    if "tesseract" in str(result.get("engine", "")).casefold():
        return "Tesseract.js"
    return "Windows.Media.Ocr"


def render_pdfium_page(
    pdf: Path,
    page_number: int,
    output_prefix: Path,
    image_format: str,
    scale_to: int = OCR_SCALE_TO,
) -> Path:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("pypdfium2 is required for the PDFium rendering fallback but is unavailable.") from exc
    if image_format not in {"png", "tiff"}:
        raise ValueError(f"Unsupported page image format: {image_format}")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    image_path = output_prefix.with_suffix(".png" if image_format == "png" else ".tif")
    document = pdfium.PdfDocument(str(pdf))
    try:
        page = document[page_number - 1]
        width_pt, height_pt = page.get_size()
        scale = scale_to / max(width_pt, height_pt)
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        if image_format == "png":
            image.save(image_path, format="PNG")
        else:
            image.save(image_path, format="TIFF", compression="raw")
    finally:
        document.close()
    if not image_path.is_file() or image_path.stat().st_size < 1024:
        raise RuntimeError(f"PDFium did not produce a usable image for {pdf.name} page {page_number}.")
    return image_path


def image_is_valid(path: Path | None) -> bool:
    if path is None or not path.is_file() or path.stat().st_size < 1024:
        return False
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            if width < 100 or height < 100:
                return False
            image.verify()
        return True
    except Exception:
        return False


def render_pdf(
    pdf: Path,
    output_prefix: Path,
    pages: list[int],
    image_format: str = "tiff",
    scale_to: int = OCR_SCALE_TO,
    dpi: int = OCR_DPI,
) -> dict[int, Path]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm was not found; install Poppler or add it to PATH.")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    if image_format not in {"png", "tiff"}:
        raise ValueError(f"Unsupported page image format: {image_format}")
    extension = ".png" if image_format == "png" else ".tif"
    format_args = ["-png"] if image_format == "png" else ["-tiff", "-tiffcompression", "none"]
    sorted_pages = sorted(set(pages))
    rendered: dict[int, Path] = {}
    runs: list[tuple[int, int]] = []
    for page in sorted_pages:
        if not runs or page > runs[-1][1] + 1:
            runs.append((page, page))
        else:
            runs[-1] = (runs[-1][0], page)
    for start, end in runs:
        if start == end:
            rendered[start] = render_one_page(
                pdf,
                start,
                output_prefix.parent / f"page-{start}",
                image_format=image_format,
                scale_to=scale_to,
                dpi=dpi,
            )
            continue
        command = [
            pdftoppm,
            *format_args,
            "-f",
            str(start),
            "-l",
            str(end),
            "-r",
            str(dpi),
            "-scale-to",
            str(scale_to),
            str(pdf),
            str(output_prefix),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        # Poppler zero-pads the suffix based on the PDF page count for ranges.
        # Parse the numeric suffix instead of assuming the unpadded spelling.
        for image in output_prefix.parent.glob(f"{output_prefix.name}-*{extension}"):
            match = re.fullmatch(rf"{re.escape(output_prefix.name)}-(\d+)\{extension}", image.name, re.I)
            if match:
                rendered[int(match.group(1))] = image
    # Poppler sometimes exits successfully but leaves a tiny or undecodable
    # image for a page with a malformed optional-content-group entry. Fall back
    # to PDFium for only those pages, and keep the renderer visible in the name.
    for page_number in sorted_pages:
        image = rendered.get(page_number)
        if not image_is_valid(image):
            fallback_prefix = output_prefix.parent / f"page-{page_number}.pdfium"
            rendered[page_number] = render_pdfium_page(pdf, page_number, fallback_prefix, image_format, scale_to)
    return rendered


def render_one_page(
    pdf: Path,
    page_number: int,
    output_prefix: Path,
    image_format: str = "png",
    scale_to: int = OCR_SCALE_TO,
    dpi: int = OCR_DPI,
) -> Path:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm was not found; install Poppler or add it to PATH.")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    if image_format not in {"png", "tiff"}:
        raise ValueError(f"Unsupported page image format: {image_format}")
    extension = ".png" if image_format == "png" else ".tif"
    format_args = ["-png"] if image_format == "png" else ["-tiff", "-tiffcompression", "none"]
    command = [
        pdftoppm,
        *format_args,
        "-singlefile",
        "-f",
        str(page_number),
        "-l",
        str(page_number),
        "-r",
        str(dpi),
        "-scale-to",
        str(scale_to),
        str(pdf),
        str(output_prefix),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    image = output_prefix.with_suffix(extension)
    if not image_is_valid(image):
        return render_pdfium_page(pdf, page_number, output_prefix.with_name(output_prefix.name + ".pdfium"), image_format, scale_to)
    return image


def cache_read(cache_path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not cache_path.is_file():
        return cache
    with cache_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                item = json.loads(line)
                cache[item["key"]] = item["result"]
            except Exception:
                print(f"Warning: ignored malformed OCR cache line {line_number}.", file=sys.stderr)
    return cache


def cache_append(cache_path: Path, key: str, result: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps({"key": key, "result": result}, ensure_ascii=False) + "\n")
        stream.flush()


def ocr_cache_key(pdf_sha: str, page: int, language: str, renderer: str = "poppler") -> str:
    engine = "Tesseract.js" if language.startswith("tesseract:") else "Windows.Media.Ocr"
    return f"{pdf_sha}:{engine}:{language}:{OCR_DPI}:{OCR_SCALE_TO}:{renderer}:{page}"


def ocr_cache_lookup(
    cache: dict[str, dict[str, Any]],
    pdf_sha: str,
    page: int,
    language: str,
    renderer: str,
) -> dict[str, Any] | None:
    key = ocr_cache_key(pdf_sha, page, language, renderer)
    if key in cache:
        return cache[key]
    if renderer == "poppler":
        # Read caches generated before renderer was part of the key. Those
        # pages were rendered by Poppler; PDFium retries use a distinct key.
        engine = "Tesseract.js" if language.startswith("tesseract:") else "Windows.Media.Ocr"
        legacy_key = f"{pdf_sha}:{engine}:{language}:{OCR_DPI}:{OCR_SCALE_TO}:{page}"
        return cache.get(legacy_key)
    return None


def sample_pages(page_records: list[dict[str, Any]]) -> tuple[dict[str, list[int]], dict[str, str]]:
    texts = {record["page"]: record["text"] for record in page_records}
    nonempty = [page for page, text in texts.items() if compact_length(text) > 0]
    toc_pages = [page for page, text in texts.items() if page <= 35 and re.search(r"目\s*录|目\s*錄|contents", text, re.I)]
    directory_candidates = toc_pages or [page for page in nonempty if page <= 20]
    body_start = (toc_pages[-1] + 1) if toc_pages else 5
    body_candidates = [page for page in nonempty if page >= body_start and compact_length(texts[page]) >= 200]
    table_pattern = re.compile(r"表\s*[0-9一二三四五六七八九十]|图\s*[0-9一二三四五六七八九十]|公式|[=≤≥±×÷∑√∫]|\b(?:x|y|m|kg|cm|km|%|℃)\b", re.I)
    table_candidates = [page for page, text in texts.items() if table_pattern.search(text)]

    candidates = {
        "directory": directory_candidates,
        "body": body_candidates,
        "table_or_formula_candidate": table_candidates,
    }
    reasons = {
        "directory": "显式目录标记" if toc_pages else "前20页首个非空页面的候选，需检查是否为目录/前言",
        "body": "目录之后首个正文长度不少于200字符的页面" if body_candidates else "正文页候选回退，需核对",
        "table_or_formula_candidate": "匹配表/图/公式/数学符号的页面" if table_candidates else "从未选页面中回退，需核对是否含表格或公式",
    }

    selected: dict[str, list[int]] = {}
    used: set[int] = set()
    fallback_pages = [page for page in nonempty if page not in used]
    for category, options in candidates.items():
        chosen = next((page for page in options if page not in used), None)
        if chosen is None:
            fallback_pages = [page for page in nonempty if page not in used]
            chosen = fallback_pages[0] if fallback_pages else None
            if chosen is not None:
                reasons[category] += "；使用非空页回退"
        if chosen is None and page_records:
            chosen = min(len(page_records), max(1, len(used) + 1))
            reasons[category] += "；全文无非空页，取连续页标记"
        selected[category] = [chosen] if chosen is not None else []
        if chosen is not None:
            used.add(chosen)
    return selected, reasons


def write_qa_samples(
    pdf: Path,
    relative_pdf: Path,
    page_records: list[dict[str, Any]],
    samples: dict[str, list[int]],
    temp_root: Path,
) -> list[str]:
    if "义务教育-2022" not in relative_pdf.as_posix():
        return []
    artifact_dir = temp_root / "qa-samples" / pdf.stem
    render_dir = artifact_dir / "_render"
    if render_dir.exists():
        shutil.rmtree(render_dir)
    render_dir.mkdir(parents=True, exist_ok=True)
    sample_entries = [(category, pages[0]) for category, pages in samples.items() if pages]
    rendered = render_pdf(pdf, render_dir / "page", sorted({page for _, page in sample_entries}), image_format="png")
    records_by_page = {record["page"]: record for record in page_records}
    artifacts: list[str] = []
    for category, page_number in sample_entries:
        image = rendered.get(page_number)
        if image is None or not image.is_file():
            raise RuntimeError(f"Could not preserve QA source image for {relative_pdf.as_posix()} page {page_number}.")
        name = f"page-{page_number}-{category}.png"
        destination = artifact_dir / name
        shutil.copyfile(image, destination)
        text_destination = destination.with_suffix(".cleaned.txt")
        text_destination.write_text(records_by_page[page_number]["text"] + "\n", encoding="utf-8", newline="\n")
        artifacts.extend(
            [
                (Path("tmp") / "pdfs" / "qa-samples" / pdf.stem / name).as_posix(),
                (Path("tmp") / "pdfs" / "qa-samples" / pdf.stem / text_destination.name).as_posix(),
            ]
        )
    shutil.rmtree(render_dir)
    return artifacts


def title_and_version(pdf: Path) -> tuple[str, str]:
    title = pdf.stem
    version_match = re.search(r"\(([^()]*(?:\d{4}年版|\d{4}年修订)[^()]*)\)", title)
    if not version_match:
        version_match = re.search(r"（([^（）]*(?:\d{4}年版|\d{4}年修订)[^（）]*)）", title)
    version = version_match.group(1) if version_match else "未能从文件名识别"
    return title, version


def build_markdown(
    pdf: Path,
    source_relative: str,
    pdf_sha: str,
    page_records: list[dict[str, Any]],
    tools_used: list[str],
) -> str:
    title, version = title_and_version(pdf)
    lines = [
        f"# {title}",
        "",
        f"- 来源 PDF：`{source_relative}`",
        f"- 版本：{version}",
        f"- PDF SHA256：`{pdf_sha}`",
        f"- PDF 总页数：{len(page_records)}",
        f"- 提取工具：{'；'.join(tools_used)}",
        "",
    ]
    for record in page_records:
        lines.append(f"## PDF 第 {record['page']} 页")
        lines.append("")
        text = record["text"].strip("\n")
        if text:
            lines.extend(text.split("\n"))
        lines.append("")
    return "\n".join(line.expandtabs(4).rstrip() for line in lines).rstrip() + "\n"


def validate_markdown_page_markers(markdown: str, expected_pages: int, source_name: str) -> None:
    observed = [int(value) for value in re.findall(r"^## PDF 第 (\d+) 页$", markdown, re.MULTILINE)]
    expected = list(range(1, expected_pages + 1))
    if observed != expected:
        raise RuntimeError(
            f"Refusing incomplete or misaligned Markdown for {source_name}: "
            f"expected {expected_pages} sequential page markers; got {len(observed)} markers "
            f"(first mismatch details: {observed[:12]})."
        )


def inspect_one_page(
    pdf: Path,
    page_number: int,
    language: str = "zh-Hans-CN",
    output_prefix: Path | None = None,
) -> int:
    reader = PdfReader(str(pdf), strict=False)
    if page_number < 1 or page_number > len(reader.pages):
        raise ValueError(f"Page must be between 1 and {len(reader.pages)}.")
    if output_prefix is None:
        work_tmp = REPO_ROOT / "tmp" / "pdfs" / "ocr-inspect"
        work_tmp.mkdir(parents=True, exist_ok=True)
        prefix = work_tmp / "sample"
    else:
        output_prefix = output_prefix.resolve()
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix = output_prefix
    image = render_one_page(pdf, page_number, prefix)
    started = time.perf_counter()
    try:
        client = make_ocr_client(language, REPO_ROOT / "tmp" / "pdfs")
        try:
            startup_seconds = time.perf_counter() - started
            ocr_started = time.perf_counter()
            response = client.recognize(image, language)
            elapsed = time.perf_counter() - ocr_started
            recognized_text = str(response.get("text") or "")
            response["cleaned_text_preview"] = clean_page_text(recognized_text)[:1200]
            response["text_diagnostics"] = {
                "characters": len(recognized_text),
                "cjk_characters": sum("\u3400" <= char <= "\u9fff" for char in recognized_text),
                "replacement_characters": recognized_text.count("\ufffd"),
                "spaces_between_cjk": len(re.findall(r"[\u3400-\u9fff] [\u3400-\u9fff]", recognized_text)),
            }
            report = {
                "pdf": str(pdf),
                "page": page_number,
                "page_count": len(reader.pages),
                "native_characters": len(reader.pages[page_number - 1].extract_text() or ""),
                "ocr_seconds": round(elapsed, 3),
                "helper_startup_seconds": round(startup_seconds, 3),
                "language": language,
                "available_languages": client.ready.get("available_languages", []),
                "ocr": response,
            }
            if output_prefix is not None:
                cleaned_text = clean_page_text(recognized_text)
                report["saved_image"] = str(image)
                report["saved_raw_text"] = str(output_prefix.with_suffix(".raw.txt"))
                report["saved_cleaned_text"] = str(output_prefix.with_suffix(".cleaned.txt"))
                output_prefix.with_suffix(".raw.txt").write_text(recognized_text + "\n", encoding="utf-8", newline="\n")
                output_prefix.with_suffix(".cleaned.txt").write_text(cleaned_text + "\n", encoding="utf-8", newline="\n")
                output_prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(json.dumps(report, ensure_ascii=True, indent=2))
        finally:
            client.close()
    finally:
        if output_prefix is None:
            image.unlink(missing_ok=True)
    return 0


def subject_ocr_languages(pdf: Path) -> tuple[str, list[str], str | None]:
    title = pdf.stem
    if "日语" in title or "日文" in title:
        return (
            "zh-Hans-CN",
            ["ja"],
            "中文主体使用zh-Hans-CN；ja模型对中文正文误识较多，仅追加含假名的行；日文汉字行仍需原图复核。",
        )
    if "俄语" in title:
        return (
            "zh-Hans-CN",
            ["tesseract:rus+chi_sim"],
            "中文主体使用zh-Hans-CN；仅追加西里尔字母占比较高的Tesseract行；俄文重音、近形字与混排需对照原图。",
        )
    if "英语" in title:
        return (
            "zh-Hans-CN",
            ["tesseract:eng+chi_sim"],
            "中文主体使用zh-Hans-CN；仅追加拉丁字母占比较高的Tesseract行；英文拼写、大小写与标点仍需原图复核。",
        )
    return "zh-Hans-CN", [], None


def cached_ocr_result(
    cache: dict[str, dict[str, Any]],
    pdf_sha: str,
    page: int,
    language: str,
) -> tuple[dict[str, Any] | None, str | None]:
    for renderer in ("poppler", "pdfium"):
        result = ocr_cache_lookup(cache, pdf_sha, page, language, renderer)
        if result is not None:
            return result, renderer
    return None, None


def language_supplement_label(language: str) -> str:
    if language == "ja":
        return "日文"
    if "rus" in language:
        return "俄文"
    if "eng" in language:
        return "英文"
    return "外文"


def extract_supplement_lines(text: str, language: str) -> list[str]:
    selected: list[str] = []
    if language == "ja":
        pattern = re.compile(r"[ぁ-ゟ゠-ヿ]")
        for line in text.splitlines():
            if len(pattern.findall(line)) >= 2:
                selected.append(clean_page_text(line).strip())
        return [line for line in selected if line]

    for line in text.splitlines():
        letters = [char for char in line if char.isalpha()]
        if not letters:
            continue
        if "rus" in language:
            foreign = [char for char in letters if 0x0400 <= ord(char) <= 0x052F]
        elif "eng" in language:
            foreign = [char for char in letters if char.isascii() and char.isalpha()]
        else:
            continue
        ratio = len(foreign) / len(letters)
        if len(foreign) >= 3 and ratio >= 0.45:
            selected.append(clean_page_text(line).strip())
    return [line for line in selected if line]


def load_visual_corrections(output_root: Path) -> dict[str, dict[str, dict[str, str]]]:
    """Load page-level transcriptions confirmed against source-page images."""
    corrections: dict[str, dict[str, dict[str, str]]] = {}
    for filename in ("ocr-corrections.json", "ocr-corrections-extra.json"):
        path = output_root / filename
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for pdf_sha, document in payload.get("documents", {}).items():
            pages = document.get("pages", {})
            for page_key, correction in pages.items():
                text = correction.get("text")
                reason = correction.get("reason")
                if not isinstance(text, str) or not text.strip() or not isinstance(reason, str) or not reason.strip():
                    raise ValueError(f"Invalid visual OCR correction in {path.name} for {pdf_sha} page {page_key}.")
                page_number = str(int(page_key))
                candidate = {"text": text, "reason": reason, "source": filename}
                if correction.get("status") == "uncertain":
                    candidate.update({"status": "uncertain", "issues": correction.get("issues", [])})
                existing = corrections.setdefault(pdf_sha, {}).get(page_number)
                if existing is not None and existing["text"] != candidate["text"]:
                    raise ValueError(
                        f"Conflicting visual OCR corrections for PDF {pdf_sha} page {page_number} "
                        f"in {existing['source']} and {filename}."
                    )
                corrections[pdf_sha][page_number] = candidate
    return corrections


def convert(args: argparse.Namespace) -> int:
    source_root = Path(args.source_root).resolve()
    output_root = Path(args.output_root).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source root does not exist: {source_root}")
    pdfs = sorted(source_root.rglob("*.pdf"))
    if args.only:
        filters = [part.casefold() for part in args.only]
        pdfs = [pdf for pdf in pdfs if any(part in pdf.as_posix().casefold() for part in filters)]
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found under {source_root}")

    temp_root = REPO_ROOT / "tmp" / "pdfs"
    cache_path = Path(args.ocr_cache).resolve() if args.ocr_cache else temp_root / "ocr-cache.jsonl"
    cache = cache_read(cache_path)
    temp_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "conversion-manifest.json"
    manifest: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root_relative": "docs/standards" if source_root.name == "standards" else source_root.name,
        "output_root_relative": output_root.relative_to(REPO_ROOT).as_posix() if output_root.is_relative_to(REPO_ROOT) else output_root.name,
        "conversion_tool": "scripts/convert_standards.py",
        "pypdf_version": PYPDF_VERSION,
        "ocr_engine": "Windows.Media.Ocr + Tesseract.js (selected by document language)",
        "run_status": "running",
        "ocr_render": {
            "dpi": OCR_DPI,
            "scale_to_max_dimension": OCR_SCALE_TO,
            "windows_media_format": "TIFF, no compression",
            "tesseract_format": "PNG",
            "render_chunk_pages": OCR_RENDER_CHUNK_PAGES,
            "qa_sample_format": "PNG",
        },
        "visual_correction_sources": [
            filename for filename in ("ocr-corrections.json", "ocr-corrections-extra.json")
            if (output_root / filename).is_file()
        ],
        "documents": [],
    }
    visual_corrections = load_visual_corrections(output_root)
    manifest["visual_correction_page_count"] = sum(len(pages) for pages in visual_corrections.values())

    ocr_clients: dict[str, Any] = {}
    current_pdf: Path | None = None
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    try:
        for pdf_index, pdf in enumerate(pdfs, 1):
            current_pdf = pdf
            relative_pdf = pdf.relative_to(source_root)
            relative_output = relative_pdf.with_suffix(".md")
            output_path = output_root / relative_output
            pdf_sha = sha256_file(pdf)
            reader = PdfReader(str(pdf), strict=False)
            total_pages = len(reader.pages)
            page_records: list[dict[str, Any]] = []
            ocr_pages: list[int] = []
            source_text_pages: list[int] = []
            issues: list[dict[str, Any]] = []
            primary_language, supplement_languages, language_limitation = subject_ocr_languages(pdf)
            all_ocr_languages = [primary_language, *supplement_languages]
            render_dir = temp_root / f"render-{pdf_sha[:16]}"
            for page_index, page in enumerate(reader.pages, 1):
                raw_text = page.extract_text() or ""
                cleaned = clean_page_text(raw_text)
                if compact_length(cleaned) < SHORT_PAGE_THRESHOLD:
                    ocr_pages.append(page_index)
                else:
                    source_text_pages.append(page_index)
                    page_records.append(
                        {
                            "page": page_index,
                            "text": cleaned,
                            "extraction": "pypdf",
                            "raw_abnormal_characters": abnormal_counts(raw_text),
                        }
                    )
            # Place OCR-needed pages in their exact slots while preserving original reading order.
            by_page = {record["page"]: record for record in page_records}
            document_corrections = visual_corrections.get(pdf_sha, {})
            for page_key, correction in document_corrections.items():
                page_number = int(page_key)
                if not 1 <= page_number <= total_pages:
                    raise ValueError(f"Visual correction outside PDF: {relative_pdf.as_posix()}, {page_number}.")
                record = by_page.setdefault(page_number, {"page": page_number})
                record.update({
                    "text": clean_page_text(correction["text"]),
                    "extraction": "visual_transcription",
                    "visual_correction_applied": True,
                    "visual_correction_reason": correction["reason"],
                    "visual_correction_source": correction["source"],
                    "visual_review_status": correction.get("status", "checked"),
                    "visual_review_issues": correction.get("issues", []),
                })
            pages_needing_ocr = [n for n in ocr_pages if str(n) not in document_corrections]
            uncached_ocr_pages = [
                page_number
                for page_number in pages_needing_ocr
                if any(cached_ocr_result(cache, pdf_sha, page_number, language)[0] is None for language in all_ocr_languages)
            ]
            if uncached_ocr_pages:
                if render_dir.exists():
                    shutil.rmtree(render_dir)
                render_dir.mkdir(parents=True, exist_ok=True)
                prefix = render_dir / "page"
                image_format = "png" if any(language.startswith("tesseract:") for language in all_ocr_languages) else "tiff"
                try:
                    for offset in range(0, len(uncached_ocr_pages), OCR_RENDER_CHUNK_PAGES):
                        page_batch = uncached_ocr_pages[offset : offset + OCR_RENDER_CHUNK_PAGES]
                        images = render_pdf(pdf, prefix, page_batch, image_format=image_format)
                        for page_number in page_batch:
                            image = images.get(page_number)
                            if not image_is_valid(image):
                                raise RuntimeError(f"Missing rendered image for {relative_pdf.as_posix()} page {page_number}.")
                            renderer = "pdfium" if ".pdfium." in image.name else "poppler"
                            for language in all_ocr_languages:
                                cached, _cached_renderer = cached_ocr_result(cache, pdf_sha, page_number, language)
                                if cached is not None:
                                    continue
                                client = ocr_clients.get(language)
                                if client is None:
                                    client = make_ocr_client(language, temp_root)
                                    ocr_clients[language] = client
                                    manifest.setdefault("ocr_backends", {})[language] = client.ready
                                try:
                                    result = client.recognize(image, language)
                                except Exception as exc:
                                    raise RuntimeError(
                                        f"OCR failed for {relative_pdf.as_posix()} page {page_number} "
                                        f"with {language}: {exc}"
                                    ) from exc
                                result["renderer"] = renderer
                                key = ocr_cache_key(pdf_sha, page_number, language, renderer)
                                cache[key] = result
                                cache_append(cache_path, key, result)
                            image.unlink(missing_ok=True)
                finally:
                    if render_dir.exists():
                        shutil.rmtree(render_dir)

            for page_number in pages_needing_ocr:
                primary_result, primary_renderer = cached_ocr_result(cache, pdf_sha, page_number, primary_language)
                if primary_result is None:
                    raise RuntimeError(f"OCR cache is missing {relative_pdf.as_posix()} page {page_number} in {primary_language}.")
                primary_text = clean_page_text(str(primary_result.get("text") or ""))
                raw_text_parts = [str(primary_result.get("text") or "")]
                fallback_attempted = False
                if compact_length(primary_text) < SHORT_PAGE_THRESHOLD:
                    fallback_attempted = True
                    fallback_result = ocr_cache_lookup(cache, pdf_sha, page_number, primary_language, "pdfium")
                    if fallback_result is None:
                        if not render_dir.exists():
                            render_dir.mkdir(parents=True, exist_ok=True)
                        fallback_format = "png" if any(language.startswith("tesseract:") for language in all_ocr_languages) else "tiff"
                        fallback_image = render_pdfium_page(
                            pdf,
                            page_number,
                            render_dir / f"page-{page_number}.pdfium",
                            fallback_format,
                        )
                        client = ocr_clients.get(primary_language)
                        if client is None:
                            client = make_ocr_client(primary_language, temp_root)
                            ocr_clients[primary_language] = client
                            manifest.setdefault("ocr_backends", {})[primary_language] = client.ready
                        try:
                            fallback_result = client.recognize(fallback_image, primary_language)
                        except Exception as exc:
                            raise RuntimeError(
                                f"PDFium fallback OCR failed for {relative_pdf.as_posix()} page {page_number}: {exc}"
                            ) from exc
                        fallback_result["renderer"] = "pdfium"
                        fallback_key = ocr_cache_key(pdf_sha, page_number, primary_language, "pdfium")
                        cache[fallback_key] = fallback_result
                        cache_append(cache_path, fallback_key, fallback_result)
                        fallback_image.unlink(missing_ok=True)
                    fallback_text = clean_page_text(str(fallback_result.get("text") or ""))
                    if compact_length(fallback_text) > compact_length(primary_text):
                        primary_result = fallback_result
                        primary_text = fallback_text
                        primary_renderer = "pdfium"

                source_results: list[dict[str, Any]] = [
                    {
                        "engine": ocr_engine_name(primary_result),
                        "language": primary_result.get("language", primary_language),
                        "renderer": primary_renderer,
                        "confidence_available": primary_result.get("confidence_available", False),
                        "average_word_confidence": primary_result.get("average_word_confidence"),
                        "text_characters": len(str(primary_result.get("text") or "")),
                        "supplement_lines": 0,
                    }
                ]
                supplement_blocks: list[str] = []
                for language in supplement_languages:
                    supplement_result, supplement_renderer = cached_ocr_result(cache, pdf_sha, page_number, language)
                    if supplement_result is None:
                        raise RuntimeError(f"OCR cache is missing {relative_pdf.as_posix()} page {page_number} in {language}.")
                    raw_supplement = str(supplement_result.get("text") or "")
                    raw_text_parts.append(raw_supplement)
                    lines = extract_supplement_lines(raw_supplement, language)
                    if lines:
                        label = language_supplement_label(language)
                        supplement_blocks.append(f"### {label}补充OCR（外语行候选，需对照原图）\n" + "\n".join(lines))
                    source_results.append(
                        {
                            "engine": ocr_engine_name(supplement_result),
                            "language": supplement_result.get("language", language),
                            "renderer": supplement_renderer,
                            "confidence_available": supplement_result.get("confidence_available", False),
                            "average_word_confidence": supplement_result.get("average_word_confidence"),
                            "text_characters": len(raw_supplement),
                            "supplement_lines": len(lines),
                        }
                    )
                recognized_text = primary_text
                if supplement_blocks:
                    recognized_text = "\n\n".join([primary_text, *supplement_blocks]).strip()
                visual_correction = visual_corrections.get(pdf_sha, {}).get(str(page_number))
                if visual_correction is not None:
                    recognized_text = clean_page_text(visual_correction["text"])
                by_page[page_number] = {
                    "page": page_number,
                    "text": recognized_text,
                    "extraction": ("tesseract_js" if ocr_engine_name(primary_result) == "Tesseract.js" else "windows_media_ocr") if primary_text else "ocr_empty",
                    "ocr_engine": ocr_engine_name(primary_result),
                    "ocr_language": primary_result.get("language", primary_language),
                    "ocr_languages": [source["language"] for source in source_results],
                    "ocr_sources": source_results,
                    "ocr_confidence_available": any(source["confidence_available"] for source in source_results),
                    "ocr_confidence": min(
                        (source["average_word_confidence"] for source in source_results if source["average_word_confidence"] is not None),
                        default=None,
                    ),
                    "ocr_word_count": primary_result.get("word_count"),
                    "ocr_render_backend": primary_renderer,
                    "ocr_fallback_attempted": fallback_attempted,
                    "ocr_fallback_used": primary_renderer == "pdfium",
                    "visual_correction_applied": visual_correction is not None,
                    "visual_correction_reason": visual_correction["reason"] if visual_correction else None,
                    "visual_correction_source": visual_correction["source"] if visual_correction else None,
                    "raw_abnormal_characters": abnormal_counts("\n".join(raw_text_parts)),
                }

            # Rebuild the ordered page list from the page-number map so native
            # text pages are included exactly once alongside OCR pages.
            page_records = []
            for page_number in range(1, total_pages + 1):
                record = by_page.get(page_number)
                if record is None:
                    raise RuntimeError(f"Missing page record for {relative_pdf.as_posix()} page {page_number}.")
                abnormal = abnormal_counts(record["text"])
                raw_abnormal = record.get("raw_abnormal_characters", abnormal)
                nonspace_chars = compact_length(record["text"])
                record.update(
                    {
                        "characters": len(record["text"]),
                        "non_whitespace_characters": nonspace_chars,
                        "empty": nonspace_chars == 0,
                        "too_short": 0 < nonspace_chars < SHORT_PAGE_THRESHOLD,
                        "raw_abnormal_characters": raw_abnormal,
                        **abnormal,
                    }
                )
                if nonspace_chars == 0:
                    issues.append({"type": "empty_page", "page": page_number})
                elif record["too_short"]:
                    issues.append({"type": "too_short_page", "page": page_number, "characters": nonspace_chars})
                if any(raw_abnormal.values()) or any(abnormal.values()):
                    issues.append({"type": "abnormal_characters", "page": page_number, "raw": raw_abnormal, "cleaned": abnormal})
                if record.get("ocr_confidence") is not None and record["ocr_confidence"] < 0.55:
                    issues.append({"type": "low_ocr_confidence", "page": page_number, "average_word_confidence": record["ocr_confidence"]})
                if record.get("visual_review_status") == "uncertain":
                    issues.append({"type": "visual_uncertain", "page": page_number, "details": record.get("visual_review_issues", [])})
                page_records.append(record)
            page_records.sort(key=lambda record: record["page"])

            seen_pages = [record["page"] for record in page_records]
            sequence_ok = seen_pages == list(range(1, total_pages + 1))
            if not sequence_ok:
                issues.append({"type": "page_sequence_error", "observed": seen_pages})
                raise RuntimeError(
                    f"Refusing to write {output_path}: page records do not align with {total_pages} PDF pages."
                )
            if not any(record["non_whitespace_characters"] for record in page_records):
                raise RuntimeError(f"Refusing to write wholly empty OCR output for {relative_pdf.as_posix()}.")
            tools_used = [f"pypdf {PYPDF_VERSION}"] if source_text_pages else []
            ocr_sources = [
                source
                for record in page_records
                for source in record.get("ocr_sources", [])
            ]
            ocr_tool_pairs = sorted({(source["engine"], source["language"]) for source in ocr_sources})
            for engine_name, language_name in ocr_tool_pairs:
                image_type = "PNG" if engine_name == "Tesseract.js" else "TIFF, no compression"
                tools_used.append(f"{engine_name} {language_name} ({image_type}, {OCR_DPI} dpi, max {OCR_SCALE_TO}px)")
            if document_corrections:
                tools_used.append("源页图像目视转写校订（ocr-corrections.json）")
            markdown = build_markdown(pdf, relative_pdf.as_posix(), pdf_sha, page_records, tools_used)
            validate_markdown_page_markers(markdown, total_pages, relative_pdf.as_posix())
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(markdown, encoding="utf-8", newline="\n")
            validate_markdown_page_markers(output_path.read_text(encoding="utf-8"), total_pages, relative_pdf.as_posix())
            samples, sample_reasons = sample_pages(page_records)
            qa_artifacts = write_qa_samples(pdf, relative_pdf, page_records, samples, temp_root)
            document = {
                "source_pdf": relative_pdf.as_posix(),
                "markdown": relative_output.as_posix(),
                "pdf_sha256": pdf_sha,
                "total_pages": total_pages,
                "markdown_characters": len(markdown),
                "text_characters": sum(record["characters"] for record in page_records),
                "source_text_pages": source_text_pages,
                "ocr_pages": ocr_pages,
                "ocr_languages": sorted({source["language"] for source in ocr_sources}),
                "ocr_engines": sorted({source["engine"] for source in ocr_sources}),
                "visual_correction_pages": [record["page"] for record in page_records if record.get("visual_correction_applied")],
                "language_limitation": language_limitation,
                "empty_pages": [record["page"] for record in page_records if record["empty"]],
                "too_short_pages": [record["page"] for record in page_records if record["too_short"]],
                "replacement_character_count": sum(record["replacement_characters"] for record in page_records),
                "private_use_character_count": sum(record["private_use_characters"] for record in page_records),
                "suspicious_placeholder_runs": sum(record["suspicious_placeholder_runs"] for record in page_records),
                "page_sequence_ok": sequence_ok,
                "quality_samples": samples,
                "quality_sample_reasons": sample_reasons,
                "quality_sample_status": "原图和清理后OCR文本已保存；转换器未做人工视觉判定",
                "qa_sample_artifacts": qa_artifacts,
                "issues": issues,
                "pages": [{key: value for key, value in record.items() if key != "text"} for record in page_records],
            }
            manifest["documents"].append(document)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(
                f"[{pdf_index}/{len(pdfs)}] {relative_pdf.as_posix()}: "
                f"{total_pages} pages, {len(source_text_pages)} pypdf, {len(ocr_pages)} OCR, "
                f"{len(document['empty_pages'])} empty; {output_path}",
                flush=True,
            )
    finally:
        for ocr_client in ocr_clients.values():
            ocr_client.close()
        exc_type, exc, _ = sys.exc_info()
        if exc is not None:
            manifest["run_status"] = "failed"
            manifest["failed_source_pdf"] = current_pdf.relative_to(source_root).as_posix() if current_pdf else None
            manifest["failure"] = str(exc)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    output_root.mkdir(parents=True, exist_ok=True)
    manifest["run_status"] = "complete"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    total_pages = sum(item["total_pages"] for item in manifest["documents"])
    source_pages = sum(len(item["source_text_pages"]) for item in manifest["documents"])
    ocr_pages = sum(len(item["ocr_pages"]) for item in manifest["documents"])
    empty_pages = sum(len(item["empty_pages"]) for item in manifest["documents"])
    print(
        f"Manifest: {manifest_path}\n"
        f"Documents: {len(manifest['documents'])}; pages: {total_pages}; "
        f"pypdf pages: {source_pages}; OCR pages: {ocr_pages}; empty pages: {empty_pages}",
        flush=True,
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT), help="PDF root; input directory names are preserved in outputs.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Markdown and conversion-manifest.json output root.")
    parser.add_argument("--only", action="append", help="Optional path substring filter; may be repeated.")
    parser.add_argument("--ocr-cache", help="JSONL cache path; defaults to workspace tmp/pdfs/ocr-cache.jsonl.")
    parser.add_argument("--inspect-pdf", help="OCR one source page and print timing/quality JSON without writing Markdown.")
    parser.add_argument("--inspect-page", type=int, help="1-based page number used with --inspect-pdf.")
    parser.add_argument("--inspect-language", default="zh-Hans-CN", help="Installed WinRT OCR language for --inspect-pdf, e.g. zh-Hans-CN or ja.")
    parser.add_argument("--inspect-output-prefix", help="Save the rendered PNG and raw/cleaned OCR text under this prefix.")
    args = parser.parse_args()
    if args.inspect_pdf:
        if not args.inspect_page:
            parser.error("--inspect-page is required with --inspect-pdf")
    elif args.inspect_page:
        parser.error("--inspect-page requires --inspect-pdf")
    return args


if __name__ == "__main__":
    parsed = parse_args()
    if parsed.inspect_pdf:
        raise SystemExit(
            inspect_one_page(
                Path(parsed.inspect_pdf).resolve(),
                parsed.inspect_page,
                parsed.inspect_language,
                Path(parsed.inspect_output_prefix) if parsed.inspect_output_prefix else None,
            )
        )
    raise SystemExit(convert(parsed))
