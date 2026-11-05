# SML ERP: user acceptance test scripts and parallel run

Backlog P2-29 (spec 8.2). Each person tests their own role on the **test server** with their
own user, using the demo data or real documents copied from QuickBooks. Tick **Pass** or
**Fail** and write what happened in **Notes**. A failed step is reported to Mewantha with a
screenshot; it is fixed and tested again before go-live.

How to use these scripts:
- Work through the steps in order: later steps use what earlier ones made.
- "Expected" is what must happen. Anything else is a fail, even if it seems harmless.
- Some steps check that something is **refused**. Those are as important as the others.
- On a phone, run at least the steps marked 📱 (approvals and the shop floor must work there).

---

## 1. Accounts Clerk (L1)

| # | Steps | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| C1 | Vouchers → New voucher. Choose a supplier, division WS, type "Supplier payment". Add two lines with invoice numbers, dates and amounts. Upload the scanned invoice (photo from the phone camera 📱). Save. | Voucher saved as a draft with a number WS + date + running number. The scan opens. | | |
| C2 | Try to enter the same supplier invoice number again on a new voucher. | Refused: the invoice number is already used for this supplier. | | |
| C3 | Submit the voucher from C1. | Status "Waiting for the Accountant". The Accountant gets a notification. | | |
| C4 | Open a voucher the Accountant returned to you. Correct it and submit again. | It goes back to the Accountant; the history shows the return and the reason. | | |
| C5 | Try to open Accounts, Financial reports or Settings from the menu. | Not in the menu; typing the address shows "no access". | | |
| C6 | Petty cash (if you are a custodian): record an expense with its slip. | The expense is listed under your float; the float balance goes down. | | |

## 2. Accountant (L2)

| # | Steps | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| A1 | Open the voucher from C3. Code each line (account, division, tax code, WHT if any) and approve. | Status "Waiting for the Director". | | |
| A2 | Try to approve a voucher you created yourself. | Refused: nobody approves their own document. | | |
| A3 | Accounts → Manual journals: make a journal for an accrual, attach the support, send it. | Waiting for the Director; not posted yet. | | |
| A4 | Sales → Tax invoices: issue an invoice from a delivered sales order. Email it to yourself. | Number in the IRD format; PDF correct (VAT, SSCL, amount in words). The email has the PDF and a customer link; opening the link shows the invoice and the bank details, and the invoice's Tracking says "viewed". | | |
| A5 | Record a OnePay link sent for that invoice (Tracking → Record a OnePay link sent). | The link appears in the invoice's history. | | |
| A6 | Approve a receipt recorded by the Cashier for that invoice. | Invoice shows "Partly paid" or "Paid"; the receivables aging agrees. | | |
| A7 | Banking → Bank statements: import a statement file. Banking → Reconciliation: match it and finish the month. | Difference nil; the month is locked. | | |
| A8 | Fixed assets → Monthly depreciation: work out the month, check it, post it. | Posted entry: Dr depreciation, Cr accumulated depreciation per class and division. | | |
| A9 | Month-end revaluation: work out the month (if anything is in a foreign currency), post it. | Unrealised gain or loss posted and reversed on the 1st. | | |
| A10 | Month-end and year-end close: tick the accruals item with a note. | The checklist shows every item done when all are. | | |
| A11 | Budgets: start the year's budget, import it from Excel (use the page's own download as the layout), send it to the Director. | Waiting for the Director; the profit and loss shows nothing for budget yet. | | |
| A12 | Financial reports: trial balance, balance sheet, profit and loss (company and WS), cash flow. Click a figure. | Each figure opens its ledger; each ledger line opens its document. Trial balance balances. | | |
| A13 | Tax reports: VAT return, SSCL and WHT for the month; download Excel. | Figures trace to the invoices and payments behind them. | | |
| A14 | Report builder: build "sales by customer by month", save it, share it with the Director role. | The Director sees it under Saved reports. | | |

## 3. Director (L3)

| # | Steps | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| D1 📱 | From the notification, open the voucher from A1 on the phone. See the scans, the coding and the history. Approve. | Status "Approved"; the Cashier can now pay it. | | |
| D2 | Try to approve at two levels of the same voucher (e.g. a voucher you also approved as Accountant, if you hold both roles in testing). | Refused. | | |
| D3 📱 | Approve the manual journal from A3. Return another one with a reason. | The approved one is posted; the returned one goes back to the Accountant with your reason. | | |
| D4 📱 | Approve a quotation: see the costing summary and the product pictures. | Approved; the salesperson can email it with the pictures. | | |
| D5 📱 | Approve the budget from A11. | Profit and loss now shows Budget, Difference and %. | | |
| D6 | Close last month (Accounts → Month-end and year-end close). Try first while an item is still open. | Refused with the list of what is still to do; closed once all items are done. Posting into it is then refused. | | |
| D7 | Reopen the month with a reason. | Reopened; the reason is in the audit log. | | |
| D8 | Home page: the finance tiles. Switch to WS and IM. | Each tile opens its report; figures agree with the reports. | | |
| D9 | Cash flow planner: add a what-if (a machine purchase); untick it. | The balance line and the lowest point move; nothing is posted. | | |

## 4. Cashier

| # | Steps | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| K1 | Pay the voucher approved in D1 by cheque from a bank account. | Payment recorded; cheque leaf used; voucher "Paid". | | |
| K2 | Try to pay more than the approved amount, or a voucher not yet approved by the Director. | Refused (by the screen and by the database). | | |
| K3 | Record a customer receipt by cheque against an invoice; record another by bank transfer. | The cheque waits in "Undeposited funds"; the transfer goes to the bank account. | | |
| K4 | Banking → Cheques: deposit the cheque. Then mark another cheque as returned. | Deposit slip made; the returned cheque's invoice is open again. | | |

## 5. Sales Executive and Sales Manager

| # | Steps | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| S1 | New quotation for a customer: lines, quantity breaks, the drawing, up to 3 product pictures (try a 4th, and one over 1 MB). | Saved. The 4th picture and the large one are refused with a clear message. | | |
| S2 | Fill in the costing and submit the quotation. | Waiting for the Director. | | |
| S3 | After D4, email the quotation; untick the pictures once, leave them ticked once. | The customer receives the PDF, with or without the pictures as chosen. Status "Sent". | | |
| S4 | Record the outcome (accepted) and make the sales order. Confirm it. | Sales order confirmed; credit control checked (a customer over their limit goes on Credit holds). | | |
| S5 | Sales Manager: see the sales dashboard and the reports for the team. | Figures for all salespeople of your divisions. | | |

## 6. Purchasing Officer, Stores and QC

| # | Steps | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| P1 | Make a purchase order; send it to the Director; after approval email it to the supplier. | PO numbered PO + date; emailed only once approved. | | |
| P2 | Stores: receive the goods against the PO, package by package; print the QR labels. | GRN confirmed; goods in Quarantine. | | |
| P3 | QC: inspect; accept some packages and reject one. | Accepted quantity in available stock; rejected one in the Rejected store. | | |
| P4 | Accounts: enter the supplier invoice; the three-way match passes. Change one price and see it blocked. | Exact match posts; a difference waits for the Director. | | |
| P5 | Stores: issue material to production; count a store and post the differences after Director approval. | Stock and its value go down; the count's differences post once approved. | | |
| P6 | Reorder: an item below its reorder level. | Alert to Stores and Purchasing; a one-click purchase request. | | |

## 7. System Administrator

| # | Steps | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| X1 | Add a user, give a role and divisions; the user signs in and sets up two-factor. | Sign-in works only with the code. | | |
| X2 | Give a sensitive right (e.g. "Approve credit notes") to a salesperson. | It waits for the Director's confirmation. | | |
| X3 | Settings → Document email: enter the mailbox (you type the password) and send a test. | Test email arrives. | | |
| X4 | Audit log: find the voucher from C1 and see every change and approval. | All there, with who, when and from where. Nothing can be edited. | | |
| X5 | Try to open a voucher, a payment or the ledger as Admin. | Not available: the Admin is kept apart from money. | | |

---

## 8. Parallel run (one month in both systems)

1. **Go-live data.** At the end of the month before the parallel month, the Accountant
   clears the QuickBooks findings (trial balance difference, unapplied payments, Undeposited
   funds, Opening balance equity), then brings over: the chart of accounts, customers and
   suppliers (Excel imports), the opening balances and the open invoices and bills (Accounts
   → Opening balances from QuickBooks), the stock count (Stores → Opening stock) and the
   fixed asset register (Fixed assets). The Director approves each.
2. **During the month.** Every transaction is entered in both systems the same day:
   vouchers and payments, receipts, tax invoices, supplier invoices, journals.
3. **At the month end.** In QuickBooks, export the trial balance, the A/R ageing detail and
   the A/P ageing detail as at the last day. In the ERP, open **Accounts → Parallel run:
   compare with QuickBooks**, upload them and press Compare.
4. **Explain every difference.** Each line that does not agree is either a mistake in one
   system (correct it and compare again) or a known difference, written down below.
   Known by design: income and costs before go-live sit in Retained earnings in the ERP.
5. **Bank balances.** The bank accounts are among the accounts compared; they must also
   agree with the bank statements (Banking → Reconciliation, nil difference).
6. **Sign-off** when everything agrees or is explained.

| Item | QuickBooks | ERP | Difference | Explained by | Initials |
| --- | --- | --- | --- | --- | --- |
| Trial balance total | | | | | |
| Debtors | | | | | |
| Creditors | | | | | |
| Each bank account | | | | | |
| Profit for the month | | | | | |

## 9. Sign-off

| | Name | Signature | Date |
| --- | --- | --- | --- |
| Accountant: parallel run agreed | | | |
| Auditors: opening balances and parallel run reviewed | | | |
| Director: user acceptance testing passed | | | |
| Owner: go-live approved; QuickBooks closed for entry from (date) | | | |

After sign-off, QuickBooks is kept read-only for reference and is not used for new entries.
