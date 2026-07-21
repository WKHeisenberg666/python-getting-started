# Python: Getting Started

A barebones Django app, which can easily be deployed to Heroku.

## Deploying to Heroku

Using resources for this example app counts towards your usage. [Delete your app](https://devcenter.heroku.com/articles/heroku-cli-commands#heroku-apps-destroy) and [database](https://devcenter.heroku.com/articles/heroku-postgresql#removing-the-add-on) as soon as you are done experimenting to control costs.

By default, apps use Eco dynos if you are subscribed to Eco. Otherwise, it defaults to Basic dynos. The Eco dynos plan is shared across all Eco dynos in your account and is recommended if you plan on deploying many small apps to Heroku. Learn more about our low-cost plans [here](https://blog.heroku.com/new-low-cost-plans).

Eligible students can apply for platform credits through our new [Heroku for GitHub Students program](https://blog.heroku.com/github-student-developer-program).

This application supports the [Getting Started with Python on Heroku](https://devcenter.heroku.com/articles/getting-started-with-python) article - check it out for instructions on how to deploy this app to Heroku and also run it locally.

Alternatively, you can deploy it using this Heroku Button:

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/heroku/python-getting-started)

For more information about using Python on Heroku, see these Dev Center articles:

- [Python on Heroku](https://devcenter.heroku.com/categories/python)

## Finanz-Dashboard

Neben der Heroku-Beispielseite (`/hello/`) enthält dieses Projekt ein Dashboard unter `/`,
das Schulden und Kontostände anzeigt und neue Dokumente (JPG/PNG/PDF/Excel) automatisch
ausliest.

### Lokal starten

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data   # optional: Beispieldaten
python manage.py runserver
```

Für OCR von Bildern (JPG/PNG) muss zusätzlich die Tesseract-Systembibliothek installiert
sein (`apt install tesseract-ocr tesseract-ocr-deu` bzw. `brew install tesseract`).
PDF-Text wird ohne zusätzliche Systemabhängigkeiten gelesen. Fehlt Tesseract, wird das
Dokument trotzdem gespeichert – nur die automatische Erkennung von Betrag/Gläubiger
funktioniert dann für Bilder nicht.

### Dokumente hochladen

- Manuell: über „Dokument hochladen“ im Dashboard.
- Automatisch aus Proton Drive: Proton bietet keine öffentliche API für Drittanbieter-Apps.
  Stattdessen den betreffenden Proton-Drive-Ordner über die **Proton Drive Bridge**/Desktop-App
  lokal synchronisieren, den Pfad in `PROTON_DRIVE_SYNC_FOLDER` eintragen und dann:

  ```
  python manage.py sync_drive_folder --once        # einmaliger Scan (z.B. per Cron alle paar Minuten)
  python manage.py sync_drive_folder --interval 300 # dauerhaft laufen lassen
  ```

  Jede neue Datei wird ausgelesen, Betrag/Gläubiger/Fälligkeit/Referenz werden per Heuristik
  erkannt, als `Debt`-Eintrag angelegt und zusätzlich als Zeile in die Excel-Datei unter
  `DEBT_EXCEL_EXPORT_PATH` (Standard: `media/schuldenliste.xlsx`) angehängt – das ist die
  gleiche Liste, die bisher von Hand geführt wurde.

### Sparkasse & Revolut anbinden

Weder Sparkasse noch Revolut geben Privatkunden einen einfachen persönlichen API-Key. Die
Anbindung läuft über den PSD2-Open-Banking-Aggregator **GoCardless Bank Account Data**
(ehemals Nordigen), der beide Banken unterstützt:

1. Kostenlosen Account unter [bankaccountdata.gocardless.com](https://bankaccountdata.gocardless.com)
   anlegen und `GOCARDLESS_SECRET_ID` / `GOCARDLESS_SECRET_KEY` als Umgebungsvariable setzen.
2. Pro Bank einmalig den Login-/Consent-Flow starten:
   ```
   python manage.py gocardless_connect_bank SPARKASSE_XXXXXXXX
   python manage.py gocardless_connect_bank REVOLUT_REVOGB21
   ```
   Den ausgegebenen Link öffnen und die Bank-Anmeldung abschließen.
3. Die ausgegebene Requisition-ID in `GOCARDLESS_SPARKASSE_REQUISITION_ID` bzw.
   `GOCARDLESS_REVOLUT_REQUISITION_ID` eintragen.
4. Kontostände/Umsätze abholen:
   ```
   python manage.py sync_bank_accounts
   ```
   Das PSD2-Consent ist maximal 90 Tage gültig und muss danach über Schritt 2 erneuert werden.
   Für regelmäßige Aktualisierung `sync_bank_accounts` per Cron laufen lassen.

Alle Zugangsdaten werden ausschließlich über Umgebungsvariablen konfiguriert, nie im Code
hinterlegt.
