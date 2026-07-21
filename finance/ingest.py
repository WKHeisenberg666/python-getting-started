"""Single entry point for turning a raw file into Document + Debt records.

Used by both the manual upload view and the `sync_drive_folder` management
command, so a document is handled identically regardless of whether it
arrived by drag-and-drop or by showing up in the local Proton Drive folder.
"""

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from . import extraction
from .excel_export import append_debt_row
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
    file_path = Path(document.file.path)
    text = extraction.extract_text(file_path, document.doc_type)
    document.extracted_text = text

    debt = None
    # The "biggest amount / first text line" heuristic only makes sense for a single-creditor
    # letter (PDF/scan). Excel files in the drive folder are typically multi-row overviews or
    # summary exports - running the same heuristic on them picks up grand totals as if they
    # were one debt. So Excel documents are stored for reference only, never auto-parsed.
    fields = (
        extraction.parse_debt_fields(text, document.original_filename)
        if document.doc_type != Document.DocType.EXCEL
        else {"amount": None}
    )
    if fields["amount"] is not None:
        creditor, _ = Creditor.objects.get_or_create(name=fields["creditor_name"])
        debt = Debt.objects.create(
            creditor=creditor,
            amount=fields["amount"],
            due_date=fields["due_date"],
            reference=fields["reference"],
            source_document=document,
            description=f"Automatisch erfasst aus {document.original_filename}",
        )
        document.debt = debt
        try:
            append_debt_row(Path(settings.DEBT_EXCEL_EXPORT_PATH), debt)
        except Exception:
            # The Excel export is a convenience mirror of the DB; never let it block ingestion.
            pass

    document.processed_at = timezone.now()
    document.save()
    return debt
