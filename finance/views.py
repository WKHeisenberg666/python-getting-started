from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import excel_store, ingest, reconciliation
from .bank_sync import BankSyncError, run_bank_sync
from .models import Account, Document


def _excel_path():
    return settings.DEBT_EXCEL_EXPORT_PATH


_CLOSED_STATUSES = (excel_store.STATUS_PROPOSAL, excel_store.STATUS_PAID, excel_store.STATUS_SETTLED)


def dashboard(request):
    rows = excel_store.read_rows(_excel_path())
    review_rows = [r for r in rows if r["status"] == excel_store.STATUS_PROPOSAL]
    confirmed_rows = [r for r in rows if r["status"] not in _CLOSED_STATUSES]

    total_debt = sum((r["open_amount"] or r["amount"] for r in confirmed_rows), Decimal("0"))
    total_balance = Account.objects.aggregate(total=Sum("balance"))["total"] or 0
    net_worth = total_balance - total_debt

    fixed_costs = reconciliation.detect_fixed_costs()

    context = {
        "total_debt": total_debt,
        "total_balance": total_balance,
        "net_worth": net_worth,
        "debts": sorted(confirmed_rows, key=lambda r: r["amount"], reverse=True)[:20],
        "review_debts": review_rows,
        "accounts": Account.objects.all(),
        "recent_documents": Document.objects.all()[:10],
        "unprocessed_count": Document.objects.filter(processed_at__isnull=True).count(),
        "fixed_costs": fixed_costs,
        "monthly_fixed_costs_total": sum((f["amount"] for f in fixed_costs), Decimal("0")),
        "gocardless_configured": bool(
            settings.GOCARDLESS_SPARKASSE_REQUISITION_ID or settings.GOCARDLESS_REVOLUT_REQUISITION_ID
        ),
    }
    return render(request, "finance/dashboard.html", context)


def upload_document(request):
    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            messages.error(request, "Bitte eine Datei auswählen.")
            return redirect("finance:upload")

        result = ingest.ingest_bytes(
            uploaded_file.read(),
            uploaded_file.name,
            Document.Source.MANUAL_UPLOAD,
        )
        if result.duplicate:
            messages.warning(request, f"„{uploaded_file.name}“ wurde bereits importiert.")
        elif result.extraction_error:
            messages.error(
                request, f"„{uploaded_file.name}“ gespeichert, aber KI-Analyse fehlgeschlagen: {result.extraction_error}"
            )
        elif result.debt_proposal:
            messages.success(
                request,
                f"„{uploaded_file.name}“ importiert – Vorschlag "
                f"{result.debt_proposal.amount} EUR für {result.debt_proposal.creditor_name} "
                "wartet im Dashboard auf Prüfung.",
            )
        else:
            messages.info(
                request,
                f"„{uploaded_file.name}“ importiert, aber kein Forderungsschreiben mit Betrag erkannt.",
            )
        return redirect("finance:dashboard")

    return render(request, "finance/upload.html")


def debt_list(request):
    rows = [
        r for r in excel_store.read_rows(_excel_path()) if r["status"] != excel_store.STATUS_PROPOSAL
    ]
    status = request.GET.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["amount"], reverse=True)
    status_choices = [
        excel_store.STATUS_OPEN,
        excel_store.STATUS_INSTALLMENT,
        excel_store.STATUS_PAID,
        excel_store.STATUS_SETTLED,
    ]
    return render(
        request,
        "finance/debt_list.html",
        {"debts": rows, "status_choices": status_choices, "selected_status": status},
    )


def document_list(request):
    return render(
        request, "finance/document_list.html", {"documents": Document.objects.all()}
    )


@require_POST
def confirm_debt(request, row_id):
    updated = excel_store.update_row(_excel_path(), row_id, status=excel_store.STATUS_OPEN)
    if updated:
        messages.success(request, "Vorschlag übernommen.")
    else:
        messages.error(request, "Eintrag nicht gefunden.")
    return redirect("finance:dashboard")


@require_POST
def reject_debt(request, row_id):
    deleted = excel_store.delete_row(_excel_path(), row_id)
    if deleted:
        messages.info(request, "Vorschlag verworfen.")
    else:
        messages.error(request, "Eintrag nicht gefunden.")
    return redirect("finance:dashboard")


@require_POST
def reconcile_banks(request):
    try:
        sync_result = run_bank_sync()
    except BankSyncError as exc:
        messages.error(request, str(exc))
        return redirect("finance:dashboard")

    summary = reconciliation.reconcile_debts_with_transactions(_excel_path())
    messages.success(
        request,
        f"Bankabgleich fertig: {len(sync_result.synced_account_names)} Konto(en) synchronisiert, "
        f"{sync_result.new_transaction_count} neue Transaktion(en), "
        f"{summary['matched_debts']} Schulden mit Zahlungen abgeglichen.",
    )
    return redirect("finance:dashboard")
