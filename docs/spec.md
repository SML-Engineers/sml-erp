# SML ERP — System Design Specification

Oct 26, 2026 · @P R H M P Somarathna

## 1. Overview

SML ERP is a custom-built, web-based ERP for a business with two divisions: a metal machining workshop and a plastic injection moulding plant. It is delivered in four phases, starting with a payment voucher approval system that becomes the only route by which supplier payments enter the books.

| Phase | Scope | Depends on |
| --- | --- | --- |
| 0. Core foundation | Users, roles, company, divisions, chart of accounts, suppliers, journal, audit log, approval engine | — |
| 1. Payment vouchers | Invoice upload, 3-level approval, supplier payments locked to approved vouchers | Phase 0 |
| 1.5. Sales documents | Customers, quotations with costing, proforma invoices, sales orders, customer advances | Phase 0 |
| 2. Financial accounting | QuickBooks-equivalent modules: AP, AR, banking, assets, inventory valuation, payroll, tax, reports | Phases 0, 1 |
| 3. Production | Machining job cards, moulding shift production, supervisor entry pages, QC, OEE, job costing | Phases 0, 2 |

**Users**

| Role | Level | Main responsibility |
| --- | --- | --- |
| Accounts Clerk | L1 | Create vouchers, upload scanned invoices |
| Accountant | L2 | Verify and code vouchers, first approval |
| Director | L3 | Final approval of vouchers, high-value quotations, low-margin quotations |
| Cashier / Payment Officer | — | Record payments against approved vouchers |
| Sales Executive | — | Prepare quotations and proforma invoices |
| Production Supervisor | — | Enter shift production data for assigned sections |
| Production Manager | — | Approve shift reports, plan production |
| Stores Manager / Executive | — | Goods receipts with weights and counts per package, material issues and returns (SML has one stores person) |
| Auditor | — | Read-only access, including all logs |
| System Admin | — | Users, roles, master configuration |

One user can hold several roles. Permissions attach to roles, never directly to users.

### 1.1 Standard roles

The roles follow the usual ERP practice of separating three duties: whoever *records* a transaction does not *approve* it, and neither of them *pays* it. IT administration is kept apart from money. The standard roles below are loaded at setup; the Admin can also create custom roles by ticking permissions, and can assign several roles to one person.

| Role | From phase | Can | Cannot |
| --- | --- | --- | --- |
| System Administrator | 0 | Users, roles, settings pages, master codes; delete vouchers that have no payment (with reason) | Create, approve or pay vouchers; post journals |
| Director | 1 | Final approval (L3); approve deletions, cancellations, quotation limits, period close; all reports | Record payments |
| Accountant | 1 | Review and code vouchers (L2); suppliers and payees; chart of accounts; journals; bank reconciliation | Final approval; record payments |
| Accounts Clerk | 1 | Create vouchers, upload scans, submit; create payees | Approve anything |
| Cashier / Payment Officer | 1 | Record payments against Director-approved vouchers; cheque register | Create, edit or approve vouchers |
| Auditor | 1 | Read everything, including audit and approval logs; export | Change anything |
| Sales Executive | 1.5 | Customers, quotations, proformas, sales orders | Approve quotations above limits |
| Sales Manager | 1.5 | Approve quotations within the limits; sales reports | Change rate tables |
| Purchasing Officer | 1.6 | Purchase requests and orders | Approve own purchase orders |
| Stores Manager / Executive | 1.6 | Goods receipts with weights and counts, material issues and returns | Inspection results; holding the QC Inspector role (refused) |
| QC Inspector | 1.6 | Inspection results; accept or reject lots | Change received quantities; holding a stores role (refused) |
| HR and Payroll Officer | 2b | Employees, attendance, payroll preparation | Approve payroll (Director) |
| Production Planner | 3 | Job orders, production plans | Approve shift reports |
| Production Supervisor | 3 | Shift entries for assigned sections only | Other sections' data |
| Production Manager | 3 | Approve shift reports, corrections, deviations | Payments |

**Conflicting combinations.** When the Admin gives one person two roles that should be separated (Clerk + Cashier, Accountant + Cashier, Admin + any finance role), the system shows a warning and records the reason in the audit log. Whatever roles a person holds, they can never approve a document they created or approve one document at two levels.

**Phase 1 permissions**

| Action | Clerk | Accountant | Director | Cashier | Auditor | Admin |
| --- | --- | --- | --- | --- | --- | --- |
| Create, edit draft, upload scans, submit | ✓ |  |  |  |  |  |
| Review and code, approve / return / reject at L2 |  | ✓ |  |  |  |  |
| Approve / return / reject at L3 |  |  | ✓ |  |  |  |
| Delete an unsubmitted draft | own |  |  |  |  | ✓ |
| Delete a submitted voucher with no payment (reason required) |  |  | ✓ |  |  | ✓ |
| Start an amendment of an approved voucher | ✓ | ✓ |  |  |  |  |
| Request / approve cancellation |  | request | approve |  |  |  |
| Record payment |  |  |  | ✓ |  |  |
| View and print vouchers | own | all | all | approved | all |  |
| Add payees / edit bank details | add | ✓ |  |  |  |  |
| Chart of accounts |  | ✓ | view |  | view |  |
| Settings pages, users and roles |  |  | confirm limits |  | view | ✓ |
| Audit and approval logs |  |  | view |  | view | view |

### 1.2 Access control model

Access follows role-based access control (RBAC, as defined in the NIST RBAC standard, ANSI/INCITS 359) and the access-control controls of ISO/IEC 27001:2022 Annex A: access control (5.15), access rights (5.18), segregation of duties (5.3), privileged access (8.2) and information access restriction (8.3).

**Principles**

- **Deny by default:** a user sees only the areas their roles open; everything else is hidden from menus and refused by the server.
- **Least privilege and need to know:** each role gets only what its job needs, and only for its own divisions and sections.
- **Segregation of duties:** recording, approving and paying are held by different people (1.1).
- **Privileged access kept separate:** the System Administrator manages users and settings, not money.
- **Every grant is traceable:** who gave which access, to whom, when, why and until when.
- **Regular review:** access is reviewed and confirmed periodically, and removed when people leave or change jobs.

**How a user's access is worked out**

1. **Roles** give the default access, from the matrices below. A user can hold several roles.
2. **Data scope** limits it to the user's divisions (WS, IM, HO…) and, for production staff, their sections. A Production Supervisor for Manual Milling sees only Manual Milling.
3. **Overrides** set by the Admin for that user add or remove access to an area or action (1.3).
4. **Hard controls** apply last and cannot be overridden by anyone (1.3).

The result is shown on the user's **Effective access** page, so it is always clear what a person can do and why.

**Access levels**

| Level | Meaning |
| --- | --- |
| — | No access: the area is hidden |
| V | View: read, search, print and export |
| E | Enter: create and edit their own records, and submit them |
| A | Approve: review, approve, return or reject at the role's level (includes V) |
| M | Manage: full maintenance of that area's records or settings (includes V and E) |

Special actions sit outside the levels and are granted one by one: record payments, delete a submitted voucher, close a period, change bank details, export personal data, manage users and roles.

**Default access: finance and administration roles**

| Area | Admin | Director | Accountant | Clerk | Cashier | Auditor |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard | V (system) | V (all) | V | V (own) | V (own) | V |
| Payment vouchers | V, delete\* | A (L3), delete\* | E, A (L2) | E | V (approved) | V |
| Supplier payments | — | V | V | — | E, pay\* | V |
| Banking and reconciliation | — | V | M | — | V | V |
| Suppliers and payees | — | V | M, bank details\* | E (add) | V | V |
| Chart of accounts and journals | — | V, close period\* | M | — | — | V |
| Financial reports (P&L, balance sheet) | — | V | V | — | — | V |
| Sales | — | A (above limits) | V | — | — | V |
| Purchasing | — | A | V | — | — | V |
| Stores and goods receipt | — | V | V | — | — | V |
| Quality | — | A (deviations) | V | — | — | V |
| Production and costing | — | V | V | — | — | V |
| HR and payroll | — | A (payroll) | V (totals) | — | — | V (totals) |
| Settings (divisions, sections, machines, shifts, currencies, numbering) | M | V, confirm limits | V | — | — | V |
| Users, roles and access | M | V, confirm sensitive grants | — | — | — | V |
| Audit and approval logs | V | V | V (finance) | — | — | V |

**Default access: operations roles**

| Area | Sales Exec. | Sales Mgr | Purchasing | Store Sup. | QC Insp. | HR & Payroll | Planner | Prod. Sup. | Prod. Mgr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dashboard | V (own) | V (sales) | V (own) | V (own) | V (own) | V (own) | V (prod.) | V (sections) | V (prod.) |
| Payment vouchers | — | — | — | — | — | — | — | — | — |
| Suppliers and payees | — | — | E | V | V | — | — | — | — |
| Sales: customers, quotations, proformas, orders | E | A (within limits) | — | — | — | — | V | — | V |
| Purchasing | — | — | E | V | V | — | V | — | V |
| Stores and goods receipt | — | — | V | E | V | — | V | V | V |
| Quality: inspection | — | — | V | V | A | — | — | V | A (deviations) |
| Production planning and job orders | V (status) | V (status) | — | — | — | — | E | V | A |
| Shop-floor entry | — | — | — | — | E (inspection) | — | — | E (own sections) | V |
| Production approvals and reports | — | — | — | — | V | — | V | V (own sections) | A |
| Job and order profitability | — | V | — | — | — | — | — | — | V |
| HR and payroll | — | — | — | — | — | M | — | V (attendance) | V (attendance) |

Operations roles have no access to vouchers, payments, banking, accounting, financial reports, settings, users or logs unless the Admin grants it. \* = special action. Areas for later phases switch on as those phases go live.

### 1.3 Admin overrides and access administration

The Admin can give or remove access for an individual user, overriding their roles' defaults, from the **User access** page.

**User access page**

- The user's roles and data scope (divisions, sections).
- A grid of every area and action showing, for each: the default from the roles, any override, and the resulting effective access, colour-coded (granted by override, removed by override).
- **Grant** or **remove** any area or action for this user, with a mandatory reason and an optional end date for temporary access (e.g. covering for someone on leave). Expired overrides lapse automatically and the user is notified.
- A removal always beats a grant, from a role or from another override.
- **Copy access from another user**, and **reset to role defaults**.
- History of every change to this user's access.

**Sensitive grants need the Director's confirmation.** Following ISO/IEC 27001 control 8.2 on privileged access, an override that gives any of the following takes effect only after the Director confirms it on the same page: approving vouchers at any level, recording payments, deleting vouchers, changing supplier bank details, closing periods, managing users and roles, and access to payroll. Removing access never needs confirmation, so access can be cut immediately.

**Hard controls (cannot be overridden by anyone)**

- No one approves a document they created, or approves one document at two levels (rules 5 and 6).
- Every voucher passes all three approval levels; no override can skip the Director.
- The Admin cannot change their own access or roles; another Admin or the Director must do it.
- Audit and approval logs cannot be edited by anyone.
- Data scope can be widened only by an explicit override, never by accident through a role.

**Joiners, movers and leavers**

- **New user:** created by the Admin from a role template, with divisions and sections; temporary password and two-factor setup on first login. The account is created switched off and can only be activated once it has at least one role and its divisions (owner's decision, 31 Oct 2026).
- **Password reset:** the Admin requests it with a reason (optionally resetting the authenticator too, for a lost phone); a Director other than the requester and the person approves it; within 24 hours the Admin makes a temporary password, shown once and never stored. The person is signed out everywhere and must choose a new password at the next sign-in. Every step is audited (owner's decision, 31 Oct 2026).
- **One Admin, no backup Admin account** (owner's decision, 31 Oct 2026). If the Admin forgets the password, it is reset on the server with a technical command run by the owner with support (`manage.py changepassword`); this bypasses the Director's approval and the ERP's audit log, so the owner records each use in writing. Recovery codes cover a lost phone.
- **Change of job:** roles changed and old overrides reviewed on the same screen, so access from the old job is not carried over.
- **Leaver:** one action deactivates the account, ends all sessions and removes overrides. The user's records and history stay.
- Accounts unused for 90 days are deactivated automatically (configurable).

**Access review**

- Every quarter the system produces an **access review report** per manager: each user, their roles, overrides, sensitive access and last login.
- The Director (or each manager for their people) confirms or removes each line. Unconfirmed sensitive overrides are flagged.
- Reports of conflicting role combinations, active overrides and their expiry dates are available at any time.

## 2. Technology stack and architecture

The system is a modular monolith: one codebase and one PostgreSQL database, split into modules with clear boundaries. Microservices are deliberately avoided; they add operational cost an ERP of this size does not need.

| Layer | Choice | Reason |
| --- | --- | --- |
| Database | PostgreSQL | ACID transactions, exact NUMERIC money, constraints and triggers enforce business rules |
| Backend | Python, Django + Django REST Framework | Mature ORM, admin for master data, permissions, strong data libraries for analytics |
| Background jobs | Celery + Redis | Notifications, report generation, invoice thumbnails, scheduled tasks |
| Frontend | React + TypeScript, AG Grid or TanStack Table | Table- and form-heavy UI, large grids, responsive layouts |
| File storage | S3-compatible (self-hosted SeaweedFS, or AWS S3) | Scanned invoices and drawings kept outside the database, versioned |
| Shop-floor client | Same React app as a PWA | Works on tablets, offline entry with sync |
| Deployment | Docker, Nginx, Hostinger Ubuntu VPS | Simple to run, restore and scale |

If the development team is stronger in PHP, Laravel replaces Django with no change to the rest of this design.

**Module layout**

```
erp/
├── core/          users, roles, permissions, company, divisions,
│                  number series, audit log, approval engine, notifications
├── masters/       suppliers, customers, items, banks, machines, moulds
├── accounting/    chart of accounts, journal, periods, financial reports
├── vouchers/      Phase 1: voucher types, workflow, attachments
├── payments/      Phase 1: supplier payments (locked to approved vouchers)
├── sales/         Phase 1.5: quotations, proformas, sales orders, advances
├── purchasing/    Phase 2: purchase requests, POs, GRNs, bills
├── inventory/     Phase 2: stock, warehouses, valuation
├── assets/        Phase 2: fixed assets, depreciation
├── payroll/       Phase 2: salaries, EPF/ETF, payslips
├── production/
│   ├── common/    sections, shifts, shift reports, downtime, rejects
│   ├── machining/ Phase 3: job orders, routings, job cards
│   └── moulding/  Phase 3: mould runs, shots, material, OEE
└── quality/       Phase 3: inspection plans and records
```

**Module rules**

- Modules call each other through service functions, never by writing into another module's tables.
- Only the `accounting` module writes journal entries. Other modules (payments, sales invoices, payroll, production costing) ask it to post.
- Every module exposes a REST API; the frontend uses only that API, so a mobile app or integrations can be added later.

**Security**

- HTTPS everywhere; passwords hashed with Argon2.
- Two-factor authentication required for Accountant, Director, Cashier and Admin.
- Permissions checked on the server for every request, not only hidden in the UI.
- Scanned files served through short-lived signed URLs.
- Session timeout and login history per user.
- Nightly encrypted database and file backups, copied off-site, with a monthly restore test.

**Hosting on Hostinger Ubuntu VPS**

- Ubuntu LTS release, with the application, PostgreSQL, Redis and SeaweedFS (file storage) running in Docker containers behind Nginx.
- Free SSL certificates from Let's Encrypt, renewed automatically.
- Starting size: 4 vCPU, 16 GB RAM, 200 GB NVMe disk; scanned invoices and drawings are the main growth in disk use.
- Data centre: the region closest to Sri Lanka that the provider offers, for fast page loads.
- Firewall open only for HTTPS and SSH; SSH by key only, no password login.
- Backups: the provider's VPS snapshots, plus nightly database and file backups copied to separate storage outside Hostinger, so a problem with the VPS account cannot take the backups with it.
- A second, smaller VPS as a test environment, where every update is tried before production.

## 3. Core foundation (Phase 0)

The accounting core is built first, even though users first see the voucher system. Vouchers and payments are accounting transactions; building them on a correct ledger from day one avoids rewriting them in Phase 2.

**Organisation**

- Company: name, registration, VAT number, base currency (LKR), financial year start.
- Divisions: Workshop and Plastic Injection Moulding today; the Admin adds more at any time. Every income and expense line carries a division, so every report, including the profit and loss, can be run per division (see 3.1).
- Branches or locations, if the factories are at different sites.

### 3.1 Divisions and divisional reporting

Division is the one dimension every part of the system reports by, from vouchers to the profit and loss, so the profit of each division (for example Plastic Injection Moulding) can be seen at any time.

**Division master** (Admin, page 3A.1)

| Code (PP) | Division | Type |
| --- | --- | --- |
| WS | Workshop | Production |
| IM | Plastic Injection Moulding | Production |
| HO | Head Office (shared costs) | Shared |

These starting divisions and codes are confirmed by the owner. The Admin maintains divisions (add, rename, deactivate) from the Divisions control panel (3A.1). A new division added later appears at once in every form, filter and report; earlier periods are unaffected.

**Adding a division while the system is live.** The Admin adds a division at any time after go-live, from the Divisions control panel, with no developer, no new deployment, no restart and no downtime. The steps are on one screen: code and name, type (Production or Shared), default bank account, which users may work in it, then its sections and machines (3A.1). From that moment the division can be chosen on vouchers and every other document, has its own voucher numbers (its code + date + running number), appears in every filter, report and dashboard, and gets its own column in the divisional profit and loss. Earlier periods and other divisions' figures do not change. The Accountant then adds it to the overhead allocation bases and budgets.

**Every transaction carries a division**

- Every income and expense line in the ledger must have a division; the system refuses to post one without it.
- Documents take their division from where they start: a voucher from its header (the PP in its number), a sales invoice from its sales order, a goods receipt from its purchase order, production from the section's division.
- A shared bill can be split across divisions by amount or % on one voucher (e.g. an electricity bill split by sub-meter readings).
- Balance sheet items such as bank and loans belong to the company. Receivables, payables, stock, work in progress and fixed assets also carry a division, so they can be analysed per division too.

**Shared costs and allocation**

Costs that belong to the whole company (rent, directors, audit fee, office staff) are booked to the Shared division (HO). Once a month the Accountant runs an **overhead allocation**: HO costs are spread to the production divisions by a basis set per group of accounts (fixed %, machine hours, headcount, floor area or sales). The allocation is posted as a journal, so it is visible, traceable and reversible. Divisional reports show profit both before and after allocated overheads.

**Work between divisions**

When the Workshop makes or repairs moulds, or supplies parts, for Plastic Injection Moulding, it is recorded as an inter-division transfer at cost (or cost plus a set %). It is income for the Workshop and a cost or an asset for Moulding, and is eliminated in the company totals so nothing is counted twice.

**Divisional reports**

| Report | Per division |
| --- | --- |
| Profit and loss | Side by side: WS, IM, HO and company total; month, year to date, comparison with last year and budget; before and after allocated overheads |
| Key figures | Sales, gross margin %, direct cost, overheads, net profit, cost per machine hour |
| Budget vs actual | Budget set per account and division |
| Payables and vouchers | Pending and paid vouchers, supplier spend |
| Receivables and sales | Sales, quotations won and lost, customer aging |
| Stock and purchasing | Stock value, purchases, incoming inspection results |
| Production | Output, rejects, OEE, job and production order profitability (7.7) |
| Balance sheet | Company total, with division breakdown of receivables, payables, stock, WIP and fixed assets |

Every list and report has a division filter, and the dashboard can be switched between divisions or show all of them together.

**Chart of accounts**

- Works like QuickBooks: the Accountant adds, renames, merges or deactivates accounts at any time from the Chart of Accounts page, with no code change.
- Every account has an **account type** and a **detail type**, as in QuickBooks. The type decides where the account appears in the reports and how it behaves:

| Report section | Account types |
| --- | --- |
| Balance sheet: assets | Bank, Accounts receivable, Other current asset, Fixed asset, Other asset |
| Balance sheet: liabilities | Accounts payable, Credit card, Other current liability, Long-term liability |
| Balance sheet: equity | Equity |
| Profit and loss | Income, Other income, Cost of goods sold, Expense, Other expense |

- Detail types refine the type (e.g. Fixed asset → Machinery and equipment, Vehicles, Moulds and tooling; Expense → Electricity, Repairs and maintenance). The list of detail types is editable.
- **Sub-accounts** to any depth (e.g. Repairs and maintenance → Machine repairs → CNC machines). Reports can show sub-accounts or roll them up into their parent. As in QuickBooks, a sub-account has the same account type as its parent, so it is printed in the same block of the reports.
- **Account numbers** are optional, as in QuickBooks; when used, they set the sort order. Names must be unique within the same parent and cannot contain a colon (the Excel import writes Parent:Sub-account). Once an account has been used, its number is fixed (rule 9); its name can still change.
- Accounts with transactions cannot be deleted, only made inactive (rule 9); making an account inactive also makes its sub-accounts inactive. Two accounts of the same type can be merged, moving all their history to one: posted entries are never rewritten (rule 3), so the merged account keeps them, becomes inactive and points at the remaining account, and every report counts its entries under the remaining account. Its sub-accounts move to the remaining account. A merge cannot be undone.
- Each account can carry a default tax code and a default division.
- Each company bank, cash or petty cash account is linked to one Bank-type account in the chart, its ledger.
- Some accounts are created by the system and cannot be removed: Accounts payable, Accounts receivable, Retained earnings, Opening balance equity, Undeposited funds, Customer advances, VAT payable and receivable.
- A starter chart for a manufacturing company, based on QuickBooks' default chart, is loaded at setup. The company accountant reviews and edits it before go-live.
- Import and export of the chart from Excel, so an existing chart can be loaded in one step.

**Taxes (as in QuickBooks)**

- The Accountant keeps the taxes, with no code change (confirmed by the owner, 29 October 2026). A **tax** (VAT, SSCL, withholding tax…) has dated rates (rule 11) and the ledger accounts it is recorded in: on sales, the tax owed to the government; on purchases, the tax claimed back, or none when it is part of the cost.
- A **tax code** is chosen on each document line. It lists the taxes charged, in order; each is charged on the net amount or on the net amount plus the taxes above it. The tax invoice's rule (6.1: SSCL, then VAT on the amount plus SSCL) is the starting code VAT-SSCL. Each tax is rounded half-up to the cent.
- Once a document has used a tax, a new rate can only start today or later and a rate in force cannot change; once a tax code has been used, its taxes cannot change (a new code is made instead). Withholding tax is deducted when paying, not in tax codes. The Accountant picks it per voucher line when coding; the Cashier pays the payee the net and prints a WHT certificate (P2-12).

**Journal (the ledger)**

- `journal_entry`: number, date, source document type and id, narration, posted\_by, status.
- `journal_line`: account, division, party (supplier or customer), debit, credit.
- Rules enforced in code and by a database check: total debits equal total credits, amounts are `NUMERIC(18,2)`, never floating point.
- Only posted entries are stored; a document's draft lines stay on the document until it is posted.
- Posted entries are never edited or deleted; corrections are made by reversing entries. A reversal is the mirror entry, linked to the original, dated like it when its month is open and otherwise today; it cannot itself be reversed.
- Lines go only to active accounts that have not been merged; income and expense lines need a division (database too).
- Accounting periods (calendar months) can be closed by the Director once the month has ended, and reopened with a reason. No posting into a closed period, and an account with entries in a closed period keeps its type.

**Number series**

Each document type has a number format built from tokens and set by the Admin. The voucher format is **PPYYMMDDXXX**: PP is the two-character code of the voucher's division (set by the Admin on the division), YY the year, MM the month, DD the day, and XXX a running number that restarts at 001 each day for each division. For example, if Plastic Injection Moulding has the code IM, the third voucher of that division created on 23 October 2026 is IM261023003. The voucher type (cheque, online, petty cash…) is a field on the voucher and a filter in every list, not part of the number. Other documents use the same mechanism with their own formats. Numbers are allocated inside the database transaction that saves the document, so there are no duplicates, and a number once given is never reused, even if its document is later deleted.

Tokens are written in braces so they cannot be confused with fixed text: {PP} division code, {IC} the division's tax invoice code, {YY} or {YYYY} year, {MM} month number or {MMM} month letters (JAN … DEC), {DD} day, and one running number ({XX}, {XXX}, {NNNN}: one letter per digit, at least). Each series also says what happens when the running number has used all its digits: stop and ask the Admin to widen it, or carry on with more digits (99, 100, 101 …).

| Document | Format | Example | Restarts | When full |
| --- | --- | --- | --- | --- |
| Payment voucher | {PP}{YY}{MM}{DD}{XXX} | IM261023003 | Daily, per division | Stop (Admin widens) |
| Tax invoice | {YY}{MMM}_{IC}_{XX} | 26SEP_W1_35 | Monthly, per division | Carry on (26SEP_W1_100) |
| Quotation | QL{YY}{MM}{DD}{XX} | QL26102105 (5th on 21 Oct 2026) | Daily | Carry on |
| Proforma invoice | PI-{YYYY}-{NNNN} | PI-2026-0001 | Yearly | Carry on |
| Journal entry | JV{YY}{MM}{NNNN} | JV26100001 | Monthly | Carry on |

The tax invoice number follows the government format YYMMM_QQQQ_XXXXX (Inland Revenue, Gazette 2481/22, in force from 1 July 2026): YY year, MMM month letters, QQQQ an alphanumeric code of 1 to 15 characters for the issuing unit (here the division's tax invoice code, e.g. W1 for the Workshop), XXXXX a numeric serial with no letters or symbols; no spaces, 40 characters at most. Confirmed by the owner: the serial restarts at 01 each month for each division and never stops.

**Approval engine (shared)**

One generic engine serves vouchers, quotations, purchase orders, shift reports and corrections.

- An approval *matrix* defines, per document type, the levels required and the conditions (amount range, division, voucher type).
- Each level names a role, not a person, so leave cover works by assigning the role.
- A user can never approve a document they created or one they already approved at a lower level.
- Every action writes to an insert-only approval log.
- Level 1 is the person who submits; approval levels start at 2. Where several rules fit a document at the same level, the most specific one (division, sub-type, amount range) is used. The route is copied onto the document when it is submitted, so a later matrix change never alters a document already on its way; a returned document is routed afresh when resubmitted.
- The Admin maintains the matrix on a settings page. Rules are added or switched off, never edited, and the matrix always keeps each document type's minimum: for vouchers, two approval levels that apply to every voucher, the last being the Director.

**Audit log**

Every create, update and delete on master data and transactions records the user, timestamp, IP address, and old and new values. The log is insert-only; no role, including Admin, can edit it.

**Notifications**

In-app bell (as in the current system), email, and optionally SMS or WhatsApp. Users choose which events notify them. Typical events: voucher awaiting my approval, voucher returned to me, quotation approved, shift report awaiting approval.

## 3A. Admin settings pages

Factory structure, shifts, approval limits and currencies are maintained by the System Admin on settings pages, never in code. Every change on these pages is recorded in the audit log with old and new values, and settings that affect costs or approvals are dated, so past documents keep the values in force when they were created.

| Page | Maintains | Used by |
| --- | --- | --- |
| 3A.1 Divisions, sections and machines | Factory structure, machine details and rates | Supervisor pages, planning, OEE, costing, quotations |
| 3A.2 Shifts and rosters | Shift times, roster patterns, crews, seasonal assignments | Shift reports, manpower, OEE planned time, overtime |
| 3A.3 Quotation approval limits | Minimum margin % and value limits | Quotation approval (5.1) |
| 3A.4 Currencies and exchange rates | Currencies, daily rates | Quotations, invoices, receipts (5.5) |

### 3A.1 Divisions, sections and machines

**Layout:** a tree on the left (Division → Section → Machine) with search, and the selected item's form on the right. Buttons: Add division, Add section, Add machine, Import from Excel, Export.

**Division fields:** two-character code (the PP in document numbers; cannot change once used), name, type (Production or Shared), tax invoice code (1 to 15 letters or digits, e.g. W1: the QQQQ in tax invoice numbers; set by the Admin, unique, and fixed once an invoice has used it), default bank account, active. Adding a division makes it available at once in every form, filter and report.

**Section fields:** code, name, division, category (Manual or CNC), section type (Machining, Moulding, Support), supervisors (multi-select from users), active.

**Machine fields (all divisions):** code, name, section, make, model, serial no., year, hourly machine rate (dated history), status (Active, Under maintenance, Retired), photo, notes.

**Extra machine fields for moulding machines:** clamping force (tonnes), maximum shot weight (g), screw diameter (mm), tie-bar spacing (mm × mm), maximum mould height and thickness (mm). The system uses these to warn when a mould is planned on a machine that is too small for it.

**Rules**

- Codes are unique and cannot be changed once used on a transaction; names can.
- A machine can be moved to another section; its earlier production stays reported under the old section.
- A section or machine with history cannot be deleted, only made inactive, which hides it from entry pages.
- A new rate applies from its effective date; earlier jobs keep the old rate.

**Initial data: Workshop division (18 sections)**

| Code | Section | Category |
| --- | --- | --- |
| M-MIL | Manual Milling | Manual |
| M-LAT | Manual Lathe | Manual |
| M-DRL | Manual Drilling | Manual |
| M-SHP | Manual Shaping | Manual |
| M-GRD | Manual Grinding | Manual |
| M-POL | Manual Polishing | Manual |
| M-EDM | Manual EDM | Manual |
| M-WED | Manual Wire EDM | Manual |
| M-BSW | Manual Bandsaw | Manual |
| C-MIL | CNC Milling | CNC |
| C-LAT | CNC Lathe | CNC |
| C-DRL | CNC Drilling | CNC |
| C-SHP | CNC Shaping | CNC |
| C-GRD | CNC Grinding | CNC |
| C-POL | CNC Polishing | CNC |
| C-EDM | CNC EDM | CNC |
| C-WED | Wire EDM | CNC |
| C-BSW | CNC Bandsaw | CNC |

Codes are suggestions; the Admin can change them before go-live. No machines are pre-loaded. The Admin adds every machine under its section from this control panel, including the 3 Manual Milling machines and the 8 moulding machines with their tonnage, and adds new sections or machines whenever the factory changes.

### 3A.2 Shifts and rosters

Four tabs:

1. **Shifts:** name, start time, end time, break minutes. Shifts ending after midnight are detected automatically. Pre-filled: General 08:00–17:00.
2. **Roster patterns:** name and an ordered cycle built by picking a shift or Off for each day, e.g. Day, Day, Night, Night, Off, Off. Shows hours per cycle and average hours per week.
3. **Crews:** crew name (A, B, C…), division, members picked from the employee list.
4. **Roster calendar:** assign a pattern to a division or section for a date range, with each crew's starting point in the cycle. A 4-week preview shows who is on each shift each day.

**Checks:** a warning when a section has a day or night with no crew on shift, when one crew is assigned two overlapping rosters, or when a change would alter shifts that already have submitted production reports.

### 3A.3 Quotation approval limits

| Setting | Per | Example (to be set) |
| --- | --- | --- |
| Minimum margin % | Division (optional: per customer group) | Workshop 20%, Moulding 15%; 1% while none is confirmed (owner, 2 Nov 2026) |
| Maximum value (a warning to the Director) | Division, in LKR (foreign-currency quotations converted at the day's rate); may be left empty for no maximum | LKR 1,000,000 |
| Approver | Role | Director |

- Each setting has an effective date and a history of earlier values.
- Because these limits are financial controls, a change entered by the Admin takes effect only after the Director confirms it on the same page.

### 3A.4 Currencies and exchange rates

**Currencies tab:** LKR is the fixed base currency. Common currencies are pre-loaded and switched on or off by the Admin: USD, EUR, GBP, AUD, JPY, CNY, INR, SGD, AED. Fields: ISO code, name, symbol, decimal places, active. Other currencies can be added.

**Exchange rates tab:** date, currency, rate to LKR (buying and selling, if the bank quotes both). Entered daily by the Accountant or imported from a CSV. If no rate exists for a date, the latest earlier rate is used and flagged on the document.

**Customer currency:** each customer record has a default currency chosen from the active list.

## 3B. Sending documents and reports by email

Every document and report the company sends out (quotations, proforma invoices, tax invoices, purchase orders, payment advices to suppliers, customer statements and outstanding reports, and any other report) can be emailed directly from the system, from a separate company mailbox such as finance@domain.com. Confirmed by the owner on 29 October 2026.

**Sending account (Admin, Settings → Document email)**

- The Admin sets the mailbox documents are sent from: sender name and address, reply-to address, the mail server (host, port, security: STARTTLS, SSL or none) and its user name and password, and an optional address that receives a copy of every email (so the finance mailbox keeps everything that was sent).
- The password is stored encrypted and is never shown again or sent to the browser; the Admin can only replace it.
- A **Send test email** button checks the settings before they are used.
- This account is used only for documents and reports. System notifications (P0-18) keep their own account.
- The mail server is normally the finance mailbox's own provider (for example the Hostinger email service of the company domain), so that the domain's SPF and DKIM records cover the emails and they do not land in spam. A mail server on the VPS itself can be used instead by entering its address.

**Default messages (Admin, same page)**

- For each kind of document or report, the Admin sets a default subject and message body. They can contain placeholders that are filled in for each email, for example {customer_name}, {document_number}, {amount}, {due_date}, {company_name}, {sender_name}. The page lists the placeholders each kind of document allows and refuses any other.
- Starting messages are provided for every kind; the Admin edits them before go-live.

**Sending (anyone who may view and send that document)**

- Email opens a form filled in from the default message: To (the customer's or supplier's email), Cc, subject and body, with the document attached as a PDF. Everything can be edited before sending; the edits apply to that email only.
- Sending is refused if the sending account is not set up, an address is not valid, or there are more than 20 recipients.
- Every email sent, or failed, is recorded for good: who sent it, when, to whom, the subject and body exactly as sent, and the attachment with its SHA-256 fingerprint. The record is insert-only and is shown on the document; the Admin and the Auditor can see all of them.

## 4. Phase 1: Payment voucher approval system

No supplier payment can be recorded unless its voucher has been approved by the Accountant and then the Director. This is enforced in the user interface, the application and the database.

### 4.1 Voucher types

| Type | Payment method | Notes |
| --- | --- | --- |
| Cheque Payment | Cheque | Cheque number, bank and cheque date recorded at payment |
| Online Payment | Bank transfer | Transfer reference recorded at payment |
| Petty Cash | Cash | Same three-level approval as every other type |
| Internal Transfer | Between own accounts | No supplier; debit and credit are both company bank/cash accounts |
| Supplier Advance | Cheque or transfer | Paid before the invoice; later set off against the invoice |
| Staff Reimbursement | Any | Payee is an employee, with receipts attached |

Types are master data; new types can be added without code changes. Every voucher is numbered PPYYMMDDXXX (section 3, Number series). Every voucher belongs to one division, chosen when it is created, and the division's code is the PP part of the number. The date part is the date the voucher is first saved.

**Payees.** A voucher is paid to a payee from the supplier master. Each payee has a category: Supplier, Utility (e.g. water board, electricity), Bank or credit card, Government, Employee, or Other. Recurring payments such as credit card and utility bills are vouchers like any other, with the same three-level approval.

### 4.2 Workflow

&#91;embedded content: voucher approval flow · 3 levels, payment lock\]

A return at either level sends the voucher back to the clerk, and approval restarts at the Accountant after resubmission.

| Status | Set by | Next possible actions |
| --- | --- | --- |
| Draft | Clerk (L1) | Edit, attach invoices, submit, delete |
| Submitted | Clerk (L1) | Accountant approves, returns or rejects |
| Accountant Approved | Accountant (L2) | Director approves, sends back to the Accountant, returns to the Clerk or rejects |
| Director Approved | Director (L3) | Cashier records payment |
| Returned | L2 or L3 | Clerk corrects and resubmits; approvals restart at L2 |
| Rejected | L2 or L3 | None (final). Reason mandatory |
| Partly Paid | System | Further payments up to the approved amount |
| Paid | System | None; voucher locked |
| Cancelled | Accountant, with Director approval | Only before any payment |

**Amendments.** A Director-approved voucher cannot be edited. A change creates an amendment (revision 1, 2, …) linked to the original, which goes through L2 and L3 approval again. Amendments appear in the Amendments List.

### 4.3 Approval rules

- Every voucher of every type and amount goes through all three levels: L1 submit → L2 approve → L3 approve. No type or amount skips the Director.
- A user cannot approve their own voucher, or approve at two levels.
- Reject and Return require a reason; Approve allows an optional comment.
- The Director can send a voucher back to the Accountant instead of to the Clerk, with a reason, for things the Accountant is responsible for (coding, division, tax). It goes back to the Accountant's queue as Submitted with the reason shown at the top; every Accountant who can approve is notified, the Clerk is not. The Accountant corrects and approves again, and it returns to the Director. The history shows "Sent back to the Accountant" with who and why.
- Optional reminder: notify the next approver again if a voucher waits longer than a set number of days.
- The approval matrix (section 3) still allows extra levels to be added later, but not fewer than three for vouchers.

### 4.4 Screens

**Clerk: create voucher**

1. Choose voucher type and supplier (searchable, with supplier's outstanding balance shown).
2. Add one or more invoice lines: supplier invoice number, invoice date, amount, tax.
3. Upload scanned invoices (PDF, JPG, PNG; multiple files; drag and drop, or camera on a phone).
4. Save as draft or submit.

The system **refuses** the same supplier and invoice number (ignoring case and spaces) if it is already on another voucher, checked by the service and by the database; the same number from a different supplier is accepted, and a deleted, rejected, amended or cancelled voucher frees its invoices (owner's decision, 31 Oct 2026). It warns if an uploaded file is identical (same hash) to one already in the system.

**Accountant: review**

- Queue of submitted vouchers with the invoice preview beside the details.
- Assigns the GL expense account, division and tax treatment to each line; the division defaults to the voucher's division, and a shared bill (e.g. electricity) can be split across divisions by amount or %.
- Approve, return to clerk with a comment, or reject.

**Director: approve (redesign of the current page)**

Keeps what works in the current page (type tabs, approve and reject columns, reason box, bulk actions, Confirm and Reset) and adds:

- Pending count on each tab, e.g. "Cheque Payment (5)", instead of only a green dot.
- Clicking a row opens a side panel with the scanned invoice preview, line details, the Accountant's comment and the supplier's outstanding balance and aging.
- Reason required for Reject; optional for Approve.
- Bulk approve shows a confirmation: number of vouchers and total amount.
- Filters by date range, supplier, amount and division; totals shown at the foot of the list.
- Fully usable on a phone, so approvals do not wait for the Director to be at a desk.

**Row actions menu (all voucher lists)**

As in the current system, every row has an actions button (⋯) with the four actions below, and a paperclip icon when the voucher has attachments. Actions the user is not allowed to take are hidden, and the server refuses them even if called directly.

| Action | What it does | Who can use it, and when |
| --- | --- | --- |
| Resources | Opens the scanned invoices and other attachments in a viewer: page through, zoom, rotate, download. More files can be added while the voucher is still in Draft or Returned | Anyone who can see the voucher, at any status |
| Print | Produces the payment voucher as a PDF in the company format (see below) | Anyone who can see the voucher. A reprint is marked "Copy" and logged |
| Edit | Opens the voucher form | **Clerk:** Draft or Returned vouchers. **Accountant:** while waiting at L2. **Director:** while waiting at L3, can correct description and coding; a change to payee, amount or lines sends the voucher back to the Accountant, with the change highlighted. After Director approval, Edit becomes **Amend** (new revision, spec 4.2) |
| Delete | Removes the voucher | A Draft never submitted: its creator or the Admin. A submitted voucher with no payment: the Director or the Admin only, with a mandatory reason. A deleted voucher is marked Deleted and removed from all working lists, but kept with its full history in a Deleted Vouchers report; its number is never reused. A voucher with any payment cannot be deleted |

Every edit, deletion and print is written to the audit log.

**Printed payment voucher**

- Company letterhead, voucher type and number, date.
- Payee name and bank details; supplier invoice numbers and dates.
- Lines with GL account, division and amount; tax; total in figures and in words.
- Payment details once paid: bank account, cheque number and date, or transfer reference.
- Prepared by, checked by (Accountant) and approved by (Director), each with name, date and time from the approval log, plus space for the payee's signature.
- A4 by default; A5 selectable.

**Cashier: record payment**

- Lists only Director-approved, unpaid vouchers.
- A payment is created from a voucher, never from a blank form. Supplier and maximum amount come from the voucher.
- Records bank account, method, cheque or transfer reference and date. Supports partial payments.
- Saving the payment posts the journal entry (Dr Supplier payable or expense, Cr Bank) and prints the payment voucher.

**Lists and reports**

Voucher List, Approved List, Amendments List (as today), plus: vouchers pending by approver and age, payments made by period, and the approval history of any voucher.

### 4.5 Data model

```sql
CREATE TABLE voucher_type (
  id             SERIAL PRIMARY KEY,
  code           VARCHAR(10) UNIQUE NOT NULL,   -- CHQ, ONL, PCH, INT, ADV, RMB
  name           VARCHAR(50) NOT NULL,
  number_series  VARCHAR(20) NOT NULL,
  needs_supplier BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE voucher (
  id              BIGSERIAL PRIMARY KEY,
  voucher_no      VARCHAR(20) UNIQUE NOT NULL,
  voucher_type_id INT NOT NULL REFERENCES voucher_type(id),
  division_id     INT NOT NULL REFERENCES division(id),     -- PP in the voucher number
  supplier_id     INT REFERENCES supplier(id),
  voucher_date    DATE NOT NULL,
  total_amount    NUMERIC(18,2) NOT NULL CHECK (total_amount > 0),
  status          VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
  revision        INT NOT NULL DEFAULT 0,
  parent_id       BIGINT REFERENCES voucher(id),
  created_by      INT NOT NULL REFERENCES app_user(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE voucher_line (
  id             BIGSERIAL PRIMARY KEY,
  voucher_id     BIGINT NOT NULL REFERENCES voucher(id),
  invoice_no     VARCHAR(50),
  invoice_date   DATE,
  description    TEXT,
  account_id     INT REFERENCES account(id),
  division_id    INT REFERENCES division(id),       -- defaults to the voucher's division
  amount         NUMERIC(18,2) NOT NULL,
  tax_amount     NUMERIC(18,2) NOT NULL DEFAULT 0
);

CREATE TABLE voucher_attachment (
  id          BIGSERIAL PRIMARY KEY,
  voucher_id  BIGINT NOT NULL REFERENCES voucher(id),
  file_key    TEXT NOT NULL,
  file_name   TEXT NOT NULL,
  sha256      CHAR(64) NOT NULL,
  uploaded_by INT NOT NULL REFERENCES app_user(id),
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE approval_log (             -- shared by all documents
  id          BIGSERIAL PRIMARY KEY,
  doc_type    VARCHAR(30) NOT NULL,
  doc_id      BIGINT NOT NULL,
  level       SMALLINT NOT NULL,
  action      VARCHAR(20) NOT NULL,     -- SUBMIT, APPROVE, RETURN, REJECT
  reason      TEXT,
  user_id     INT NOT NULL REFERENCES app_user(id),
  ip_address  INET,
  acted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE supplier_payment (
  id               BIGSERIAL PRIMARY KEY,
  payment_no       VARCHAR(20) UNIQUE NOT NULL,
  voucher_id       BIGINT NOT NULL REFERENCES voucher(id),
  bank_account_id  INT NOT NULL REFERENCES account(id),
  method           VARCHAR(20) NOT NULL,   -- CHEQUE, TRANSFER, CASH
  reference        VARCHAR(50),            -- cheque no. or transfer ref
  payment_date     DATE NOT NULL,
  amount           NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  journal_entry_id BIGINT REFERENCES journal_entry(id),
  cancelled        BOOLEAN NOT NULL DEFAULT false,
  created_by       INT NOT NULL REFERENCES app_user(id)
);
```

### 4.6 The payment lock

The rule is enforced at three layers, so a bug or a future change in one layer cannot bypass it.

1. **Interface:** payments can only be started from an approved voucher.
2. **Application:** the payment service checks status, remaining balance and user role before saving.
3. **Database:** a trigger rejects any payment row that does not meet the rule.

```sql
CREATE FUNCTION check_payment_voucher() RETURNS trigger AS $$
DECLARE v_status TEXT; v_total NUMERIC; v_paid NUMERIC;
BEGIN
  SELECT status, total_amount INTO v_status, v_total
    FROM voucher WHERE id = NEW.voucher_id FOR UPDATE;

  IF v_status NOT IN ('DIRECTOR_APPROVED', 'PARTLY_PAID') THEN
    RAISE EXCEPTION 'Voucher % is not approved by the Director', NEW.voucher_id;
  END IF;

  SELECT COALESCE(SUM(amount), 0) INTO v_paid
    FROM supplier_payment
   WHERE voucher_id = NEW.voucher_id AND NOT cancelled;

  IF v_paid + NEW.amount > v_total THEN
    RAISE EXCEPTION 'Payment exceeds the approved amount';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_payment_requires_approval
BEFORE INSERT ON supplier_payment
FOR EACH ROW EXECUTE FUNCTION check_payment_voucher();
```

In Phase 2, the same lock extends to manual journal entries: a journal line that debits a supplier's payable account and credits a bank or cash account is refused unless it comes from a supplier payment.

## 5. Phase 1.5: Sales documents

Quotations and proforma invoices come right after Phase 1 because they need only the core foundation, and they give sales staff a working tool early. Each document is created from the previous one, so data is entered once and any invoice traces back to its quotation.

```
Enquiry → Quotation (revisions) → Proforma Invoice (optional) → Sales Order
        → Job / Work Order → Delivery Note → Tax Invoice
```

Delivery notes and tax invoices are completed in Phase 2; job and work orders in Phase 3.

### 5.1 Quotations

**Header:** customer, contact, enquiry reference, division (Machining or Moulding), currency, validity date, payment terms, delivery lead time, revision number. An optional **discount %** comes off every line before taxes and is printed as its own line (owner's decision, 31 Oct 2026).

**Machining costing (per line, internal only)**

| Cost element | How it is calculated |
| --- | --- |
| Material | Stock size and weight × material rate, plus cutting allowance |
| Machining | Per operation: machine time × hourly rate of that machine type |
| Setup | Setup hours × rate, divided by order quantity |
| Subcontract | Heat treatment, plating, etc., plus transport |
| Overhead | Configurable % on direct cost |
| Margin | Configurable %, **on the cost** (owner's decision, 31 Oct 2026): a cost of LKR 1,000 (overhead included) with 20% margin gives a price of LKR 1,200. The margin of a quoted price is (price − cost) ÷ cost |

Quantity breaks show unit prices for several quantities (e.g. 10, 50, 100) on one quotation. Each line carries the customer's drawing, with its revision number.

**Product pictures (owner, 4 Nov 2026).** The person making the quotation may add up to three pictures of the product (JPG or PNG, at most 1 MB each) while it is a draft. The approver sees them on the quotation when approving, and they are attached to the email to the customer with the quotation PDF (the sender can leave them out). They change only while the quotation is a draft (database), and a revision keeps them.

**Moulding costing (per line, internal only)**

| Cost element | How it is calculated |
| --- | --- |
| Material | (Part weight + runner weight ÷ cavities) × resin rate, plus masterbatch % **on top of** the resin weight (owner, 31 Oct 2026) |
| Machine | Cycle time ÷ cavities → machine hours per 1,000 pcs × machine hourly rate |
| Rejects | Expected reject % added to material and machine cost (cost × (1 + reject %); owner, 31 Oct 2026) |
| Packing | Per piece or per carton |
| Overhead and margin | As for machining |
| Tooling (separate line) | Mould cost: charged once (a quotation line marked as tooling), amortised over a quantity (added to the price without overhead or margin), or customer-owned (owner, 31 Oct 2026) |

Minimum order quantity is stated on each line.

**Rate tables** (`machine_rate`, `material_rate`, `overhead_rate`) are maintained by the Accountant, dated, so old quotations keep the rates in force when they were made. In Phase 3, actual job times feed back to keep these rates realistic.

**Controls and tracking**

- Number QL{YY}{MM}{DD}{XX}, e.g. QL26102105 (section 3, Number series). Revisions keep the number and add Rev 0, Rev 1, … with full history of what was offered.
- Approval through the shared approval engine: **every quotation needs the Director's approval before it is printed or sent**, by email or otherwise (owner's decision, 31 Oct 2026). Quotations below the division's minimum margin, or above its set value, are flagged to the Director as warnings.
- Costing is seen by the Sales Manager, the Accountant, the Director and the quotation's creator; not by other Sales Executives, and not by the Auditor (owner's decisions, 31 Oct 2026).
- Status: Draft, Awaiting Approval, Sent, Accepted, Lost (reason required), Expired.
- Customer copy shows only description, quantity, unit price, terms. Costing never appears on it.
- Output as PDF with company letterhead, and sent by email from the system.

**Printed quotation** (based on the owner's current quotation; not a government format, so the layout can be improved): letterhead (logo, company name, address, phone, fax, email), title QUOTATION, Our Ref (the number), date, customer name and address; lines with description, quantity, unit price and total; SSCL line and subtotal; VAT with its rate; total; payment terms and notes (e.g. advance payment with the purchase order); quotation validity (e.g. 07 days); delivery term (Incoterm, e.g. EXW); closing and signature (Managing Director); the company slogan "Excellence through expertise". The current form still asks for the customer's SVAT registration; the SVAT scheme ended on 1 October 2025, so that line is dropped unless the tax advisor says otherwise.

### 5.2 Proforma invoices

- Created from an accepted quotation or a sales order; prices and terms carried over.
- Used to request an advance payment, or for the customer's import, LC or bank documents.
- **Not an accounting entry.** Issuing it records no sale and no receivable.
- Own number series in the old style, PI{YY}{MM}{DD}-{XX}, e.g. PI261031-01 (owner's decision, 31 Oct 2026), and clearly titled "Proforma Invoice". Discount as on quotations.
- Advance received against it posts as a customer advance: Dr Bank, Cr Customer Advances (liability). The Accountant's approval is enough (owner's decision, 31 Oct 2026).
- When the tax invoice is raised, the advance is set off automatically against it.
- One click converts it to the sales order, and later to the tax invoice.

### 5.3 Sales orders

- Created from an accepted quotation or proforma, or entered directly for repeat orders.
- Holds the customer's PO number, delivery schedule (several dates for moulding call-offs) and the agreed price.
- Numbered SO{YY}{MM}{DD}{XX}, e.g. SO26103101. Prices come from the quotation or proforma; a repeat order entered directly has typed prices and is approved by the Director before it is open (owner's decisions, 31 Oct 2026).
- Confirming needs the customer's PO number; a confirmed order is never changed, and the delivery dates of each line add up to its quantity.
- Status: Draft, Waiting for the Director (repeat orders), Open, Partly delivered and Delivered (moved by delivery notes, Phase 2), Completed, Cancelled (with a reason; not once an approved advance or a delivery note stands against it).
- An order records no sale and posts nothing; customer advances may be recorded against it.
- In Phase 3, a sales order line generates a machining job order or a moulding production requirement.

### 5.4 Added tables

| Table | Purpose |
| --- | --- |
| `customer`, `customer_contact` | Customer master |
| `quotation`, `quotation_line` | Header and lines, with revision and parent link |
| `quotation_costing` | Cost build-up per line (internal) |
| `quotation_qty_break` | Unit prices for alternative quantities |
| `machine_rate`, `material_rate`, `overhead_rate` | Dated rate tables |
| `proforma_invoice`, `proforma_line` | Proforma documents |
| `sales_order`, `sales_order_line`, `delivery_schedule` | Confirmed orders |
| `customer_advance` | Advances received and their set-off against invoices |

### 5.5 Export sales and foreign currency

Export customers are quoted, invoiced and paid in their own currency from Phase 1.5.

- Each customer has a default currency (LKR, USD, EUR or any other added by the Admin).
- Quotations, proformas, sales orders and invoices are issued in that currency; costing stays in LKR, and the quotation shows the exchange rate used to convert.
- Exchange rates are kept in a dated table, entered daily or imported.
- Export documents: commercial invoice, packing list (cartons, net and gross weight, dimensions), and proforma for the buyer's bank or LC. The packing list is issued with the proforma from Phase 1.5 (owner's decision, 31 Oct 2026).
- Shipping terms (Incoterms such as FOB, CIF) and port of loading and destination on each document.
- Foreign-currency bank accounts; receipts recorded in the invoice currency.
- In Phase 2, exchange gains and losses are posted on receipt and revalued at month-end; export sales are treated under the applicable VAT rules (confirm with the tax advisor).
- Profitability (7.7) is always reported in LKR, using the rate at invoice date.

## 5A. Phase 1.6: Purchasing, goods receipt and supplier invoices

Owner's requirement (31 Oct 2026), treated as a critical financial and inventory control:
suppliers are paid only for goods actually received, accepted and verified. This phase brings
forward from Phase 2 the purchase orders, goods receipt and incoming inspection (section 6A),
stock and supplier invoices with three-way matching; the rest of Phase 2 (full ledger, tax
invoices, receivables, banking) stays where it was.

```
Purchase Order → Goods Receiving Note (GRN) → QC acceptance → Supplier Invoice
   (Director)        (Stores)                    (QC)          (Accounts, 3-way match)
             → Payment Voucher (Clerk → Accountant → Director) → Payment (Cashier)
```

**Owner's decisions (31 Oct 2026)**

1. Built next, as its own phase, while Phase 1.5 is in user testing.
2. Stores receive the goods; a QC Inspector accepts or rejects (section 6A). Only accepted
   quantities go to available stock and can be paid. SML has **one stores person**, who both
   enters and confirms the GRN; the independent checks are QC acceptance (always a different
   person: holding a stores role and the QC Inspector role together is refused) and the
   Accounts three-way match.
3. Three-way match with **no tolerance**: any difference in quantity or price between the
   PO, the accepted GRN quantity and the supplier invoice blocks payment until the
   Accountant investigates and the Director approves the exception, with a reason.
4. A Purchasing Officer raises purchase orders; the Director approves every PO before it is
   sent.
5. The same supplier invoice number (supplier + invoice number, ignoring case and spaces)
   can never be entered twice, on a supplier invoice or a payment voucher; the same number
   from another supplier is accepted. Enforced by the service and the database.

### 5A.1 Purchase orders

- Supplier, division, items (from the item master) with quantity, unit, agreed price, tax
  code and delivery date; terms and delivery address. Numbered PO{YY}{MM}{DD}{XX}, as on the
  owner's sample PO26061701.
- Raised by the Purchasing Officer; approved by the Director (approval engine, never by the
  person who raised it); printed and emailed to the supplier only once approved.
- An approved PO never changes: a revision (Rev 1) goes through approval again. Status:
  Draft, Awaiting approval, Approved (open), Partly received, Received, Closed (short-closed
  with a reason), Cancelled (with a reason; not once goods are received).

### 5A.2 Goods receiving note (GRN)

- Made against an approved PO: supplier, items, ordered and still-to-receive quantities and
  agreed prices are filled in from it. Header: delivery note number, vehicle, supplier's
  invoice number if delivered with the goods, date and time.
- The stores person enters the quantities actually received (package by package where the
  item needs it, section 6A.2), damaged quantities and photos, and confirms the GRN.
  Numbered GRN{YY}{MM}{DD}{XX}. (With one stores person, entry and confirmation are one
  person; QC acceptance by someone else is the check. If a second stores person joins, a
  second confirmation can be added.)
- Partial deliveries and several GRNs per PO. A delivery above the PO's remaining quantity
  is flagged as an excess: the excess cannot be accepted or paid unless the Director
  approves it (or the PO is revised).
- A confirmed GRN never changes (database guard). Corrections are a GRN reversal with a
  reason, approved by the Director, recorded and linked.
- Goods go into the **Quarantine** store on confirmation, then QC acceptance moves accepted
  quantities to available stock and rejected ones to the Rejected store (section 6A).
- Who received, confirmed, inspected and approved, with date and time, is on the GRN and in
  the audit log.

### 5A.3 Stock and its accounting (IAS 2)

- Item master: code, description, unit, category (raw material, consumable, spare,
  bought-out part, packing), stock or non-stock, package type and inspection need (6A),
  inventory account, division.
  Item codes are typed (up to 20 letters, digits or dashes) and fixed once used. Only the
  Accountant chooses an item's accounts; by default raw materials and bought-out parts use
  1210 Raw materials, and consumables, spares and packing use 1240.
- Stores per production division: main stores (any number), one Quarantine and one
  Rejected store; set by the Admin.
- Stock is held by item, store and lot, with every movement recorded (receipt, acceptance,
  rejection, return, issue, adjustment); balances are never typed.
- Valuation at weighted average cost (spec 6). Inventory is recognised when goods are
  accepted, at the PO price: Dr Inventory, Cr Goods received not invoiced (GRNI). The
  supplier invoice then clears it: Dr GRNI, Dr VAT input, Cr Accounts payable (the supplier).
  Payment: Dr Accounts payable, Cr Bank. All postings balance and are never edited (rules 2,
  3).

- **Invoice price differences (owner, 2 Nov 2026; P16-18).** Stock is carried at what it actually cost (IAS 2). When the supplier's invoice price differs from the PO price, the difference (with any tax that cannot be recovered) adjusts the value of the goods still in stock; only the part for goods already used or gone goes to Purchase price variance.
- **Foreign currency (owner, 2 Nov 2026; P16-19; IAS 21).** Goods are valued at the exchange rate of their receipt date; the supplier's invoice is posted at the rate of its date, and the difference from the receipt's rate goes to Exchange loss or Exchange gain. The payment's difference at its own date follows with foreign-currency payments (Phase 2, P2-11).
- **Tax rates (owner, 2 Nov 2026; P16-20).** VAT and the SSCL rates (one per kind of supply: manufactured goods, services, resold goods; all printed as SSCL) are kept on Settings → Tax rates. The Admin or the Accountant enters a change from its date; it applies only after the Director confirms it. Documents keep the rate of their date.

### 5A.4 Supplier invoices and three-way match

- Entered by the Accounts Clerk with the scanned invoice: supplier, invoice number and date,
  lines linked to the GRN lines they bill (from one or more GRNs of the supplier).
- Supplier + invoice number is unique (decision 5).
- The match, line by line: invoiced quantity ≤ accepted quantity not yet invoiced; invoiced
  price = PO price; tax as on the PO. Any difference marks the invoice **Held:
  discrepancy**, with the differences listed; the Accountant investigates and either the
  supplier corrects (credit note, new invoice) or the Director approves the exception with
  a reason.
- Goods not yet received or not accepted can never be invoiced for payment.

### 5A.5 Payment vouchers from supplier invoices

- For goods bought on a PO, the payment voucher is prepared from matched (or
  exception-approved) supplier invoices; it carries the invoice, GRN and PO links, and its
  amount can never exceed what is unpaid on those invoices, so an invoice is never paid
  twice.
- The voucher still passes the Clerk, the Accountant and the Director (rule 6), and the
  Cashier pays it (rule 4). The voucher shows PO, GRN and invoice quantities and prices side
  by side for the approvers.
- Services, utilities and other purchases with no goods (non-stock) continue as today's
  vouchers. A payment in advance of delivery on a PO is an exception the Director approves.

### 5A.6 Internal controls (COSO) and standards

- Segregation: the Purchasing Officer orders, Stores receive, QC accepts, Accounts invoice and
  prepare vouchers, the Director approves, the Cashier pays. Conflicting role pairs warn the
  Admin (Purchasing Officer with Stores, Stores with Accounts Clerk or Cashier); a stores
  role with the QC Inspector role is refused, because QC is the check on the single stores
  person.
- Nobody approves a document they created, or at two levels of one document (rule 5).
- Confirmed GRNs, matched invoices and posted entries are never edited; reversals and
  amendments are documents of their own, approved and linked.
- Traceability both ways on every document: PO ↔ GRN ↔ QC result ↔ supplier invoice ↔
  payment voucher ↔ payment, and down to the lot used in production (Phase 3).
- Standards followed: IAS 2 (recognition and cost of inventories), IFRS accrual of supplier
  liabilities (GRNI), three-way matching, COSO (authorisation, verification, segregation,
  audit trail), ISO 9001 (documented process, traceability, control of nonconforming goods).
  The accounting treatment is confirmed with the company's auditors before go-live.

### 5A.7 Reports

Open POs and overdue deliveries; goods received not invoiced (GRNI); invoices held for
discrepancies; three-way-match exceptions approved; receipts and rejections by supplier;
stock on hand by store and lot, with value; the full trail of any PO, GRN or invoice.

## 6. Phase 2: Financial accounting

Phase 2 extends the Phase 0 ledger to cover what QuickBooks provides, with the voucher system remaining the only route for supplier payments.

| Module | Main features |
| --- | --- |
| General ledger | Chart of accounts, manual journals (with approval), recurring journals, period close, year-end close and carry-forward |
| Accounts payable | Purchase requests, debit notes, supplier statements, aging (purchase orders, GRNs and supplier invoices with 3-way match come first, in Phase 1.6, section 5A). Payments only via approved vouchers |
| Accounts receivable | Delivery notes, tax invoices, credit notes, receipts, advance set-off, customer statements, aging, credit limits, reminders |
| Banking | Bank and cash accounts, cheque register (issued and received), post-dated cheques, bank reconciliation with statement import (CSV/Excel), deposits, inter-account transfers |
| Petty cash | Imprest float per custodian, replenishment through a petty cash voucher |
| Inventory valuation | Raw material, consumables, finished goods, WIP; weighted average cost; stock journal postings |
| Fixed assets | Asset register (machines, moulds, vehicles), depreciation schedules, disposals, mould assets linked to their shot count |
| Payroll | Phase 2b, after core accounting is live: employee master, salary components, overtime, attendance import, EPF and ETF, PAYE, payslips, bank transfer file |
| Tax | VAT on sales and purchases, SSCL, withholding tax; tax reports for filing |
| Multi-currency | Foreign currency invoices and bills, exchange rate table, realised and unrealised gains and losses |
| Budgeting | Budgets by account and division, monthly budget vs actual |
| Reports | Trial balance, P&L and balance sheet (company and per division), cash flow statement, general ledger detail, AP/AR aging, VAT report, audit trail |

Tax rates and rules change; they are stored as dated master data, never hard-coded, and must be confirmed with the company's tax advisor before go-live.

### 6.1 Tax invoice (compulsory government format)

The tax invoice layout is set by the Inland Revenue Department (Gazette 2481/22, in force from 1 July 2026, replacing Gazette 2463/05) and must be followed exactly; the owner's current invoice is the model.

**Required by law**

- Title **TAX INVOICE**, prominent (bold).
- Supplier's TIN (nine digits), name and address, as on the VAT registration certificate.
- Purchaser's TIN (nine digits), name and address, where the purchaser is VAT-registered.
- Tax invoice number in the format YYMMM_QQQQ_XXXXX (section 3).
- Date of invoice and date of supply, both as MM/DD/YYYY.
- Description of the goods or services, and quantity.
- Value of supply in LKR excluding VAT, VAT amount, and total including VAT, each to two decimal places (the "three-line" VAT breakdown).

**Optional by law, kept because the current invoice has them:** telephone numbers, place of supply, total amount in words, terms (mode of payment), additional information.

**Layout of SML's invoice:** logo, company name and email; TAX INVOICE; boxes for Date of invoice / Tax Invoice No; supplier details (TIN, name, address, telephone) / customer TIN, name and address; Date of supply / Place of supply; Terms (e.g. Due on receipt); a line table with Product Code, Description, PO No, Rate (Rs), Qty, Amount (Rs); Subtotal; SSCL line (code SSCL, rate 2.125%, amount); Subtotal; VAT amount; Total amount including VAT; total in words; signature line for Customer, Prepared By and Checked By.

**Calculation, as on the current invoice:** SSCL = subtotal × SSCL rate; VAT = (subtotal + SSCL) × VAT rate; each amount rounded half-up to the cent. Example: 115,750.00 + SSCL 2,459.69 = 118,209.69; VAT 18% = 21,277.74; total 139,487.43. The SSCL and VAT rates are dated tax master data (rule 11), and the treatment is confirmed with the tax advisor before go-live.

**Amounts** are shown with international grouping (115,750.00), on screens and printed documents (owner's decision; the current invoice's 1,15,750.00 style is not required).

**Controls:** an invoice cannot be issued for a division without a tax invoice code; once issued it is never edited or deleted (a credit note corrects it); the number comes from the number series inside the saving transaction.

**Later option:** the Inland Revenue accepts invoices sent from an ERP to its RAMIS system through a web API; integration can be considered once Phase 2 is live.

**Migration at go-live:** opening trial balance, open supplier and customer balances by invoice, open POs and sales orders, fixed asset register with accumulated depreciation, stock on hand with value.

## 6A. Goods receipt and incoming inspection

Every raw material delivery is received, weighed or counted package by package, and held in quarantine until inspected. Only accepted material can be issued to production, and only accepted quantities can be paid for.

### 6A.1 Flow

1. **Arrival:** delivery recorded at the store against the purchase order: supplier, vehicle, delivery note number, supplier's invoice number.
2. **Goods receipt (Stores Manager / Executive):** quantities entered per package (see 6A.2). Every package gets a printed QR label with its lot number. Status: *Quarantine*.
3. **Incoming inspection (QC Inspector):** checks from the item's inspection plan, results entered, certificates attached.
4. **Decision:** Accept, Reject, or Accept under deviation (needs Production Manager approval, Director for critical materials). *Owner, 1 Nov 2026: QC decides per package, rejecting single bags or bundles and accepting the rest. Owner, 8 Nov 2026: with the Production Manager role switched on, the Production Manager approves deviations and the Director approves those on a failed critical check (until then the Director approved every deviation).*
5. **Stock update:** accepted lots move to available stock; rejected lots move to a rejected location for return to the supplier, with a debit note.

### 6A.2 Stores receiving entry page

The page adapts to how the material arrives. Package types are configured per item.

| Material arrives as | Entered per package | Calculated |
| --- | --- | --- |
| Bags (resin, masterbatch) | Bag no., supplier lot no., gross weight, tare (bag weight, defaulted per item), declared weight on bag | Net weight per bag, total net, variance vs declared and vs invoice |
| Bars, rods, tubes | Bundle no., heat no., number of pieces, length per piece or total, weight | Total length, total weight, kg per metre vs standard |
| Plates, sheets | Plate no., heat no., length × width × thickness, weight | Theoretical weight vs actual |
| Coils | Coil no., heat no., gross and tare weight | Net weight |
| Counted items (inserts, fasteners, cartons) | Boxes and quantity per box, or total count | Total quantity |

- Weighbridge or platform scale: weights can be typed, or read directly from a connected digital scale to avoid typing errors.
- Tolerance per item (e.g. ±0.5% on resin net weight, configurable): variances outside it are highlighted and the Accountant sees them on the supplier's payment voucher.
- Photos of damaged or wet bags can be attached from a phone or tablet.
- Fast entry for large deliveries: "40 bags × 25 kg declared" creates 40 lines, then the supervisor enters or scans each actual weight.

### 6A.3 Inspection plans

An inspection plan per item, or per material category, defines what is checked, the limits and the sample size.

| Material | Typical checks |
| --- | --- |
| Plastic resin | Grade and colour vs PO, bag condition, contamination, moisture, Certificate of Analysis attached; melt flow index if tested in-house |
| Masterbatch | Colour match against master sample, lot number, certificate |
| Steel and other metals | Grade vs mill test certificate, heat number matches certificate, diameter or thickness, length, hardness, rust and surface defects |
| Bought-out parts | Dimensions per drawing, visual, quantity |

- Each check is numeric (with min and max) or pass/fail.
- Sampling: all packages, a fixed number, or a percentage per lot.
- Out-of-limit results are marked automatically; the inspector cannot accept a lot with a failed critical check without raising a deviation.

### 6A.4 Links to other modules

- **Payment vouchers (Phase 1):** when a voucher is for a material delivery, the voucher shows the GRN's accepted quantity next to the invoiced quantity. Shortages and rejections are flagged to the Accountant and Director before approval.
- **Accounts payable (Phase 2):** 3-way match uses accepted quantity, not delivered quantity. Rejections and shortages generate a debit note.
- **Inventory:** stock is held by lot with status Quarantine, Available, Rejected or On Hold. Production can issue only Available lots.
- **Production (Phase 3):** material issues record the lot number, so any moulded or machined batch traces back to the resin or steel lot and its supplier certificate.

### 6A.5 Roles

- **Stores Manager / Executive:** goods receipt and package-level weights and counts; cannot record inspection results, and cannot also hold the QC Inspector role.
- **QC Inspector (new role):** inspection results and accept or reject decisions; cannot change received quantities.
- **Production Manager / Director:** approve deviations.

### 6A.6 Added tables

| Table | Purpose |
| --- | --- |
| `goods_receipt`, `goods_receipt_line` | Delivery header (PO, supplier, delivery note, vehicle) and items |
| `receipt_package` | One row per bag, bundle, coil or box: lot or heat no., gross, tare, net, count, declared value |
| `inspection_plan`, `inspection_parameter` | Checks per item or category, limits, sampling rule |
| `incoming_inspection`, `inspection_result` | Inspection per lot and the value of each check |
| `material_lot` | Lot with status and location, linked to receipt and inspection |
| `quality_deviation` | Accept-under-deviation requests and approvals |
| `supplier_return` | Rejected material returned, linked to the debit note |

### 6A.7 Reports

- Receipts by supplier and material, with weight variance.
- Rejection rate by supplier and material, and a supplier quality rating.
- Lots in quarantine and how long they have waited.
- Lot traceability: from a supplier lot to the production batches that used it, and back.

**Phasing:** brought forward into Phase 1.6 with purchase orders and supplier invoices (section 5A; owner's decision, 31 Oct 2026).

## 7. Phase 3: Production

The two divisions are modelled differently: the workshop is a make-to-order job shop tracked by job card, and the moulding plant is repetitive production tracked by machine and shift. Both share sections, shifts, supervisor entry pages, downtime, rejects and quality records.

### 7.1 Masters

| Master | Key fields |
| --- | --- |
| Section | Name, division, section type (Machining, Moulding, Support), supervisors |
| Shift | Name, start, end, break; used by roster patterns (see 7.1A) |
| Machine | Code, section, type, hourly rate, capacity (tonnage for moulding machines), status |
| Mould | Code, part(s), cavities, standard cycle time, shot weight, runner weight, required tonnage, compatible machines, owner (company or customer), shot count, maintenance interval |
| Item | Raw materials (bar, plate, resin, masterbatch), consumables, finished parts, with unit and drawing |
| Routing | For machined parts: ordered operations, machine type, standard setup and run time |
| Reason codes | Reject reasons and downtime reasons per division |

**Factory structure: Division → Section → Machine.** All three levels are added, renamed and deactivated by the System Admin, with no code change. A machine bought next year is one new record; it immediately appears on the supervisor pages, production plans, OEE and costing.

| Level | Current setup (initial data) | Admin can |
| --- | --- | --- |
| Division | Workshop (WS), Plastic Injection Moulding (IM), Head Office (HO, shared costs), confirmed by the owner | Add a division, set its type (Machining, Moulding or Support) |
| Section | Workshop: 18 sections (list in 3A.1). Moulding: one or more sections grouping the machines | Add a section under any division, assign supervisors |
| Machine | Manual Milling: 3 machines. Moulding: 8 machines | Add, move between sections, retire; set hourly rate, capacity, tonnage |

Machines that are retired keep their history; they are hidden from entry pages, not deleted.

### 7.1A Shifts and rosters

Both divisions run day and night. The roster changes with the season, so shift patterns are data with effective dates, not fixed settings.

| Shift (examples) | Times | Hours |
| --- | --- | --- |
| General | 08:00–17:00 | 9 (incl. break) |
| Day 12-hour | Configurable, e.g. 07:00–19:00 | 12 |
| Night 12-hour | Configurable, e.g. 19:00–07:00 | 12 |
| 3-shift A / B / C | Configurable, 8 hours each | 8 |

- **Roster pattern:** a repeating cycle of shifts and off days, e.g. *Day, Day, Night, Night, Off, Off* (6-day cycle). Three crews start the cycle 2 days apart, so every day has one crew on days, one on nights and one off.
- **Crews:** operators are assigned to crews (A, B, C…); the manpower entry page pre-fills the crew on shift.
- **Seasonal change:** a roster assignment links a pattern to a division or section for a date range. Switching from 3 shifts to 12-hour rotation is a new assignment from a date; past data is unaffected.
- **Mixed rosters:** staff on the General shift and crews on rotation can work in the same section at once.
- **Night shifts crossing midnight** belong to the date the shift started, for production reports, OEE and costing.
- **Planned time** for OEE availability comes from the active roster; off days are not counted as lost time.
- Roster and attendance give overtime hours for payroll when it is added.

Added tables: `division`, `shift_pattern`, `shift_pattern_day`, `crew`, `crew_member`, `roster_assignment`.

### 7.1B Bills of materials (BOMs)

Every manufactured item (finished part, sub-assembly, mould or tool) can have a bill of materials: the list of materials, parts and services needed to make one unit, or a stated batch quantity. Together with its routing (the operations, 7.1) it is the item's manufacturing recipe, used for quotations, planning, material issues and costing.

**What a BOM line can be**

| Component type | Example | Quantity per unit |
| --- | --- | --- |
| Raw material | Steel bar Ø50 EN8, aluminium plate, PP resin | Length or weight per piece, plus cutting or runner allowance |
| Masterbatch and additives | Black masterbatch | % of resin weight |
| Bought-out part | Brass insert, bearing, fastener | Count per piece |
| Sub-assembly | A machined shaft used in an assembly | Count per piece; has its own BOM (multi-level) |
| Subcontract service | Heat treatment, plating, anodising | Per piece or per kg |
| Packing | Carton, polybag, label | Per piece, or pieces per carton |

Each line also has: unit of measure, scrap or yield allowance %, the operation it is used at (so material is issued when that operation starts), how it is issued (manual issue, or **backflush**: deducted automatically when output is reported), and whether the customer supplies it.

**Machining BOMs** hold the stock size and cut length per piece, with facing and saw-cut allowance, and calculate pieces per bar or plate and weight per piece.

**Moulding BOMs** are built from the mould and part data: part weight, plus runner weight shared over the cavities, plus the reject allowance, gives resin per piece. Masterbatch is added as a % of resin, and the maximum regrind % allowed for the part is shown. A **family mould** that makes several different parts in one shot has one BOM for the mould run, with each part as an output.

**Revisions and control**

- Each BOM has a revision linked to the item's drawing revision, an effective-from date and a status: Draft, Approved, Obsolete.
- The Production Planner prepares BOMs; the Production Manager approves them before they can be used. The Accountant and Director can view them with costs.
- A job or production order takes a copy of the approved BOM when it is released, so a later BOM change never alters orders already in progress. Changes to a running order's materials are recorded against the order.
- Copy a BOM to start a similar item; compare two revisions side by side; import and export with Excel.

**What BOMs are used for**

| Use | How |
| --- | --- |
| Quotations (5.1) | A quotation for a known part starts from its BOM and routing, so material and machine costs are filled in automatically |
| Standard cost | Rolled up through all levels from material rates and routing machine rates; feeds the estimate in job profitability (7.7) |
| Material requirements | An order's quantity × its BOM gives materials needed; compared with stock and open purchase orders, it produces a **shortage list** and suggested purchase requests |
| Material issues | Stores issues material against the order's BOM; issuing more than the BOM allows needs a reason and the Production Manager's approval |
| Backflush (moulding) | When a shift report is approved, resin, masterbatch and packing are deducted from stock for the good and rejected quantity |
| Variance | Actual material used versus BOM, per order: the material usage variance in 7.7 |
| Where-used | Which items and open orders use a given material or part, e.g. before changing a supplier or a resin grade |

**Added tables:** `bom` (item, revision, division, status, effective from, base quantity), `bom_line` (component, quantity, unit, scrap %, operation, issue method, customer-supplied), `bom_output` (for family moulds), `order_bom_line` (the copy on each job or production order).

**Phasing:** BOMs need the item master and stock, which arrive with inventory in Phase 2, so BOMs are built at the start of Phase 3, ahead of job orders. Until then, quotations (Phase 1.5) use their own costing sheet.

### 7.2 Machining workshop

- **Job order** created from a sales order line: part, drawing revision, quantity, due date, routing copied from the part's standard routing (editable per job).
- **Material issue** from stores against the job.
- **Job card** per operation: printed with a QR code, travels with the parts.
- **Subcontract operations:** parts sent out and received back against the job, with the supplier's bill going through the voucher system.
- **Inspection:** first-article, in-process and final inspection results recorded against the job, with measurements.
- **Job costing:** actual material, machine time, labour and subcontract cost vs the quotation estimate, per job.

### 7.3 Injection moulding

- **Production plan:** which mould runs on which machine, per shift, from sales order delivery schedules and stock levels.
- **Shift production:** shots, good quantity, rejects by reason, material used.
- **Material:** resin and masterbatch issued per machine, regrind generated and used, with a maximum regrind % per part.
- **Mould maintenance:** shot count updated from production; preventive maintenance due when the interval is reached; repair history per mould.
- **Finished goods:** good quantity moves to finished stock when the shift report is approved.

**Mould making link:** when the workshop builds or repairs a mould, it is an internal job order. Its cost is capitalised to the mould asset (new mould) or charged to the Plastic Injection Moulding division (repair), through an inter-division transfer (3.1).

### 7.4 Production supervisor entry pages

Each supervisor sees only the sections assigned to them, and the page they get depends on the section type.

**Shift production entry**

| Section type | What the supervisor enters | What the system calculates |
| --- | --- | --- |
| Machining | Scan job card; operation, machine, operator, start and end time, quantity completed, rejected (with reason), for rework | Time per piece vs standard; quantity available for next operation |
| Moulding | Per machine: mould, material batch, shot counter at start and end, rejects by reason, operator | Good qty = shots × cavities − rejects; actual cycle time; material per good piece |
| Support | Input quantity, output quantity, waste | Yield % |

**Other entry pages**

1. **Downtime log:** machine, from and to time, reason (breakdown, mould change, setup, power failure, no material, no operator, planned maintenance), remarks.
2. **Material issue and return:** material, batch, quantity drawn from stores and returned; regrind generated.
3. **Manpower:** operators present per shift and machine, overtime hours.
4. **Shift summary:** totals for the shift, then Submit.

**Controls**

- Supervisor can enter data only for assigned sections.
- Entry allowed during the shift and up to a grace period after it ends (default 2 hours, configurable). After that, changes need a correction request approved by the Production Manager.
- Submitted reports are locked. The Production Manager approves them; only approved data updates stock, mould shot counts and job costs.
- Validation: completed quantity cannot exceed what the previous operation released; shot counters cannot decrease; time entries on one machine cannot overlap; rejects cannot exceed shots × cavities.
- Every change recorded in the audit log.

**Shop-floor usability**

- Tablet and phone layout: large buttons, number pads, dropdowns instead of typing.
- QR or barcode scanning for job cards, moulds, machines and material batches.
- Interface language option: English, Sinhala, Tamil.
- Offline entry: saved on the device and synced when Wi-Fi returns, with a visible sync status.

### 7.5 Added tables

| Table | Purpose |
| --- | --- |
| `section`, `section_supervisor` | Sections and their assigned supervisors |
| `shift`, `machine`, `mould`, `routing`, `routing_operation` | Production masters |
| `job_order`, `job_card` | Machining jobs and their operations |
| `production_plan` | Planned mould-machine runs per shift |
| `shift_report` | One per section per shift: draft, submitted, approved |
| `production_entry` | Job card operations and moulding machine runs |
| `reject_entry`, `downtime_entry` | Rejects and downtime by reason |
| `material_movement` | Issues, returns, regrind |
| `manpower_entry` | Operators and hours per shift |
| `inspection_record` | QC results and measurements |
| `mould_maintenance` | Planned and actual maintenance per mould |

### 7.6 Reports

- Daily production by section, machine and shift.
- Reject % by reason, part, mould and machine.
- OEE per moulding machine: availability × performance × quality.
- Downtime by reason and machine (Pareto).
- Machining: actual vs estimated time and cost per job; on-time delivery.
- Material consumption vs standard; regrind usage.
- Moulds approaching their maintenance shot count.

### 7.7 Job and production order profitability

Every machining job order and moulding production order shows its cost, revenue and margin while it is running, and a final profitability report when it closes. Figures update each time a shift report, material issue or supplier bill linked to the order is approved, so they are at most one shift old.

**What profitability is measured on**

| Division | Unit | Revenue |
| --- | --- | --- |
| Machining | Job order (one per sales order line, or internal job such as mould making) | Sales order value; earned revenue = completed qty × unit price |
| Moulding | Production order (part, quantity, delivery schedule); also part and mould per month for continuous runs | Good qty × unit price |
| Support sections | Not a profit unit; costs absorbed into the orders they serve | — |
| Division | Division P&L from the ledger (Phase 2), reconciled with the order totals | Invoiced sales |

**Where each cost comes from**

| Cost element | Source | Valued at |
| --- | --- | --- |
| Material | Material issues by lot (6A, 7.4) | Actual lot cost from goods receipt; regrind credited at its set value |
| Machine time | Job cards and moulding shift runs | Actual hours × machine hourly rate |
| Labour | Manpower entries | Operator hours × labour rate (actual payroll cost once Phase 2 payroll runs) |
| Setup and mould change | Downtime entries coded to the order | Hours × machine and labour rate |
| Subcontract | Supplier bills through payment vouchers | Actual invoiced cost |
| Direct expenses | Voucher lines tagged to the order (tools, inserts, special packing, transport) | Actual cost |
| Rejects and rework | Reject entries | Cost already spent on the rejected pieces, shown separately |
| Mould cost | Moulding runs | Amortisation per shot for company-owned moulds |
| Overhead | Calculated | Overhead rate per machine hour (set by the Accountant, reviewed yearly) |

To let supplier bills reach the right order, each payment voucher line gets an optional **job / production order** field, filled by the Accountant when coding the voucher (section 4.4).

**Three figures for every order**

| Figure | Meaning |
| --- | --- |
| Estimate | Cost and margin from the accepted quotation |
| Actual to date | Costs posted so far, revenue earned on completed quantity |
| Forecast at completion | Actual to date + estimated cost of remaining quantity at standard rates |

```latex
\text{Forecast margin} = \text{Order value} - (\text{Actual cost to date} + \text{Remaining qty} \times \text{Standard unit cost})
```

**During production**

- **Order dashboard:** all open orders with % complete, order value, cost to date, forecast margin and a red, amber or green status. Filter by division, customer, section, due date.
- **Drill-down:** from any order to each cost line and its source document (job card, shift report, material issue, voucher).
- **Alerts** to the Production Manager and Director when:
  - cost to date for the completed quantity exceeds the estimate by a set % (e.g. 10%);
  - forecast margin falls below the minimum margin;
  - reject % on the order exceeds its limit.
- **Moulding view per machine and mould:** actual vs standard cycle time, material per good piece, rejects, and margin per 1,000 pieces.

**At completion**

When the last quantity is delivered, the order is closed and its final report shows estimate vs actual by element:

| Variance | Explains |
| --- | --- |
| Material price | Paid more or less per kg than quoted |
| Material usage | Used more or less material per piece (scrap, cut losses, runner weight) |
| Machine time | Took longer or shorter than the quoted time per piece or cycle time |
| Setup | Setup or mould changes longer than planned |
| Rejects | Cost of rejected and reworked pieces |
| Subcontract and direct expenses | Actual vs quoted outside costs |

Closed orders feed the quotation rate tables (5.1): average actual cycle times, setup times and material usage per part, so the next quotation for the same or a similar part is priced on real data.

**Accounting (Phase 2)**

- Costs of open orders sit in a Work in Progress account per division.
- On completion, cost moves to finished goods, then to cost of sales when invoiced.
- Month-end WIP valuation report reconciles open orders with the WIP account.
- Machine time not charged to any order (idle time) is reported separately as unabsorbed overhead, so it is visible instead of hidden in job costs.

**Profitability reports**

- Margin by order, customer, part, mould and division, for any period.
- Most and least profitable customers and parts.
- Estimate accuracy: average variance of closed orders by element, showing where quotations are consistently off.
- Daily snapshot of each open order's forecast margin, so its trend over the life of the order can be charted.

**Added tables**

| Table | Purpose |
| --- | --- |
| `production_order` | Moulding production orders (part, quantity, sales order link) |
| `cost_rate` | Dated machine, labour and overhead rates |
| `order_cost_entry` | Every cost posted to a job or production order: element, source document, quantity, rate, amount |
| `order_profit_snapshot` | Daily snapshot of cost, revenue, % complete and forecast margin per open order |
| `voucher_line.order_id` | New optional column linking supplier bills to an order |

**Phasing:** live profitability using standard rates is available as soon as Phase 3 production entry runs. Actual material lot costs need the Phase 2 inventory module, and actual labour cost needs Phase 2 payroll.

## 7A. Interactive features, as in QuickBooks (owner request, 29 Oct 2026)

The owner asked for the interactive features of QuickBooks Online and Desktop. Each is placed in the phase that builds what it depends on; none changes the order of Phase 1. Where QuickBooks relies on services that do not exist in Sri Lanka, the nearest workable equivalent is given.

**Dashboards and reporting**

| Feature | How it works here | Phase |
| --- | --- | --- |
| Interactive business overview | Dashboard tiles and charts (profit and loss, cash, payables, receivables, vouchers waiting), per division or for the company. Clicking any figure opens the report behind it, and any report line opens the transactions behind it, down to the document and its scans | Vouchers dashboard in Phase 1; financial tiles in Phase 2 |
| Cash flow planner | Projects bank balances day by day for 13 weeks from approved and unpaid vouchers, invoices due (by each customer's payment history), payroll and recurring payments. The user adds "what-if" items (a machine purchase, a delayed receipt) that change the projection but are never posted | Phase 2 |
| Custom report builder | Start from a standard report or a data source (journal lines, vouchers, invoices, stock, production). Choose columns, filters, grouping and subtotals, sort, and period columns (months, divisions); save it, share it with a role, export to Excel or PDF, and email it (3B). Columns are chosen and ordered by drag-and-drop. A user only ever sees data their role and divisions allow | Phase 2 |

**Invoicing and payments**

| Feature | How it works here | Phase |
| --- | --- | --- |
| Pay Now on invoices | The emailed invoice (3B) carries a secure link to a customer page showing the invoice, its PDF and a Pay Now button. Payment goes through a Sri Lankan payment gateway (for example PayHere: Visa, Mastercard, Amex and local wallets, with payment links and payment notifications), and the page also shows the bank account and reference for a transfer (owner's decision: both). A confirmed payment is recorded as a receipt waiting for the Accountant to deposit. US-style ACH does not exist in Sri Lanka; a gateway account and its fees are the company's decision | Phase 2 (with tax invoices) |
| Automated reminders | Per customer, a reminder schedule (e.g. 3 days before due, on the due date, every 7 days after), with the Admin's default message and placeholders (3B). Sent automatically from the finance mailbox; stops when paid; each reminder is recorded. A customer can be excluded | Phase 2 |
| Live invoice tracking | Each invoice shows its history: sent (from the email record, 3B), viewed (the customer opened the link; email "open" tracking is unreliable, so only the link counts), partly paid, paid, deposited | Phase 2 |

**Banking and expenses**

| Feature | How it works here | Phase |
| --- | --- | --- |
| Bank feeds | Sri Lankan banks do not yet offer a shared feed service (open banking is still being planned by the Central Bank), so live feeds as in the US are not available. Instead: import the bank's statement file (CSV or Excel) as often as wanted, using the bank's import template; templates are provided for the 15 largest Sri Lankan banks (below). If a bank used by the company offers a corporate API, a direct feed can be added for that bank | Phase 2 (bank reconciliation) |
| Transaction matching | Imported lines are matched to payments, receipts and transfers already in the books (amount, date, cheque number, reference). Suggestions for the rest come from rules and from how similar lines were coded before. The Accountant approves, matches, splits or adds with one click; nothing is posted without that click | Phase 2 |
| Receipt capture and match | Photograph a receipt or invoice on the phone (the voucher upload already takes the camera, P1-02). The system reads supplier, date, invoice number, amounts and VAT from the image and fills in the voucher lines for the Clerk to check. Images are read by Anthropic's Claude (owner's decision, below) | Reading invoices: after Phase 1 go-live; matching to bank lines: Phase 2 |

**Payroll and people**

| Feature | How it works here | Phase |
| --- | --- | --- |
| Employee self-service portal | Each employee signs in (phone friendly) to see their payslips, EPF and ETF contributions, APIT certificates, leave balance and attendance; to apply for leave; and to request changes to personal or bank details, which HR approves (bank details need the same check as suppliers' bank details) | Phase 2b (payroll) |
| Time tracking | Attendance uploaded by the HR executive from an Excel template (owner's decision, below), plus a phone punch clock for staff working away. A phone punch can be limited to a set area around each site (geofencing, with the employee's consent). Shifts and rosters already exist (3A.2); worked hours, overtime and holiday work flow to payroll and to job costing | Phase 2b |

**Inventory and projects**

| Feature | How it works here | Phase |
| --- | --- | --- |
| Project profitability | Each job order and production order already has its live profitability: income, material, labour, machine time and overheads against the estimate, with a red, amber or green status (7.7) | Phase 3 (7.7) |
| Inventory alerts | Each item has a reorder level and quantity per store. Falling below it notifies the storekeeper and purchasing (P0-18), with a one-click draft purchase request to the usual supplier, which then follows its normal approval | Phase 2 (stores and purchasing) |

**Decisions made by the owner (29 Oct 2026)**

- **Card payments: both.** The customer page offers Pay Now through a payment gateway (for example PayHere) and also shows the bank transfer details with the reference to use. The gateway account and its keys are set by the Admin in a settings page; the keys are stored encrypted, like the mailbox password (3B).
- **Receipt reading: Claude.** Images are read by Anthropic's Claude through its API. Only the image and the request leave the server; the API key is an environment setting on the server, never in the repository (rule 12). What Claude reads only fills in a draft for the Clerk to check; nothing is saved or posted without a person confirming it. Each reading is recorded with the file's SHA-256 fingerprint.
- **Attendance: an Excel template.** No device link. The system provides an attendance template (employee number, date, time in, time out, shift, leave code, remarks) that the HR executive fills in and uploads, as for the factory structure import (3A.1): checked first, all or nothing, every refused row listed. Uploaded attendance is confirmed by HR before payroll uses it. A device export can be loaded later if its columns are mapped to the template.
- **Banks: statement import templates for the 15 largest banks in Sri Lanka.** The company uses Commercial Bank of Ceylon, Sampath Bank, Seylan Bank, People's Bank, Bank of Ceylon and Hatton National Bank. Templates are prepared for these and for National Development Bank, Nations Trust Bank, DFCC Bank, National Savings Bank, Pan Asia Bank, Union Bank of Colombo, Amana Bank, Cargills Bank and Standard Chartered Bank Sri Lanka. A template is a column mapping (which columns hold the date, description, cheque number or reference, debit, credit and balance; the date format; header rows), so the Accountant can correct one or add a bank without a code change. Each bank's template is checked against a real statement export from that bank before go-live: one sample statement per bank used (account numbers can be masked).

## 8. Non-functional requirements, roadmap and team

### 8.1 Non-functional requirements

| Area | Requirement |
| --- | --- |
| Performance | List pages load in under 2 seconds with 50 concurrent users |
| Availability | 99.5% during working hours; maintenance outside shifts |
| Backup | Nightly encrypted backup of database and files, kept 30 days, off-site copy, monthly restore test |
| Browsers | Current Chrome, Edge, Safari; tablets and phones for approvals and shop-floor entry |
| Data retention | Financial records kept at least the legally required period (confirm with auditor) |
| Accessibility | Readable on phones; keyboard navigation for data entry screens |
| Testing | Automated tests for every posting rule and every approval rule; accountant sign-off on posting test cases |

### 8.2 Roadmap

| Phase | Scope | Estimate (2–3 developers) |
| --- | --- | --- |
| 0 + 1 | Core foundation, voucher approval, supplier payments | 3–4 months |
| 1.5 | Customers, quotations with costing, proforma invoices, sales orders | 2 months |
| 1.6 | Purchase orders, goods receipt with QC acceptance, stock, supplier invoices with three-way match, vouchers from matched invoices (section 5A) | 2–3 months |
| 2 | Full financial accounting, migration, one-month parallel run; payroll follows as Phase 2b | 9–12 months |
| 3 | Moulding production and supervisor pages first, then machining job cards and costing, QC, OEE | 6–9 months |

Each phase ends with user acceptance testing by the people who will use it, then go-live. Phase 1 can run alongside the existing accounting system until Phase 2 replaces it.

### 8.3 Team

| Role | Commitment |
| --- | --- |
| Senior backend developer (owns the data model) | Full-time |
| Frontend developer | Full-time |
| Second developer (backend or full-stack) | Full-time from Phase 2 |
| QA tester | Part-time |
| Accountant reviewing the accounting design and test cases | Part-time, essential |
| Production Manager as process owner for Phase 3 | Part-time |

### 8.4 Open questions

**Decisions made**

| Question | Decision | Where in this document |
| --- | --- | --- |
| Divisions, sections, machines | Admin-configurable at all three levels; initial data includes Manual Milling (3 machines) and 8 moulding machines | 7.1 |
| Shifts | Both divisions run nights. General shift 08:00–17:00; seasonal rosters (3 × 8-hour, or 12-hour Day/Night/Off rotation) | 7.1A |
| Voucher approval thresholds | None. Every voucher needs the Director's approval | 4.3 |
| Existing system | Not custom-built; no voucher history migrated. Phase 1 starts fresh | 4 |
| Hosting | Hostinger Ubuntu VPS, in the region closest to Sri Lanka | 2 |
| Payroll | Phase 2b, after core accounting is live | 6, 8.2 |
| Quotation approval limits | Yes: minimum margin % and maximum value, set by the Director in settings | 5.1 |
| Export customers | Yes: foreign-currency quotations, proformas, invoices and receipts | 5.5 |
| QuickBooks-style interactive features | Added to the plan in the phase each depends on; Sri Lankan equivalents where US services do not exist | 7A |
| Tax invoice and quotation numbers | Tax invoice YYMMM_XX_PP per division, restarting monthly and carrying on past 99; quotation QL + YYMMDD + daily count; amounts as 115,750.00 | 3, 5.1, 6.1 |
| Go-live (owner, 2 Nov 2026) | Opening stock counted and loaded; open paper vouchers typed into the ERP and approved again; amendments started by the Clerk only; quotation limits kept by the Admin (defaults 1% margin, no maximum); www redirects to the main address; usual accounting standards (IAS 2 and IAS 21 corrections), confirmed by the auditors; VAT 18%, SSCL chosen per line from SSCL codes, confirmed by the tax advisor | 5A, backlog phase 1.6 section H |
| Customer receipts (P2-07; owner, 3 Nov 2026) | Recorded by the Cashier and split over issued invoices, never more than is open; approved by the Accountant, or a person the Admin gives the right to, confirmed by the Director (receipts and advances); cheques to Undeposited funds, post-dated cheques posted on their date; extra money recorded as an advance, set off automatically against the customer's next or any later invoice; advances of an order set off first when its invoice is issued | 5.2, 6 |
| Credit control (owner, 3 Nov 2026; P2-08) | Block: a customer with an overdue invoice, or over its credit limit with the new document, gets no sales order confirmed or tax invoice issued until the Director allows that document, with a note. An empty limit means no limit; one day overdue counts (defaults the owner can change) | 6, 7A |
| Credit limits and payment terms (owner, 3 Nov 2026) | Changed only by the Accountant or the Director (or a person given the right, confirmed by the Director), with a reason; Sales see them | 5.4, 6 |
| Export invoices (P2-09, IAS 21) | In the order's currency at the invoice date's rate; receipts and advances at their own rates; the realised difference to Exchange gain or Exchange loss; one currency per receipt, into an account of that currency | 5.5, 6 |
| VAT on exports (owner, 3 Nov 2026) | Goods for an export customer are zero-rated (VAT 0%, no SSCL: tax code ZERO-RATED on every line); a local customer paying in a foreign currency pays VAT and SSCL as usual | 5.5, 6.1 |
| Payables (P2-10) | What we owe each supplier comes from our documents (matched supplier invoices and invoices on vouchers, less set-offs, debit notes and what is paid); supplier statements typed or imported and matched line by line | 6 |
| Payment cancellation and foreign payments (P2-11) | A payment is cancelled only with the Director's approval: reversing entry, cheque spoiled, voucher open to pay again. Vouchers of supplier invoices in one foreign currency may be paid in it at the payment date's rate, the difference posted as exchange gain or loss (IAS 21) | 4.4, 4.6, 5A |
| Withholding tax on payments (P2-12) | Built switched off (owner, 3 Nov 2026): none until the Accountant sets a rate. Then coded per voucher line on the amount before VAT; the payee is paid the net, WHT payable credited, and a numbered WHT certificate printed per payment | 4.4, 6 |
| Reorder alerts and purchase requests (P2-13) | Reorder level and quantity per item and main store; at or below it (counting what is ordered or requested) the stores person and purchasing are told once; one click makes a draft request to the usual supplier. The Director approves requests by default (the Admin can change the role); purchasing makes an approved request into a draft PO at the last price | 6, 5A |
| Cheque register and deposits (P2-14) | One register of our and customers' cheques; deposit slips from Undeposited funds; a returned cheque reverses its receipt (the bank credited) and opens the invoices again; transfers between own accounts stay Internal Transfer vouchers | 4.1, 6 |
| Bank statement import (P2-15) | Templates per bank kept by the Accountant (Excel/CSV headings, or PDF text line by line); every balance checked against the one before, so a misread file is refused; the same file once; overlapping lines skipped; imported lines never change | 7A |
| Bank reconciliation (P2-16) | Statement lines matched to journal entries (amount, direction, date window, reference on the line); charges and interest posted from the line by rule or earlier coding; nothing without the Accountant's click; a month finished only with every line in the books and nil difference, then locked and its cheques marked cleared | 6, 7A |
| Petty cash (P2-17) | Imprest: the custodian records expenses with slips (never more than the float); the Clerk tops up with a Petty Cash voucher listing them, through the three approvals; paying it posts the expenses | 4.1, 6 |
| Stock issues, adjustments and counts (P2-18) | Issues and returns at weighted average cost, oldest lot first, posted at once; adjustments, write-offs and count differences posted only on the Director's approval; WIP and finished goods accounts ready for Phase 3 | 6, 5A |
| Fixed assets (P2-19) | Classes with dated methods and rates entered as the auditors agree (none depreciated until then; land never); monthly depreciation checked then posted in order; disposals post the gain or loss; mould shot count kept for Phase 3 | 6 |
| Tax reports (P2-20) | VAT return by month (standard, zero-rated exports apart, exempt, outside VAT; output VAT checked against the ledger; input VAT as claimed in the books), SSCL with its base, WHT with certificates; each line traced to its document; Excel and PDF | 6 |
| Month-end revaluation (P2-21) | Open foreign-currency customer and supplier invoices revalued at the month-end rate, posted to Unrealised exchange gain or loss and reversed on the 1st; foreign-currency bank and cash balances (from the statement or typed) revalued to Exchange gain or loss and kept; checked by the Accountant then posted | 5.5, 6 |
| Budgets (P2-22) | A financial year's budget by account, division and month, typed or imported from Excel, approved by the Director; revisions are new versions; the profit and loss shows budget, difference and % beside the actual | 6 |
| Month-end and year-end close (P2-23) | Month-end checklist (bank reconciliations, depreciation, revaluation, open journals, accruals) checked by the system or ticked with a note before the Director closes; year-end close carries income and costs to retained earnings on the next year's first day; reopening by the Director with a reason | 6 |
| Quotation pictures (owner, 4 Nov 2026) | Up to 3 product pictures (JPG/PNG, 1 MB each) added to a draft quotation, shown to the approver and emailed with the quotation | 5.1 |
| Cash flow and finance tiles (P2-24) | Cash flow statement (indirect method) for the company, adding up to the change in cash; home page tiles for profit (month, year with budget), cash, receivables and payables, per division or company, each opening its report | 6, 7A |
| Cash flow planner (P2-25) | Bank and cash balance projected day by day for 13 weeks from receivables (by each customer's payment history), cheques held, payables and recurring payments, with what-if items that are never posted | 7A |
| Report builder (P2-26) | Own reports from journal lines, vouchers, sales and supplier invoices or stock movements: columns by drag-and-drop, filters, grouping with subtotals, sort, period columns by month or division; saved, shared with a role, Excel, PDF and email; each person sees only what their access allows | 7A |
| Invoice tracking (P2-27) | The emailed invoice carries a secret link to a customer page (invoice, PDF, bank transfer details); views are recorded; OnePay card links sent are recorded; the invoice shows open/overdue/partly paid/paid and its full history. No Pay Now button (owner, 3 Nov 2026) | 7A |
| Opening balances from QuickBooks (P2-28, part 1) | QuickBooks' trial balance, A/R and A/P ageing and item list read as exported and checked (balance, accounts, customers, suppliers, totals); one opening entry approved by the Director | 6.1 |
| Open invoices and bills from QuickBooks (P2-28, part 2) | Each open invoice and bill in the QuickBooks ageing brought over for what is still open, agreeing per customer and supplier with the opening balances; paid by receipts and vouchers like any other | 6.1 |
| Parallel run tools (P2-29) | Test scripts per role and sign-off sheets (docs/uat-scripts.md); a page comparing QuickBooks' trial balance and ageing with the ERP at the same date, every difference listed | 8.2 |
| Employee master (P2B-01) | Employees kept by HR, seen by HR and the Director only; salary bank account checked by a second person; NIC checked and unique; never deleted, number never changes; Excel import checked first, all or nothing | 2.1, 6, 7A |
| Pay structure (P2B-02) | Pay components kept by HR, each marked for EPF/ETF and APIT (a deduction never is); each employee's amounts dated from the 1st of a month and never changed, a raise is a new amount, 0 ends a component, a future amount can be withdrawn; budgetary relief allowance not separate since 31 March 2025 | 2.1, 6, 7A |
| Holidays and leave (P2B-03) | Holidays kept by HR (past ones kept); leave types with the Shop and Office Employees Act rules by default, no carry-forward; the year's leave granted once, adjustments with a reason; leave counted Monday to Saturday without holidays, never beyond the balance; applied-for leave approved by HR, never one's own; leave cancelled, never deleted | 2.1, 6, 7A |
| Attendance from Excel (P2B-04) | The template sheet checked first, all or nothing, every refused row listed; minutes worked, late and early against the shift; leave codes become leave when HR confirms a division's month after it ends; confirmed days never change (database); reopening needs a reason | 7A |
| Overtime and attendance rules (P2B-05) | Dated work rules per division (default 8 hours a day, 1.5 / 2 / 2 times); overtime, short time, short leave and no-pay worked out from confirmed attendance; each month checked by the section's supervisor or the Director, never the person who confirmed the attendance; checked figures kept for payroll, voided if attendance is reopened | 7A |
| Pay period (owner, 5 Nov 2026; P2B-15) | Everyone paid monthly; the pay period is the 21st to the 20th of the next month, paid on the last day of the month; attendance, overtime and no-pay are worked out per pay month | 6, 7A |
| Pay period setting (P2B-15) | A pay month is named by the month it ends in (November = 21 Oct – 20 Nov); the start day is a dated setting kept by HR (default the 21st), never changed, refused when it would move a confirmed pay month; confirmed attendance frozen per pay month in the database; work rules in force from the first day of their pay month | 7A |
| Labour categories and leave (owner, 5 Nov 2026; P2B-16) | Each employee is Shop and Office or Wages Board. Annual leave 14 / 7; casual and sick leave together 7 for both; maternity as the law gives; short leave up to 2 × 1.5 hours a month, paid for Shop and Office, unpaid for Wages Board (a quarter day's pay each); more than 2 must be leave | 6, 7A |
| Employee pay settings (owner, 5 Nov 2026; P2B-17) | Pay amounts, attendance bonus (default LKR 1,500, lost when absent four half days in the period), up to four allowances, overtime and leave settings and the APIT setting are set per employee by HR and take effect only when the Director approves, for new employees and every change; never approved by the person who prepared them | 6, 7A |
| Payroll approval and payment (owner, 5 Nov 2026) | The Director approves the payroll, then the salary voucher goes through Clerk → Accountant → Director; Commercial Bank of Ceylon PLC pays by bulk transfer; payslips on the self-service page, emailed, printed on request; APIT from the IRD tables | 6, 7A |
| Advances, loans and gratuity (owner, 5 Nov 2026; P2B-10, P2B-07) | Advances paid during the period, deducted from the month-end salary; loans in equal monthly instalments over the loan period; gratuity by the Payment of Gratuity Act, the accounting provision confirmed with the auditors | 6, 7A |
| Payroll follow-up answers (owner, 5 Nov 2026) | Day rate = monthly pay ÷ 30, also for part periods; the attendance bonus is lost for four half days absent, approved leave included (maternity leave and holidays excepted by default); HR enters pay settings; every advance and loan approved by the Director, interest agreed per loan; the employee always receives more than 40% of the basic salary at month end; Wages Board annual leave 7 from the first full year; EPF/APIT marks and gratuity settings per employee (gratuity by the Accountant), approved by the Director | 6, 7A |
| Labour categories and leave (P2B-16) | Employee category Shop and Office or Wages Board; leave types may give Wages Board staff their own rule and days (annual 7 from the first full year); casual and sick leave 7 for both; maternity 84 working days a live birth (42 still birth), paid, at most 84 in one leave (Acts No. 14 and 15 of 2018); Wages Board short leave unpaid by default, kept on the checked month for payroll to deduct a quarter day each | 6, 7A |
| Employee pay settings (P2B-17) | Pay changes prepared by HR and approved by the Director (approval type "pay_change"; never by the preparer): amounts with the employee's own EPF/APIT marks, attendance bonus (default LKR 1,500), at most four allowances, own normal day, grace, overtime rates, leave days and APIT table; nothing takes effect before approval; decided changes and approved settings never change (database); HR no longer enters amounts directly | 6, 7A |
| Monthly payroll run (P2B-06) | Per division and pay month, after confirmed attendance and checked overtime; earnings from approved settings (part periods by days ÷ 30), attendance bonus lost for four half days away, day rate = monthly pay (components "in the day rate") ÷ 30, OT = hours × monthly pay ÷ divisor × rate, no-pay and Wages Board quarter days, EPF 8/12% and ETF 3% (dated), APIT from dated IRD tables (Table 01 from 1 Apr 2025; Table 07 entered by the Accountant), net ≥ 40% of basic; Director approves, then locked; attendance and pay changes for paid months refused | 6, 7A |
| Payroll posting and paying (P2B-07) | On approval a payroll is numbered (PRyymmNN) and posts Dr Salaries and wages and EPF/ETF contributions (division), Cr EPF, ETF, APIT, payroll deductions and salaries payable, dated the end of the pay period; the net is paid by a salary voucher coded to Salaries payable through the three approvals; bank file (P2B-18) and gratuity (P2B-19) are separate tasks | 6, 7A |
| Payslips (P2B-08) | From approved payrolls only; A5 PDF with every figure and its basis, employer EPF/ETF, year to date from 1 April; printed by HR or the Director; emailed by HR to employees with an email address, locked with the NIC number, no company copy, recorded; self-service with P2B-11 | 3B, 6, 7A |
| Statutory returns (P2B-09) | From approved payrolls only, company-wide within the user's divisions: EPF C form, ETF monthly and half-year, APIT monthly schedule, APIT for the year and year-end certificates; on screen, Excel and PDF; EPF and ETF employer numbers on the company profile; electronic upload files wait for the official layouts | 6, 7A |
| Advances and loans (P2B-10) | Recorded by HR, approved by the Director (never the recorder), numbered SLyymmNN; advance recovered in its pay month, loan in equal instalments of (amount + interest) ÷ months; refused if the first recovery leaves 40% of basic or less; the payroll reduces a recovery to keep more than 40% (rest next month); leaver repays the balance as far as it goes; recoveries Cr Staff loans and advances, interest share Cr Interest earned; paid out by voucher coded to Staff loans and advances | 6, 7A |
| Self-service (P2B-11) | Each signed-in person sees only their own records (the employee HR linked to their sign-in by email): payslips, EPF/ETF/APIT, APIT certificate, leave balances, attendance; applies for and withdraws leave; leave applied for is approved by a supervisor of the employee's section or HR, never the applicant; detail-change requests in P2B-20 | 6, 7A |
| Phone punch clock (P2B-12) | Per employee (HR): not used, from anywhere, or only at a site; server time; sites a point and radius (20 m–5 km), never deleted; location read only when pressing the button and only with the employee's consent (withdrawable), accuracy within 150 m; punches never change; HR brings a pay month into attendance after a preview (first in, last out, nearest shift within 2 h; sheet days kept; unclosed clock-ins listed) | 7A |
| Detail-change requests (P2B-20) | The employee asks on the self-service page (phone, address, email, salary account; one waiting at a time, withdrawable); HR approves or rejects with a reason, never their own; approval changes the record as HR would, a new salary account still waits for the Director's check; nobody checks their own salary account; a request is refused if HR changed those fields since; never deleted, never changed once decided | 7A, 4.6 |
| Payroll in the rest of the system (P2B-13) | Cash flow planner: net pay on the last day of the pay month, EPF/ETF by the end of the next month, APIT by the 15th of the next month; ledger balances owed matched to approved payrolls, coming months estimated from the latest approved payroll per division; month-end checklist item "payroll approved for every division"; report builder source "Payroll" (HR and Director only); labour cost per hour = (gross + EPF 12% + ETF 3%) ÷ attendance hours, per division and section | 6, 7A |
| Gratuity (P2B-19) | The Payment of Gratuity Act by default (half a month's wage of basic + fixed per completed year after 5 years, service from joining); per-employee settings (service from, months per year 0.5–3, earned after 0–5 years) entered by the Accountant, approved by the Director, never below the Act; each payroll provides the change in the liability (Dr Gratuity 6015, Cr Provision for gratuity 2520); paid on leaving by voucher; method confirmed with the auditors | 6, 7A |
| Payroll takeover (P2B-14) | HR copies the old (Excel) payroll into the ERP's templates: pay (each row a new employee's pay settings for the Director), the year's figures to date with the gratuity provided (the Director approves; then in year to date, APIT year return and certificates, and gratuity), and one pay month compared employee by employee with the payroll here, signed off by the Director (never the uploader; a note for differences) | 6, 7A |
| Fingerprint machine file (P2B-21) | The machine's own Schedule report uploaded as it is on the attendance page; people matched by each employee's Fingerprint ID; earliest punch in, latest out, nearest shift; single punches and days outside employment listed, sheet corrections and leave kept, earlier machine days replaced; read safely (defusedxml) | 7A |
| Moulds (P3-01) | Parts and cavities (family moulds), size, clamping force, shot and runner weight, compatible machines with fit warnings, company (optional fixed asset) or customer owner, shot count and maintenance interval; Excel import/export and QR labels; code fixed once used, retired not deleted; production roles switched on; item category Finished part | 7.1 |
| Reasons and production settings (P3-02) | Reject and downtime reasons per division (downtime planned or unplanned for OEE), kept by the Admin, used codes fixed and never deleted; dated limits (grace 4 h, reject 5%, overrun 10%, margin from the quotation) changed from today or later with a reason, never once in force | 7.4, 7.7 |
| Routings (P3-03) | Operations by section (machining method) and optional machine with setup and run minutes, or subcontracted at a cost per piece; drafts by the Planner approved by the Production Manager (approval engine), one in force per part, approved revisions never change; copy, new revision, Excel | 7.1 |
| Bills of materials (P3-04) | Multi-level BOMs (machining, moulding, general) with raw material, masterbatch % of resin, bought-out, sub-assembly, subcontract and packing lines; machining cut-length and moulding resin calculators, family moulds; drafts approved by the Production Manager, approved revisions never change; copy, compare, where-used, Excel; standard cost rolled up through all levels | 7.1B |
| Production cost rates (P3-05) | Dated labour per section (accepted from the latest approved payroll, a division's rate for a section of fewer than three people), overhead per machine hour per section or machine (0 until set), regrind credit per kg (100% of the material's cost unless set) and mould amortisation per shot for company moulds only, kept by the Accountant and read by production; a rate in force never changes; the BOM standard cost adds labour, overhead and mould amortisation | 7.7 |
| Moulding production orders (P3-06) | Orders for stock or a sales order line (its delivery schedule as due dates, never more than the line's quantity), numbered MO; the Planner releases them, copying the approved moulding BOM (family moulds by the shot), never changed afterwards; materials needed against stores, open purchase orders, requests and other released orders; shortages notified to stores and purchasing, who raise a draft purchase request from the order; Draft → Released → Completed → Closed or Cancelled, never deleted | 7.3, 7.7, 7.1B |
| Production plan (P3-07) | Released orders' moulds on moulding machines per shift and date, picked and moved by the Planner, days copied; planned quantity = shots in the planned minutes at the standard cycle time × cavities; warnings (mould too big, maintenance, machine twice or beyond the shift, mould on two machines, no crew rostered, material short, more than the order) never block; past days never change; supervisors see their own sections | 7.3, 3A.1, 3A.2 |
| Moulding shift report (P3-08) | Supervisors' phone page for their own moulding sections: runs per machine (order from the plan, batch, operator, times, shot counters, rejects by reason), downtime, material issued/returned/regrind, manpower; good qty = shots × cavities − rejects, actual cycle time, material per good piece; counters never go down, rejects ≤ shots × cavities, no overlapping times (database), entry only in the shift and grace period; submitted reports locked (database); camera scanning with the browser's barcode reader | 7.4, 7.5 |
| Shift report approval and corrections (P3-09) | The Production Manager approves or returns submitted reports (never the submitter); approval backflushes the orders' materials at average cost (resin for good and rejected, packing for good), puts good pieces (and family parts) and regrind into stock with a journal, adds the mould's shots; corrections after the entry time by the Production Manager, the Director or a person given the action (Director confirming), never the asker: reopen a late draft or reverse an approved report; originals kept | 7.4 |
| Mould maintenance (P3-10) | Shots since the last preventive maintenance against the interval: approaching at 90%, due at 100%, the Production Manager notified once per stage on shift report approval; records (preventive or repair, date, shot count, work, cost, by whom, our workshop) by the Production Manager or Planner, never changed (database); preventive maintenance restarts the count; history per mould | 7.4, 7.5 |
| QC deviation approver (fix, G10) | Deviations approved by the Production Manager; on a failed critical check by the Director (approval subtypes standard/critical; refused if the matrix skips the Director) | 6A.4 |
| Production demo data | `load_demo_data` adds an HR officer, Planner, Supervisor and Production Manager, moulding staff on a roster, presses, a mould, an approved BOM, opening stock, cost rates, a released and a draft order and today's plan | — |
| Asset depreciation terms (owner, 8 Nov) | Class defaults (straight line: buildings 5%/20 y, plant and machinery and moulds 10%/10 y, vehicles 20%/5 y, furniture and fittings and computers and software 20%/5 y, amended by the owner on 9 Nov from 25%/4 y; months already posted keep the old rate); each asset's own dated method, rate and useful life, approved by the Director before depreciation; class default changes approved by the Director; straight line rate = 100 ÷ life; approved terms never change (database) | 6 |
| Job orders and material issue (P3-11) | Job orders (JO) for a sales order line or internal work (mould making, mould repair, tools, other); approved routing and BOM copied, changeable while a draft, fixed on release; the jobs and production orders of a sales line never exceed it; Stores issues by lot up to per piece × quantity; more needs the Production Manager's approval with a reason; returns credited; cancel only with no material out | 7.2 |
| Job cards and operation entry (P3-12) | A5 job card per operation with QR "job/operation"; machining shift reports with job card work (machine, operator, times, completed, rejected by reason, rework, setup); completed + rejected never above what the operation before completed; no overlapping times on a machine (database); minutes per piece against standard; per operation received, in hand and ready for the next; approval as P3-09 without stock moves | 7.2, 7.4 |
| Subcontract operations (P3-13) | Parts sent out on a numbered note (SC) for a subcontract operation, never more than received; counted back good and rejected (reason), never more than out (database); good parts go on to the next operation; voucher lines and supplier invoice lines coded to a released or completed job or production order; bills shown on the job | 7.2, 7.7 |
| Inspection on jobs (P3-14) | First-article, in-process and final inspections by QC with the part's plan checks per piece (extra checks allowed); a failure holds the job (no work, sending out or completion); the Production Manager decides rework or scrap of N pieces (flow adjusted) or deviation, the Director approving on a failed critical check; never changed once decided (database) | 7.2, 6A.4 |
| Mould making and inter-division transfers (P3-15) | Completed mould jobs transferred at cost by the Accountant (material net, bills coded, labour and overhead for approved job card time); new company mould capitalised (Dr 1530 in the mould's division, fixed asset registered); repair charged (Dr Inter-division charges 5080); Cr Inter-division sales 4800 in the workshop; repairs eliminated in the company total; never changed (database) | 3.1, 7.3 |
| Order costs, part 1 (P3-16) | Insert-only cost entries per job and production order from approved sources (material, labour, machine time and overhead, setup and mould change, mould amortisation, subcontract and direct bills) at the rates of the day; adjusting entries when a source changes; shown by element with cost per good piece and rejects; ledger postings follow in part 2 | 7.7 |
| Order costs, part 2: work in progress (P3-16) | Order costs posted to the ledger against their source account: machining jobs with a stock part through 1220 Work in progress per division, to the part's stock on completion (unfinished to 5005 cost of finished goods sold); moulding costs added to the parts' stock value; mould and tool jobs not posted. Delivery notes name the part and take it out of stock FIFO at weighted average (Dr 5005), refused without stock; cancelling puts it back. Month-end WIP report reconciled with 1220, unabsorbed downtime, on the checklist | 7.7 |
| Live order profitability (P3-17) | Each open job and production order: estimate from the quotation costing (else BOM standard cost), actual cost and earned revenue in LKR, forecast at completion, margin % on cost, red/amber/green against the dated overrun, margin and reject limits; dashboard with filters; cost lines linked to their shift report, voucher or supplier invoice; one alert per order and kind to the Production Manager and Director; insert-only daily snapshot; moulding view per machine and mould | 7.7 |
| Closing an order and variances (P3-18) | Orders for a sales line close on the last delivery (or on completion if delivered first); an insert-only final report: revenue at the invoices' rates, cost, margin, estimate (quotation costing flexed to good pieces) against actual for material (price and usage), machine time, setup, rejects, subcontract and direct; actual kg, machine hours, setup and cycle time per part averaged over closed orders for quoting | 7.7 |
| Machine OEE (P3-19) | Per moulding machine, shift, day and month from approved shift reports: planned time from the roster (off days not counted, planned stops taken off, other worked shifts added), availability, performance against the mould's standard cycle, quality, OEE = A × P × Q; machines compared with each one's trend | 7.4 |
| Production reports, part 1 (P3-20) | From approved shift reports in the user's sections: daily production by section, machine and shift; rejects by reason, part, mould and machine; downtime Pareto by reason and machine; machining jobs' estimated against actual hours and cost, on-time delivery; moulding material issued against the backflushed standard, regrind; moulds near maintenance | 7.6 |
| Production reports, part 2 (P3-20) | Report builder sources: moulding runs, downtime and job card entries (approved shift reports, own sections), order costs and closed orders (cost access only); closed orders' margin by customer, part, mould, division or order, most profitable first; estimate accuracy by element with material price and usage | 7.6, 7.7 |
| Shop-floor Sinhala (P3-21 part 1) | Sinhala wording (machine translation, owner to have it checked) for the shift report, production plan, menu, sign-in, notifications and tables; language chosen on the sign-in page or side menu and kept on the device; untranslated text falls back to English | 3A, 7.4 |
| Offline shift report entry (P3-21 part 2) | Saves kept on the phone without a connection, sent when it returns, with a status line; a save on an older version refused (409) and both versions shown for the supervisor to choose; the page opens offline from a kept copy (service worker for the app files only); kept data cleared on signing out | 7.4 |
| Owner's wording from testing (10 Nov 2026) | The shift report is called **Work shift report** (Sinhala **වැඩ මුර වාර්තාව**; "shift" is මුරය throughout the Sinhala); every side-menu heading and page name, and the home page, in Sinhala (the pages themselves stay English except the shop-floor ones); side-menu headings in black bold, a little larger | 7.4 |
| Plan move after removal (owner's testing, 11 Nov 2026) | Removing a run closes its Move box; moving or removing a run that has gone says "This run is no longer in the plan", closes the box and reloads the plan; no API error shows Django's "No <record> matches the given query." (a plain "This record is no longer here" instead) | 7.3 |
| Demo plan for a week (owner's testing, 11 Nov 2026) | The demo data plans the moulding order for the load day and the next six days, so later testing days still show a planned run | 7.3 |
| Machines without a shift supervisor (owner's testing, 11 Nov 2026) | The production plan marks a machine whose section has no active shift supervisor (its runs would reach no work shift report), beside the machine and when it is chosen; planning there is still allowed | 7.3 |
| Ask to issue more: choose the material (owner's testing, 11 Nov 2026) | The material for a request to issue more is chosen from the job's materials; "Another item…" lets a material not on the job be typed | 7.2 |
| Production Manager's dashboard (owner, 11 Nov 2026) | The Production Manager's home page shows what waits for their decision (shift reports, corrections, requests to issue more, inspection decisions, BOMs and routings), good pieces made today and moulds due, instead of the sales and purchasing summaries they can only view | 7.6 |
| Delivery refused for stock: plain wording (owner's testing, 12 Nov 2026) | A delivery note refused for too little finished stock gives the quantity in stock and the quantity asked for in plain figures, and says to finish or approve more production first | 7.7 |
| Production Planner's dashboard (owner, 12 Nov 2026) | The Production Planner's home page shows the Production panel instead of the sales and purchasing figures, as the Production Manager's does | 7.6 |
| Supervisors only in their own sections (owner's testing, 12 Nov 2026) | A Production Supervisor sees and enters only the sections they supervise or are assigned to, even with "All sections" ticked: work shift report, production plan, production reports and the report builder's shift data | 7.4 |
| Demo workshop operators (owner, 12 Nov 2026) | The demo data adds four made-up workshop operators (two on M-BSW, two on C-LAT); a PC with the earlier demo gets just them when the demo is loaded again | 7.4 |
| Demo inspection plan for the drive shaft (owner's testing, 13 Nov 2026) | The demo data adds QC's inspection plan for SH-600 (Diameter 44.95–45.05 mm), so the job's inspection shows its check | 7.9 |
| Layout fixes from testing (owner, 13 Nov 2026) | Report builder: each column's tick box beside its name, and counts with thousands separators; job cost entries: the date on one line | 7A |
| Times in Sri Lanka time, 24-hour clock (owner, 13 Nov 2026) | Every date and time shown is Sri Lanka time on the 24-hour clock on any PC or phone; new documents default to the factory's date; time boxes take HH:MM | 3 |
| Admin switch for two-factor sign-in (owner, 14 Nov 2026) | The Admin can switch two-factor sign-in off or on for the whole company, with a reason, audited; on by default; off only while testing and it must be on before go-live | 3 |
| Stock values only for cost viewers (owner, 14 Nov 2026) | Stock on hand shows average cost, values and the total value only to people who may see costs (Director, Accountant, Auditor, cost viewers); everyone else sees quantities | 5A.3 |
| Waiting for your approval on every dashboard (owner, 14 Nov 2026) | Each person's dashboard shows how many documents of each kind wait at a level they approve, each linking to where it is approved | 3 |
| Director sends a voucher back to the Accountant (owner, 14 Nov 2026) | Besides Return to Clerk, the Director can send a voucher back to the Accountant with a reason; the Accountant corrects and approves again, then it returns to the Director | 4.3 |
| Shop-floor supervisor's dashboard (owner, 12 Nov 2026) | A supervisor's home page shows, for their own sections: shifts open for entry, reports still to finish, today's and tomorrow's plan, good pieces made yesterday and today, and moulds due; in English and Sinhala | 7.6 |

**Still needed for initial setup**

- [x] Workshop sections: 18 sections listed; Admin maintains them on page 3A.1.
- [x] Moulding machine grouping and tonnage: entered by the Admin on page 3A.1.
- [x] Roster shift times: entered by the Admin on page 3A.2.
- [x] Quotation margin and value limits: set on page 3A.3, confirmed by the Director.
- [x] Export currencies: common currencies pre-loaded on page 3A.4.
- [x] VPS provider: Hostinger Ubuntu VPS.
- [ ] Before go-live: Admin enters all machines, crews and roster patterns; Director sets the quotation limits.
