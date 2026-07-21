from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import redirect, render

from . import ingest
from .models import Account, Debt, Document


def dashboard(request):
    open_debts = Debt.objects.exclude(status=Debt.Status.SETTLED).select_related("creditor")
    total_debt = open_debts.aggregate(total=Sum("amount"))["total"] or 0
    total_balance = Account.objects.aggregate(total=Sum("balance"))["total"] or 0
    net_worth = total_balance - total_debt

    context = {
        "total_debt": total_debt,
        "total_balance": total_balance,
        "net_worth": net_worth,
        "debts": open_debts.order_by("-amount")[:20],
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
                f"„{uploaded_file.name}“ importiert – "
                f"{result.debt.amount} {result.debt.currency} für {result.debt.creditor.name} erfasst.",
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
    debts = Debt.objects.select_related("creditor").all()
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
