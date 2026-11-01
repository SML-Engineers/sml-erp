"""Items and stores API (P16-03). Rules live in items.py."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import Account
from apps.core.permissions import AreaAccess
from apps.masters import excel
from apps.masters.models import Material
from apps.masters.services import MastersError

from . import items
from .models import Item, Store


class _Stores(APIView):
    """Viewing needs Stores: View; changes are checked by the service (Purchasing, Stores or
    Accounting: Enter for items; Settings: Manage for stores)."""

    permission_classes = [AreaAccess]
    access_area = "stores"
    access_write_level = "view"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _item(i: Item) -> dict:
    return {
        "id": i.id,
        "code": i.code,
        "name": i.name,
        "description": i.description,
        "category": i.category,
        "unit": i.unit,
        "is_stock": i.is_stock,
        "package_type": i.package_type,
        "inspection_required": i.inspection_required,
        "inventory_account": None
        if i.inventory_account is None
        else {"number": i.inventory_account.number, "name": i.inventory_account.name},
        "expense_account": None
        if i.expense_account is None
        else {"number": i.expense_account.number, "name": i.expense_account.name},
        "material": i.material.code if i.material else None,
        "division": i.division.code if i.division else None,
        "notes": i.notes,
        "is_active": i.is_active,
        "used": i.first_used_at is not None,
    }


def _store(s: Store) -> dict:
    return {
        "id": s.id,
        "code": s.code,
        "name": s.name,
        "division": s.division.code,
        "kind": s.kind,
        "is_active": s.is_active,
        "used": s.first_used_at is not None,
    }


def _rows():
    return Item.objects.select_related(
        "inventory_account", "expense_account", "material", "division"
    )


FIELDS = (
    "code",
    "name",
    "description",
    "category",
    "unit",
    "is_stock",
    "package_type",
    "inspection_required",
    "inventory_account",
    "expense_account",
    "material",
    "division",
    "notes",
)


def _values(data) -> dict:
    return {k: data[k] for k in FIELDS if k in data}


class ItemListView(_Stores):
    def get(self, request):
        rows = items.search(_rows(), request.query_params.get("q", ""))
        params = request.query_params
        if params.get("category"):
            rows = rows.filter(category=params["category"])
        if params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        return Response([_item(i) for i in rows[:3000]])

    def post(self, request):
        try:
            item = items.create_item(request.user, _values(request.data))
        except MastersError as error:
            return _error(error)
        return Response(_item(_rows().get(pk=item.pk)), status=status.HTTP_201_CREATED)


class ItemOptionsView(_Stores):
    """What the item form offers, and what this user may do."""

    def get(self, request):
        return Response(
            {
                "can_enter": items.can_enter(request.user),
                "can_set_accounts": items.can_set_accounts(request.user),
                "categories": [{"value": v, "label": label} for v, label in Item.Category.choices],
                "units": [v for v, _ in Item.Unit.choices],
                "package_types": [
                    {"value": v, "label": label} for v, label in Item.PackageType.choices
                ],
                "inventory_accounts": [
                    {"number": a.number, "name": a.name}
                    for a in Account.objects.filter(
                        is_active=True, account_type__in=items.INVENTORY_TYPES
                    ).order_by("number")
                ],
                "expense_accounts": [
                    {"number": a.number, "name": a.name}
                    for a in Account.objects.filter(
                        is_active=True, account_type__in=items.EXPENSE_TYPES
                    ).order_by("number")
                ],
                "materials": [
                    {"code": m.code, "name": m.name}
                    for m in Material.objects.filter(is_active=True).order_by("code")
                ],
            }
        )


class ItemDetailView(_Stores):
    def get(self, request, pk):
        return Response(_item(get_object_or_404(_rows(), pk=pk)))

    def patch(self, request, pk):
        item = get_object_or_404(Item, pk=pk)
        try:
            item = items.update_item(
                request.user,
                item,
                _values(request.data),
                reason=str(request.data.get("reason", "")),
            )
        except MastersError as error:
            return _error(error)
        return Response(_item(_rows().get(pk=item.pk)))

    def delete(self, request, pk):
        item = get_object_or_404(Item, pk=pk)
        try:
            items.delete_item(request.user, item)
        except MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ItemActiveView(_Stores):
    def post(self, request, pk):
        item = get_object_or_404(Item, pk=pk)
        try:
            item = items.set_active(
                request.user,
                item,
                bool(request.data.get("active")),
                reason=str(request.data.get("reason", "")),
            )
        except MastersError as error:
            return _error(error)
        return Response(_item(_rows().get(pk=item.pk)))


class ItemExportView(_Stores):
    def get(self, request):
        rows = _rows()
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        response = HttpResponse(
            items.export_workbook(rows.order_by("code")),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        today = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="items-{today}.xlsx"'
        return response


class ItemImportView(_Stores):
    """Import items from Excel. `dry_run` checks every row without saving."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        if uploaded.size > excel.MAX_BYTES:
            return _error("The file must be 5 MB or smaller.")
        dry_run = str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes")
        try:
            counts = items.import_workbook(
                uploaded.read(),
                user=request.user,
                reason=str(request.data.get("reason", "")),
                dry_run=dry_run,
            )
        except excel.ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"dry_run": dry_run, **counts})


class _Settings(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


class StoreListView(_Settings):
    def get(self, request):
        return Response([_store(s) for s in Store.objects.select_related("division")])

    def post(self, request):
        try:
            store = items.create_store(request.user, dict(request.data.items()))
        except MastersError as error:
            return _error(error)
        return Response(_store(store), status=status.HTTP_201_CREATED)


class StoreDetailView(_Settings):
    def patch(self, request, pk):
        store = get_object_or_404(Store, pk=pk)
        try:
            store = items.update_store(
                request.user,
                store,
                {k: request.data[k] for k in ("name", "is_active") if k in request.data},
                reason=str(request.data.get("reason", "")),
            )
        except MastersError as error:
            return _error(error)
        return Response(_store(store))
