# Backlog — Phase 1.5 (sales documents)

Customers, quotations with costing, proforma invoices and sales orders (spec 5). Same rules
as Phase 1: work top to bottom, one task per pull request, and a task is done when every
acceptance criterion is a passing test (or, for pure UI items, checked by the owner).

```
Enquiry → Quotation (revisions) → Proforma Invoice (optional) → Sales Order
        → (Phase 3: job / work order) → (Phase 2: delivery note, tax invoice)
```

**Already built in Phase 0, used here:** number series QL{YY}{MM}{DD}{XX} and PI-{YYYY}-{NNNN}
(P0-08b), currencies and dated exchange rates (P0-11), quotation approval limits per division,
confirmed by the Director (P0-12), dated machine rates (P0-09), the approval engine (P0-17),
sending documents by email with the company letterhead (P0-19), tax codes SSCL and VAT (P0-20),
and the Sales Executive and Sales Manager roles (P0-04).

Status: `[ ]` to do · `[x]` done

---

## A. Customers and rates

- [x] **P15-01 Customers and contacts** (spec 5.4, 5.5)
  Customer master: code (C0001, immutable once used), name, addresses (billing and delivery),
  VAT / TIN number, default currency, payment terms, credit limit (shown, not yet enforced),
  export customer flag with country, default Incoterm and port of destination; contacts
  (name, position, phone, email; one is the main contact). Search, Excel export, import in
  the same layout (checked first, all or nothing, as for sections and machines).
  - The Sales Executive enters and edits; the Sales Manager or Director deactivates (with a
    reason); the Accountant can look. A customer with documents is
    deactivated, never deleted (rule 9, database guard); every change is in the audit log.
  - Duplicate warning on the same name or VAT number.
  - The Sales Executive and Sales Manager roles are switched on so they can be assigned.
  - Owner, 19 Nov 2026: **EXW by default.** Every customer's delivery term is "EXW – Ex
    works" unless changed (e.g. FOB for an export customer); a blank term is saved as EXW,
    and customers without one were given EXW (masters migration 0012). Quotations and
    direct sales orders use EXW when the customer has no other term. Payment terms were
    already the customer's own ("Payment terms (days)", 30 unless changed).

- [x] **P15-02 Costing rates** (spec 5.1, rule 11)
  Dated rate tables maintained by the Accountant: material rates (material or resin grade,
  form, LKR per kg; masterbatch per kg), overhead % and default margin % per division,
  setup labour rate. Machine hourly rates already exist per machine (P0-09).
  - A rate in force on a date is the one used; a rate whose date has arrived cannot be changed
    or removed, only replaced from a later date (as for machine rates).
  - A quotation keeps the rates of its date: changing a rate later does not change it.

## B. Quotations

  Owner, 15 Nov 2026 (testing 2.7): **Remove** on a price or division rate not started yet
  asked for "a reason" that had to be typed in the add form's Reason box, which nobody could
  guess. Now Remove opens a "Reason for removing" box next to it with its own Remove (only
  with a reason) and Cancel; the same on the tax rates page.
- [x] **P15-03 Quotation entry** (spec 5.1, 5.5)
  Header: customer, contact, enquiry reference, division (WS or IM), currency and the
  exchange rate of the day, validity (days or date), payment terms, delivery lead time,
  Incoterm, notes. Lines: description, drawing number and revision with the drawing file,
  quantity, minimum order quantity, unit price; quantity breaks (e.g. 10, 50, 100) with a unit
  price each. Taxes from tax codes: SSCL, then VAT on the amount plus SSCL (as on vouchers).
  - Number QL{YY}{MM}{DD}{XX} given on first save, in the saving transaction (rule 10).
  - Money is Decimal throughout; foreign-currency amounts carry the rate used and the LKR value.
  - Status Draft; only the creator edits a draft (the Sales Manager approves, not enters).
  - A Sales Executive sees their own quotations; the Sales Manager, Director and Accountant
    see all quotations of their divisions. Only production divisions (WS, IM) quote.
  - Owner, 19 Nov 2026: a quotation with a tax code whose rate is not entered for today
    (e.g. VAT-SSCL-M without an SSCL-M rate) showed "Something went wrong". Now every page
    shows the accounting rule's own message ("SSCL-M has no rate on 2026-11-19. The Admin or
    the Accountant enters it under Settings → Tax rates.") and nothing is saved.
  - Owner, 19 Nov 2026: **validity in days.** Beside "Valid until" is "Valid for (days)";
    typing 14 fills the date, picking a date fills the days (counted from the quotation's
    date). Only the date is saved; the printout already shows both. A new quotation starts
    at **14 days** for every customer (was 7), on the page and on the server.

- [x] **P15-04 Machining costing** (spec 5.1)
  Per line, internal only: material (stock size and weight × material rate + cutting
  allowance), operations (machine × minutes × that machine's rate), setup hours × rate ÷
  quantity, subcontract (heat treatment, plating, transport), overhead %, margin %. Shows
  the suggested unit price and the margin of the price actually quoted; per quantity break.
  - Rates come from the tables in force on the quotation date (P15-02).
  - Costing is never sent to the customer: not in the PDF, the email or any customer page.
  - Who sees costing (owner, 31 Oct 2026): the Sales Manager, the Accountant, the Director and
    the quotation's creator; not other Sales Executives, and not the Auditor (tested on the
    server).
  - Margin % is on the cost (owner, 31 Oct 2026): cost 1,000 + 20% = price 1,200.
  - Owner, 19 Nov 2026: **"Use this price".** Under each quantity of the price build-up, the
    quotation's creator (while it is a draft) has a button that puts the suggested price on
    the line, or on that quantity break, and saves the quotation again (taxes and totals
    worked out as usual; the costing stays). With a quotation discount, the price before the
    discount is set so the net price is the suggested one.
  - Testing T2, 20 Nov 2026: the costing names a material or machine once when its name
    starts with its code ("EN8 steel bar", not "EN8 EN8 steel bar"); the margin figures say
    "Margin on cost" (they are worked out on cost, not on the price); the operation box reads
    "Operation (e.g. Turning)".

- [x] **P15-05 Moulding costing and tooling** (spec 5.1)
  Per line, internal only: material ((part weight + runner weight ÷ cavities) × resin rate +
  masterbatch %), machine (cycle time ÷ cavities → hours per 1,000 pieces × machine rate),
  reject % on material and machine, packing per piece or carton, overhead and margin. Tooling
  as a separate line: charged once, amortised over a quantity, or customer-owned.
  - Owner, 19 Nov 2026: the "Costing for" choices read **Machining** and **Production**
    (was Moulding); the costing itself is unchanged.

- [x] **P15-06 Approval, revisions and status** (spec 5.1, 3)
  **Every quotation needs the Director's approval before it can be printed or sent**, by
  email or otherwise (owner, 31 Oct 2026), through the approval engine. The division's
  confirmed limits (P0-12) are shown to the Director as warnings: margin below the minimum,
  value above the limit. A revision keeps the number and adds Rev 1, Rev 2, … with
  the full history of what was offered. Status: Draft, Awaiting Approval, Sent, Accepted,
  Lost (reason required), Expired (daily job after the validity date).
  - Segregation of duties: nobody approves a quotation they created (rule 5).
  - Until approved, the PDF is only a draft marked NOT APPROVED and cannot be emailed.
  - A sent quotation is never edited; a change is a new revision.
  - Win / loss reasons are kept for the sales reports.
  - Testing T8 (21 Nov 2026): the outcome (won or lost) is recorded only after the
    quotation is marked sent to the customer, or emailed; also once a sent one has expired.
  - Testing T17 (21 Nov 2026): a second proforma or sales order from the same quotation,
    or a second order from the same proforma, is asked for first ("SO26112001 already
    exists for this quotation. Make another sales order?"); cancelled ones don't count.
  - Owner, 20 Nov 2026: **Duplicate** on any quotation the user can see makes a new draft
    quotation with the next number of the day, dated today, for the same customer, with the
    same terms, lines, quantity breaks, costing, drawings and pictures (prices, taxes and the
    exchange rate worked out again for today). The original is unchanged; the copy says
    which quotation it was duplicated from. Only those who make quotations (Sales: Enter)
    in its division can duplicate.
  - Testing T12 (21 Nov 2026): the Director cannot approve a quotation past its validity
    date (he sends it back so the date is changed). An expired quotation's page says it
    expired, not "Not yet approved", and says its PDF is marked EXPIRED.
  - Testing T5 (21 Nov 2026): a costing with no cost at all (no material, operations,
    setup, extras or tooling) is refused, and one saved empty before counts as no costing.
    When some lines have no costing, the Director's margin is labelled "costed lines only".

- [x] **P15-07 Printed quotation and email** (spec 5.1, 3B)
  PDF in the layout of the owner's current quotation, improved: letterhead, QUOTATION, Our
  Ref, date, customer name and address, lines (description, quantity, unit price, total),
  quantity breaks, SSCL and subtotal, VAT and rate, total in the quotation's currency (and
  the rate used for an export quotation), payment terms, validity, delivery term (Incoterm),
  signature (Managing Director), the slogan "Excellence through expertise". No SVAT line.
  Sent by email from the system with the PDF attached (P0-19); every send is recorded.
  Only an approved quotation is printed as final or emailed (P15-06).
  - The PDF and email contain no costing figures (tested on the generated PDF text).

- [x] **P15-07b Discount on quotations** (owner, 31 Oct 2026)
  An optional discount % on the quotation, taken off every line before its taxes (SSCL then
  VAT on what is left), as on the owner's proforma sample ("Discount – 3%"). Shown as its own
  line on the printed quotation; the costing margin uses the price after the discount;
  revisions keep it; the database refuses changing it once out of draft. Proformas carry it
  over (P15-08).

## C. Proforma invoices, advances and sales orders

- [x] **P15-08 Proforma invoices** (spec 5.2, 5.5)
  Created from an accepted quotation (or a sales order); prices and terms carried over.
  Number PI-{YYYY}-{NNNN}; titled "Proforma Invoice"; PDF and email; export fields (Incoterm,
  port of loading and destination, bank details for payment).
  **Packing list with the proforma** (owner, 31 Oct 2026): per line the cartons, quantity per
  carton, net and gross weight and carton dimensions, with totals; printed as its own page.
  - Records no sale and no receivable: no journal entry is made (tested).
  - Built (31 Oct 2026): numbered PI{YY}{MM}{DD}-{XX}; each line's price is the quotation's
    price for its quantity (quantity breaks apply), so prices are never typed again; discount,
    advance % (advance and balance printed), bank details for payment; draft → issued (never
    changed, database guard) → cancelled with a reason, unless an advance was received
    against it. Customer advances can now be recorded against an issued proforma (P15-09).
    The PDF follows the owner's sample PI191120-02, titled PROFORMA INVOICE.
  - Owner, 16 Nov 2026: **clear statuses.** "Draft of Dilini", "Issued to the customer",
    "Issued, order made" (a sales order that is not cancelled was made from it) and
    "Cancelled by Dilini".

- [x] **P15-09 Customer advances** (spec 5.2)
  An advance received against a proforma (or a sales order) is recorded by the Cashier with
  the Accountant's approval, which is enough (owner, 31 Oct 2026): Dr Bank, Cr Customer
  Advances (a liability account), in the
  receipt currency with the rate of the day. Receipt number from its own series; receipt PDF.
  - The journal entry balances and is never edited; a mistake is reversed (rules 2 and 3).
  - The advance waits for set-off against the tax invoice, which is built in Phase 2.
  - Built before P15-08 (the quotation sample is still awaited): an advance is linked to one
    of the customer's approved quotations, or to a division; the links to proformas and sales
    orders are added with P15-08 and P15-10. The Cashier needs the new "Record customer
    receipts" action (given to the Cashier role, core migration 0017).
  - Owner, 17 Nov 2026: the advance page shows the sales order and proforma it was taken
    against (with links), not only the quotation; the list's column is now "Against" (sales
    order, else proforma, else quotation).
  - Owner, 16 Nov 2026: **clear statuses** (see P2-07): "Waiting for Nimal (Accountant)",
    "Approved by Nimal", "Partly set off", "Set off in full", "Rejected by Nimal".

- [x] **P15-10 Sales orders** (spec 5.3)
  Created from an accepted quotation or a proforma, or entered directly for a repeat order:
  customer PO number and date, agreed prices, delivery schedule (several dates and quantities
  per line for moulding call-offs). Status: Open, Partly delivered (from Phase 2), Completed,
  Cancelled (reason). One click from a proforma.
  - Every document links back to the one it came from, and forward to those made from it.
  - Done: numbered SO{YY}{MM}{DD}{XX} (SO26103101), daily. Prices come from the quotation
    (its quantity breaks apply); only a repeat order typed in has typed prices, and the
    Director approves it before it is open. Confirming needs the customer's PO number; after
    that the order never changes (database guard). The deliveries of a line must add up to its
    quantity. Cancelling needs a reason and is refused once an approved advance stands against
    the order. Advances can be recorded against an open order. An order posts nothing to the
    accounts. Partly delivered is set by deliveries in Phase 2.
  - The number format and the Director's approval of repeat orders were confirmed by the owner
    (decisions 12 and 13).
  - Owner, 16 Nov 2026: **who cancelled it and when.** Sales orders, proformas, delivery notes
    and supplier invoices keep who cancelled them and when (sales 0020, purchasing 0010; a
    trigger keeps them fixed once set; documents already cancelled get them from the audit
    log). The page says "Cancelled by Dilini Wijesekara on 2026-11-16 14:52: wrong quantity";
    the sales order list says "Cancelled by Dilini".
  - Owner, 16 Nov 2026: **a repeat order linked to a quotation.** A repeat order typed in can
    be linked to an earlier quotation of the same customer that was sent to them (sent,
    accepted, lost or expired). Its prices stay typed in. The page shows "Repeats quotation
    QL…"; when that quotation had expired by the order date it is highlighted ("Expired
    quotation linked"), and with no link it says "Not linked to a quotation", so the Director
    sees it before approving. The quotation lists the order among its sales orders.
  - Owner, 16 Nov 2026: **clear statuses.** The list and page say "Draft of Dilini", "Waiting
    for Ruwan (Director)", "Returned by Ruwan" or "Cancelled by Dilini"; the plain statuses
    read "Open, to deliver", "Partly delivered", "All delivered" and "Completed and closed".

## D. Reports and go-live

- [x] **P15-11 Sales reports and dashboard**
  Quotation register (by status, customer, division, salesperson), win / loss with reasons,
  quotations awaiting approval and expiring this week, open sales orders and their delivery
  dates, advances received and not yet set off. Excel and PDF (P1-08 pattern); sales tiles on
  the dashboard. A user sees only their divisions (and a Sales Executive their own quotations).
  - Done: Sales → Sales reports, five tabs, each with Excel and PDF. Win rate by number and
    by value, per reason and per salesperson. "Expiring this week" means approved or sent
    quotations whose validity ends within 7 days. Open orders are listed per delivery, overdue
    ones in red. A Sales Executive sees advances against their own documents; the Sales
    Manager and the payments roles see all of their divisions. Sales tiles on the home page
    for anyone with Sales: View.
  - Owner, 20 Nov 2026 (test script 6.3): the register's Salesperson filter is always shown
    (it was hidden when one person had made every quotation), the chosen salesperson is named
    on the Excel and PDF, and the division is chosen from a list of the user's production
    divisions instead of typed.
  - Testing T21, 20 Nov 2026: no screen text talks about the project's phases ("from Phase 2"
    on Advances not set off; "until production is built (Phase 3)" on delivery notes, which
    now says that issuing takes the parts out of the finished goods store); a test keeps it so.
  - Testing T20, 20 Nov 2026: in Open orders and deliveries an overdue delivery's date and
    "Overdue" are in red, as the page says; a delivery due today reads "Due today" (it said
    "This week"), also in the Excel and PDF.
  - Testing T19, 20 Nov 2026: the register's Excel and PDF use the screen's status words
    ("Customer accepted", not "Accepted"); report headings give the period in words ("all
    dates", "from 01/11/2026", "01/11/2026 to 30/11/2026", not "start to today"; also on the
    purchasing reports) and name the status filter used.

- [ ] **P15-12 User acceptance testing and go-live**
  Sales staff and the Director run test scripts for each role on the test server; the owner
  signs off; customers and rates are loaded.
  - Owner's decision (31 Oct 2026): every role tests on the owner's PC, at times he gives each
    person, with the demo data (reloaded so it includes the sales examples). Only after all
    tests pass is the live server bought (Hostinger KVM 4, smlerp.com.lk) with a Backblaze
    bucket; no separate test server for now. Before real data goes in, the live server is
    checked for what a PC cannot show (HTTPS, real emails, phones, a backup and a full
    restore) and then wiped. The test scripts and go-live checklist are a shared document.

---

## Owner's decisions (31 Oct 2026)

1. **Quotation approval:** the Director approves every quotation before it is printed or
   sent, including by email (P15-06, P15-07).
2. **Who sees costing:** the Sales Manager, the Accountant, the Director and the quotation's
   creator; not other Sales Executives (P15-04).
3. **Customer advances:** the Accountant's approval is enough (P15-09).
4. **Packing list:** needed with the proforma (P15-08).
5. **Margin %** is on the cost: a cost of LKR 1,000 (overhead included) with a 20% margin
   gives a price of LKR 1,200. The Director's margin warnings (P15-06) use the same meaning.
6. **The Auditor does not see quotation costing** (P15-04).
7. **Masterbatch %** is added on top of the resin weight (P15-05).
8. **Rejects** add their % to material and machine cost (P15-05).
9. **Tooling** is charged once on its own quotation line, spread over a quantity, or owned
   by the customer (P15-05).
10. **Proforma numbers** keep the old style, the date and the number of the day:
    PI{YY}{MM}{DD}-{XX}, e.g. PI261031-01 (P15-08).
11. **Discount**: an optional discount % on both quotations and proformas (P15-07b, P15-08).
12. **Sales order numbers** follow the quotations: SO{YY}{MM}{DD}{XX}, e.g. SO26103101
    (P15-10).
13. **Repeat orders typed in** without a quotation are allowed for the Sales Executive; the
    Director approves the order before it is open, so typed prices never reach the customer
    unchecked (P15-10).

Samples received 31 Oct 2026: quotation QL26061501, proforma PI191120-02 and purchase order
PO26061701 (for the purchasing phase). The printed quotation follows QL26061501 (P15-07).
