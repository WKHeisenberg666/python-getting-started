import hashlib

from django.db import models


class Document(models.Model):
    """A scanned letter/statement (jpg, pdf or xlsx) that was ingested.

    Debt content itself is not modeled here - see finance/excel_store.py. The Excel workbook
    is the source of truth for debts; this model only tracks the uploaded file and whatever
    text was extracted from it.
    """

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
