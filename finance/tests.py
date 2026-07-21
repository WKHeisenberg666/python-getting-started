import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase

from . import excel_store, extraction, ingest, reconciliation
from .claude_extraction import ExtractedDebt
from .models import Account, BankTransaction, Document


class ExtractionHelperTests(TestCase):
    def test_guess_doc_type(self):
        self.assertEqual(extraction.guess_doc_type("brief.pdf"), Document.DocType.PDF)
        self.assertEqual(extraction.guess_doc_type("scan.jpg"), Document.DocType.IMAGE)
        self.assertEqual(extraction.guess_doc_type("liste.xlsx"), Document.DocType.EXCEL)


class ExcelStoreTests(TestCase):
    def test_upsert_then_read_round_trips_a_row(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "schulden.xlsx"
            row = excel_store.DebtRow(
                id="abc123",
                creditor_name="Amtsgericht Hagen",
                amount=Decimal("228.93"),
                open_amount=Decimal("228.93"),
                status=excel_store.STATUS_PROPOSAL,
            )
            excel_store.upsert_row(path, row)

            rows = excel_store.read_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["creditor_name"], "Amtsgericht Hagen")
            self.assertEqual(rows[0]["amount"], Decimal("228.93"))
            self.assertEqual(rows[0]["status"], excel_store.STATUS_PROPOSAL)

    def test_upsert_with_same_id_overwrites_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "schulden.xlsx"
            excel_store.upsert_row(path, excel_store.DebtRow(id="x", amount=Decimal("10")))
            excel_store.upsert_row(path, excel_store.DebtRow(id="x", amount=Decimal("20")))

            rows = excel_store.read_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["amount"], Decimal("20"))

    def test_update_row_changes_only_given_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "schulden.xlsx"
            excel_store.upsert_row(
                path,
                excel_store.DebtRow(id="x", creditor_name="Firma GmbH", amount=Decimal("50")),
            )
            excel_store.update_row(path, "x", status=excel_store.STATUS_OPEN)

            rows = excel_store.read_rows(path)
            self.assertEqual(rows[0]["status"], excel_store.STATUS_OPEN)
            self.assertEqual(rows[0]["creditor_name"], "Firma GmbH")

    def test_delete_row_removes_it(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "schulden.xlsx"
            excel_store.upsert_row(path, excel_store.DebtRow(id="x", amount=Decimal("50")))
            self.assertTrue(excel_store.delete_row(path, "x"))
            self.assertEqual(excel_store.read_rows(path), [])

    def test_delete_row_returns_false_when_not_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "schulden.xlsx"
            self.assertFalse(excel_store.delete_row(path, "missing"))


class IngestBytesTests(TestCase):
    @mock.patch("finance.ingest.claude_extraction.extract_debt_fields_with_ai")
    def test_pdf_with_recognized_debt_creates_a_proposal_row(self, mock_extract):
        mock_extract.return_value = ExtractedDebt(
            creditor_name="Amtsgericht Hagen",
            collection_agency="",
            category="Behörde",
            amount=Decimal("228.93"),
            due_date=None,
            reference="AZ-1",
            summary="Mahnbescheid.",
        )
        excel_path = str(Path(tempfile.mkdtemp()) / "s.xlsx")
        with self.settings(DEBT_EXCEL_EXPORT_PATH=excel_path):
            result = ingest.ingest_bytes(b"fake pdf bytes", "brief.pdf", Document.Source.MANUAL_UPLOAD)

            self.assertTrue(result.created)
            self.assertIsNotNone(result.debt_proposal)
            self.assertIsNone(result.extraction_error)

            rows = excel_store.read_rows(excel_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], excel_store.STATUS_PROPOSAL)
            self.assertEqual(rows[0]["creditor_name"], "Amtsgericht Hagen")

    @mock.patch("finance.ingest.claude_extraction.extract_debt_fields_with_ai")
    def test_text_not_a_debt_letter_creates_no_row(self, mock_extract):
        mock_extract.return_value = None
        with self.settings(DEBT_EXCEL_EXPORT_PATH=str(Path(tempfile.mkdtemp()) / "s.xlsx")):
            result = ingest.ingest_bytes(b"irrelevant", "foto.jpg", Document.Source.MANUAL_UPLOAD)
            self.assertTrue(result.created)
            self.assertIsNone(result.debt_proposal)

    @mock.patch("finance.ingest.claude_extraction.extract_debt_fields_with_ai")
    def test_extraction_error_is_reported_but_does_not_break_ingestion(self, mock_extract):
        from .claude_extraction import ExtractionError

        mock_extract.side_effect = ExtractionError("kein API-Key")
        with self.settings(DEBT_EXCEL_EXPORT_PATH=str(Path(tempfile.mkdtemp()) / "s.xlsx")):
            result = ingest.ingest_bytes(b"irrelevant", "brief.pdf", Document.Source.MANUAL_UPLOAD)
            self.assertTrue(result.created)
            self.assertIsNone(result.debt_proposal)
            self.assertEqual(result.extraction_error, "kein API-Key")

    def test_excel_file_is_never_sent_for_ai_extraction(self):
        with mock.patch("finance.ingest.claude_extraction.extract_debt_fields_with_ai") as mock_extract:
            result = ingest.ingest_bytes(b"PK\x03\x04fake", "uebersicht.xlsx", Document.Source.MANUAL_UPLOAD)
            mock_extract.assert_not_called()
            self.assertTrue(result.created)
            self.assertIsNone(result.debt_proposal)

    def test_duplicate_file_is_not_reingested(self):
        content = b"same bytes"
        first = ingest.ingest_bytes(content, "a.txt", Document.Source.MANUAL_UPLOAD)
        second = ingest.ingest_bytes(content, "a-renamed.txt", Document.Source.MANUAL_UPLOAD)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.document.id, second.document.id)
        self.assertEqual(Document.objects.count(), 1)


class ReconciliationTests(TestCase):
    def test_matching_transaction_marks_debt_paid(self):
        account = Account.objects.create(provider=Account.Provider.SPARKASSE, name="Girokonto")
        BankTransaction.objects.create(
            account=account,
            booking_date="2026-05-01",
            amount=Decimal("-228.93"),
            description="Zahlung an Amtsgericht Hagen AZ-1",
            external_id="tx-1",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "schulden.xlsx"
            excel_store.upsert_row(
                path,
                excel_store.DebtRow(
                    id="x",
                    creditor_name="Amtsgericht Hagen",
                    amount=Decimal("228.93"),
                    open_amount=Decimal("228.93"),
                    status=excel_store.STATUS_OPEN,
                ),
            )
            summary = reconciliation.reconcile_debts_with_transactions(path)
            self.assertEqual(summary["matched_debts"], 1)

            rows = excel_store.read_rows(path)
            self.assertEqual(rows[0]["status"], excel_store.STATUS_PAID)
            self.assertEqual(rows[0]["open_amount"], Decimal("0"))

    def test_proposal_rows_are_never_touched(self):
        account = Account.objects.create(provider=Account.Provider.SPARKASSE, name="Girokonto")
        BankTransaction.objects.create(
            account=account,
            booking_date="2026-05-01",
            amount=Decimal("-50.00"),
            description="Zahlung an Test GmbH",
            external_id="tx-1",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "schulden.xlsx"
            excel_store.upsert_row(
                path,
                excel_store.DebtRow(
                    id="x",
                    creditor_name="Test GmbH",
                    amount=Decimal("50.00"),
                    open_amount=Decimal("50.00"),
                    status=excel_store.STATUS_PROPOSAL,
                ),
            )
            reconciliation.reconcile_debts_with_transactions(path)
            rows = excel_store.read_rows(path)
            self.assertEqual(rows[0]["status"], excel_store.STATUS_PROPOSAL)

    def test_detect_fixed_costs_needs_at_least_two_distinct_months(self):
        account = Account.objects.create(provider=Account.Provider.SPARKASSE, name="Girokonto")
        BankTransaction.objects.create(
            account=account,
            booking_date="2026-04-01",
            amount=Decimal("-9.99"),
            description="Netflix",
            external_id="tx-1",
        )
        BankTransaction.objects.create(
            account=account,
            booking_date="2026-05-01",
            amount=Decimal("-9.99"),
            description="Netflix",
            external_id="tx-2",
        )
        BankTransaction.objects.create(
            account=account,
            booking_date="2026-05-15",
            amount=Decimal("-3.00"),
            description="Einmalkauf",
            external_id="tx-3",
        )
        fixed_costs = reconciliation.detect_fixed_costs()
        descriptions = [item["description"] for item in fixed_costs]
        self.assertIn("Netflix", descriptions)
        self.assertNotIn("Einmalkauf", descriptions)


class DashboardViewTests(TestCase):
    def test_dashboard_renders(self):
        with self.settings(DEBT_EXCEL_EXPORT_PATH=str(Path(tempfile.mkdtemp()) / "s.xlsx")):
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)

    def test_upload_page_renders(self):
        response = self.client.get("/upload/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_excludes_review_drafts_from_totals(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "s.xlsx"
            excel_store.upsert_row(
                path,
                excel_store.DebtRow(
                    id="x",
                    creditor_name="Draft GmbH",
                    amount=Decimal("500.00"),
                    status=excel_store.STATUS_PROPOSAL,
                ),
            )
            with self.settings(DEBT_EXCEL_EXPORT_PATH=str(path)):
                response = self.client.get("/")
                self.assertEqual(response.context["total_debt"], 0)
                self.assertEqual(len(response.context["review_debts"]), 1)
                self.assertContains(response, "Draft GmbH")


class DebtReviewViewTests(TestCase):
    def test_confirm_marks_row_as_open(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "s.xlsx"
            excel_store.upsert_row(
                path,
                excel_store.DebtRow(
                    id="row-1", creditor_name="Test GmbH", amount=Decimal("50"),
                    status=excel_store.STATUS_PROPOSAL,
                ),
            )
            with self.settings(DEBT_EXCEL_EXPORT_PATH=str(path)):
                self.client.post("/schulden/row-1/uebernehmen/")
                rows = excel_store.read_rows(path)
                self.assertEqual(rows[0]["status"], excel_store.STATUS_OPEN)

    def test_reject_deletes_row(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "s.xlsx"
            excel_store.upsert_row(
                path,
                excel_store.DebtRow(
                    id="row-1", creditor_name="Test GmbH", amount=Decimal("50"),
                    status=excel_store.STATUS_PROPOSAL,
                ),
            )
            with self.settings(DEBT_EXCEL_EXPORT_PATH=str(path)):
                self.client.post("/schulden/row-1/verwerfen/")
                self.assertEqual(excel_store.read_rows(path), [])
