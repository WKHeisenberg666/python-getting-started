"""Ingests new files that show up in the local Proton Drive sync folder.

Proton Drive has no public API for third-party apps, so this relies on the
Proton Drive Bridge / desktop app keeping PROTON_DRIVE_SYNC_FOLDER mirrored
to disk. This command then behaves like a regular folder watcher: on every
run it looks for files not seen before (tracked via the ProcessedFile model,
keyed by path + content checksum) and ingests them through the same pipeline
as a manual upload.

Usage:
    # one-off scan, e.g. from a cron job every few minutes
    python manage.py sync_drive_folder --once

    # keep running and poll the folder for daily/ongoing scans
    python manage.py sync_drive_folder --interval 60
"""

import os
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ... import excel_store, ingest
from ...extraction import IMAGE_EXTENSIONS, PDF_EXTENSIONS
from ...models import Document, ProcessedFile

# Only scanned letters (images/PDFs) are picked up automatically. Excel files in the drive
# folder tend to be the user's own overview/backup spreadsheets rather than creditor letters,
# and since ingestion no longer auto-creates debts from them (see finance/ingest.py), storing
# copies of every backup/version as a "Document" was just clutter.
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS


class Command(BaseCommand):
    help = "Watches the local Proton Drive sync folder and ingests new documents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Scan the folder a single time and exit (suitable for cron).",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=300,
            help="Seconds between scans when running continuously (default: 300).",
        )

    def handle(self, *args, **options):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise CommandError(
                "ANTHROPIC_API_KEY ist nicht gesetzt. Die Dokumenten-Analyse läuft über die "
                "Claude-API - trag deinen eigenen Anthropic-API-Key in .env ein (siehe README)."
            )
        folder = settings.PROTON_DRIVE_SYNC_FOLDER
        if not folder:
            raise CommandError(
                "PROTON_DRIVE_SYNC_FOLDER is not set. Point it at the local folder that "
                "Proton Drive Bridge/the desktop app syncs your debt-letters folder to."
            )
        folder_path = Path(folder)
        if not folder_path.is_dir():
            raise CommandError(f"PROTON_DRIVE_SYNC_FOLDER does not exist or is not a directory: {folder}")

        try:
            excel_store.read_rows(settings.DEBT_EXCEL_EXPORT_PATH)
        except excel_store.IncompatibleWorkbookError as exc:
            raise CommandError(str(exc)) from exc

        if options["once"]:
            self._scan(folder_path)
            return

        self.stdout.write(f"Watching {folder_path} every {options['interval']}s (Ctrl+C to stop)...")
        try:
            while True:
                self._scan(folder_path)
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("Stopped.")

    def _scan(self, folder_path: Path):
        excluded_dirs = {name.lower() for name in settings.PROTON_DRIVE_EXCLUDE_SUBFOLDERS}
        found = 0
        for file_path in sorted(folder_path.rglob("*")):
            if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            # "~$foo.xlsx" etc. are transient lock files apps create while a file is open,
            # not real documents. ".foo" covers OS/sync metadata files (e.g. .DS_Store).
            if file_path.name.startswith("~$") or file_path.name.startswith("."):
                continue
            relative_parts = file_path.relative_to(folder_path).parts[:-1]
            if excluded_dirs.intersection(part.lower() for part in relative_parts):
                continue

            content = file_path.read_bytes()
            checksum = Document.checksum_for(content)
            rel_path = str(file_path.relative_to(folder_path))

            already_seen = ProcessedFile.objects.filter(
                path=rel_path, checksum=checksum
            ).exists()
            if already_seen:
                continue

            result = ingest.ingest_bytes(content, file_path.name, Document.Source.DRIVE_SYNC)
            ProcessedFile.objects.update_or_create(
                path=rel_path, defaults={"checksum": checksum}
            )
            found += 1

            if result.duplicate:
                self.stdout.write(f"  {rel_path}: bereits als Dokument vorhanden (übersprungen)")
            elif result.extraction_error:
                self.stdout.write(self.style.WARNING(f"  {rel_path}: {result.extraction_error}"))
            elif result.debt_proposal:
                self.stdout.write(
                    f"  {rel_path}: importiert -> Vorschlag {result.debt_proposal.creditor_name} "
                    f"{result.debt_proposal.amount} EUR"
                )
            else:
                self.stdout.write(f"  {rel_path}: importiert, kein Forderungsschreiben erkannt")

        if found:
            self.stdout.write(self.style.SUCCESS(f"{found} neue Datei(en) verarbeitet."))
        else:
            self.stdout.write("Keine neuen Dateien.")
