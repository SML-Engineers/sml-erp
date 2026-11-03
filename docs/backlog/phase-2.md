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

- [x] **P2-07 Customer receipts and allocation**
  The Cashier records money in (cheque, transfer, cash, card, QR), allocated to one or more
  invoices; advances (Phase 1.5) set off against the invoice of their order. Cheques received
  go to Undeposited funds until deposited (P2-14); post-dated cheques wait for their date.
  - Done: Vouchers and payments → Customer receipts. The Cashier records the money (how, the
    reference, the date) and splits it over the customer's issued invoices, with a "fill
    oldest first" button; the split must add up to the amount and no invoice gets more than
    is open on it (total less approved credit notes, other receipts not rejected and advances
    set off; also a database rule). Numbered from the RC series shared with advances. The
    Accountant approves (question 12, default); approval posts Dr the bank or cash account
    (Undeposited funds for a cheque), Cr Accounts receivable with the customer per invoice. A
    post-dated cheque is approved but posted by a daily job on its date; cheques more than six
    months ahead or old are refused. Rejecting posts nothing and frees the invoices. Printed
    receipt listing the invoices paid. Issuing a tax invoice now sets off the approved
    advances of its order (or of the order's proforma or quotation), oldest first, up to the
    invoice total: Dr Customer advances, Cr Accounts receivable; the Accountant can also set
    off any approved advance of the customer by hand, from the advance's page. The invoice page
    shows what was received, waiting, set off and still open. LKR only until P2-09.

- [x] **P2-08 Customer statements, aging and credit limits** (spec 6, 7A)
  Statements (PDF, email), receivables aging (current, 30, 60, 90, over 90 days), credit limit
  and payment terms per customer checked on new sales orders and invoices (question 5).
  Automatic reminders per customer on a schedule from the finance mailbox, stopping when paid;
  each reminder is recorded.
  - Done: Sales → Receivables and statements. The aging shows per customer what is open on
    its invoices at a date (not yet due, 1-30, 31-60, 61-90, over 90 days past the due date;
    approved receipts only), next to its receivables ledger balance, with Excel and PDF. The
    statement is the customer's receivables ledger for a period (opening balance, every
    posting with a running balance, closing balance) with its open invoices by age, advances
    held and credit status; printed, Excel, and emailed by the Accountant from the finance
    mailbox. Credit control (question 5, block): confirming a sales order or issuing a tax
    invoice is refused when the customer has an overdue invoice or would go over its credit
    limit (open invoices less receipts recorded and advances held, plus the new document; no
    limit when empty). The document goes on Sales → Credit holds, the Director is notified
    and allows that one document with a note ("Allow documents on credit hold", Director's
    role; sensitive); the allowance covers it up to that amount. Holds are never deleted and
    allowed ones never change (database). Reminders: the Accountant switches them on per
    customer with how often (1-90 days); a daily job (Monday to Saturday, 08:15) emails the
    statement while invoices are overdue, in the name of the person who switched them on, and
    stops once paid; each is recorded (insert-only).

- [x] **P2-09 Export invoices and exchange differences** (spec 5.5, 6)
  Tax invoices in the customer's currency at the day's rate; the receipt at its own rate posts
  the realised exchange gain or loss. Export VAT treatment as the tax advisor confirms.
  - Done: a tax invoice is in its sales order's currency, at the rate of the invoice date (the
    latest on or before it; no rate, no invoice), printed with the currency, the rate and the
    LKR total. The ledger carries LKR: each sales account and tax converted, the receivable
    their sum. Receipts are in the invoices' currency (one currency per receipt, into an
    account of that currency; also a database rule) at the receipt date's rate: Dr bank at
    that rate, Cr receivable at the invoice's rate, the difference to Exchange gain or
    Exchange loss per division. The last payment of an invoice takes off exactly what is left
    in LKR, so no cents stay behind. Advances are set off only against invoices of their
    currency: Dr Customer advances at the advance's rate, Cr receivable at the invoice's,
    difference to exchange gain or loss. Credit notes reverse at the invoice's rate. Aging,
    statements and credit control count each invoice in LKR at its rate. Existing records
    were all LKR (rate 1). VAT treatment of exports follows the tax code on the lines
    (question 14). Month-end revaluation of what is still open is P2-21.

## C. Payables, completed

- [x] **P2-10 Supplier statements and payables aging**
  Payables aging per supplier and division; the supplier's statement typed or imported and
  reconciled with our ledger, differences listed.
  - Done: Vouchers -> Payables and supplier statements. What we owe each supplier comes from
    our documents, so it covers both ways suppliers are paid: matched supplier invoices (LKR
    total less advances set off, debit notes and the paid part of their vouchers) and invoices
    on vouchers (each line less the paid part of its voucher; payments pay a voucher's lines in
    proportion, as the ledger books them). Advances before goods are not payables. Aged by
    days past the due date (the invoice's, or the voucher line's invoice date plus the
    supplier's terms), at any date, per division, with Excel and PDF; a supplier opens its
    items. Supplier statements: typed in or imported from Excel or CSV (heading row with
    Date, Reference, Description, Debit, Credit found anywhere in the first 30 rows; totals
    and balance lines skipped), then matched to our invoices, debit notes and payments of the
    period by reference (letters and digits only; "Chq 000100" matches cheque 000100) and
    payments without one by amount within a week. The page lists what agrees, what is only on
    theirs, what is only in ours, and their closing balance against what we owe. The
    Accountant marks it checked with a note; it then never changes (database). Suppliers in
    another currency are compared for invoices only until foreign payments (P2-11).

- [x] **P2-11 Payment follow-ups: spoiled cheques, cancelled payments, foreign currency**
  (known gaps from Phase 1) A payment is cancelled with a reason and the Director's approval:
  a reversing entry, the cheque leaf marked spoiled, the voucher open to pay again. Payments in
  the supplier's currency at the day's rate, with the realised exchange difference.
  - Done: on the voucher page the Cashier or the Accountant asks to cancel a payment, with the
    reason; the Director approves through the approval engine ("payment_cancellation", one
    request at a time; nobody approves their own). Approval posts the reversing entry (dated
    like the payment when its month is open, otherwise today), marks the payment cancelled and
    its cheque leaf spoiled (the number is never used again), and opens the voucher to pay
    again (approved, or partly paid). Refused when the voucher paid an advance already set off.
    The database still keeps payments and cheque leaves insert-only, except exactly these
    changes with an approved request, and a paid voucher locked except when a cancelled
    payment leaves part of it unpaid. Foreign currency: a voucher whose lines all pay supplier
    invoices in one foreign currency may be paid from an account in that currency, at the
    payment date's rate; the payment covers the voucher in proportion (the last one exactly
    what is left) and the difference between the bank's LKR and the invoices' rate is posted
    to Exchange gain or Exchange loss. Payments keep their currency, the amount that left the
    account and the rate; supplier statements now compare payments in the statement's
    currency.

- [x] **P2-12 Withholding tax on payments** (spec 6, tax)
  Where the law requires it (question 6): WHT worked out on the voucher, the supplier paid the
  net, WHT payable credited, and a WHT certificate printed for the supplier.
  - Done: built switched off (owner, 3 Nov 2026). A withholding tax can be chosen only once it
    has a confirmed rate; the "WHT" tax has none, so nothing changes until the Accountant enters
    a rate under Settings → Tax rates. Then, when coding a voucher, the Accountant picks WHT per
    line (not on an advance line); it is the rate on the invoice date times the amount before
    VAT, rounded half-up, kept on the line with its rate (rule 11). The voucher shows the WHT
    kept and the amount payable; the Director approves both, and the database freezes them.
    The Cashier enters what the payee receives: the payment settles the matching share of the
    voucher, credits the bank with what was paid and the WHT payable account (2120) with the
    rest, and numbers a WHT certificate (WHT{YY}{MM}{NNNN}) with the supplier's name and TIN,
    gross, rate, tax kept and amount paid, printable as a PDF. The last payment keeps exactly
    the WHT left; a cancelled payment gives its WHT back to keep again. A voucher with WHT is
    paid in LKR. Supplier statement matching lists the WHT kept as its own credit, with the
    certificate number. Defaults you can change: WHT is on the amount before VAT; the payment
    date sets the certificate month.

- [x] **P2-13 Purchase requests and reorder alerts** (spec 6, 7A)
  A reorder level and quantity per item and store; falling below it notifies the stores
  person and purchasing, with a one-click purchase request to the usual supplier. Requests
  are approved, then become a draft PO.
  - Done: Purchasing → Reorder levels. The stores person or purchasing sets a level and a
    reorder quantity per stock item and main store, with the usual supplier (or, if none, the
    supplier of the item's last order). Every hour (and when a level is saved) the stock in
    the store plus what is coming (open purchase orders of the division and requests not yet
    ordered) is compared with the level; at or below it, the stores person and purchasing of
    that division are told once (bell and email, "reorder_alert"), and again only after the
    stock has gone back above. One click raises a draft purchase request (PR{YY}{MM}{NNNN})
    for the reorder quantity from the usual supplier; requests can also be typed in. Its
    author sends it; it is approved through the approval engine, never by its author, and can
    be returned or rejected. Purchasing then makes an approved request into a draft purchase
    order, at the last price paid to that supplier unless a price is typed; the order goes to
    the Director as usual. The database keeps a request's lines once it is sent and never
    changes a rejected, cancelled or ordered one. Defaults you can change: the Director
    approves requests (Settings → Approvals can give it to another role); "at or below" the
    level raises the alert; the check runs hourly.

## D. Banking and cash

- [x] **P2-14 Cheque register, deposits and transfers**
  Cheques issued and received in one register (status: issued, presented, cleared,
  returned, spoiled); deposit slips from Undeposited funds; returned cheques reverse the
  receipt; transfers between the company's own accounts, approved like vouchers.
  - Done: Accounts → Cheque register (Cashier or Accountant). Customers' cheques: awaiting
    approval, post-dated, in hand (posted to Undeposited funds), deposited, cleared, returned.
    A deposit slip (DP{YY}{MM}{NNNN}) takes cheques in hand, dated on or before the deposit
    day, to an LKR bank account: Dr the bank, Cr Undeposited funds. A returned cheque needs
    the bank's reason: the receipt's entry is posted in reverse, crediting the bank it was
    deposited in (or Undeposited funds if it never was), the receipt becomes "Cheque returned"
    and its invoices are open again (also in the database's open-amount check and in the
    aging at any date). A cleared cheque is not returned. Our cheques: issued, cleared,
    spoiled (cancelled payments, P2-11), each with its payment and payee. "Presented" is not
    kept separately: the bank shows a cheque only once it is paid, so it goes from issued to
    cleared (by hand now; from the bank statement with P2-16). Deposits, deposit lines and
    clearances are insert-only. Transfers between our own accounts were already Internal
    Transfer vouchers (Clerk → Accountant → Director, paid by the Cashier); nothing new was
    needed. Defaults you can change: no approval for deposits or returned cheques (the
    Cashier or the Accountant records them, with the audit log); bank charges on a returned
    cheque are a separate journal; advances paid by cheque still go straight to the bank
    account chosen.

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
  - Owner's QuickBooks exports received 3 Nov 2026 (as at 31 Oct 2026; kept out of the
    repository: business data). Layouts to read, one sheet each, values in alternate columns
    with empty spacer columns between:
    - Trial balance: title row with the date ("Oct 31, 26"), then "Debit"/"Credit"; one row
      per account in column B (sub-accounts as "Parent:Child"), debit in C, credit in E; a
      "TOTAL" row in column A.
    - A/R aging detail ("open invoices"): grouped by customer (a name row, the lines, a
      "Total <customer>" row); columns Type, Date, Num, P. O. no, Terms, Due Date, Class,
      Ageing, Open Balance; types Invoice, Payment, Credit Note, Cheque, General Journal.
    - A/P aging detail ("open bills"): grouped by age band (Current, 1 - 30, 31 - 60, 61 - 90,
      > 90 with "Total ..." rows); columns Type, Date, Num, Name, Due Date, Ageing, Open
      Balance; types Bill, Bill Pmt -Cheque, Cheque, Credit, Deposit, General Journal.
    - Item list: Item ("Parent:Child" for sub-items), Description, Type (Stock Part, Non-stock
      Part, Service, VAT Item...), Cost, Price, VAT Code, VAT Code for Purchases, Quantity On
      Hand, Reorder Pt (Min), Quantity On Purchase Order, Preferred Supplier.
  - Findings sent to the owner for the Accountant to clear in QuickBooks before go-live: the
    trial balance is out by 6,750.00; about 970 customer payments (-222.6 million) are not
    applied to invoices, the debtors accounts have credit balances and Undeposited Funds holds
    218.2 million; supplier cheques and credits are not matched to bills (A/P aging -5.4
    million); Opening Balance Equity 20.3 million and Uncategorized income/expenses to clear.
  - Owner, 3 Nov 2026: the Accountant will fix all of these in QuickBooks before migrating;
    the report formats and templates stay the same, so P2-28 reads these four layouts.

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
     them a payment link from **OnePay** (owner, 3 Nov 2026). P2-27 becomes: invoice tracking
     (sent, viewed, paid) and recording the OnePay link sent for an invoice and the card
     payment received; no Pay Now button.
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
12. **Customer receipts (P2-07).** Defaults taken on 3 Nov 2026, the owner can change them:
    the Accountant approves receipts (as for advances); a customer who pays more than the
    invoices chosen has the extra recorded as an advance; cheques dated more than six months
    ahead or older than six months are refused; card payments (OnePay links) are recorded as
    money into the bank account they reach.
    - Owner, 3 Nov 2026: the Accountant approves receipts, and the Admin can give that right
      to any other person on the user page, confirmed by the Director (built as the action
      "Approve customer receipts and advances", for receipts and advances alike). The extra
      recorded as an advance is set off automatically against the customer's next invoice,
      or any later one, after the advances of that invoice's own order.
13. **Who changes credit limits and payment terms (P2-08).** Today salespeople can change
    them on the customer, which would let them lift their own customer's credit hold.
    Recommended: only the Accountant or the Director.
    - Owner, 3 Nov 2026: yes. Built as the action "Change customers' credit limits and payment
      terms" (Accountant and Director roles; a grant to anyone else is sensitive). On the
      customer page they are read-only for Sales; the Accountant or Director changes them in
      the "Credit terms" box, with a reason. A new customer starts with 30 days and no limit;
      a customer import changing them is refused for anyone without the right.
14. **VAT on export invoices (P2-09).** The ERP charges whatever the tax code on each line
    says. Exports of goods are normally zero-rated for VAT and SSCL does not apply, but the tax
    advisor should confirm. Recommended: the Accountant adds a tax code "Zero-rated export"
    (VAT at 0%) on Accounts -> Taxes and Sales use it on export quotations. Asked 3 Nov 2026.
    - Owner, 3 Nov 2026: exports of goods are zero-rated for VAT (0%) and SSCL does not
      apply; local customers who pay in a foreign currency are charged VAT and SSCL as usual.
      Built: the tax code ZERO-RATED (no tax), put on every quotation, proforma, sales order
      and invoice line for a customer marked "Export customer", whatever code was chosen. The
      currency does not decide it.
