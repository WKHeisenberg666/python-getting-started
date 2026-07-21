from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .excel_export import append_debt_row
from .models import Debt


@receiver(post_save, sender=Debt)
def mirror_confirmed_debt_to_excel(sender, instance, created, **kwargs):
    """Appends a row once a debt is confirmed (needs_review=False), whether that happens
    immediately (manually created / seeded) or later (a draft gets reviewed and accepted).
    excel_synced_at guards against appending the same debt twice across repeated saves."""
    if instance.needs_review or instance.excel_synced_at:
        return
    try:
        append_debt_row(Path(settings.DEBT_EXCEL_EXPORT_PATH), instance)
    except Exception:
        # The Excel export is a convenience mirror of the DB; never let it block saving.
        return
    Debt.objects.filter(pk=instance.pk).update(excel_synced_at=timezone.now())
