import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the private file-storage bucket if it does not exist yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wait",
            type=int,
            default=90,
            help="Seconds to keep retrying while the storage service starts up.",
        )

    def handle(self, *args, **options):
        client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        deadline = time.monotonic() + options["wait"]

        while True:
            try:
                existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
                break
            except (BotoCoreError, ClientError) as error:
                if time.monotonic() >= deadline:
                    raise CommandError(f"File storage is not reachable: {error}") from error
                self.stdout.write("Waiting for file storage to start...")
                time.sleep(3)

        if bucket in existing:
            self.stdout.write(f"Bucket '{bucket}' already exists.")
            return
        client.create_bucket(Bucket=bucket)  # private by default: no public policy is set
        self.stdout.write(self.style.SUCCESS(f"Created bucket '{bucket}'."))
