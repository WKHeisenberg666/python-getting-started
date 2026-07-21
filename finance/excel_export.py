"""Keeps the "Schuldenliste" Excel workbook in sync with the Debt table.

This is the file the user already maintains by hand; every newly ingested
document appends a row here too, so the workbook stays the single
human-readable export even though the dashboard reads from the database.
"""

from pathlib import Path

HEADER = [
    "Erfasst am",
    "Gläubiger",
    "Betrag",
    "Währung",
    "Fällig am",
    "Referenz",
    "Status",
    "Quelldokument",
]


def append_debt_row(workbook_path: Path, debt) -> None:
    import openpyxl

    workbook_path = Path(workbook_path)
    workbook_path.parent.mkdir(parents=True, exist_ok=True)

    if workbook_path.exists():
        workbook = openpyxl.load_workbook(workbook_path)
        sheet = workbook.active
    else:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Schulden"
        sheet.append(HEADER)

    sheet.append(
        [
            debt.created_at.strftime("%d.%m.%Y") if debt.created_at else "",
            debt.creditor.name,
            float(debt.amount),
            debt.currency,
            debt.due_date.strftime("%d.%m.%Y") if debt.due_date else "",
            debt.reference,
            debt.get_status_display(),
            debt.source_document.original_filename if debt.source_document else "",
        ]
    )
    workbook.save(workbook_path)
