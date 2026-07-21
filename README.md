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
das Schulden und Kontostände anzeigt, neue Dokumente per KI ausliest und auf Knopfdruck
Banktransaktionen gegen offene Schulden abgleicht.

**Architektur in einem Satz:** Die Excel-Datei unter `DEBT_EXCEL_EXPORT_PATH` (Standard:
`media/schuldenliste.xlsx`) ist die einzige Quelle der Wahrheit für Schulden. Das Dashboard
liest sie bei jedem Aufruf neu ein – Zeilen von Hand in Excel ergänzen oder korrigieren
funktioniert also genauso wie über das Dashboard.

### Lokal starten

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Für OCR von Bildern (JPG/PNG) muss zusätzlich die Tesseract-Systembibliothek installiert
sein (`apt install tesseract-ocr tesseract-ocr-deu` bzw. `brew install tesseract`).
PDF-Text wird ohne zusätzliche Systemabhängigkeiten gelesen.

### KI-Analyse der Dokumente (erforderlich)

Betrag/Gläubiger/Kategorie/Fälligkeit werden nicht per Regex geraten, sondern von der
Claude-API strukturiert aus dem extrahierten Text gelesen (siehe
`finance/claude_extraction.py`) – das war mit einer einfachen Text-Heuristik bei echten,
teils schräg fotografierten Schreiben zu unzuverlässig.

1. Eigenen API-Key unter [console.anthropic.com](https://console.anthropic.com) anlegen
   (eigener Account, eigene Kosten – bei Bildern/Briefen ca. Cent-Beträge pro Dokument mit
   dem Standardmodell `claude-haiku-4-5-20251001`).
2. In `.env` eintragen: `ANTHROPIC_API_KEY=sk-ant-...`
3. Optional ein anderes Modell wählen: `CLAUDE_EXTRACTION_MODEL=claude-sonnet-5`

Ohne gesetzten Key bricht `sync_drive_folder` sofort mit einer klaren Fehlermeldung ab,
statt stillschweigend nichts zu erkennen.

### Dokumente einlesen

- Manuell: über „Dokument hochladen“ im Dashboard.
- Automatisch aus Proton Drive: Proton bietet keine öffentliche API für Drittanbieter-Apps.
  Stattdessen wird der Ordner über die **Proton Drive Bridge**/Desktop-App lokal auf den Mac
  synchronisiert. Bei dir ist das:

  ```
  PROTON_DRIVE_SYNC_FOLDER=/Users/marcel/Library/CloudStorage/ProtonDrive-marcel.peters@proton.me-folder/Forderungen 2026
  ```

  Diesen Wert in `.env` eintragen (bereits vorbereitet), dann:

  ```
  python manage.py sync_drive_folder --once        # einmaliger Scan (z.B. per Cron alle paar Minuten)
  python manage.py sync_drive_folder --interval 300 # dauerhaft laufen lassen
  ```

  Es werden nur Bilder (jpg/png) und PDFs automatisch gescannt – Excel-Dateien im Ordner
  (Übersichten, Backups, Office-Lock-Dateien wie `~$....xlsx`) werden übersprungen, da sie
  keine einzelnen Schreiben sind und nicht automatisch verändert werden sollen. Unterordner,
  die keine Schreiben enthalten (bei dir z.B. `dashboard`, `venv`), werden über
  `PROTON_DRIVE_EXCLUDE_SUBFOLDERS` in `.env` (kommagetrennt) ausgeschlossen.

  Jede neue Datei wird gespeichert, ihr Text extrahiert (PDF-Text bzw. OCR bei Bildern) und
  von Claude analysiert. Ein erkanntes Forderungsschreiben landet **nicht** direkt als „echte“
  Schuld im Dashboard, sondern als Zeile mit Status „Vorschlag (KI)“ im Abschnitt
  „Vorschläge zur Prüfung“ – dort mit einem Klick auf „Übernehmen“ bestätigen (Status wird
  „Offen“) oder auf „Verwerfen“ löschen. Erst bestätigte Zeilen zählen zu „Offene Schulden“.

  **Damit neu gescannte Schreiben automatisch (ohne manuelles Anstoßen) erfasst werden**, liegt
  unter `scripts/com.finanzdashboard.syncdrive.plist` eine macOS-LaunchAgent-Vorlage, die
  `sync_drive_folder --interval 120` dauerhaft im Hintergrund laufen lässt (neue Dateien werden
  spätestens 2 Minuten nach dem Sync durch Proton Drive verarbeitet, auch nach einem Neustart des
  Macs). Einrichtung:

  1. In der Datei alle `<<PROJEKTORDNER>>`-Platzhalter durch den echten absoluten Pfad des
     Projekts auf deinem Mac ersetzen. `PROTON_DRIVE_SYNC_FOLDER` ist dort bereits gesetzt;
     `ANTHROPIC_API_KEY` musst du zusätzlich ergänzen, da LaunchAgents `.env` nicht automatisch
     laden.
  2. Datei nach `~/Library/LaunchAgents/com.finanzdashboard.syncdrive.plist` kopieren.
  3. `mkdir -p <<PROJEKTORDNER>>/logs && launchctl load ~/Library/LaunchAgents/com.finanzdashboard.syncdrive.plist`
  4. Läuft's? `tail -f <<PROJEKTORDNER>>/logs/sync_drive.log`
  5. Stoppen: `launchctl unload ~/Library/LaunchAgents/com.finanzdashboard.syncdrive.plist`

### Sparkasse & Revolut anbinden + Bankabgleich

Weder Sparkasse noch Revolut geben Privatkunden einen einfachen persönlichen API-Key. Die
Anbindung läuft über den PSD2-Open-Banking-Aggregator **GoCardless Bank Account Data**
(ehemals Nordigen), der beide Banken unterstützt:

1. Kostenlosen Account unter [bankaccountdata.gocardless.com](https://bankaccountdata.gocardless.com)
   anlegen und `GOCARDLESS_SECRET_ID` / `GOCARDLESS_SECRET_KEY` in `.env` eintragen.
2. Pro Bank einmalig den Login-/Consent-Flow starten:
   ```
   python manage.py gocardless_connect_bank SPARKASSE_XXXXXXXX
   python manage.py gocardless_connect_bank REVOLUT_REVOGB21
   ```
   Den ausgegebenen Link öffnen und die Bank-Anmeldung abschließen.
3. Die ausgegebene Requisition-ID in `GOCARDLESS_SPARKASSE_REQUISITION_ID` bzw.
   `GOCARDLESS_REVOLUT_REQUISITION_ID` eintragen. Das PSD2-Consent ist maximal 90 Tage gültig
   und muss danach über Schritt 2 erneuert werden.

Danach erscheint im Dashboard bei „Konten“ ein Button **„Jetzt abgleichen“**, der:

- Kontostände/Umsätze live über GoCardless lädt,
- jede offene/Ratenzahlungs-Schuld gegen die Umsätze abgleicht (Gläubigername kommt im
  Überweisungstext vor) und Status/„Bereits gezahlt“/„Offener Betrag“ in der Excel-Datei
  aktualisiert (Status wird automatisch „Bezahlt“, wenn der offene Betrag auf 0 sinkt, oder
  „Ratenzahlung“, wenn mehrere Teilzahlungen erkannt wurden),
- wiederkehrende Abbuchungen (gleicher Betrag/Text in ≥2 verschiedenen Monaten) als
  „monatliche Fixkosten“ erkennt und im Dashboard aufsummiert.

Das Matching ist ein einfacher Textabgleich (kein Wunder-Algorithmus) – Ergebnisse im
Zweifel in der Excel-Datei gegenprüfen. Für regelmäßige Aktualisierung ohne Klick:
`python manage.py sync_bank_accounts` per Cron laufen lassen (macht Sync + Abgleich in einem).

Alle Zugangsdaten werden ausschließlich über Umgebungsvariablen konfiguriert, nie im Code
hinterlegt.
