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

- [ ] **P16-11 Payment vouchers from matched invoices** (spec 5A.5)
  A voucher for PO goods is made from matched or exception-approved invoices, carries the PO,
  GRN and invoice links, and can never exceed what is unpaid on them; the approvers see PO,
  GRN and invoice side by side. Clerk → Accountant → Director → Cashier as today. Advance
  payment on a PO only as a Director-approved exception. Non-stock purchases stay as today.

- [ ] **P16-12 Supplier returns and debit notes**
  Rejected or short goods returned to the supplier with a return note; a debit note reduces
  what is owed; linked to the GRN and invoice.

## G. Reports and go-live

- [ ] **P16-13 Traceability and reports** (spec 5A.7, 6A.7)
  The full trail on every document (PO ↔ GRN ↔ QC ↔ invoice ↔ voucher ↔ payment); open POs
  and overdue deliveries; GRNI; invoices held; exceptions approved; receipts and rejections
  by supplier; stock on hand. Excel and PDF; purchasing and stores tiles on the dashboard.

- [ ] **P16-14 User acceptance testing and go-live**
  Test scripts per role (Purchasing Officer, Stores Executive and Manager, QC Inspector,
  Accounts Clerk, Accountant, Director, Cashier); items, stores and open POs loaded; the
  accounting treatment confirmed with the auditors; the owner signs off.
