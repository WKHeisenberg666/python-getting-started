from decimal import Decimal
from unittest import mock

from django.test import TestCase

from . import extraction, ingest
from .models import Creditor, Debt, Document


class ExtractionParsingTests(TestCase):
    def test_parse_amount_prefers_labeled_total_over_bigger_stray_number(self):
        text = "Mahngebühr 5,00 EUR\nGesamtbetrag: 1.234,56 EUR\nVergleichsangebot 9.999,00 EUR"
        self.assertEqual(extraction.parse_amount(text), Decimal("1234.56"))

    def test_parse_amount_falls_back_to_largest_number_without_a_label(self):
        text = "Mahngebühr 5,00 EUR\nRechnungssumme 42,00 EUR"
        self.assertEqual(extraction.parse_amount(text), Decimal("42.00"))

    def test_parse_due_date(self):
        text = "Bitte zahlen Sie bis zum 15.08.2026."
        self.assertEqual(extraction.parse_due_date(text).isoformat(), "2026-08-15")

    def test_parse_reference(self):
        text = "Aktenzeichen: AZ-2026-00042"
        self.assertEqual(extraction.parse_reference(text), "AZ-2026-00042")

    def test_guess_doc_type(self):
        self.assertEqual(extraction.guess_doc_type("brief.pdf"), Document.DocType.PDF)
        self.assertEqual(extraction.guess_doc_type("scan.jpg"), Document.DocType.IMAGE)
        self.assertEqual(extraction.guess_doc_type("liste.xlsx"), Document.DocType.EXCEL)

    def test_guess_creditor_name_prefers_org_marker_line(self):
        text = "12.03.2026\nAmtsgericht Hagen\nAktenzeichen: 1 C 2/26"
        self.assertEqual(extraction.guess_creditor_name(text, "brief.pdf"), "Amtsgericht Hagen")

    def test_guess_creditor_name_ignores_junk_lines(self):
        # Short/symbol-heavy OCR noise should not be picked as a name.
        text = "--- | ---\nreg -\nHIER STEHT DER ECHTE NAME GmbH\nweiterer Text"
        self.assertEqual(
            extraction.guess_creditor_name(text, "brief.pdf"), "HIER STEHT DER ECHTE NAME GmbH"
        )


class IngestBytesTests(TestCase):
    @mock.patch("finance.extraction.extract_text")
    def test_pdf_with_recognizable_amount_creates_a_review_draft(self, mock_extract_text):
        mock_extract_text.return_value = "Amtsgericht Hagen\nGesamtbetrag: 228,93 EUR"
        result = ingest.ingest_bytes(b"fake pdf bytes", "brief.pdf", Document.Source.MANUAL_UPLOAD)

        self.assertTrue(result.created)
        self.assertIsNotNone(result.debt)
        self.assertTrue(result.debt.needs_review)
        self.assertEqual(result.debt.amount, Decimal("228.93"))
        self.assertEqual(result.debt.creditor.name, "Amtsgericht Hagen")

    @mock.patch("finance.extraction.extract_text")
    def test_pdf_without_recognizable_amount_creates_no_debt(self, mock_extract_text):
        mock_extract_text.return_value = "Text ohne jeden Geldbetrag."
        result = ingest.ingest_bytes(b"fake pdf bytes", "brief.pdf", Document.Source.MANUAL_UPLOAD)

        self.assertTrue(result.created)
        self.assertIsNone(result.debt)

    @mock.patch("finance.extraction.extract_text")
    def test_unrecognized_file_type_never_creates_a_debt(self, mock_extract_text):
        # Even if the (mocked) extracted text contains a clean amount, non-letter file types
        # (here: .txt -> DocType.OTHER) are never parsed into a debt.
        mock_extract_text.return_value = "Firma GmbH\nGesamtbetrag: 42,00 EUR"
        result = ingest.ingest_bytes(b"irrelevant", "notiz.txt", Document.Source.MANUAL_UPLOAD)

        self.assertTrue(result.created)
        self.assertIsNone(result.debt)

    def test_duplicate_file_is_not_reingested(self):
        content = b"same bytes"
        first = ingest.ingest_bytes(content, "a.txt", Document.Source.MANUAL_UPLOAD)
        second = ingest.ingest_bytes(content, "a-renamed.txt", Document.Source.MANUAL_UPLOAD)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.document.id, second.document.id)
        self.assertEqual(Document.objects.count(), 1)

    def test_excel_overview_does_not_create_a_bogus_debt(self):
        import io

        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["FORDERUNGSÜBERSICHT 2026 – Marcel Peters"])
        sheet.append(["Gesamtsumme aller Forderungen", "209679,90 EUR"])
        buffer = io.BytesIO()
        workbook.save(buffer)

        result = ingest.ingest_bytes(buffer.getvalue(), "uebersicht.xlsx", Document.Source.MANUAL_UPLOAD)
        self.assertTrue(result.created)
        self.assertIsNone(result.debt)
        self.assertEqual(Debt.objects.count(), 0)


class DebtExcelSignalTests(TestCase):
    def test_confirmed_debt_is_appended_to_the_excel_export(self):
        import tempfile

        import openpyxl
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = f"{tmp_dir}/schuldenliste.xlsx"
            with override_settings(DEBT_EXCEL_EXPORT_PATH=export_path):
                creditor = Creditor.objects.create(name="Test Inkasso GmbH")
                Debt.objects.create(creditor=creditor, amount=Decimal("99.90"))

            workbook = openpyxl.load_workbook(export_path)
            rows = list(workbook.active.iter_rows(values_only=True))
            self.assertEqual(rows[1][1], "Test Inkasso GmbH")
            self.assertEqual(rows[1][2], 99.9)

    def test_review_draft_is_not_appended_until_confirmed(self):
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = f"{tmp_dir}/schuldenliste.xlsx"
            with override_settings(DEBT_EXCEL_EXPORT_PATH=export_path):
                creditor = Creditor.objects.create(name="Draft GmbH")
                debt = Debt.objects.create(
                    creditor=creditor, amount=Decimal("10.00"), needs_review=True
                )
                self.assertFalse(Path(export_path).exists())

                debt.needs_review = False
                debt.save()

            import openpyxl

            workbook = openpyxl.load_workbook(export_path)
            rows = list(workbook.active.iter_rows(values_only=True))
            self.assertEqual(rows[1][1], "Draft GmbH")


class DashboardViewTests(TestCase):
    def test_dashboard_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_upload_page_renders(self):
        response = self.client.get("/upload/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_excludes_review_drafts_from_totals(self):
        creditor = Creditor.objects.create(name="Draft GmbH")
        Debt.objects.create(creditor=creditor, amount=Decimal("500.00"), needs_review=True)
        response = self.client.get("/")
        self.assertEqual(response.context["total_debt"], 0)
        self.assertEqual(len(response.context["review_debts"]), 1)
        self.assertContains(response, "Draft GmbH")


class DebtReviewViewTests(TestCase):
    def setUp(self):
        self.creditor = Creditor.objects.create(name="Test GmbH")
        self.draft = Debt.objects.create(
            creditor=self.creditor, amount=Decimal("50.00"), needs_review=True
        )

    def test_confirm_marks_debt_as_reviewed(self):
        self.client.post(f"/schulden/{self.draft.pk}/uebernehmen/")
        self.draft.refresh_from_db()
        self.assertFalse(self.draft.needs_review)

    def test_reject_deletes_debt(self):
        self.client.post(f"/schulden/{self.draft.pk}/verwerfen/")
        self.assertFalse(Debt.objects.filter(pk=self.draft.pk).exists())

    def test_cannot_confirm_an_already_confirmed_debt_via_this_endpoint(self):
        self.draft.needs_review = False
        self.draft.save()
        response = self.client.post(f"/schulden/{self.draft.pk}/uebernehmen/")
        self.assertEqual(response.status_code, 404)
