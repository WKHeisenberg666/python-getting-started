from django.contrib import admin

from .models import Account, BankTransaction, Document, ProcessedFile


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "doc_type", "source", "uploaded_at", "is_processed")
    list_filter = ("doc_type", "source")
    readonly_fields = ("checksum",)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("provider", "name", "balance", "currency", "last_synced_at")
    list_filter = ("provider",)


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = ("account", "booking_date", "amount", "currency", "description")
    list_filter = ("account",)
    date_hierarchy = "booking_date"


@admin.register(ProcessedFile)
class ProcessedFileAdmin(admin.ModelAdmin):
    list_display = ("path", "processed_at")
