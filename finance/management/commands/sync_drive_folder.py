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

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ... import ingest
from ...extraction import EXCEL_EXTENSIONS, IMAGE_EXTENSIONS, PDF_EXTENSIONS
from ...models import Document, ProcessedFile

SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS | EXCEL_EXTENSIONS


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
        folder = settings.PROTON_DRIVE_SYNC_FOLDER
        if not folder:
            raise CommandError(
                "PROTON_DRIVE_SYNC_FOLDER is not set. Point it at the local folder that "
                "Proton Drive Bridge/the desktop app syncs your debt-letters folder to."
            )
        folder_path = Path(folder)
        if not folder_path.is_dir():
            raise CommandError(f"PROTON_DRIVE_SYNC_FOLDER does not exist or is not a directory: {folder}")

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
        found = 0
        for file_path in sorted(folder_path.rglob("*")):
            if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
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
            elif result.debt:
                self.stdout.write(
                    f"  {rel_path}: importiert -> {result.debt.creditor.name} "
                    f"{result.debt.amount} {result.debt.currency}"
                )
            else:
                self.stdout.write(f"  {rel_path}: importiert, kein Betrag erkannt")

        if found:
            self.stdout.write(self.style.SUCCESS(f"{found} neue Datei(en) verarbeitet."))
        else:
            self.stdout.write("Keine neuen Dateien.")
