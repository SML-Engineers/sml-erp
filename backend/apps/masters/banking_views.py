"""Company bank and cash accounts API (P0-14). Rules live in banking.py."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Division
from apps.core.permissions import AreaAccess

from . import banking
from .models import ChequeBook, ChequeLeaf, CompanyAccount, DivisionBankDefault
from .services import MastersError


class ChequeBookSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()
    first = serializers.SerializerMethodField()
    last = serializers.SerializerMethodField()

    class Meta:
        model = ChequeBook
        fields = [
            "id",
            "first",
            "last",
            "first_number",
            "last_number",
            "digits",
            "received_on",
            "is_active",
            "summary",
        ]

    def get_summary(self, book):
        summary = banking.book_summary(book)
        if summary["next"] is not None:
            summary["next"] = banking.format_cheque(book, summary["next"])
        return summary

    def get_first(self, book):
        return banking.format_cheque(book, book.first_number)

    def get_last(self, book):
        return banking.format_cheque(book, book.last_number)


class LeafSerializer(serializers.ModelSerializer):
    number = serializers.SerializerMethodField()
    used_by = serializers.SlugRelatedField(read_only=True, slug_field="email")

    class Meta:
        model = ChequeLeaf
        fields = ["id", "number", "status", "reason", "used_by", "used_at"]

    def get_number(self, leaf):
        return banking.format_cheque(leaf.book, leaf.number)


class AccountSerializer(serializers.ModelSerializer):
    currency = serializers.SlugRelatedField(read_only=True, slug_field="code")
    division = serializers.SlugRelatedField(read_only=True, slug_field="code")
    custodian = serializers.SerializerMethodField()
    default_for = serializers.SerializerMethodField()
    cheque_books = serializers.SerializerMethodField()
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = CompanyAccount
        fields = [
            "id",
            "code",
            "name",
            "kind",
            "bank_name",
            "branch",
            "account_number",
            "currency",
            "division",
            "custodian",
            "float_amount",
            "is_active",
            "default_for",
            "cheque_books",
            "in_use",
        ]

    def get_custodian(self, account):
        return (
            None
            if account.custodian is None
            else {"id": account.custodian_id, "name": account.custodian.full_name}
        )

    def get_default_for(self, account):
        return sorted(account.default_for.values_list("division__code", flat=True))

    def get_cheque_books(self, account):
        return ChequeBookSerializer(account.cheque_books.all(), many=True).data

    def get_in_use(self, account) -> bool:
        from .services import is_in_use

        return is_in_use(account)


class AccountInput(serializers.Serializer):
    code = serializers.CharField(max_length=30, required=False, allow_blank=True)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    kind = serializers.CharField(max_length=20, required=False)
    bank_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    branch = serializers.CharField(max_length=100, required=False, allow_blank=True)
    account_number = serializers.CharField(max_length=40, required=False, allow_blank=True)
    currency = serializers.CharField(max_length=3, required=False)
    division = serializers.CharField(max_length=2, required=False, allow_blank=True)
    custodian = serializers.IntegerField(required=False, allow_null=True)
    float_amount = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class BookInput(serializers.Serializer):
    first_number = serializers.IntegerField()
    last_number = serializers.IntegerField()
    digits = serializers.IntegerField(required=False, default=6)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class LeafInput(serializers.Serializer):
    number = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class DefaultInput(serializers.Serializer):
    division = serializers.CharField(max_length=2)
    account = serializers.IntegerField(allow_null=True)


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _Banking(APIView):
    permission_classes = [AreaAccess]
    access_area = "banking"
    access_write_level = "manage"


class AccountListView(_Banking):
    def get(self, request):
        rows = CompanyAccount.objects.select_related("currency", "division", "custodian")
        if request.query_params.get("include_closed") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        return Response(AccountSerializer(rows, many=True).data)

    def post(self, request):
        data = AccountInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("is_active", None)
        try:
            account = banking.create_account(
                request.user,
                code=values.pop("code", ""),
                kind=values.pop("kind", ""),
                reason=values.pop("reason"),
                **values,
            )
        except MastersError as error:
            return _error(error)
        return Response(AccountSerializer(account).data, status=status.HTTP_201_CREATED)


class AccountDetailView(_Banking):
    def patch(self, request, pk):
        account = get_object_or_404(CompanyAccount, pk=pk)
        data = AccountInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("kind", None)  # the kind of an account never changes
        reason = values.pop("reason")
        try:
            account = banking.update_account(request.user, account, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(AccountSerializer(account).data)


class ChequeBookListView(_Banking):
    def post(self, request, pk):
        account = get_object_or_404(CompanyAccount, pk=pk)
        data = BookInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            book = banking.add_cheque_book(
                request.user,
                account,
                first=v["first_number"],
                last=v["last_number"],
                digits=v["digits"],
                reason=v["reason"],
            )
        except MastersError as error:
            return _error(error)
        return Response(ChequeBookSerializer(book).data, status=status.HTTP_201_CREATED)


class ChequeBookCloseView(_Banking):
    def post(self, request, pk, book_pk):
        book = get_object_or_404(ChequeBook, pk=book_pk, account_id=pk)
        try:
            book = banking.close_book(request.user, book, str(request.data.get("reason", "")))
        except MastersError as error:
            return _error(error)
        return Response(ChequeBookSerializer(book).data)


class ChequeRegisterView(_Banking):
    """Used cheque numbers of an account; the Cashier may record a spoiled leaf."""

    access_write_level = "view"  # the service requires the Cashier's or Accountant's rights

    def get(self, request, pk):
        account = get_object_or_404(CompanyAccount, pk=pk)
        leaves = account.cheques.select_related("book", "used_by")
        nxt = banking.next_cheque(account)
        return Response(
            {
                "next": None if nxt is None else banking.format_cheque(*nxt),
                "used": LeafSerializer(leaves, many=True).data,
            }
        )

    def post(self, request, pk):
        account = get_object_or_404(CompanyAccount, pk=pk)
        data = LeafInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            leaf = banking.use_cheque(
                request.user,
                account,
                data.validated_data["number"],
                status=ChequeLeaf.Status.SPOILED,
                reason=data.validated_data["reason"],
            )
        except MastersError as error:
            return _error(error)
        return Response(LeafSerializer(leaf).data, status=status.HTTP_201_CREATED)


class DivisionDefaultsView(_Banking):
    def get(self, request):
        defaults = {d.division_id: d for d in DivisionBankDefault.objects.select_related("account")}
        return Response(
            [
                {
                    "division": division.code,
                    "account": None
                    if division.pk not in defaults
                    else {
                        "id": defaults[division.pk].account_id,
                        "code": defaults[division.pk].account.code,
                    },
                }
                for division in Division.objects.filter(is_active=True)
            ]
        )

    def put(self, request):
        data = DefaultInput(data=request.data)
        data.is_valid(raise_exception=True)
        division = Division.objects.filter(code=data.validated_data["division"].upper()).first()
        if division is None:
            return _error("Unknown division.")
        account_id = data.validated_data["account"]
        account = None
        if account_id is not None:
            account = CompanyAccount.objects.filter(pk=account_id).first()
            if account is None:
                return _error("Unknown account.")
        try:
            banking.set_division_default(request.user, division, account)
        except MastersError as error:
            return _error(error)
        return self.get(request)
