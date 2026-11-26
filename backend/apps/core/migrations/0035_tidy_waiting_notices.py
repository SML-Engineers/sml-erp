from django.db import migrations
from django.db.models import Max
from django.utils import timezone

# Testing T7 (21 Nov 2026): the bell kept "waiting for your approval" notices of documents
# already decided, and one reminder per day for the same document. From now on the approval
# engine settles them as it goes; this tidies the notices made before:
# - waiting notices and reminders of documents decided, or acted on since the notice was
#   made, are marked read (they stay in the list as read);
# - of several reminders for the same document and person, only the newest is kept.


def tidy(apps, schema_editor):
    Notification = apps.get_model("core", "Notification")
    ApprovalState = apps.get_model("core", "ApprovalState")
    ApprovalLog = apps.get_model("core", "ApprovalLog")
    events = ("approval_waiting", "approval_reminder")
    open_docs = set(
        ApprovalState.objects.filter(status="in_progress").values_list(
            "document_type", "document_id"
        )
    )
    last_action = {
        (row["document_type"], row["document_id"]): row["last"]
        for row in ApprovalLog.objects.values("document_type", "document_id").annotate(
            last=Max("acted_at")
        )
    }
    settled = []
    for n in Notification.objects.filter(event__in=events, read_at__isnull=True):
        key = (n.document_type, n.document_id)
        acted = last_action.get(key)
        # Decided, or acted on since this notice was made (it now waits for someone else).
        if key not in open_docs or (acted is not None and n.created_at < acted):
            settled.append(n.pk)
    Notification.objects.filter(pk__in=settled).update(read_at=timezone.now())
    newest = {}
    for n in Notification.objects.filter(event="approval_reminder").order_by("created_at", "id"):
        newest[(n.user_id, n.document_type, n.document_id)] = n.pk
    Notification.objects.filter(event="approval_reminder").exclude(pk__in=newest.values()).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_top_bar_notice"),
    ]

    operations = [migrations.RunPython(tidy, migrations.RunPython.noop)]
