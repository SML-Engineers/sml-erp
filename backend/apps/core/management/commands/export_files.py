"""Copy every stored file (scanned invoices and others) into a plain folder, for the nightly
backup (backlog P1-11). The folder is kept between runs as a mirror: only new or changed
files are downloaded, and files no longer in storage are removed from it."""

from pathlib import Path

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand


def client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )


def safe_path(root: Path, key: str) -> Path:
    path = (root / key).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"Unsafe file name in storage: {key!r}")
    return path


class Command(BaseCommand):
    help = "Mirror all stored files into a folder (for backups)."

    def add_arguments(self, parser):
        parser.add_argument("folder")

    def handle(self, *args, **options):
        root = Path(options["folder"])
        root.mkdir(parents=True, exist_ok=True)
        s3 = client()
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        seen, copied = set(), 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                key = item["Key"]
                path = safe_path(root, key)
                seen.add(path)
                if path.exists() and path.stat().st_size == item["Size"]:
                    continue  # stored files are never changed in place, only added
                path.parent.mkdir(parents=True, exist_ok=True)
                partial = path.with_name(path.name + ".partial")
                s3.download_file(bucket, key, str(partial))
                partial.replace(path)
                copied += 1
        removed = 0
        for path in root.rglob("*"):
            if path.is_file() and path.resolve() not in seen:
                path.unlink()
                removed += 1
        self.stdout.write(f"Files: {len(seen)} in storage, {copied} copied, {removed} removed.")
