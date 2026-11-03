# Backlog — Phase 2 (financial accounting)

The full accounting system, so the ERP can replace the company's current accounting system
(spec 6, with the QuickBooks-style features placed in Phase 2 by spec 7A). Payroll follows as
Phase 2b, with its own backlog, once core accounting is live. Same rules as before: work top
to bottom, one task per pull request, and a task is done when every acceptance criterion is a
passing test (or, for pure UI items, checked by the owner).

```
Sales order → Delivery note → Tax invoice → Receipt → Bank deposit → Bank reconciliation
Supplier invoice (Phase 1.6) → Voucher → Payment → Bank reconciliation
Journals, assets, stock, tax, FX → Trial balance → P&L and balance sheet → Month-end and year-end close
```

**Already built, used here:** the chart of accounts and its import, the journal (balanced,
never edited, reversed only), monthly periods closed by the Director, profit and loss per
division, tax components, rates and codes (VAT, SSCL), currencies and dated exchange rates,
company bank accounts and cheque books, payment vouchers and supplier payments with the
Director lock, customers, quotations, proformas, sales orders and customer advances (Phase
1.5), purchase orders, GRNs, QC, stock at weighted average cost, supplier invoices with
three-way match, debit notes and advances to suppliers (Phase 1.6), the approval engine,
number series, document email and the audit log.

**How it goes live (spec 8.2):** migration of the opening balances, one month in parallel with
the current system, then the current system stops. Until then Phases 1, 1.5 and 1.6 run
alongside it.

Status: `[ ]` to do · `[x]` done

---

## A. The ledger

- [x] **P2-01 Manual journal entries with approval** (spec 6, 4.6)
  The Accountant enters a journal (date, narration, lines with account, division, debit,
  credit; scans attached); it is numbered, and posted only when approved. Nobody approves
  their own journal. A line that debits a supplier's payable and credits a bank or cash
  account is refused (spec 4.6: suppliers are paid only through vouchers). Posted journals
  are reversed, never changed. Journals list with Excel and PDF.
  - Done: Accounts → Manual journals. Numbered MJ{YY}{MM}{DD}{XX}; the Director approves
    every journal for now (question 3 still open; the approval matrix can add an amount
    limit later); returned journals go back to draft, rejected ones stay rejected. Approval
    posts the entry (JV…), so a month closed meanwhile refuses it. Income and expense lines
    need a division, payables lines need the supplier, and accounts receivable is not
    offered (customer balances change only through sales documents). The payment lock is
    also a database rule on every journal entry that is not a supplier payment. Once sent,
    a journal, its lines and files never change (database guard); only drafts are deleted.

- [x] **P2-02 Recurring journals**
  A template (lines, amounts, every month or quarter, start and end) makes a draft journal on
  its date, which then follows P2-01's approval. Accruals can be set to reverse on the first
  day of the next month.
  - Done: Accounts → Recurring journals. The Accountant keeps templates (every month, quarter
    or year, on a day 1–28 or the last day, from a start date to an optional end date). Each
    morning (00:40) a due template makes a numbered draft for its owner, who is notified and
    sends it for approval as usual; days the job missed are caught up, a closed month is
    skipped with a notice, and a template stops after its end date. Any manual journal can be
    marked as an accrual: once approved, it is reversed automatically (00:45) on the first day
    of the next month, or today if that month has been closed meanwhile. Template changes
    affect only journals still to be made; a journal's template link never changes.

- [x] **P2-03 Trial balance, general ledger and balance sheet** (spec 6, reports)
  Trial balance for any date, general ledger detail per account for a period, balance sheet,
  each for the company or one division, with comparison columns (previous month, previous
  year). Every figure opens the transactions behind it, down to the document and its scans
  (spec 7A). Excel and PDF.
  - Done: Accounts → Financial reports, with four tabs: trial balance, balance sheet, profit
    and loss (the P0-16 report, now on screen and in Excel/PDF) and general ledger. Any date,
    the company or one division, sub-accounts shown or rolled into their parent, comparison
    with the end of the previous month or the same day last year. Every figure opens the
    ledger behind it; every ledger line opens its journal entry and the document (with its
    scans) that posted it: manual journal, opening stock, GRN, supplier invoice, debit note,
    customer advance, or the voucher of a supplier payment. Merged accounts show under the
    account that replaced them. Until the year-end close (P2-23), the profit to date is shown
    inside equity, so the balance sheet balances; a division's balance sheet shows bank, loans
    and capital as "funded at company level".

## B. Sales invoicing and receivables

- [x] **P2-04 Delivery notes** (spec 5.3, 6)
  From an open sales order, the delivery of what leaves the factory: quantities per line
  against the order's deliveries, vehicle, received by; printed for the customer to sign. The
  order becomes Partly delivered, then Delivered. (Finished-goods stock: see question 4.)
  - Done: Sales → Delivery notes (also open to the Store Supervisor). Numbered
    DN{YY}{MM}{DD}{XX}; made from an open order with the quantity of each line delivered
    now, vehicle, driver and delivery address; issued when the goods leave, which moves the
    order to Partly delivered or Delivered (a new order status). Never more than is still to
    deliver (also a database rule, checked again at issue). Printed without prices, with a box
    for the customer's name, signature, date and stamp; the signed copy (scan), who received
    it and when are recorded when it comes back. An issued note never changes; the Sales
    Manager or the stores cancel it with a reason and its quantities are open again. An order
    with delivery notes is completed, not cancelled. No finished-goods stock (question 4).

- [x] **P2-05 Tax invoices** (spec 6.1)
  From delivered quantities: the Inland Revenue format exactly (Gazette 2481/22), numbered
  YYMMM_QQQQ_XXXXX per division, SSCL then VAT on (subtotal + SSCL), amount in words. Issuing
  posts Dr Accounts receivable, Cr Sales (per division), SSCL and VAT payable. Never edited or
  deleted once issued; refused for a division without its tax-invoice code. PDF and email.
  - Done: Sales → Tax invoices. A draft is prepared by Sales or the Accountant from an
    order's delivery notes not yet invoiced (each delivery line is invoiced once, a database
    rule); prices, discount and tax codes come from the order, taxes at the invoice date's
    rates. The Director, the Accountant or a salesperson given the "Issue tax invoices" right
    issues it (owner, 3 Nov 2026): only then is it
    numbered (YYMMM_IC_XX, monthly per division, so drafts leave no gaps), the supplier's and
    customer's details copied onto it, and Dr Accounts receivable (with the customer, a new
    field on ledger lines), Cr the division's sales account (Accounts → Sales accounts:
    goods and tooling), Cr SSCL and VAT payable posted. Needs the division's tax invoice code
    and the company's TIN. Printed as in spec 6.1 (dates MM/DD/YYYY, amount in words,
    Customer / Prepared By / Checked By), emailed with the PDF. Issued invoices, their lines
    and taxes never change (database guard); an invoiced delivery note cannot be cancelled.
    A delivered order is Completed once fully invoiced. LKR only until P2-09.

- [x] **P2-06 Credit notes**
  Against an issued invoice (returned goods, price correction), with a reason and the
  approval the owner chooses (question 3); posts the reverse of the invoice's lines, never more
  than what was invoiced.
  - Done: Sales → Credit notes, made from an issued invoice by Sales or the Accountant: kind
    (goods returned, price correction, other) and reason required; each line credits an
    amount before tax (and the quantity for returned goods), never more than is left after
    approved notes (database rule, checked again at approval); taxes at the invoice's rates.
    Approved through the approval engine by the Director, or by a person the Admin gives the
    "Approve credit notes" right to, confirmed by the Director (owner, 3 Nov 2026); the engine
    now lets a document type name such a right. Approval numbers it CN{YY}{MM}{DD}{XX} and
    posts Dr Sales, Dr SSCL and VAT payable, Cr Accounts receivable (the customer). Printed;
    approved and rejected notes never change. Returned goods go back into no stock until
    Phase 3.

- [ ] **P2-07 Customer receipts and allocation**
  The Cashier records money in (cheque, transfer, cash, card, QR), allocated to one or more
  invoices; advances (Phase 1.5) set off against the invoice of their order. Cheques received
  go to Undeposited funds until deposited (P2-14); post-dated cheques wait for their date.

- [ ] **P2-08 Customer statements, aging and credit limits** (spec 6, 7A)
  Statements (PDF, email), receivables aging (current, 30, 60, 90, over 90 days), credit limit
  and payment terms per customer checked on new sales orders and invoices (question 5).
  Automatic reminders per customer on a schedule from the finance mailbox, stopping when paid;
  each reminder is recorded.

- [ ] **P2-09 Export invoices and exchange differences** (spec 5.5, 6)
  Tax invoices in the customer's currency at the day's rate; the receipt at its own rate posts
  the realised exchange gain or loss. Export VAT treatment as the tax advisor confirms.

## C. Payables, completed

- [ ] **P2-10 Supplier statements and payables aging**
  Payables aging per supplier and division; the supplier's statement typed or imported and
  reconciled with our ledger, differences listed.

- [ ] **P2-11 Payment follow-ups: spoiled cheques, cancelled payments, foreign currency**
  (known gaps from Phase 1) A payment is cancelled with a reason and the Director's approval:
  a reversing entry, the cheque leaf marked spoiled, the voucher open to pay again. Payments in
  the supplier's currency at the day's rate, with the realised exchange difference.

- [ ] **P2-12 Withholding tax on payments** (spec 6, tax)
  Where the law requires it (question 6): WHT worked out on the voucher, the supplier paid the
  net, WHT payable credited, and a WHT certificate printed for the supplier.

- [ ] **P2-13 Purchase requests and reorder alerts** (spec 6, 7A)
  A reorder level and quantity per item and store; falling below it notifies the stores
  person and purchasing, with a one-click purchase request to the usual supplier. Requests
  are approved, then become a draft PO.

## D. Banking and cash

- [ ] **P2-14 Cheque register, deposits and transfers**
  Cheques issued and received in one register (status: issued, presented, cleared,
  returned, spoiled); deposit slips from Undeposited funds; returned cheques reverse the
  receipt; transfers between the company's own accounts, approved like vouchers.

- [ ] **P2-15 Bank statement import** (spec 7A)
  Statement files (CSV or Excel) read with a template per bank: Commercial Bank, Sampath,
  Seylan, People's Bank, Bank of Ceylon and HNB first, each checked against a real export
  (the owner supplies one per bank); then the other nine.
  - Received (2 Nov 2026): a Commercial Bank statement as a PDF with real text (JasperReports),
    columns date, description, debit, credit, balance with Cr/Dr. Kept outside the
    repository (it holds account data). Excel/CSV exports asked for as well. The Accountant can correct a
  template or add a bank without a code change.

- [ ] **P2-16 Bank reconciliation** (spec 6, 7A)
  Imported lines matched to payments, receipts, deposits and transfers (amount, date, cheque
  number, reference); suggestions for the rest from rules and earlier coding; bank charges and
  interest added with one click. Nothing posts without the Accountant's click. The month's
  reconciliation is locked when done.

- [ ] **P2-17 Petty cash** (spec 6)
  An imprest float per custodian; small expenses recorded with their slips; replenishment
  through a petty cash voucher that follows the normal three approvals.

## E. Stock and fixed assets

- [ ] **P2-18 Stock issues, adjustments and stock count** (spec 6, inventory valuation)
  Material issued to a division or section (later to a job or production order, Phase 3) and
  returned to stores, at weighted average cost; adjustments and write-offs with a reason and
  the Director's approval; a stock count sheet, counted quantities entered, differences
  approved and posted. The same count loads opening stock (question 7). Finished goods and WIP
  accounts are set up for Phase 3.

- [ ] **P2-19 Fixed asset register and depreciation** (spec 6)
  Assets (machines, moulds, vehicles, buildings, equipment) with cost, date, division, method
  and rate per class (question 8); monthly depreciation posted after the Accountant checks
  it; disposals with the gain or loss; moulds carry their shot count, filled from production
  in Phase 3.

## F. Tax, currencies, budgets and closing

- [ ] **P2-20 Tax reports** (spec 6)
  VAT return (output and input tax, by month), SSCL and WHT reports in the layouts the filings
  need, each traced to the invoices behind it. Rates stay dated master data.

- [ ] **P2-21 Month-end revaluation** (spec 5.5, 6)
  Open foreign-currency receivables, payables and bank balances revalued at the month-end rate;
  the unrealised difference posted and reversed on the first day of the next month.

- [ ] **P2-22 Budgets** (spec 6)
  Budgets by account, division and month (typed or imported from Excel), approved by the
  Director; budget against actual in the P&L, with the difference and %.

- [ ] **P2-23 Month-end and year-end close**
  A month-end checklist (reconciliations, depreciation, revaluation, accruals) before the
  Director closes the month; the year-end close carries the year's profit to retained earnings
  and opens the next year. Reopening needs the Director and a reason.

## G. Reports and dashboards

- [ ] **P2-24 Cash flow statement and financial dashboard** (spec 6, 7A)
  Cash flow statement (indirect method). Home page tiles for P&L, cash, receivables and
  payables, per division or for the company; every tile opens the report behind it.

- [ ] **P2-25 Cash flow planner** (spec 7A)
  Bank balances projected day by day for 13 weeks from approved unpaid vouchers, invoices due
  (by each customer's payment history) and recurring payments; "what-if" items change the
  projection but are never posted.

- [ ] **P2-26 Custom report builder** (spec 7A)
  From a standard report or a data source: columns, filters, grouping, subtotals and period
  columns; saved, shared with a role, exported and emailed. A user sees only what their role
  and divisions allow.

- [ ] **P2-27 Pay Now and invoice tracking** (spec 7A)
  The emailed invoice links to a customer page with the PDF, a Pay Now button through a Sri
  Lankan gateway (e.g. PayHere) and the bank transfer details; the invoice history shows sent,
  viewed, paid and deposited. Needs the company's gateway account (question 9).

## H. Migration and go-live

- [ ] **P2-28 Migration** (spec 6.1, "Migration at go-live")
  Excel templates, checked first and all or nothing: opening trial balance, open customer and
  supplier balances by invoice, open sales orders, the fixed asset register with accumulated
  depreciation, stock on hand with value. Totals must agree with the trial balance.

- [ ] **P2-29 Parallel run, user acceptance testing and go-live** (spec 8.2)
  One month entered in both systems; the trial balance, receivables, payables and bank
  balances compared and differences explained; test scripts per role; the auditors and the
  owner sign off; the current system stops.

---

## Questions for the owner

None blocks P2-01 to P2-03. Each names the tasks that need its answer.

1. **The current accounting system.** What is it (QuickBooks, Tally, Excel or other), and can
   it export the trial balance and open invoices to Excel? (P2-28)
   - Owner, 3 Nov 2026: QuickBooks; it exports to Excel. P2-28 reads QuickBooks' own Excel
     exports (trial balance, open invoices and bills, item list) as well as the templates.
2. **Financial year and start date.** Is the financial year April to March? Phase 2 is
   easiest to start on the first day of a financial year (e.g. 1 April 2027). (P2-23, P2-28,
   P2-29)
   - Owner, 3 Nov 2026: yes, April to March. Go-live on 1 April (of the year agreed).
3. **Approvals.** Who approves manual journals and credit notes: the Director always, or the
   Accountant up to a limit? (P2-01, P2-06)
   - Credit notes, answered 3 Nov 2026: the Director, and anyone the Admin gives the right to,
     confirmed by the Director. Manual journals: still the Director.
4. **Finished goods before Phase 3.** Should delivery notes reduce a finished-goods stock now,
   or only record what was delivered until production is built in Phase 3? (P2-04, P2-18)
   - Default taken on 3 Nov 2026 (the recommendation, no answer yet): only record what was
     delivered; finished-goods stock starts with production in Phase 3. The owner can still
     choose otherwise before P2-18.
5. **Credit limits.** When a customer is over their limit or overdue: warn only, or block new
   orders and invoices until the Director allows it? (P2-08)
   - Owner, 3 Nov 2026: block. A customer over their credit limit or with overdue invoices
     gets no new sales order or tax invoice until the Director allows it (for that document).
6. **Withholding tax.** Does SML deduct WHT on any payments (rent, services, interest)? To
   confirm with the tax advisor. (P2-12)
   - Owner, 3 Nov 2026: currently no. P2-12 is built switched off (no WHT unless the
     Accountant sets it up), so it costs nothing until it is needed.
7. **Opening stock.** Count the stores and load the balances at Phase 1.6 go-live, or at
   Phase 2 go-live? (P2-18, P2-28)
8. **Depreciation.** The method and rate per asset class (straight line or reducing balance),
   as the auditors agree. (P2-19)
   - Owner, 3 Nov 2026, asked which classes: proposed list sent (land, buildings, plant and
     machinery, moulds and tooling, motor vehicles, furniture and fittings, office and computer
     equipment); methods and rates to be agreed with the auditors.
9. **Payment gateway.** Will SML open a PayHere (or other) merchant account for Pay Now? If
   not yet, P2-27 waits. (P2-27)
   - Owner, 3 Nov 2026: no gateway account. When a customer asks to pay by card, SML sends
     them a payment link. P2-27 becomes: invoice tracking (sent, viewed, paid) and recording a
     card payment link sent to a customer; no Pay Now button.
10. **Order of release.** Build all of Phase 2 and go live once, or release in stages (for
    example sales invoicing and receipts first, while the current system still keeps the
    books)? (all)
    - Owner, 3 Nov 2026: all at once.
11. **Who issues tax invoices.** Answered 3 Nov 2026: the Director and the Accountant, and the
    salespeople the Admin chooses (not every salesperson). Built as the special action "Issue
    tax invoices": held by the Director and Accountant roles, granted to a salesperson one by
    one on their user page (a sensitive grant the Director confirms). Sales or the Accountant
    prepare the draft. (P2-05) The Sales Manager too is granted it only when the Admin sets it
    and the Director confirms (owner, 3 Nov 2026).
