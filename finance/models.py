import hashlib

from django.db import models


class Creditor(models.Model):
    """Someone or something money is owed to (bank, authority, person, ...)."""

    name = models.CharField(max_length=200, unique=True)
    contact_info = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Document(models.Model):
    """A scanned letter/statement (jpg, pdf or xlsx) that was ingested."""

    class DocType(models.TextChoices):
        PDF = "pdf", "PDF"
        IMAGE = "image", "Bild (JPG/PNG)"
        EXCEL = "excel", "Excel"
        OTHER = "other", "Sonstiges"

    class Source(models.TextChoices):
        MANUAL_UPLOAD = "manual", "Manueller Upload"
        DRIVE_SYNC = "drive_sync", "Proton Drive Ordner"

    file = models.FileField(upload_to="documents/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    doc_type = models.CharField(max_length=10, choices=DocType.choices)
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.MANUAL_UPLOAD
    )
    checksum = models.CharField(max_length=64, unique=True, editable=False)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    extracted_text = models.TextField(blank=True)

    debt = models.ForeignKey(
        "Debt", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.original_filename

    @property
    def is_processed(self):
        return self.processed_at is not None

    @staticmethod
    def checksum_for(content_bytes):
        return hashlib.sha256(content_bytes).hexdigest()


class Debt(models.Model):
    """A single debt/liability item, usually extracted from a Document."""

    class Status(models.TextChoices):
        OPEN = "open", "Offen"
        IN_PROGRESS = "in_progress", "In Bearbeitung (Rate/Widerspruch)"
        SETTLED = "settled", "Beglichen"

    creditor = models.ForeignKey(
        Creditor, on_delete=models.PROTECT, related_name="debts"
    )
    reference = models.CharField(
        "Aktenzeichen/Referenz", max_length=100, blank=True
    )
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="EUR")
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    source_document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    notes = models.TextField(blank=True)

    # True for debts auto-created from OCR/PDF-text extraction that a human hasn't confirmed
    # yet. The heuristic extraction is not reliable enough on real scans to trust blindly, so
    # these are excluded from dashboard totals and shown separately for review until confirmed.
    needs_review = models.BooleanField(default=False)
    excel_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.creditor} – {self.amount} {self.currency}"


class Account(models.Model):
    """A bank account tracked via an open-banking connection (Sparkasse, Revolut, ...)."""

    class Provider(models.TextChoices):
        SPARKASSE = "sparkasse", "Sparkasse"
        REVOLUT = "revolut", "Revolut"
        OTHER = "other", "Sonstige"

    provider = models.CharField(max_length=20, choices=Provider.choices)
    name = models.CharField(max_length=100)
    iban_masked = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=3, default="EUR")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    external_account_id = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["provider", "name"]

    def __str__(self):
        return f"{self.get_provider_display()} – {self.name}"


class BankTransaction(models.Model):
    """A single transaction pulled from an Account via the bank connector."""

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="transactions"
    )
    booking_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="EUR")
    description = models.CharField(max_length=255, blank=True)
    external_id = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["-booking_date"]

    def __str__(self):
        return f"{self.booking_date} {self.amount} {self.currency} – {self.description}"


class ProcessedFile(models.Model):
    """Tracks which files in the local Proton Drive sync folder were already ingested."""

    path = models.CharField(max_length=1024, unique=True)
    checksum = models.CharField(max_length=64)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.path
