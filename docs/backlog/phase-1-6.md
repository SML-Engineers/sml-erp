# Backlog — Phase 1.6 (purchasing, goods receipt and supplier invoices)

Purchase orders, goods receiving notes with QC acceptance, stock, supplier invoices with
three-way matching, and payment vouchers made from matched invoices (spec 5A, with the
receiving details of spec 6A). Owner's requirement of 31 Oct 2026: suppliers are paid only for
goods actually received, accepted and verified. Same rules as before: work top to bottom, one
task per pull request, and a task is done when every acceptance criterion is a passing test
(or, for pure UI items, checked by the owner).

```
Purchase Order → GRN (Stores) → QC acceptance → Supplier Invoice (3-way match)
   (Director)                                    → Payment Voucher (Clerk → Accountant → Director)
                                                 → Payment (Cashier)
```

**Owner's decisions (31 Oct 2026):** built next, while Phase 1.5 is tested; Stores receive and
QC accepts (one stores person enters and confirms the GRN); no tolerance in the three-way match (differences need the Director); the
Purchasing Officer raises POs and the Director approves every PO; supplier + invoice number
is unique everywhere (spec 5A, decisions 1–5).

**Already built, used here:** suppliers and their bank details (P1), the approval engine and
reminders, number series, tax codes, the chart of accounts and journal entries, payment
vouchers and payments with the Director lock, divisions, sections and the audit log.

Status: `[ ]` to do · `[x]` done

---

## A. Controls available at once

- [x] **P16-01 Duplicate supplier invoices refused** (spec 4.4, 5A decision 5)
  The same supplier and invoice number (ignoring case and spaces) cannot be on two vouchers
  that still count; another supplier may use the same number; a deleted, rejected, amended or
  cancelled voucher frees it. Service message and a database trigger.

## B. Masters and roles

- [x] **P16-02 Roles and access** (spec 5A.6, 6A.5)
  Switch on the Purchasing Officer, Stores Executive (today's "Store Supervisor"), Stores
  Manager and QC Inspector roles. Conflicting pairs warn the Admin: Purchasing Officer with
  Stores; Stores with Accounts Clerk or Cashier. A stores role together with QC Inspector is
  refused (QC is the check on the single stores person). The Director approves POs; stores
  staff never approve payments.
  - Done: the three roles are switched on (core migration 0019); the stores role is named
    "Stores Manager / Executive" (one stores person). Ordering + receiving, receiving +
    invoicing, receiving + paying, and ordering + paying warn and need a reason; stores + QC
    Inspector is refused even with a reason. QC acceptance itself (P16-08) will also refuse the
    person who confirmed the GRN, so an access override cannot get around it.

- [x] **P16-03 Item master and stores** (spec 5A.3, 6A)
  Items: code (immutable once used), description, unit, category, stock or non-stock, package
  type, inspection needed, inventory account, division; Excel import and export. Stores per
  division: Main, Quarantine, Rejected. Deactivated, never deleted, once used.
  - Done: new app `inventory`. Item codes are typed (e.g. PP-H-WHITE), up to 20 letters,
    digits or dashes. The Purchasing Officer, the stores person and the Accountant add items;
    only the Accountant chooses accounts, otherwise raw materials and bought-out parts go to
    1210 Raw materials and consumables, spares and packing to 1240. A non-stock item has no
    store, package or QC. Stores WS-MAIN, WS-QUAR, WS-REJ, IM-MAIN, IM-QUAR, IM-REJ are set up;
    the Admin adds more main stores (Settings → Stores); one quarantine and one rejected store
    per division (database constraint). Used items and stores keep their codes (database
    guard). Menu: Purchasing and stores → Items.

## C. Purchase orders

- [x] **P16-04 Purchase orders** (spec 5A.1)
  Raised by the Purchasing Officer from the supplier and item master; numbered
  PO{YY}{MM}{DD}{XX}; quantities, agreed prices, tax, delivery dates, terms.
  - Director approval for every PO through the approval engine (never the creator); reminders.
  - An approved PO never changes (database guard); a revision goes through approval again.
  - Status: draft, awaiting approval, approved, partly received, received, closed (reason),
    cancelled (reason; refused once goods are received).
  - Done: new app `purchasing`. A PO is in the supplier's currency at the day's rate, with
    "Net <days>" terms from the supplier and the company address as "Deliver to"; items must
    be active and of the PO's division (or all divisions). Sending needs a delivery date. On
    approval the supplier's and items' codes become fixed. A revision is allowed only while
    nothing has been received; the old PO is marked "Replaced by a revision" at once.
    Reminder to the Director after 2 days. Menu: Purchasing and stores → Purchase orders.

- [x] **P16-05 Printing and emailing the PO**
  PDF in the layout of the owner's sample PO26061701, the company letterhead, emailed to the
  supplier's contact; a draft prints marked DRAFT and cannot be emailed.
  - Done: laid out like PO26061701 (To:, P.O. No., Date, Pay Mode, Pay Terms; Delivery Date,
    Deliver to; Item, Description, UOM, Qty, Rate, Amount; Grand Total; the two instructions;
    Subtotal and VAT Total box; Yours Faithfully; Managing Director and Checked By). Marked
    DRAFT – NOT APPROVED until approved, CANCELLED or REPLACED BY A REVISION. Emailed by the
    Purchasing Officer to the supplier's email, only when approved or partly received, with
    the "purchase_order" message the Admin edits (Settings → Document email). Item codes may
    now contain slashes and dots, like 48/BL/08.

## D. Receiving and inspection

- [x] **P16-06 Goods receiving note** (spec 5A.2)
  Against an approved PO only, filled from it; the stores person enters received and damaged
  quantities, delivery note, vehicle, photos, and confirms it (one stores person, owner's
  decision; QC acceptance by someone else is the check). Numbered GRN{YY}{MM}{DD}{XX}.
  - Partial deliveries and several GRNs per PO; the PO's received quantities and status
    update.
  - Excess over the PO is flagged and cannot be accepted without the Director.
  - A confirmed GRN never changes (database guard); a reversal with a reason needs the
    Director and is linked.
  - Confirmed goods go to the Quarantine store.
  - Done: the stores person picks an approved or partly received PO (Purchasing and stores →
    Goods receipts → Receive goods); the lines start with what the PO still expects. They
    enter received (damaged included) and damaged quantities, the delivery note, vehicle and
    supplier's invoice number, and photos or scans (JPG, PNG, PDF, at most 20 MB, checked from
    the file). Confirming adds the good quantity to the PO, which becomes Partly received or
    Received. Good quantity above what the PO still expects holds the GRN for the Director, who
    accepts the excess or sends the GRN back. A confirmed GRN, its lines and photos never
    change (database guard); photos can still be added. A reversal needs a reason and the
    Director, takes the quantities off the PO again, and is final. Reminders after 1 day.

- [x] **P16-07 Package-level receiving** (spec 6A.2)
  Bags, bars, plates, coils, boxes: one row per package with lot or heat number, gross, tare,
  net, count; "40 bags × 25 kg" fast entry; variance against declared and invoiced weight;
  QR labels per package.
  - Done: an item that arrives by package (Items: "Arrives as") is received one row per bag,
    bundle, plate, coil or box, each with its own lot number (GRN number - line - package,
    e.g. GRN26110101-1-007). Weights are typed from the scale (owner, 1 Nov 2026); the tare is
    filled from the item. The line's received quantity is the total of its packages (net kg,
    metres or pieces, by the item's unit) and damaged packages count as damaged. Checks,
    highlighted outside the item's tolerance (0.5% to start): bags against the declared
    weight, bars against the item's kg per metre, plates against length × width × thickness
    × density. The GRN keeps the tolerance in force when entered (rule 11). Fast entry
    ("40 × 25 kg declared") adds the rows; the GRN cannot be confirmed until every package is
    weighed or counted. QR labels 100 × 50 mm, one per package, for a sticker printer (owner,
    1 Nov 2026), marked QUARANTINE. Packages never change once the GRN is confirmed
    (database guard). The variance against the invoiced weight comes with supplier invoices
    (P16-10); reading a connected scale directly can be added later.

- [x] **P16-08 QC inspection and acceptance** (spec 6A.3, 6A.4)
  Inspection plans per item or category; the QC Inspector records results and accepts,
  rejects, or accepts under deviation (Production Manager, Director for critical materials).
  Accepted quantities move to available stock; rejected ones to the Rejected store for return.
  The QC Inspector cannot change received quantities.
  - Owner's decisions (1 Nov 2026): the Director approves every deviation until the
    Production Manager role is switched on; QC decides per package (rejects single bags or
    bundles and accepts the rest).
  - Done: plans per item, or per category for items without their own; checks measured
    (min/max) or pass/fail, some critical; sampling every package, a fixed number or a
    percentage. Confirmed GRN lines wait in Purchasing and stores → QC inspection. The QC
    Inspector (never the person who received or confirmed the GRN) starts an inspection,
    which copies the plan's checks (rule 11), enters results, attaches certificates, and
    accepts (all, all but some packages, or part of an item not received by package),
    rejects all with a reason, or asks the Director to accept under deviation with a reason.
    A failed critical check cannot simply be accepted; a deviation needs a failed check.
    Items that need no inspection are accepted automatically on confirming. A decided
    inspection never changes (database guard). A GRN QC has started on can no longer be
    reversed. The stock movements into Available and Rejected come with P16-09.

## E. Stock and accounting

- [x] **P16-09 Stock movements and valuation** (spec 5A.3, IAS 2)
  Every movement recorded by item, store and lot; balances computed, never typed; weighted
  average cost. On acceptance: Dr Inventory, Cr Goods received not invoiced (GRNI), at the PO
  price, balanced and never edited. Stock on hand report with value.
  - Done: confirming a GRN puts the good quantity in the division's quarantine store and
    damaged goods in its rejected store, lot by lot (package lot numbers, or GRN-line), at
    no value. QC's final decision (or confirming an item that needs no inspection) moves
    accepted goods to the main store at the PO price in LKR (PO exchange rate) and rejected
    goods to the rejected store at no value, and posts Dr the item's inventory account, Cr
    Goods received not invoiced (new system account 2190), with the division and supplier.
    Approving a GRN reversal takes everything back out and reverses the journal entry.
    Movements are insert-only (database guard); balances and the weighted average cost
    (value ÷ quantity in the main stores) are worked out from them. Non-stock items have no
    movements. Purchasing and stores → Stock on hand, with lots and movements.

## F. Supplier invoices and payment

- [x] **P16-10 Supplier invoices with three-way match** (spec 5A.4)
  Entered by the Accounts Clerk with the scan, linked to GRN lines; supplier + invoice number
  unique (service and database). Line by line: invoiced quantity ≤ accepted and not yet
  invoiced; price = PO price; tax as on the PO. Any difference: **Held: discrepancy**, listed;
  the Accountant investigates; the Director approves an exception with a reason. Posting: Dr
  GRNI, Dr VAT input, Cr Accounts payable.
  - Done: Vouchers → Supplier invoices. The Clerk chooses the supplier and division, ticks the
    GRN lines with goods QC accepted and not yet invoiced, types quantity, price, tax code and
    the printed total as on the invoice, attaches the scan and clicks Match. More than
    accepted and not yet invoiced is refused outright (never an exception). A price or tax
    different from the PO, or a printed total different from the worked-out one, holds the
    invoice with the differences listed; the Clerk can send it back to draft for a typing
    mistake or cancel it (supplier's credit note or new invoice); the Accountant asks the
    Director to approve the exception with a reason. Posting, in LKR at the PO rate: Dr GRNI
    at the PO price (non-stock items: their expense account), Dr recoverable taxes (VAT
    input), Dr/Cr the difference to the new system account 5060 Purchase price variance, Cr
    Accounts payable for the supplier; due date from the supplier's terms. Supplier +
    invoice number is unique across supplier invoices and vouchers (service and database,
    both ways). A posted or cancelled invoice never changes (database guard).

- [x] **P16-11 Payment vouchers from matched invoices** (spec 5A.5)
  A voucher for PO goods is made from matched or exception-approved invoices, carries the PO,
  GRN and invoice links, and can never exceed what is unpaid on them; the approvers see PO,
  GRN and invoice side by side. Clerk → Accountant → Director → Cashier as today. Advance
  payment on a PO only as a Director-approved exception. Non-stock purchases stay as today.
  - Done: on a voucher for a supplier, the Clerk sees that supplier's matched invoices of the
    voucher's division with something unpaid and adds them with "Pay"; the line copies the
    invoice number and date, has no tax (it is on the invoice) and is coded to Accounts
    payable, which the Accountant cannot change. A line can pay part of an invoice; all the
    vouchers that still count never pay more than the invoice (service and database), and a
    deleted, rejected, amended or cancelled voucher frees its amount. The invoice's scan is
    enough to submit. The voucher and the review page show PO, GRN (received and accepted)
    and invoice side by side; the supplier invoice shows what is on vouchers and still to
    pay. Payment then posts Dr Accounts payable, Cr Bank.
  - Advance payments on a PO are split out as P16-11a below.

- [x] **P16-11a Advance payments on a purchase order**
  A voucher line paying in advance on an approved PO (Director-approved exception), posted to
  1320 Advances to suppliers, then set off against the supplier's invoice when it is matched.
  - Done: on a voucher, "Pay an advance on a purchase order" lists the payee's approved POs
    still waiting for goods in the voucher's division; the line needs a reason, is coded to
    Advances to suppliers (1320, now a system account), has no tax, and the advances on a PO
    never add up to more than the PO (service and database). The voucher shows it as an
    exception to the Accountant and the Director, who approve it as any voucher. Once the
    voucher is fully paid, the advance is set off against the supplier's invoice for that PO
    when it is posted (Dr Accounts payable, Cr Advances to suppliers), or later by the
    Accountant ("Set off advances") if it was paid after the invoice; never more than the
    invoice still owes (database). What is set off reduces what can still go on vouchers.
    Set-offs are never changed (database guard).

- [x] **P16-12 Supplier returns and debit notes**
  Rejected or short goods returned to the supplier with a return note; a debit note reduces
  what is owed; linked to the GRN and invoice.
  - Done: Purchasing and stores → Supplier returns. The stores person returns lots of one GRN
    still in store, with a reason. Rejected or damaged goods (rejected store, no value) go
    back when the stores person confirms; nothing is posted. Goods QC had accepted (main
    store) need the Director: their stock value leaves the inventory account against GRNI
    for the part not yet invoiced, and against the supplier with a debit note (DN…) for the
    part already invoiced (Dr Accounts payable at the invoice price and tax, Cr recoverable
    tax, any difference to Purchase price variance). Returned goods can no longer be
    invoiced; debit notes reduce what is still to pay on the invoice (also in the database
    limits for vouchers and advance set-offs). Either way the PO expects the goods again for
    a replacement. Confirmed returns and debit notes never change (database guards). Short
    deliveries need no return: only what arrived is received and invoiced. A printed return
    note can follow with the reports (P16-13).

## G. Reports and go-live

- [x] **P16-13 Traceability and reports** (spec 5A.7, 6A.7)
  The full trail on every document (PO ↔ GRN ↔ QC ↔ invoice ↔ voucher ↔ payment); open POs
  and overdue deliveries; GRNI; invoices held; exceptions approved; receipts and rejections
  by supplier; stock on hand. Excel and PDF; purchasing and stores tiles on the dashboard.
  - Done: Purchasing and stores → Purchasing reports (Purchasing: View): open POs with what is
    still to come, overdue deliveries (days late), GRNI at the PO price next to the GRNI
    account's balance, invoices held with their differences and days held, exceptions the
    Director approved (GRN excesses, QC deviations, invoice differences, returns of accepted
    goods, advance payments) with the reason and approver, and receipts and rejections by
    supplier (late deliveries, rejected %, returns); each to Excel and PDF, as is stock on
    hand. A Trail panel on every PO, GRN and supplier invoice links the PO, its revisions,
    GRNs, QC, invoices (unpaid), returns, vouchers (advances marked) and payments. Home page
    tiles: waiting for me, open and overdue POs, waiting for QC, GRNI, invoices held, stock
    value. The goods return note prints (PDF) for the supplier, with signatures.

- [ ] **P16-14 User acceptance testing and go-live**
  Test scripts per role (Purchasing Officer, Stores Executive and Manager, QC Inspector,
  Accounts Clerk, Accountant, Director, Cashier); items, stores and open POs loaded; the
  accounting treatment confirmed with the auditors; the owner signs off.
  - Preparation (2 Nov 2026): the demo data adds a Purchasing Officer, a Stores Manager and a
    QC Inspector, four items, a resin inspection plan, and purchase orders at every stage (a
    draft, one waiting for the Director, one partly received with 10 bags waiting for QC, one
    received, accepted and invoiced, and one with 200 pieces rejected and its invoice held for
    a price difference). On a PC that already has the earlier demo, running
    `load_demo_data` again adds only the missing parts. The test scripts per role and the
    go-live rows (items, stores, open POs, auditors' confirmation) are in the shared test
    document. Stock starts at zero at go-live: opening stock comes with the Phase 2 migration
    (spec 6, "Migration at go-live"), unless the owner decides otherwise.

## H. Before go-live: owner's decisions of 2 Nov 2026

The owner's answers to the open go-live questions (also in spec 8.4):

1. **Opening stock:** the stores are counted and the balances loaded at go-live (P16-15).
2. **Paper vouchers still open at go-live** are typed into the ERP with their scans and the
   signed paper voucher, and go through all three approvals again; a partly paid one is
   entered for its unpaid balance only.
3. **Amendments** are started by the Clerk only (as built).
4. **Quotation limits** are settings the Admin keeps (the Director confirms); defaults: minimum
   margin 1%, no maximum value (P16-16).
5. **www.smlerp.com.lk** redirects to smlerp.com.lk (at server set-up).
6. **Accounting treatment:** the usual standards. GRNI and supplier advances already follow
   them; price differences go into the stock's cost while the goods are in stock (IAS 2,
   P16-18) and foreign-currency purchases use the rate of each transaction's date (IAS 21,
   P16-19). The auditors still confirm before go-live.
7. **VAT** 18%. **SSCL** varies with the kind of supply (2.5% of liable turnover: 2.125% on
   manufactured goods, 2.5% on services, 1.25% on resale): chosen per line from a list of
   SSCL codes, to be confirmed by the tax advisor (P16-17).

- [x] **P16-15 Opening stock from the stores count**
  The Accountant loads the count from Excel (item, main store, quantity, cost per unit, lot);
  checked first, all or nothing, every bad row listed. The Director approves; approval puts
  the stock into the main stores and posts Dr Inventory, Cr Opening balance equity per
  division. Only for an item and store that have not moved yet, and once per item and store.
  - Done: Purchasing and stores → Opening stock. Numbered OS{YY}{MM}{DD}{XX}; the sheet to
    fill in lists the active stock items and main stores; loading again replaces a draft's
    lines; the count date cannot be in the future or in a closed month. Movements of kind
    "Opening stock" link back to it from Stock on hand. Database guard: no change once sent,
    only drafts deleted, posted and rejected for good.

- [x] **P16-16 Quotation limits: no maximum, defaults**
  The maximum value can be left empty (no value warning); with no limits set, 1% and no
  maximum apply.
  - Done: Settings → Quotation limits: the maximum value may be left empty ("No maximum");
    divisions without confirmed limits show "1.00% (default)" and "No maximum", and the
    Director's review of a quotation warns only below 1%. The Admin still proposes and the
    Director confirms every change. The page's wording now says the Director approves every
    quotation and the limits are warnings.

- [x] **P16-17 SSCL codes per line**
  SSCL tax codes (2.125%, 2.5%, 1.25%, exempt) chosen per line on quotations, proformas,
  POs, supplier invoices and vouchers; VAT worked out on top as now.
  - Done: every document line already takes a tax code; a tax in a code can now be charged
    on a share of the amount ("Charged on %", Taxes page), so SSCL keeps one dated rate as in
    the law (2.5%) and the codes apply it to the liable share. New codes, for sales and
    purchases: VAT-SSCL-M (manufactured goods, SSCL on 85% = 2.125%), VAT-SSCL-R (resold
    goods, 50% = 1.25%); VAT-SSCL (if not yet used) is renamed "Services: SSCL on 100%".
    VAT only, EXEMPT and NO-TAX are unchanged. Printed documents show the effective rate
    (SSCL 2.125%). The share of a used code is fixed (database guard). The SSCL rate entered
    on the Taxes page must be 2.5%. To be confirmed by the tax advisor.

- [x] **P16-20 Tax rates control panel** (owner's decision of 2 Nov 2026, evening)
  The Admin enters the SSCL rates (2.125%, 2.5%, 1.25%) and VAT in a control panel and
  changes them when the government does; the Director confirms every change.
  - Done: Settings → Tax rates. SSCL now has its own tax per kind of supply, each with dated
    rates: SSCL-M manufactured goods, SSCL services, SSCL-R resold goods; all print as "SSCL"
    on documents. VAT-SSCL-M and VAT-SSCL-R use them at 100% (the "share" of P16-17 stays
    for special cases). The Admin or the Accountant enters a new rate from today or later,
    with a reason; it applies only after the Director confirms (not the person who entered
    it); one change waits per tax; withdrawn and rejected changes never apply; documents keep
    the rate of their date. The Taxes page's "add rate" is for setting up a tax not yet used.
    Director action "confirm_tax_rates" (core migration 0020); database guard: confirmed,
    rejected and withdrawn rates never change status, and a confirmed rate in force on a
    used tax never changes.

- [x] **P16-18 Price differences into the cost of stock (IAS 2)**
  An invoice price different from the PO price adjusts the value of the goods still in
  stock; only the part already used goes to cost.
  - Done: when a supplier invoice is posted, the difference from the PO price (with any tax
    that cannot be recovered, such as SSCL) is shared between the goods of that GRN line
    still in a main store, which take it as a value-only "Invoice price difference" movement
    (Dr/Cr the item's inventory account, lot by lot), and the goods no longer in stock, whose
    part goes to Purchase price variance. The weighted average cost then reflects the
    invoice price. For a non-stock item the difference goes to its expense account. The
    database allows a movement without quantity only for this kind, and only with a value.

- [x] **P16-19 Foreign-currency purchases at the transaction date's rate (IAS 21)**
  Goods valued at the GRN date's rate, the invoice and payment at their own dates' rates,
  with realised exchange differences posted.
  - Done: confirming a GRN fixes the exchange rate of its receipt date (latest rate on or
    before it; refused if there is none), and QC-accepted goods go into stock at that rate.
    A supplier invoice is posted at the rate of its date: Goods received not invoiced is
    cleared at the receipt's rate, the payable taken at the invoice's, and the difference
    posted to Exchange loss or Exchange gain (now system accounts, 8010 and 7010). Price
    differences and tax are at the invoice's rate; debit notes reverse at it. Both rates are
    kept on the GRN and the invoice and never change (database guard for GRNs; posted
    invoices never change). LKR purchases are unchanged (rate 1). Paying a foreign invoice
    in its own currency, with the realised difference at the payment date, is P2-11.
