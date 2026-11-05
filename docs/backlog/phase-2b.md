# Backlog — Phase 2b (payroll and people)

Salaries paid from the ERP: employees, attendance, overtime, the monthly payroll with EPF, ETF
and APIT, payslips, the bank transfer file, the statutory returns, and the employee
self-service page (spec 2.1 "HR and Payroll Officer", 6 "Payroll", 7A "Payroll and people",
owner's decision of 29 Oct 2026 on attendance). It goes live after core accounting is live
(spec 6, 8.2); it is built now so it is ready by then. Same rules as before: work top to
bottom, one task per pull request, and a task is done when every acceptance criterion is a
passing test.

```
Employee master → Attendance (Excel) → HR confirms → Overtime and leave
     → Payroll run (HR prepares) → Director approves → Journal posted
     → Salary voucher (Clerk → Accountant → Director) → Bank transfer file → Payslips
     → EPF / ETF / APIT returns
```

**Already built, used here:** users, roles and the sensitive "HR and payroll" area (Director
confirms grants), divisions, sections, shifts, rosters and crews (3A.2), the approval engine,
number series, the journal and periods, vouchers and the payment lock (rule 4), company bank
accounts, document email, PDFs and Excel exports, dated master data (rule 11), the cash flow
planner and the report builder.

**Rules carried over:** money in `Decimal`; statutory rates and tax tables are dated master
data confirmed with the tax advisor, never hard-coded (spec 6); a person never approves their
own payroll; an approved payroll never changes (a correction is the next month's adjustment
or a reversal); payroll figures are visible only to the HR and payroll area and to the
Director (others see totals, as set in the role defaults).

Status: `[ ]` to do · `[x]` done

---

## A. People

- [ ] **P2B-01 Employee master**
  Employee number, name, NIC, date of birth, address, phone, email; EPF and ETF numbers;
  division, section, designation, grade; employment type (permanent, probation, contract,
  casual, trainee) with join, confirmation and leaving dates; the bank account for salary
  (changing it needs the same second check as a supplier's bank details, spec 4.6); linked
  to a user for self-service. Imported from Excel (checked first, all or nothing). History
  kept: an employee with payroll is deactivated, never deleted.

- [ ] **P2B-02 Pay structure**
  Earnings and deductions as components (basic, budgetary relief allowance, fixed and
  variable allowances, incentives; loans, advances, welfare, union), each marked
  EPF-liable or not and taxable for APIT or not. Each employee's amounts are dated (a
  raise starts on a date; earlier months keep the old amount).

## B. Time

- [ ] **P2B-03 Holidays and leave**
  The year's public and mercantile holidays; leave types with yearly entitlements and
  carry-forward rules; leave balances per employee; leave taken from attendance or applied
  for and approved.

- [ ] **P2B-04 Attendance from Excel**
  The template of the owner's decision (employee number, date, time in, time out, shift,
  leave code, remarks); checked first, every refused row listed; HR confirms the month
  before payroll uses it. Late arrivals, short leave and no-pay days worked out by the
  rules of P2B-05.

- [ ] **P2B-05 Overtime and attendance rules**
  Normal hours per shift and day; overtime at the rates in force (e.g. 1.5 times on normal
  days, 2 times on holidays, as the owner confirms); night-shift and holiday rules; the
  monthly overtime hours per employee, checked by the supervisor's division.

## C. Payroll

- [ ] **P2B-06 Monthly payroll run**
  HR prepares the month: earnings, overtime, no-pay, deductions; EPF employee 8% and
  employer 12%, ETF 3% (dated rates); APIT from the dated tax table; net pay. Each figure
  traces to its source (attendance, component, rate). Draft → sent → Director approves
  (never the person who prepared it) → locked.

- [ ] **P2B-07 Posting and paying**
  Approval posts: Dr salaries and wages per division and section, Dr employer EPF and ETF;
  Cr EPF payable, ETF payable, APIT payable, deductions payable, net salaries payable. A
  salary voucher for the net pay goes through the usual three approvals (no payment without
  the Director, rule 4); the Cashier pays it and the bank transfer file is produced in the
  bank's format.

- [ ] **P2B-08 Payslips**
  A payslip per employee (PDF), emailed or printed, in English first (Sinhala and Tamil with
  the rest of the system later); year-to-date figures.

- [ ] **P2B-09 Statutory returns**
  EPF monthly return (C form) and its contribution file, ETF return, the APIT monthly
  schedule and the year-end certificates (T-10); each from the approved payrolls, with
  Excel and PDF.

- [ ] **P2B-10 Salary advances and loans**
  An advance or loan recorded and approved (by the Director), paid through a voucher, and
  recovered from payroll in instalments; balance per employee.

## D. Self-service and links

- [ ] **P2B-11 Employee self-service (phone)**
  Each employee signs in to see their payslips, EPF and ETF contributions, APIT
  certificates, leave balance and attendance; applies for leave (approved by their
  supervisor); asks to change personal or bank details, which HR approves (bank details
  with the second check).

- [ ] **P2B-12 Phone punch clock**
  For staff working away: clock in and out from the phone, optionally limited to an area
  around each site (with the employee's consent); feeds attendance like the Excel upload.

- [ ] **P2B-13 Payroll in the rest of the system**
  Net pay and statutory payments in the cash flow planner; actual labour cost per hour for
  job costing (Phase 3); payroll as a report builder source (HR and payroll area only);
  payroll on the month-end checklist.

- [ ] **P2B-14 Migration and parallel payroll**
  Employees, their pay structure and the year's figures to date (gross, EPF, ETF, APIT)
  brought over from the current payroll; one month run in both, compared employee by
  employee, then sign-off.

---

## Questions for the owner

Answers are needed before the task named in brackets. Where no answer comes, the default in
italics is used and recorded, and can be changed.

1. **Who and how many.** About how many employees, and how many in each division? Who will
   be the HR and Payroll Officer(s)? (P2B-01)
2. **Current payroll.** How is payroll done today (an Excel sheet, a payroll program, the
   bank)? Can its employee list and this year's totals be exported to Excel? (P2B-14)
3. **Pay frequency.** Is everyone paid monthly, or are some (casual or daily paid) paid
   weekly or daily? *Default: monthly for all.* (P2B-06)
4. **Law that applies.** Are factory staff under a Wages Board, and office staff under the
   Shop and Office Employees Act? The overtime and leave rules follow from this. (P2B-03,
   P2B-05)
5. **Overtime.** Normal hours per day and week, and the overtime rates (normal day,
   Saturday, Sunday, holiday, night)? *Default: 8 hours a day, 45 a week; 1.5 times on
   normal days, 2 times on Sundays and holidays.* (P2B-05)
6. **Allowances and deductions.** The list of allowances (budgetary relief allowance,
   attendance, travelling, meal, shift…) and deductions (welfare, union, insurance…), and
   which count for EPF. (P2B-02)
7. **APIT.** Confirm with the tax advisor that APIT is deducted from the tax tables issued by
   the Inland Revenue for 2026/27, and whether any employee has a different tax
   arrangement. *Default: the IRD tables, entered as dated master data.* (P2B-06)
8. **Leave.** Leave types and days a year (annual, casual, sick, maternity…), and whether
   unused leave carries forward. *Default: as the law that applies, no carry-forward.*
   (P2B-03)
9. **Approval.** The Director approves the payroll, and the salary payment then goes through
   the normal voucher approval (Clerk, Accountant, Director). Is that right, or should the
   approved payroll be enough for the payment? *Default: both, as rule 4 requires.* (P2B-07)
10. **Bank.** Which bank pays the salaries, and does it take a bulk transfer file (please ask
    the bank for its file format)? (P2B-07)
11. **Payslips.** Emailed, printed, or only on the self-service page? *Default: on the
    self-service page and emailed to those with an email address; printed on request.*
    (P2B-08)
12. **Advances and loans.** Does the company give salary advances or loans, and how are they
    recovered? (P2B-10)
13. **Gratuity.** Should the gratuity liability (employees with 5 years or more) be
    provided for in the accounts each month or at year end? *Default: at year end, from a
    report.* (P2B-07)
