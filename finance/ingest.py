"""Single entry point for turning a raw file into a stored Document and, for a letter with a
recognizable debt, a proposal row in the debt-overview Excel workbook (the source of truth for
debts - see finance/excel_store.py).

Used by both the manual upload view and the `sync_drive_folder` management command, so a
document is handled identically regardless of whether it arrived by drag-and-drop or by
showing up in the local Proton Drive folder.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from . import claude_extraction, excel_store, extraction
from .models import Document

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    document: Document
    created: bool
    duplicate: bool = False
    debt_proposal: claude_extraction.ExtractedDebt | None = None
    extraction_error: str | None = None


def ingest_bytes(content_bytes: bytes, original_filename: str, source: str) -> IngestResult:
    checksum = Document.checksum_for(content_bytes)
    existing = Document.objects.filter(checksum=checksum).first()
    if existing:
        if not existing.extraction_failed:
            return IngestResult(document=existing, created=False, duplicate=True)
        # A previous attempt errored out (e.g. no API credit) rather than actually deciding
        # this isn't a debt letter - retry instead of treating it as permanently done.
        debt_proposal, extraction_error = _process_document(existing)
        return IngestResult(
            document=existing,
            created=False,
            debt_proposal=debt_proposal,
            extraction_error=extraction_error,
        )

    doc_type = extraction.guess_doc_type(original_filename)
    document = Document(
        original_filename=original_filename,
        doc_type=doc_type,
        source=source,
        checksum=checksum,
    )
    document.file.save(original_filename, ContentFile(content_bytes), save=False)
    document.save()

    debt_proposal, extraction_error = _process_document(document)
    return IngestResult(
        document=document,
        created=True,
        debt_proposal=debt_proposal,
        extraction_error=extraction_error,
    )


def _process_document(document: Document):
    """Extracts text and, for a single-creditor letter (PDF/scan), asks Claude to pull out
    structured debt fields. A match is written to the Excel workbook as a "Vorschlag (KI)" row
    that a human confirms on the dashboard before it counts as a real debt. Excel/overview
    files are never auto-parsed (they're multi-row summaries, not single letters)."""
    file_path = Path(document.file.path)
    text = extraction.extract_text(file_path, document.doc_type)
    document.extracted_text = text

    debt_proposal = None
    extraction_error = None
    document.extraction_failed = False
    if document.doc_type in (Document.DocType.PDF, Document.DocType.IMAGE):
        try:
            debt_proposal = claude_extraction.extract_debt_fields_with_ai(text)
        except claude_extraction.ExtractionError as exc:
            extraction_error = str(exc)
            document.extraction_failed = True
            logger.warning("KI-Extraktion fehlgeschlagen für %s: %s", document.original_filename, exc)

        if debt_proposal is not None and debt_proposal.amount is not None:
            row = excel_store.DebtRow(
                id=document.checksum,
                detected_at=excel_store.today_str(),
                creditor_name=debt_proposal.creditor_name,
                collection_agency=debt_proposal.collection_agency,
                category=debt_proposal.category,
                amount=debt_proposal.amount,
                open_amount=debt_proposal.amount,
                due_date=excel_store.format_date(debt_proposal.due_date),
                reference=debt_proposal.reference,
                status=excel_store.STATUS_PROPOSAL,
                summary=debt_proposal.summary,
                source_document=document.original_filename,
            )
            excel_store.upsert_row(settings.DEBT_EXCEL_EXPORT_PATH, row)
        else:
            debt_proposal = None

    document.processed_at = timezone.now()
    document.save()
    return debt_proposal, extraction_error
