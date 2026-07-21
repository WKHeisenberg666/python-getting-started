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


_AMOUNT_NUMBER = r"([0-9]{1,3}(?:[.\s][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})"

_AMOUNT_RE = re.compile(
    rf"(?:EUR|€)\s*{_AMOUNT_NUMBER}|{_AMOUNT_NUMBER}\s*(?:EUR|€)"
)

# Amounts near one of these words are much more likely to be *the* debt total than an
# arbitrary number on the page (fees, interest rates, case numbers, ...).
_LABELED_AMOUNT_RE = re.compile(
    r"(?:Gesamtbetrag|Gesamtforderung|Gesamtsumme|Restschuld|Zahlbetrag|Forderungssumme|"
    r"Rechnungsbetrag|zu\s*zahlen(?:der\s*Betrag)?)\D{0,25}" + _AMOUNT_NUMBER,
    re.IGNORECASE,
)

_DATE_RE = re.compile(r"\b([0-3]?[0-9])\.([0-1]?[0-9])\.(\d{4})\b")

_REFERENCE_RE = re.compile(
    r"(?:Aktenzeichen|Kundennummer|Referenz(?:nummer)?|Vertragsnummer)\s*[:.]?\s*([A-Za-z0-9\-/]+)",
    re.IGNORECASE,
)


def _to_decimal(raw: str) -> Decimal | None:
    normalized = raw.replace(".", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def parse_amount(text: str) -> Decimal | None:
    """Prefers an amount explicitly labeled as the total (Gesamtbetrag/Restschuld/...),
    since letters often mention several numbers (fees, case numbers, partial amounts).
    Falls back to the largest EUR-formatted number on the page if no label matches."""
    labeled = [
        d for d in (_to_decimal(m.group(1)) for m in _LABELED_AMOUNT_RE.finditer(text)) if d
    ]
    if labeled:
        return max(labeled)

    candidates = []
    for match in _AMOUNT_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        decimal_value = _to_decimal(raw)
        if decimal_value is not None:
            candidates.append(decimal_value)
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


_ORG_MARKERS = (
    "gmbh", "ag", "kg", "e.v.", "inkasso", "amtsgericht", "versicherung", "bank",
    "kasse", "behörde", "gericht", "gläubiger", "rechtsanwalt", "rechtsanwälte",
)


def _looks_like_a_name(line: str) -> bool:
    """Filters out OCR noise/labels: needs to be reasonably long and mostly letters,
    not a bare label like "Aktenzeichen:" or a fragment of punctuation/digits."""
    if len(line) < 5:
        return False
    letters = sum(char.isalpha() for char in line)
    if letters / len(line) < 0.6:
        return False
    if line.rstrip().endswith(":"):
        return False
    return True


def guess_creditor_name(text: str, fallback_filename: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidate_lines = lines[:10]

    for line in candidate_lines:
        if _looks_like_a_name(line) and any(marker in line.lower() for marker in _ORG_MARKERS):
            return line[:200]

    for line in candidate_lines:
        if _looks_like_a_name(line) and not line[0].isdigit():
            return line[:200]

    return Path(fallback_filename).stem[:200]


def parse_debt_fields(text: str, fallback_filename: str) -> dict:
    return {
        "creditor_name": guess_creditor_name(text, fallback_filename),
        "amount": parse_amount(text),
        "due_date": parse_due_date(text),
        "reference": parse_reference(text),
    }
