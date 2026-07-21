from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .excel_export import append_debt_row
from .models import Debt


@receiver(post_save, sender=Debt)
def mirror_new_debt_to_excel(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        append_debt_row(Path(settings.DEBT_EXCEL_EXPORT_PATH), instance)
    except Exception:
        # The Excel export is a convenience mirror of the DB; never let it block saving.
        pass
