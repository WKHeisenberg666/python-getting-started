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
das Schulden und Kontostände anzeigt und neue Dokumente (JPG/PNG/PDF/Excel) einliest und
per OCR/Textextraktion durchsuchbar macht.

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
Dokument trotzdem gespeichert, nur ohne extrahierten Text für Bilder.

### Dokumente hochladen

- Manuell: über „Dokument hochladen“ im Dashboard.
- Automatisch aus Proton Drive: Proton bietet keine öffentliche API für Drittanbieter-Apps.
  Stattdessen wird der Ordner über die **Proton Drive Bridge**/Desktop-App lokal auf den Mac
  synchronisiert. Bei dir ist das:

  ```
  PROTON_DRIVE_SYNC_FOLDER=/Users/marcel/Library/CloudStorage/ProtonDrive-marcel.peters@proton.me-folder/Forderungen 2026
  ```

  Diesen Wert in `.env` eintragen (bereits vorbereitet, nur auskommentiert) bzw. als
  Umgebungsvariable setzen, dann:

  ```
  python manage.py sync_drive_folder --once        # einmaliger Scan (z.B. per Cron alle paar Minuten)
  python manage.py sync_drive_folder --interval 300 # dauerhaft laufen lassen
  ```

  Es werden nur Bilder (jpg/png) und PDFs automatisch gescannt – Excel-Dateien im Ordner
  (Übersichten, Backups, Office-Lock-Dateien wie `~$....xlsx`) werden übersprungen, da sie
  keine einzelnen Schreiben sind. Unterordner, die keine Schreiben enthalten (bei dir z.B.
  `dashboard`, `venv`), werden über `PROTON_DRIVE_EXCLUDE_SUBFOLDERS` in `.env`
  (kommagetrennt) ausgeschlossen.

  Jede neue Datei wird gespeichert, ihr Text extrahiert (PDF-Text bzw. OCR bei Bildern) und
  per Heuristik nach Betrag/Gläubiger/Fälligkeit/Referenz durchsucht (bevorzugt Beträge, die
  im Text als „Gesamtbetrag“/„Restschuld“/„Zahlbetrag“ o.ä. beschriftet sind, sowie
  Gläubiger-Zeilen mit Firmen-Markern wie „GmbH“/„Inkasso“/„Amtsgericht“).

  Ein Treffer landet **nicht** direkt als „echte“ Schuld im Dashboard, sondern als Vorschlag
  im Abschnitt „Vorschläge zur Prüfung“ – dort mit einem Klick auf „Übernehmen“ bestätigen
  oder auf „Verwerfen“ löschen. Grund: bei echten, teils schräg fotografierten Scans liegt die
  Heuristik oft genug daneben, dass sie nicht ungeprüft in die Dashboard-Summen einfließen
  sollte. Erst bestätigte Schulden zählen zu „Offene Schulden“ und werden automatisch als
  Zeile an die Excel-Datei unter `DEBT_EXCEL_EXPORT_PATH` (Standard:
  `media/schuldenliste.xlsx`) angehängt. Schulden ohne erkannten Betrag bzw. Korrekturen an
  einem Vorschlag legst/bearbeitest du über die Django-Admin-Oberfläche unter `/admin/`.

  **Damit neu gescannte Schreiben automatisch (ohne manuelles Anstoßen) erfasst werden**, liegt
  unter `scripts/com.finanzdashboard.syncdrive.plist` eine macOS-LaunchAgent-Vorlage, die
  `sync_drive_folder --interval 120` dauerhaft im Hintergrund laufen lässt (neue Dateien werden
  spätestens 2 Minuten nach dem Sync durch Proton Drive verarbeitet, auch nach einem Neustart des
  Macs). Einrichtung:

  1. In der Datei alle `<<PROJEKTORDNER>>`-Platzhalter durch den echten absoluten Pfad des
     Projekts auf deinem Mac ersetzen (der `PROTON_DRIVE_SYNC_FOLDER`-Wert ist bereits auf
     deinen Ordner `.../ProtonDrive-marcel.peters@proton.me-folder/Forderungen 2026` gesetzt).
  2. Datei nach `~/Library/LaunchAgents/com.finanzdashboard.syncdrive.plist` kopieren.
  3. `mkdir -p <<PROJEKTORDNER>>/logs && launchctl load ~/Library/LaunchAgents/com.finanzdashboard.syncdrive.plist`
  4. Läuft's? `tail -f <<PROJEKTORDNER>>/logs/sync_drive.log`
  5. Stoppen: `launchctl unload ~/Library/LaunchAgents/com.finanzdashboard.syncdrive.plist`

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
