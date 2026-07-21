"""Single entry point for turning a raw file into Document + Debt records.

Used by both the manual upload view and the `sync_drive_folder` management
command, so a document is handled identically regardless of whether it
arrived by drag-and-drop or by showing up in the local Proton Drive folder.
"""

from dataclasses import dataclass
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from . import extraction
from .models import Debt, Document


@dataclass
class IngestResult:
    document: Document
    debt: Debt | None
    created: bool
    duplicate: bool = False


def ingest_bytes(content_bytes: bytes, original_filename: str, source: str) -> IngestResult:
    checksum = Document.checksum_for(content_bytes)
    existing = Document.objects.filter(checksum=checksum).first()
    if existing:
        return IngestResult(document=existing, debt=existing.debt, created=False, duplicate=True)

    doc_type = extraction.guess_doc_type(original_filename)
    document = Document(
        original_filename=original_filename,
        doc_type=doc_type,
        source=source,
        checksum=checksum,
    )
    document.file.save(original_filename, ContentFile(content_bytes), save=False)
    document.save()

    debt = _process_document(document)
    return IngestResult(document=document, debt=debt, created=True)


def _process_document(document: Document) -> Debt | None:
    """Extracts and stores text for the document, but never auto-creates a Debt.

    An earlier version guessed "creditor = first text line, amount = biggest number" and
    created a Debt straight away. On real photographed letters (skewed, noisy OCR) that
    heuristic produced wrong creditors and wrong amounts often enough that it's not
    trustworthy without a human looking at it first. Debts are created manually (e.g. via
    /admin/) after reviewing the extracted text below.
    """
    file_path = Path(document.file.path)
    document.extracted_text = extraction.extract_text(file_path, document.doc_type)
    document.processed_at = timezone.now()
    document.save()
    return None
