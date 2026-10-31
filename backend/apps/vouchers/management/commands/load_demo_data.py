"""Demo data for trying the ERP on a PC or the test server (backlog P1-12).

    python manage.py load_demo_data

Creates a Clerk, Accountant, Director and Cashier, a Sales Executive and a Sales Manager (one
shared authenticator entry), suppliers, a bank account with a cheque book, tax rates, and
vouchers at every stage: draft, returned, waiting for the Accountant, waiting for the Director,
approved, part-paid and paid. For sales (P15-12): customers, materials, machines and costing
rates, and quotations at every stage (draft, waiting for the Director, sent and expiring this
week, won with an open sales order and an advance, lost). Everything goes through the normal
services, so every business rule applies.

It refuses to run on a production server, and runs only once per database.
"""

import io
import os
from datetime import date, timedelta
from decimal import Decimal

import pyotp
import segno
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from reportlab.lib.pagesizes import A5
from reportlab.pdfgen import canvas

from apps.accounting import services as chart
from apps.accounting import taxes
from apps.accounting.models import Account, DetailType, TaxCode, TaxComponent
from apps.core import crypto
from apps.core.models import Division, Role, User, UserRole
from apps.masters import banking, costing_rates, customers, suppliers
from apps.masters import services as masters
from apps.masters.models import Section
from apps.payments import services as payments
from apps.sales import advances, orders, workflow
from apps.sales import services as quotations
from apps.sales.orders import Delivery
from apps.sales.orders import LineInput as OrderLine
from apps.sales.services import BreakInput
from apps.sales.services import LineInput as QuoteLine
from apps.vouchers import services
from apps.vouchers.models import VoucherType
from apps.vouchers.services import CodingInput, LineInput, SplitInput

DEMO_DOMAIN = "demo.sml.lk"
# Public on purpose: demo users exist only on a PC or the test server (never production).
PASSWORD = "Demo-SML-2026!"  # noqa: S105
PEOPLE = [
    ("clerk", "Nimal Perera", "clerk"),
    ("accountant", "Kumari Silva", "accountant"),
    ("director", "Ruwan Jayasinghe", "director"),
    ("cashier", "Sunil Fernando", "cashier"),
    ("sales", "Dilini Wijesekara", "sales_executive"),
    ("salesmanager", "Chaminda Ratnayake", "sales_manager"),
]


def invoice_pdf(title: str, lines: list[str]) -> SimpleUploadedFile:
    """A small PDF that stands in for a scanned invoice."""
    out = io.BytesIO()
    page = canvas.Canvas(out, pagesize=A5)
    page.setFont("Helvetica-Bold", 16)
    page.drawString(40, 540, title)
    page.setFont("Helvetica", 11)
    for i, text in enumerate(lines):
        page.drawString(40, 500 - i * 18, text)
    page.setFont("Helvetica-Oblique", 9)
    page.drawString(40, 40, "DEMO INVOICE - for testing the SML ERP only")
    page.save()
    return SimpleUploadedFile(f"{title.lower().replace(' ', '-')}.pdf", out.getvalue())


class Command(BaseCommand):
    help = "Load demo users, suppliers, accounts and vouchers (never on production)."

    def handle(self, *args, **options):
        environment = os.environ.get("APP_ENVIRONMENT", "")
        if environment == "production" or not (settings.DEBUG or environment == "test"):
            raise CommandError("Demo data is only for a PC or the test server, never production.")
        if User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}").exists():
            raise CommandError("The demo data is already loaded.")
        secret = pyotp.random_base32()
        with transaction.atomic():
            people = self.people(secret)
            self.setup(people)
            self.vouchers(people)
            self.sales(people)
        self.report(secret)

    # --- People ---------------------------------------------------------------------------

    def people(self, secret: str) -> dict:
        people = {}
        for key, name, role in PEOPLE:
            user = User.objects.create_user(
                f"{key}@{DEMO_DOMAIN}", name, PASSWORD, all_divisions=True
            )
            UserRole.objects.create(user=user, role=Role.objects.get(code=role), reason="Demo data")
            user.two_factor_required = True
            user.totp_secret_encrypted = crypto.encrypt(secret)
            user.totp_confirmed_at = timezone.now()
            user.save()
            people[key] = User.objects.get(pk=user.pk)
        return people

    # --- Accounts, taxes, suppliers ---------------------------------------------------------

    def setup(self, p: dict) -> None:
        accountant = p["accountant"]
        start = date(timezone.localdate().year - 1, 1, 1)
        for code, rate in (("VAT", "18"), ("SSCL", "2.5")):
            component = TaxComponent.objects.get(code=code)
            if not component.rates.exists():
                taxes.add_rate(accountant, component, effective_from=start, rate=rate)

        ledger = chart.create_account(
            accountant,
            name="Commercial Bank - current account",
            account_type="bank",
            detail_type=DetailType.objects.get(name="Current account"),
            number="1031",
        )
        self.bank = banking.create_account(
            accountant,
            code="com-cur",
            kind="current",
            name="Commercial Bank current",
            bank_name="Commercial Bank of Ceylon",
            branch="Ja-Ela",
            account_number="1000234567",
            ledger_account=ledger.pk,
        )
        banking.add_cheque_book(accountant, self.bank, first=100001, last=100100)
        for code in ("WS", "IM", "HO"):
            banking.set_division_default(accountant, Division.objects.get(code=code), self.bank)

        clerk = p["clerk"]
        rows = [
            ("steel", "Lanka Steel Traders", "supplier", "Commercial Bank", "8001234567"),
            ("resin", "Polymer Resins Lanka (Pvt) Ltd", "supplier", "Sampath Bank", "001234567890"),
            ("oxygen", "Ceylon Oxygen Ltd", "supplier", "Hatton National Bank", "009011223344"),
            ("ceb", "Ceylon Electricity Board", "utility", None, None),
            ("dialog", "Dialog Axiata PLC", "utility", None, None),
        ]
        self.payees = {}
        for key, name, category, bank, number in rows:
            payee = suppliers.create_supplier(clerk, {"name": name, "category": category})
            if bank:
                suppliers.add_bank_account(
                    accountant,
                    payee,
                    {"bank_name": bank, "account_name": name, "account_number": number},
                )
                suppliers.acknowledge_bank_change(accountant, payee)
            self.payees[key] = payee

    # --- Vouchers -----------------------------------------------------------------------------

    def voucher(self, p, division, type_code, payee, lines, attach=True, description=""):
        clerk = p["clerk"]
        voucher = services.save(
            clerk,
            None,
            voucher_type=VoucherType.objects.get(code=type_code),
            division=Division.objects.get(code=division),
            payee=self.payees[payee],
            description=description,
            lines=lines,
        )
        if attach:
            services.add_attachment(
                clerk,
                voucher,
                invoice_pdf(
                    f"Invoice {lines[0].invoice_no}",
                    [self.payees[payee].name, f"Amount: LKR {lines[0].amount}"],
                ),
            )
        return voucher

    def code(self, accountant, voucher, account, division=None, splits=()):
        voucher = services.code_lines(
            accountant,
            voucher,
            [
                CodingInput(
                    line_no=line.line_no,
                    account=Account.objects.get(number=account),
                    division=None if splits else Division.objects.get(code=division),
                    tax_code=line.tax_code,
                    tax_amount=line.tax_amount,
                    splits=list(splits),
                )
                for line in voucher.lines.all()
            ],
        )
        return voucher

    def vouchers(self, p: dict) -> None:
        clerk, accountant, director, cashier = (
            p["clerk"],
            p["accountant"],
            p["director"],
            p["cashier"],
        )
        vat = TaxCode.objects.get(code="VAT")
        today = timezone.localdate()

        def line(amount, invoice, days_ago, text, tax_code=None):
            return LineInput(amount, invoice, today - timedelta(days=days_ago), text, tax_code)

        def division(code):
            return Division.objects.get(code=code)

        # 1. A draft, not yet submitted.
        self.voucher(p, "WS", "CHQ", "steel", [line("125000.00", "LST-4471", 2, "MS plates 10 mm")])

        # 2. Waiting for the Accountant: a shared electricity bill (to split by division).
        v = self.voucher(
            p, "HO", "ONL", "ceb", [line("48750.00", "CEB-OCT-118", 3, "October electricity")]
        )
        services.submit(clerk, v)

        # 3. Waiting for the Accountant: resin with VAT.
        v = self.voucher(
            p, "IM", "CHQ", "resin", [line("290000.00", "PRL-2210", 4, "PP resin 2 t", vat)]
        )
        services.submit(clerk, v)

        # 4. Returned to the Clerk by the Accountant.
        v = self.voucher(
            p, "HO", "ONL", "dialog", [line("12990.00", "DLG-10-77", 5, "Internet, October")]
        )
        services.submit(clerk, v)
        services.send_back(
            accountant, v, "Please attach the bill page that shows the account number."
        )

        # 5. Waiting for the Director (coded and approved by the Accountant).
        v = self.voucher(
            p, "WS", "CHQ", "oxygen", [line("18400.00", "COX-5521", 6, "Oxygen and acetylene")]
        )
        services.submit(clerk, v)
        v = self.code(accountant, v, "5050", "WS")
        services.approve(accountant, v, "Coded to factory overheads")

        # 6. Approved, not yet paid: electricity split across the divisions.
        v = self.voucher(
            p, "HO", "ONL", "ceb", [line("61200.00", "CEB-SEP-097", 30, "September electricity")]
        )
        services.submit(clerk, v)
        v = self.code(
            accountant,
            v,
            "6100",
            splits=[
                SplitInput(division("WS"), percent="45"),
                SplitInput(division("IM"), percent="45"),
                SplitInput(division("HO"), percent="10"),
            ],
        )
        services.approve(accountant, v, "Split by sub-meter readings")
        services.approve(director, v)

        # 7. Part-paid by cheque.
        v = self.voucher(
            p, "IM", "CHQ", "resin", [line("150000.00", "PRL-2156", 20, "PP resin 1 t")]
        )
        services.submit(clerk, v)
        v = self.code(accountant, v, "5010", "IM")
        services.approve(accountant, v)
        services.approve(director, v)
        payments.record(
            cashier,
            v,
            account=self.bank,
            method="cheque",
            amount="50000.00",
            payment_date=today,
            notes="First instalment",
        )

        # 8. Paid in full by bank transfer.
        v = self.voucher(
            p, "WS", "ONL", "steel", [line("86500.00", "LST-4402", 25, "Round bars EN8")]
        )
        services.submit(clerk, v)
        v = self.code(accountant, v, "5010", "WS")
        services.approve(accountant, v)
        services.approve(director, v)
        payments.record(
            cashier,
            v,
            account=self.bank,
            method="transfer",
            amount=Decimal("86500.00"),
            payment_date=today,
            reference="CEFT 778812",
        )

    # --- Sales (Phase 1.5) ---------------------------------------------------------------------

    def sales(self, p: dict) -> None:
        accountant, director, cashier = p["accountant"], p["director"], p["cashier"]
        executive = p["sales"]
        today = timezone.localdate()

        # Rates the Accountant keeps (Sales -> Costing rates), in force from today.
        en8 = costing_rates.create_material(
            accountant,
            {
                "code": "EN8",
                "name": "EN8 steel bar",
                "kind": "metal",
                "form": "round_bar",
                "density": "7.850",
            },
        )
        costing_rates.add_material_rate(accountant, en8, effective_from=today, rate="450")
        pp = costing_rates.create_material(
            accountant, {"code": "PP-H", "name": "Polypropylene homopolymer", "kind": "resin"}
        )
        costing_rates.add_material_rate(accountant, pp, effective_from=today, rate="520")
        for code, overhead, margin, setup in (
            ("WS", "15", "20", "1500"),
            ("IM", "12", "18", "2500"),
        ):
            costing_rates.add_costing_rate(
                accountant,
                Division.objects.get(code=code),
                effective_from=today,
                overhead_pct=overhead,
                margin_pct=margin,
                setup_rate=setup,
            )
        for code, section, name, rate in (
            ("C-LAT-01", "C-LAT", "CNC lathe 1", "3000"),
            ("IMM-01", "IM-MLD", "Haitian 250", "4200"),
        ):
            machine = masters.create_machine(
                code=code, section=Section.objects.get(code=section), name=name
            )
            masters.add_rate(machine, effective_from=today, rate=rate)

        # Customers (Sales -> Customers).
        def customer(name, address, contact, days=30):
            c = customers.create_customer(
                executive,
                {"name": name, "delivery_address": address, "payment_terms_days": days},
            )
            customers.add_contact(executive, c, {"name": contact})
            return c

        unilever = customer("Unilever Sri Lanka Ltd", "Grandpass, Colombo 14", "Nimali Perera")
        rhino = customer("Rhino Roofing Products Ltd", "Wattala", "Sunil Gamage", days=45)
        tea = customer("Lanka Tea Machinery (Pvt) Ltd", "Kandy Road, Kadawatha", "Ajith Kumara")

        def quote(customer, division, lines, **values):
            return quotations.save(
                executive,
                None,
                customer=customer,
                division=Division.objects.get(code=division),
                lines=lines,
                **values,
            )

        def approved(*args, **values):
            q = quote(*args, **values)
            workflow.submit(executive, q)
            return workflow.approve(director, q, "Prices checked")

        # 1. A draft quotation, not yet sent for approval.
        quote(
            tea,
            "WS",
            [
                QuoteLine(
                    description="Drive shaft, EN8, 40 dia x 600", quantity="50", unit_price="4800"
                )
            ],
        )

        # 2. Waiting for the Director.
        q = quote(
            rhino,
            "IM",
            [
                QuoteLine(
                    description="Roof sheet clip, PP, grey", quantity="100000", unit_price="3.10"
                )
            ],
        )
        workflow.submit(executive, q, "Repeat customer, same price as last year")

        # 3. Approved and sent; it expires within the week.
        q = approved(
            unilever,
            "IM",
            [
                QuoteLine(
                    description="Bottle cap 28 mm, PP, white", quantity="20000", unit_price="2.60"
                )
            ],
            valid_until=today + timedelta(days=5),
        )
        workflow.mark_sent(executive, q)

        # 4. Won: a sales order with three monthly call-offs and an advance received.
        q = approved(
            unilever,
            "IM",
            [
                QuoteLine(
                    description="Cap 38 mm, PP, white",
                    quantity="60000",
                    unit_price="2.35",
                    breaks=[BreakInput("50000", "2.10")],
                )
            ],
        )
        q = workflow.mark_sent(executive, q)
        q = workflow.record_outcome(executive, q, accepted=True, reason="price")
        order = orders.from_quotation(executive, q)
        line = order.lines.get()
        orders.save(
            executive,
            order,
            customer_po="UL/PO/7781",
            po_date=today,
            lines=[
                OrderLine(
                    quantity="60000",
                    quotation_line=line.quotation_line,
                    schedule=[Delivery(today + timedelta(days=d), "20000") for d in (14, 44, 74)],
                )
            ],
        )
        order = orders.confirm(executive, order)
        advance = advances.record(
            cashier,
            customer=unilever,
            account=self.bank,
            method="transfer",
            amount="50000.00",
            receipt_date=today,
            reference="CEFT 901122",
            sales_order=order,
        )
        advances.approve(accountant, advance)

        # 5. Lost on price.
        q = approved(
            tea, "WS", [QuoteLine(description="Gear blank, EN8", quantity="20", unit_price="12500")]
        )
        q = workflow.mark_sent(executive, q)
        workflow.record_outcome(
            executive, q, accepted=False, reason="price", note="A competitor quoted 9,800 each"
        )

    # --- The instructions ----------------------------------------------------------------------

    def report(self, secret: str) -> None:
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=f"demo@{DEMO_DOMAIN}", issuer_name="SML ERP demo"
        )
        out = self.stdout
        out.write("")
        out.write(self.style.SUCCESS("Demo data loaded."))
        out.write("")
        out.write(
            "Sign in at the ERP's address with any of these (password for all: " + PASSWORD + "):"
        )
        for key, name, role in PEOPLE:
            out.write(f"  {key}@{DEMO_DOMAIN:<20} {name:<20} {role.title()}")
        out.write("")
        out.write("All of them use ONE authenticator entry. In Google or Microsoft Authenticator:")
        out.write("  + > Enter a setup key > Account: SML ERP demo > Key: " + secret)
        out.write("  (time based), or scan this QR code:")
        out.write("")
        buffer = io.StringIO()
        segno.make(uri, error="L").terminal(out=buffer, compact=True)
        out.write(buffer.getvalue())
