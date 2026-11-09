"""Bring every open order's costs up to date (backlog P3-16): run at month end, or after a
change of rates, from the server."""

from django.core.management.base import BaseCommand

from apps.production import costs


class Command(BaseCommand):
    help = "Bring every job order's and production order's costs up to date."

    def handle(self, *args, **options):
        made = costs.sync_open()
        self.stdout.write(f"{made} order cost entries added.")
