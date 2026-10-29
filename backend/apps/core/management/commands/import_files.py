"""Put the files of a restored backup back into storage (backlog P1-11, docs/backups.md).
Files already in storage with the same size are skipped."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .export_files import client


class Command(BaseCommand):
    help = "Upload a folder made by export_files back into storage (restore)."

    def add_arguments(self, parser):
        parser.add_argument("folder")

    def handle(self, *args, **options):
        root = Path(options["folder"])
        if not root.is_dir():
            raise CommandError(f"No folder {root}")
        s3 = client()
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        existing = {}
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                existing[item["Key"]] = item["Size"]
        uploaded = skipped = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.endswith(".partial"):
                continue
            key = path.relative_to(root).as_posix()
            if existing.get(key) == path.stat().st_size:
                skipped += 1
                continue
            s3.upload_file(str(path), bucket, key)
            uploaded += 1
        self.stdout.write(f"Files: {uploaded} uploaded, {skipped} already there.")
