"""Turns a scanned letter (PDF/JPG/PNG) or an Excel row into structured debt data.

This is a best-effort heuristic parser, not a real document-understanding model:
it looks for common German "Forderung/Betrag/Aktenzeichen" patterns. Extracted
values should be treated as a draft that a human reviews on the dashboard, not
as ground truth.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Document

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
PDF_EXTENSIONS = {".pdf"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}


def guess_doc_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in PDF_EXTENSIONS:
        return Document.DocType.PDF
    if ext in IMAGE_EXTENSIONS:
        return Document.DocType.IMAGE
    if ext in EXCEL_EXTENSIONS:
        return Document.DocType.EXCEL
    return Document.DocType.OTHER


def extract_text(path: Path, doc_type: str) -> str:
    """Best-effort text extraction. Returns "" if the required library/binary
    is missing instead of raising, so ingestion still creates a Document that
    a human can review manually."""
    try:
        if doc_type == Document.DocType.PDF:
            return _extract_pdf_text(path)
        if doc_type == Document.DocType.IMAGE:
            return _extract_image_text(path)
        if doc_type == Document.DocType.EXCEL:
            return _extract_excel_text(path)
    except Exception:
        return ""
    return ""


def _extract_pdf_text(path: Path) -> str:
    import pdfplumber

    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def _extract_image_text(path: Path) -> str:
    import pytesseract
    from PIL import Image

    with Image.open(path) as img:
        return pytesseract.image_to_string(img, lang="deu+eng")


def _extract_excel_text(path: Path) -> str:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    lines = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


_AMOUNT_RE = re.compile(
    r"(?:EUR|€)\s*([0-9]{1,3}(?:[.\s][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})"
    r"|([0-9]{1,3}(?:[.\s][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|€)"
)

_DATE_RE = re.compile(r"\b([0-3]?[0-9])\.([0-1]?[0-9])\.(\d{4})\b")

_REFERENCE_RE = re.compile(
    r"(?:Aktenzeichen|Kundennummer|Referenz(?:nummer)?|Vertragsnummer)\s*[:.]?\s*([A-Za-z0-9\-/]+)",
    re.IGNORECASE,
)


def parse_amount(text: str) -> Decimal | None:
    """Picks the largest EUR amount mentioned near a currency symbol, since
    letters usually also mention smaller fees/rates before the total."""
    candidates = []
    for match in _AMOUNT_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        normalized = raw.replace(".", "").replace(" ", "").replace(",", ".")
        try:
            candidates.append(Decimal(normalized))
        except InvalidOperation:
            continue
    if not candidates:
        return None
    return max(candidates)


def parse_due_date(text: str):
    match = _DATE_RE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).date()
    except ValueError:
        return None


def parse_reference(text: str) -> str:
    match = _REFERENCE_RE.search(text)
    return match.group(1).strip() if match else ""


def guess_creditor_name(text: str, fallback_filename: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 3 and not line[0].isdigit():
            return line[:200]
    return Path(fallback_filename).stem[:200]


def parse_debt_fields(text: str, fallback_filename: str) -> dict:
    return {
        "creditor_name": guess_creditor_name(text, fallback_filename),
        "amount": parse_amount(text),
        "due_date": parse_due_date(text),
        "reference": parse_reference(text),
    }
