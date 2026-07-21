from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import ingest
from .models import Account, Debt, Document


def dashboard(request):
    confirmed_debts = (
        Debt.objects.filter(needs_review=False)
        .exclude(status=Debt.Status.SETTLED)
        .select_related("creditor")
    )
    total_debt = confirmed_debts.aggregate(total=Sum("amount"))["total"] or 0
    total_balance = Account.objects.aggregate(total=Sum("balance"))["total"] or 0
    net_worth = total_balance - total_debt

    context = {
        "total_debt": total_debt,
        "total_balance": total_balance,
        "net_worth": net_worth,
        "debts": confirmed_debts.order_by("-amount")[:20],
        "review_debts": Debt.objects.filter(needs_review=True).select_related(
            "creditor", "source_document"
        ),
        "accounts": Account.objects.all(),
        "recent_documents": Document.objects.all()[:10],
        "unprocessed_count": Document.objects.filter(processed_at__isnull=True).count(),
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
        elif result.debt:
            messages.success(
                request,
                f"„{uploaded_file.name}“ importiert – Vorschlag "
                f"{result.debt.amount} {result.debt.currency} für {result.debt.creditor.name} "
                "wartet im Dashboard auf Prüfung.",
            )
        else:
            messages.info(
                request,
                f"„{uploaded_file.name}“ importiert, aber kein Betrag erkannt – "
                "bitte im Dashboard prüfen und den Schulden-Eintrag ggf. manuell anlegen.",
            )
        return redirect("finance:dashboard")

    return render(request, "finance/upload.html")


def debt_list(request):
    debts = Debt.objects.filter(needs_review=False).select_related("creditor")
    status = request.GET.get("status")
    if status:
        debts = debts.filter(status=status)
    return render(
        request,
        "finance/debt_list.html",
        {"debts": debts, "status_choices": Debt.Status.choices, "selected_status": status},
    )


def document_list(request):
    return render(
        request, "finance/document_list.html", {"documents": Document.objects.all()}
    )


@require_POST
def confirm_debt(request, pk):
    debt = get_object_or_404(Debt, pk=pk, needs_review=True)
    debt.needs_review = False
    debt.save()
    messages.success(request, f"Übernommen: {debt.creditor.name} – {debt.amount} {debt.currency}.")
    return redirect("finance:dashboard")


@require_POST
def reject_debt(request, pk):
    debt = get_object_or_404(Debt, pk=pk, needs_review=True)
    creditor_name = debt.creditor.name
    debt.delete()
    messages.info(request, f"Verworfen: Vorschlag für {creditor_name}.")
    return redirect("finance:dashboard")
