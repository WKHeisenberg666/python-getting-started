"""Reads structured debt fields out of a letter's extracted text using the Claude API.

This replaces an earlier regex-based heuristic ("biggest number = amount, first text line =
creditor") that was not reliable enough on real, noisy OCR text from photographed letters.
Requires the user's own ANTHROPIC_API_KEY (their own account, their own cost - a few cents per
document at most with a small model); there is no free/local fallback by design, since the
whole point is that the heuristic wasn't trustworthy.
"""

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import anthropic

DEFAULT_MODEL = os.environ.get("CLAUDE_EXTRACTION_MODEL", "claude-haiku-4-5-20251001")

_TOOL_NAME = "record_debt_letter"

_TOOL_SCHEMA = {
    "name": _TOOL_NAME,
    "description": "Speichert die aus einem Inkasso-/Forderungsschreiben extrahierten Felder.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_debt_letter": {
                "type": "boolean",
                "description": (
                    "Ob der Text überhaupt ein Forderungs-/Inkasso-/Behördenschreiben zu einer "
                    "Schuld ist (nicht z.B. Werbung, ein irrelevantes Foto, ein Vertrag ohne "
                    "konkrete Forderung)."
                ),
            },
            "creditor_name": {
                "type": "string",
                "description": "Name des ursprünglichen Gläubigers (bei wem die Schuld entstand).",
            },
            "collection_agency": {
                "type": "string",
                "description": (
                    "Name des Inkassobüros/der Kanzlei, falls das Schreiben in deren Auftrag "
                    "verschickt wurde, sonst leerer String."
                ),
            },
            "category": {
                "type": "string",
                "description": (
                    "Kurze Kategorie, z.B. 'Bank/Kredit', 'Versicherung', 'Behörde', 'Miete', "
                    "'Telekommunikation', 'Sonstiges'."
                ),
            },
            "amount": {
                "type": ["number", "null"],
                "description": (
                    "Geforderter/offener Gesamtbetrag in EUR als Zahl, z.B. 1234.56. null, falls "
                    "kein eindeutiger Betrag im Text steht."
                ),
            },
            "due_date": {
                "type": ["string", "null"],
                "description": "Fälligkeits-/Zahlungsdatum im Format YYYY-MM-DD, sonst null.",
            },
            "reference": {
                "type": "string",
                "description": "Aktenzeichen/Kundennummer/Vertragsnummer, sonst leerer String.",
            },
            "summary": {
                "type": "string",
                "description": "1-2 kurze Sätze auf Deutsch, worum es in dem Schreiben geht.",
            },
        },
        "required": ["is_debt_letter", "creditor_name", "category", "amount", "summary"],
    },
}


class ExtractionError(Exception):
    pass


@dataclass
class ExtractedDebt:
    creditor_name: str
    collection_agency: str
    category: str
    amount: Decimal | None
    due_date: date | None
    reference: str
    summary: str


def extract_debt_fields_with_ai(text: str, model: str | None = None) -> ExtractedDebt | None:
    """Returns the extracted fields, or None if the text isn't a debt-related letter at all.

    Raises ExtractionError if there's no API key configured or the API call itself fails -
    callers should let the document still be stored (just without a debt drafted from it)
    rather than let this exception break the whole ingestion run.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ExtractionError(
            "ANTHROPIC_API_KEY ist nicht gesetzt - ohne eigenen Anthropic-API-Key kann keine "
            "KI-Analyse laufen (siehe README)."
        )
    if not text.strip():
        return None

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=1024,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analysiere den folgenden Text eines eingescannten Briefs (per OCR/"
                        "PDF-Extraktion gewonnen, kann daher leicht fehlerhaft sein) und speichere "
                        "die relevanten Felder über das bereitgestellte Tool:\n\n" + text[:12000]
                    ),
                }
            ],
        )
    except Exception as exc:
        raise ExtractionError(f"Claude-API-Aufruf fehlgeschlagen: {exc}") from exc

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None:
        raise ExtractionError("Claude hat keine strukturierten Daten zurückgegeben.")

    data = tool_use.input
    if not data.get("is_debt_letter"):
        return None

    amount = data.get("amount")
    try:
        amount_decimal = Decimal(str(amount)) if amount is not None else None
    except InvalidOperation:
        amount_decimal = None

    due_date = None
    if data.get("due_date"):
        try:
            due_date = date.fromisoformat(data["due_date"])
        except ValueError:
            due_date = None

    return ExtractedDebt(
        creditor_name=(data.get("creditor_name") or "").strip() or "Unbekannt",
        collection_agency=(data.get("collection_agency") or "").strip(),
        category=(data.get("category") or "").strip(),
        amount=amount_decimal,
        due_date=due_date,
        reference=(data.get("reference") or "").strip(),
        summary=(data.get("summary") or "").strip(),
    )
