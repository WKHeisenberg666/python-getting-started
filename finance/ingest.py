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
from .models import Creditor, Debt, Document


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
    """Extracts text and, for a single-creditor letter (PDF/scan), creates a draft Debt.

    The heuristic ("amount labeled as total, else biggest number" / "first name-like line")
    isn't reliable enough on real, noisy scans to trust blindly - so any Debt it creates is
    marked needs_review=True and excluded from dashboard totals until a human confirms it.
    Excel overview/backup files are structurally different (many rows, grand totals) and are
    never auto-parsed into a single debt at all.
    """
    file_path = Path(document.file.path)
    text = extraction.extract_text(file_path, document.doc_type)
    document.extracted_text = text

    debt = None
    if document.doc_type in (Document.DocType.PDF, Document.DocType.IMAGE):
        fields = extraction.parse_debt_fields(text, document.original_filename)
        if fields["amount"] is not None:
            creditor, _ = Creditor.objects.get_or_create(name=fields["creditor_name"])
            debt = Debt.objects.create(
                creditor=creditor,
                amount=fields["amount"],
                due_date=fields["due_date"],
                reference=fields["reference"],
                source_document=document,
                description=f"Automatisch erkannt aus {document.original_filename} – bitte prüfen",
                needs_review=True,
            )
            document.debt = debt

    document.processed_at = timezone.now()
    document.save()
    return debt
