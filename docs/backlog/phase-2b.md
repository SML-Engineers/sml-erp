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

- [x] **P2B-01 Employee master**
  Employee number, name, NIC, date of birth, address, phone, email; EPF and ETF numbers;
  division, section, designation, grade; employment type (permanent, probation, contract,
  casual, trainee) with join, confirmation and leaving dates; the bank account for salary
  (changing it needs the same second check as a supplier's bank details, spec 4.6); linked
  to a user for self-service. Imported from Excel (checked first, all or nothing). History
  kept: an employee with payroll is deactivated, never deleted.
  Done: Employees page (People and payroll menu). HR (Enter) adds and changes employees and
  imports them from Excel; the Director (Approve) sees them and checks every new or changed
  salary bank account (the person who entered it never can); the Accountant's "totals only"
  view sees no personal details. Old (9 digits and V/X) and new (12 digit) NICs are checked
  and unique. A database trigger stops deleting an employee or changing the number; leavers
  get a leaving date and reason. Exporting everyone's details needs "Export personal data".
  The HR and Payroll Officer role is switched on. The link to a user is kept by the API and
  appears on the page with self-service (P2B-11).

- [x] **P2B-02 Pay structure**
  Earnings and deductions as components (basic, budgetary relief allowance, fixed and
  variable allowances, incentives; loans, advances, welfare, union), each marked
  EPF-liable or not and taxable for APIT or not. Each employee's amounts are dated (a
  raise starts on a date; earlier months keep the old amount).
  Done: Pay components page (HR keeps the list; code and kind never change; deductions
  never count for EPF or APIT, also in the database) and a Pay panel on each employee's
  page. An amount applies from the 1st of a month; it is never changed (database), a raise
  is a new amount from its month, 0 ends a component, and an amount whose month has not
  come can be withdrawn with a reason. Starting list: basic salary, fixed, attendance and
  travelling allowances, incentive; welfare, union, loan and advance recoveries; HR and the
  Accountant confirm the EPF and APIT marks (question 6). The budgetary relief allowance is
  not on the list: it stopped as a separate payment on 31 March 2025 and is part of the
  basic wage (Budgetary Relief Allowance of Workers (Amendment) Acts No. 9 and 10 of 2025).
  Defaults recorded: amounts start on the 1st of a month (no part-month raises); a raise
  needs no separate approval, the Director sees it in the payroll he approves (P2B-07).

## B. Time

- [x] **P2B-03 Holidays and leave**
  The year's public and mercantile holidays; leave types with yearly entitlements and
  carry-forward rules; leave balances per employee; leave taken from attendance or applied
  for and approved.
  Done: Holidays and leave types page, Leave page and a leave panel on each employee's page.
  Holidays entered by HR; a past one is kept (database). Leave types with the Shop and
  Office Employees Act rules (annual: none in the joining year, then 14/10/7/4 by the
  quarter of joining, then 14; casual: half a day per completed month in the joining year,
  then 7), maternity and no-pay leave without a balance; carry-forward only up to a
  maximum set per type (default none). "Grant the year's leave" gives each year's days
  (again only adds what is missing); adjustments need a reason; grants never change
  (database). Leave days are Monday to Saturday, not holidays; half days; never across the
  new year; no overlaps; never more than the balance. HR records leave from the approved
  leave form; leave applied for (self-service, P2B-11) is approved by HR or the section's
  supervisor, never by the person who applied or entered it; leave is cancelled with a reason, never deleted or
  changed (database). Attendance leave codes use the same service (P2B-04).

- [x] **P2B-04 Attendance from Excel**
  The template of the owner's decision (employee number, date, time in, time out, shift,
  leave code, remarks); checked first, every refused row listed; HR confirms the month
  before payroll uses it. Late arrivals, short leave and no-pay days worked out by the
  rules of P2B-05.
  Done: Attendance page. The template's sheet is checked first, all or nothing, every
  refused row listed (unknown employee or shift or leave code, bad dates and times, only one
  of the times, duplicates, future dates, dates outside employment, confirmed months); a
  later sheet replaces the same days while the month is open; the file's fingerprint is
  kept. Each day keeps the minutes worked (less the shift's break; night shifts past
  midnight), late and left early against the shift. A leave code without times is a day of
  leave, with times half a day. The month per division shows working days, days and hours
  worked, late, leave and absent days. HR confirms a division's month after it ends: the
  leave codes are recorded as leave (balances checked, all or nothing, a sheet that
  disagrees with recorded leave is refused) and the days never change (database).
  Reopening needs a reason and cancels the leave taken from the sheet. Grace periods, short
  leave, overtime and no-pay are worked out from these minutes in P2B-05.

- [x] **P2B-05 Overtime and attendance rules**
  Normal hours per shift and day; overtime at the rates in force (e.g. 1.5 times on normal
  days, 2 times on holidays, as the owner confirms); night-shift and holiday rules; the
  monthly overtime hours per employee, checked by the supervisor's division.
  Done: Work rules and Overtime pages. Each division has dated work rules (normal day,
  grace for late arrival, short leaves a month and their length, overtime minimum and step,
  rates for working days, Sundays and holidays, hourly divisor for payroll); a new rule
  starts from a month whose attendance is not yet confirmed and never changes (database);
  a future rule can be withdrawn. From confirmed attendance: overtime beyond the shift's
  working minutes (or the normal day; half for a half day of leave), all minutes on
  Sundays and holidays at their rates (night shifts count on the day they start); short
  time = late beyond grace + left early, covered by short leave, the rest no-pay time;
  days absent and unpaid leave are no-pay days. The section's supervisor or the Director
  checks each employee's month (never the person who confirmed the attendance, nor the
  employee); the checked figures are kept as checked (database) and are what payroll pays;
  reopening attendance voids them.

## C. Payroll

The owner's answers of 5 Nov 2026 (questions below) came after P2B-01 to P2B-05 were built
and change some of them. P2B-15, P2B-16 and P2B-17 make those changes and come **before
P2B-06**, in this order.

- [x] **P2B-15 Pay period 21st to 20th**
  Salaries are for the 21st of one month to the 20th of the next and are paid on the last
  day of the month (owner, question 3): pay month November 2026 = 21 October to 20 November,
  paid 30 November. Attendance confirmation, the month summary, overtime, short-leave counts,
  no-pay and the supervisor's check work per **pay month** instead of calendar month.
  HR confirms a division's pay month after its last day (the 20th). The Attendance and
  Overtime pages show "Pay month Nov 2026: 21 Oct – 20 Nov"; the Excel template's example
  follows the period. The cut-off day is a dated company setting (default: the period starts
  on the 21st), not a constant. Work rules start from a pay month; the leave year stays
  the calendar year. The database rule that freezes
  confirmed days follows the period (a new migration replaces the calendar-month rule).
  Nothing is live yet, so no data is moved.
  Done: a pay month is named by the month it ends in and holds the 1st of that month
  (pay month November 2026 = 21 October to 20 November). The day it starts is a dated
  setting, "Pay period" on the Work rules page (HR keeps it; seeded: the 21st from January
  2024). A rule from pay month M says on which day of the month before M the period starts
  (1 = the calendar month); M ends the day before M+1 starts, so periods never overlap or
  leave a gap when the rule changes. A new rule is refused when its pay month or the one
  before it is confirmed in any division (that month's end would move); a rule never changes
  and is withdrawn only on the same condition (also in the database). The Attendance page
  (summary, confirmation, reopening, an employee's days, the upload's months) and the
  Overtime page (overtime, short leaves a month, no-pay, checks) work per pay month and show
  "Pay month Nov 2026: 21 Oct – 20 Nov"; the default is the last pay month that has ended. A
  pay month is confirmed after its last day. The database freezes confirmed days by the same
  pay months (a function `payroll_pay_month(date)` replaces the calendar month in the
  trigger). A work rule "from November 2026" is in force from 21 October and can be
  withdrawn until then. The leave year stays the calendar year. The template's example row
  is the first day of a pay month.

- [x] **P2B-16 Labour categories and leave per category**
  Each employee is **Shop and Office** or **Wages Board** (owner, questions 4 and 8). Leave
  entitlements by category: annual 14 (Shop and Office) or 7 (Wages Board); **casual and
  sick leave together 7** for both (CASUAL becomes "Casual and sick leave"); maternity as the
  law gives (checked against the current Shop and Office Employees Act and Maternity
  Benefits Ordinance when the task is built, not from memory). Short leave by category in
  the work rules: at most 2 a month of up to 1.5 hours; **paid** for Shop and Office;
  **unpaid** for Wages Board, each one deducting **a quarter of a day's pay**. Beyond 2 a
  month the time is not covered by short leave: the employee applies for casual and sick or
  annual leave, otherwise it is no-pay time. Wages Board annual leave: none in the year of
  joining, 7 a year from the first full year. Day rate = monthly pay ÷ 30 (follow-up
  questions 1 and 6).
  Done: each employee has a category, Shop and Office or Wages Board (Employees page, the
  employee's details and the Excel sheet's "Category" column; blank = Shop and Office for a
  new employee, unchanged for an existing one). Leave types may give Wages Board staff their
  own rule and days (blank = the same): ANNUAL is 14 by the quarter-of-joining rule for Shop
  and Office and, for Wages Board, a new rule "none in the year of joining, then the full
  days" with 7. CASUAL is renamed "Casual and sick leave", 7 for both (the first-year half
  day a month applies to both). Maternity leave, by the Shop and Office Employees Act and the
  Maternity Benefits Ordinance as amended by Acts No. 14 and 15 of 2018: 84 working days for
  each live birth (42 for a still birth), paid; a new "most days at a time" setting refuses
  more than 84 working days in one leave (HR records 42 for a still birth). Short leave: the
  work rules gain "Wages Board short leave paid" (default no); the Overtime page shows each
  Wages Board employee's unpaid short leaves, and the checked month keeps them (database) for
  payroll to deduct a quarter day each (P2B-06, day rate = monthly pay ÷ 30). Short time
  beyond the 2 short leaves stays no-pay time unless leave is recorded. Per-employee leave
  and short-leave settings come with P2B-17.

- [x] **P2B-17 Employee pay settings approved by the Director**
  Every employee's pay settings are entered by HR and take effect only when the Director
  approves them, for a new employee and for every change (owner, questions 5 to 8). One
  "pay settings change" per employee, approved through the approval engine (the Director,
  with a reminder); the person who prepared it never approves it (rule 5). It carries:
  pay amounts (P2B-02); the **attendance bonus** (default LKR 1,500, lost for the pay period
  when the employee is absent four half days in it, approved leave included, follow-up
  question 2); **up to four allowances** per employee; overtime settings that differ from
  the division's work rule (rates, normal hours, grace); leave entitlements that differ from
  the category's; which earnings count for EPF/ETF and APIT (component marks by default,
  follow-up question 7); the APIT setting (IRD tables by default); the gratuity settings,
  entered by the Accountant (follow-up question 9). A rejected or withdrawn change never takes
  effect; approved settings are dated and never changed (a change is a new approved
  setting). This replaces P2B-02's default that a raise needs no separate approval: pay
  amounts entered on the employee's Pay panel become effective only through an approved
  change (how existing amounts move into the change is decided and recorded with the task).
  "The Admin" in the owner's answers: the System Admin has no payroll access by design
  (segregation of duties), so the **HR and Payroll Officer** prepares and the Director
  approves (follow-up question 3; default).
  Done: on each employee's Pay panel HR prepares a **pay change**: the pay month it starts
  from, the reason, new amounts (blank = unchanged, 0 ends a component) with the employee's
  own EPF/ETF and APIT marks where they differ from the component's, and, if ticked, the
  employee's own settings (normal day, grace, the three overtime rates, annual and casual and
  sick leave days, APIT table primary or secondary; blank = the division's work rule or the
  category's leave, shown beside each box). The first change is marked "New employee" and its
  form starts the attendance bonus (ATTEND, renamed "Attendance bonus") at LKR 1,500.
  Components can be marked "Allowance" (seeded: FIXED, TRAVEL, INCENTIVE); a change that would
  leave more than four allowances is refused. Draft → sent to the Director (approval type
  "pay_change", reminder after 1 day; it also shows in his approvals) → approved, returned
  (back to a draft for HR to correct) or rejected; HR may withdraw it until it is decided;
  one open change per employee. Only on approval do the amounts and settings take effect:
  **decision recorded: `pay.add_rate` stays as the internal step the approval uses and HR
  can no longer enter or withdraw amounts directly** (the API for it is removed); amounts
  entered before keep their place. An approved amount or setting for a pay month that has
  not yet come is replaced by a later approved change for that month; one in force is
  refused (choose a later month). The database refuses any change to a decided pay change,
  to its amounts once it is sent, and to approved settings. The settings are used at once:
  normal day and grace in the overtime figures, leave days in the year's grant, EPF/APIT
  marks in the pay totals, overtime rates and the APIT table kept for the payroll run
  (P2B-06). Gratuity settings (entered by the Accountant, follow-up 9) come with the
  gratuity itself in P2B-07, where they are used.

- [x] **P2B-06 Monthly payroll run**
  HR prepares the **pay month** (P2B-15) from the approved pay settings (P2B-17): earnings;
  the attendance bonus unless forfeited; overtime from the checked figures × the hourly rate
  (pay ÷ the divisor); no-pay days and Wages Board short-leave quarter days × the day rate
  (monthly pay ÷ 30); a joiner's or leaver's part period (calendar days employed × monthly
  pay ÷ 30, never more than the month's pay); advances
  and loan instalments (P2B-10); EPF employee 8% and employer 12%, ETF 3% (dated rates) on
  the EPF-liable earnings; APIT from the dated IRD tables (the current 2026/27 tables,
  looked up, not from memory) and the employee's APIT setting; net pay. Each figure traces
  to its source (attendance, setting, rate). Draft → sent → Director approves (never the
  person who prepared it) → locked.
  Done: People and payroll → **Payroll**. HR prepares a division's pay month once HR has
  confirmed its attendance and every employee's overtime is checked (otherwise refused, with
  the employee numbers). Per employee, each figure with where it came from: the approved
  monthly amounts for the pay month (a joiner or leaver: days employed × amount ÷ 30, never
  more); amounts HR types in for the month (incentive, advance recovery; the payroll is worked
  out again); the **attendance bonus** lost when away four half days or more (absent days and
  approved leave, maternity leave excepted); **day rate** = monthly pay ÷ 30 and **hourly
  rate** = monthly pay ÷ the rule's divisor, monthly pay being the components marked "In the
  day rate" (new mark; seeded BASIC and FIXED); **overtime** = hours × hourly rate × the
  employee's own or the rule's rate; **no-pay** days × day rate, short time × hourly rate,
  Wages Board unpaid short leaves × a quarter day; no-pay reduces EPF and APIT earnings;
  **EPF** 8% / 12% and **ETF** 3% on EPF-liable earnings (dated rates, seeded from 2024);
  **APIT** from the dated IRD table of the employee's setting on taxable earnings including
  overtime; other deductions; **net**. APIT Table 01 is seeded from 1 April 2025 (relief
  150,000 a month; 6% / 18% / 24% / 30% / 36%; the IRD's 2025/26 tables apply to later years
  until new ones are issued; checked on the web on 6 Nov 2026). **Table 07 (secondary
  employment) is not seeded**: its rates could not be read from the IRD; the Accountant
  enters it on "APIT tables and EPF rates" (accounting area) before anyone is paid under it,
  and the payroll refuses until then. A table or rate in force never changes (database).
  Draft → sent to the Director (approval type "payroll", reminder after 1 day) → approved
  (locked: the database refuses any change), returned (draft) or rejected (prepared again);
  never approved by the person who prepared it. Sent only when every employee receives more
  than 40% of the basic salary (owner, follow-up 4). Once sent or approved, the month's
  attendance cannot be reopened; a pay change cannot start in a pay month with an approved
  payroll. The Accountant sees the totals only. Advances and loans themselves (P2B-10),
  posting and the bank file (P2B-07) and payslips (P2B-08) follow.

- [x] **P2B-07 Posting and paying**
  Approval posts: Dr salaries and wages per division and section, Dr employer EPF and ETF;
  Cr EPF payable, ETF payable, APIT payable, deductions payable, net salaries payable. A
  salary voucher for the net pay goes through the usual three approvals (no payment without
  the Director, rule 4; owner, question 9); the Cashier pays it on the last day of the month
  and the bank transfer file is produced in Commercial Bank's bulk transfer format (needed
  from the bank first, follow-up question 10). Gratuity: the Payment of Gratuity Act applies;
  each employee's gratuity settings are entered by the Accountant and approved by the
  Director (never less than the Act gives); provided for monthly by default (follow-up
  question 9).
  Done: when the Director approves a payroll it gets a number (series "payroll", PRyymmNN)
  and posts one journal entry dated the last day of the pay period: Dr Salaries and wages
  (6000, earnings after no-pay) and Dr EPF and ETF contributions (6010, 12% + 3%) in the
  payroll's division; Cr EPF payable (2140, 8% + 12%), ETF payable (2150), APIT payable
  (2130), Payroll deductions payable (2195, new) and Salaries payable (2160, the net). These
  accounts carry new system roles (migration accounting 0022). If an account is missing the
  approval is refused and nothing changes. The journal and reports open the payroll from the
  entry. **Paying**: the Clerk enters a salary voucher for the net, coded to Salaries
  payable; it goes through the Accountant and the Director like any voucher (rule 4, rule 6)
  and the Cashier pays it; the payroll page says so after approval. Split out of this task,
  as the owner's material is not here yet: the Commercial Bank file (P2B-18) and gratuity
  (P2B-19). Divisions only on the journal lines (journal lines carry no section).

- [ ] **P2B-18 Commercial Bank bulk transfer file**
  From an approved payroll, the bank's bulk transfer file of each employee's net pay to the
  salary account the Director checked (P2B-01), in Commercial Bank of Ceylon's format. Waits
  for the format from the bank (owner, follow-up 10: requested).

- [ ] **P2B-19 Gratuity settings and monthly provision**
  Each employee's gratuity settings (service counted from, months' pay per year of service,
  never less than the Payment of Gratuity Act No. 12 of 1983: half a month's wage per
  completed year after 5 years) entered by the Accountant and approved by the Director
  (owner, follow-up 9). Each approved payroll provides for gratuity monthly (Dr gratuity
  expense, Cr provision for gratuity), by default as the change in the liability worked out
  per employee; the method is confirmed with the auditors (LKAS 19). Paid on leaving.

- [x] **P2B-08 Payslips**
  A payslip per employee (PDF), emailed or printed, in English first (Sinhala and Tamil with
  the rest of the system later); year-to-date figures.
  Done: from an approved payroll only. An A5 page per employee: company, PAYSLIP and the pay
  month, the pay period and payroll number; employee, designation, division, category, EPF
  number, the salary account (last four digits only); every earning and deduction as the
  payroll worked it out, each with where it came from; NET PAY; the company's EPF 12% and
  ETF 3% (not deducted); year to date for the year of assessment (from 1 April: earnings,
  EPF 8%, APIT, net) from the approved payrolls up to this one. On the payroll page HR and the
  Director print all payslips in one PDF or one employee's; HR emails them to every employee
  with an email address (owner, question 11), listing who has none (print theirs). **An
  emailed payslip is locked with the employee's NIC number as its password** and is not
  copied to the company's copy mailbox (new option of document email); every email is
  recorded with the PDF's fingerprint; the message is a new document email kind "Payslip"
  the Admin can edit. Printing is recorded in the audit log. The self-service page comes with
  P2B-11.

- [x] **P2B-09 Statutory returns**
  EPF monthly return (C form) and its contribution file, ETF return, the APIT monthly
  schedule and the year-end certificates (T-10); each from the approved payrolls, with
  Excel and PDF.
  Done: People and payroll → **Statutory returns** (HR and the Director; only the
  employees of one's divisions). From the approved payrolls only, for the whole company: the
  **EPF C form** per pay month (name, NIC, EPF member number, total earnings, 8%, 12%, total;
  a member without an EPF number is listed); **ETF monthly contributions** (earnings, 3%);
  the **ETF half-year return** (each member's ETF for each of the six months and the total);
  the **APIT monthly schedule** (taxable earnings, APIT deducted, the IRD table used); **APIT
  for the year of assessment** (April to March by pay month) and the **year-end
  certificates** as one PDF, a page per employee (to be checked against the IRD's current
  certificate form before issuing). Each shown on the page and downloaded as Excel or PDF;
  a division whose payroll for the month is not approved is named under the return. The
  company's **EPF and ETF employer numbers** are new fields on Settings → Company and print on
  the returns. Payment deadlines are noted (EPF/ETF by the last working day of the next
  month, APIT by the 15th). **Not built: the electronic upload files** (EPF e-return text
  file, ETF file): their official layouts could not be found published; they follow when
  the owner or the Accountant brings the layouts (the EPF e-return is required from 50
  employees; SML has 30–50). Figures are to the cent, as in the payroll; if the EPF
  Department wants whole rupees per member, that is a change to the payroll's rounding.

- [x] **P2B-10 Salary advances and loans**
  An advance or loan recorded and approved (by the Director), paid through a voucher, and
  recovered from payroll; balance per employee. **Advances**: one or more paid during the pay
  period and deducted from that period's salary (owner, question 3; limits and approval in
  follow-up question 4). **Loans**: recovered in equal monthly instalments over the loan
  period, e.g. LKR 240,000 over 24 months = LKR 10,000 a month (owner, question 12); interest,
  limits and a leaver's balance as follow-up question 5 settles. Every advance and loan is
  approved by the Director; a loan carries the interest agreed when it is given. **The
  employee always receives more than 40% of the basic salary at month end**: an advance or
  loan that would leave less is refused, and the payroll run checks it again.
  Done: People and payroll → **Advances and loans**. HR records an advance (recovered in
  full in its pay month) or a loan (amount, interest agreed, months; instalment = (amount +
  interest) ÷ months; the last one takes what is left), from the current pay month or later,
  with a reason; draft → sent to the Director (approval type "staff_credit", reminder after
  1 day) → approved and numbered (SLyymmNN), returned or rejected; HR may withdraw it until
  decided; never approved by the person who recorded it; a decided one never changes and
  none is deleted (database). Refused when sent or approved if the first recovery would leave
  the month's net pay (pay in force less EPF 8%, monthly deductions and recoveries already
  due; before overtime and APIT) at 40% of the basic or less. The **payroll** recovers each
  approved advance and loan with a balance as a deduction linked to it ("Salary advance",
  "Loan instalment", with the balance after); a recovery that would take the net to 40% of
  the basic or below is reduced and the rest waits for the next month (so the payroll is
  never blocked by it); a leaver repays the whole balance as far as that allows. **Posting**:
  the recoveries credit Staff loans and advances (1330) and, for a loan with interest, the
  interest share (interest ÷ (amount + interest) of each instalment) credits Interest earned
  (7000) in the division; both accounts get system roles (accounting 0023). **Paying out**:
  the Clerk enters a voucher coded to Staff loans and advances (three approvals as usual).
  Balances count recoveries in approved payrolls only. The seeded ADVANCE and LOAN pay
  components stay for amounts typed in by hand but are no longer needed for this.

## D. Self-service and links

- [x] **P2B-11 Employee self-service (phone)**
  Each employee signs in to see their payslips, EPF and ETF contributions, APIT
  certificates, leave balance and attendance; applies for leave (approved by their
  supervisor); asks to change personal or bank details, which HR approves (bank details
  with the second check).
  Done: a new page "My pay and leave", in the menu for everyone signed in, shows only the
  signed-in person's own records, whatever their role: the employee whose record HR linked
  to their sign-in (new field "Sign-in email" on the employee page; blank removes the link).
  Payslips of the approved payrolls (PDF, not password-locked as the person is signed in;
  printing recorded), each month's EPF 8% and 12%, ETF 3% and APIT, the APIT certificate
  of the year of assessment; the year's leave balances; applying for leave (not no-pay) and
  withdrawing an application not yet decided; attendance from the previous pay month. Leave
  applied for is approved or rejected (with a reason) by a **supervisor of the employee's
  section** or by HR, never by the person themselves; supervisors see their sections'
  applications on the same page, even if their own sign-in is not linked to an employee.
  Asking to change personal or bank details moved to P2B-20.

- [ ] **P2B-20 Employees ask to change their details**
  On the self-service page an employee asks to change their phone, address, email or salary
  account; HR approves the change (never the employee themselves), and a new salary account
  still needs the Director's check (P2B-01) before any payment uses it.

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
   - Owner, 5 Nov 2026: 30 to 50 employees now, growing to about 200 by the end of next
     year. Built for a few hundred; nothing assumes a small number.
2. **Current payroll.** How is payroll done today (an Excel sheet, a payroll program, the
   bank)? Can its employee list and this year's totals be exported to Excel? (P2B-14)
   - Owner, 5 Nov 2026: Excel. P2B-14 reads the payroll sheet (a sample with names and
     amounts masked is needed then; business data stays out of the repository).
3. **Pay frequency.** Is everyone paid monthly, or are some (casual or daily paid) paid
   weekly or daily? *Default: monthly for all.* (P2B-06)
   - Owner, 5 Nov 2026: everyone is paid monthly. The pay period is the 21st to the 20th of
     the next month and the salary is paid on the last day of the month (30 Nov 2026 pays
     21 Oct to 20 Nov 2026). Some employees get an advance during the month, deducted from
     the month-end salary. → P2B-15 (pay period), P2B-10 (advances).
4. **Law that applies.** Are factory staff under a Wages Board, and office staff under the
   Shop and Office Employees Act? The overtime and leave rules follow from this. (P2B-03,
   P2B-05)
   - Owner, 5 Nov 2026: factory staff are under a Wages Board. The Wages Board's rates and
     rules are dated master data (rule 11); which trade's Wages Board (and its current
     decision) is confirmed with the Accountant (follow-up question 6). Each employee gets a
     labour category, Shop and Office or Wages Board → P2B-16.
5. **Overtime.** Normal hours per day and week, and the overtime rates (normal day,
   Saturday, Sunday, holiday, night)? *Default: 8 hours a day, 45 a week; 1.5 times on
   normal days, 2 times on Sundays and holidays.* (P2B-05)
   - Not answered by P2B-05: the default is used for every division from January 2024,
     with 10 minutes' grace, 2 short leaves of up to 90 minutes a month, overtime from 30
     minutes in 15-minute steps, and an hourly rate of monthly pay ÷ 240. Overtime is
     counted per day (no separate 45-hour weekly test). HR enters the Wages Board's rules
     as a new rule from a month on the Work rules page.
   - Owner, 5 Nov 2026: keep these defaults, but they can be set for each employee, and the
     Director approves every change and every new employee. → P2B-17 (per-employee overtime
     settings in the approved pay settings; the division's work rule stays the default).
6. **Allowances and deductions.** The list of allowances (budgetary relief allowance,
   attendance, travelling, meal, shift…) and deductions (welfare, union, insurance…), and
   which count for EPF. (P2B-02)
   - Not answered by P2B-02: a starting list is loaded (see P2B-02) and HR changes it on
     the Pay components page with the Accountant. The budgetary relief allowance ended on
     31 March 2025 (now in the basic wage), so it is not a separate component.
   - Owner, 5 Nov 2026: employees get an **attendance bonus**, lost if absent four half
     days; default LKR 1,500. Some employees get other allowances, **at most four per
     employee**. All set per employee, and the Director approves every change and every new
     employee. → P2B-17, P2B-06. Which allowances count for EPF/ETF and APIT was not answered:
     follow-up question 7 (the Accountant); until then basic, fixed and attendance
     allowances count for EPF (the P2B-02 marks).
7. **APIT.** Confirm with the tax advisor that APIT is deducted from the tax tables issued by
   the Inland Revenue for 2026/27, and whether any employee has a different tax
   arrangement. *Default: the IRD tables, entered as dated master data.* (P2B-06)
   - Owner, 5 Nov 2026: follow the IRD's guidance by default; settable per employee, and
     the Director approves every change and every new employee. → P2B-06 (dated IRD
     tables), P2B-17 (the employee's APIT setting).
8. **Leave.** Leave types and days a year (annual, casual, sick, maternity…), and whether
   unused leave carries forward. *Default: as the law that applies, no carry-forward.*
   (P2B-03)
   - Not answered by P2B-03: the default is used (Shop and Office Employees Act rules, no
     carry-forward, Saturday a working day). The Wages Board's leave days for factory staff
     are entered as their own leave types once confirmed with the Accountant.
   - Owner, 5 Nov 2026: defaults per category, settable per employee, the Director approves
     every change and every new employee. **Shop and Office**: annual 14; casual and sick
     together 7; maternity as the government's rules; short leave 1.5 hours twice a month,
     paid. **Wages Board**: annual 7; casual and sick together 7; maternity as the
     government's rules; short leave 1.5 hours twice a month approved but unpaid, a quarter
     day's salary deducted for each; more than twice → apply for casual/sick or annual
     leave. → P2B-16, P2B-17.
9. **Approval.** The Director approves the payroll, and the salary payment then goes through
   the normal voucher approval (Clerk, Accountant, Director). Is that right, or should the
   approved payroll be enough for the payment? *Default: both, as rule 4 requires.* (P2B-07)
   - Owner, 5 Nov 2026: yes, both.
10. **Bank.** Which bank pays the salaries, and does it take a bulk transfer file (please ask
    the bank for its file format)? (P2B-07)
    - Owner, 5 Nov 2026: Commercial Bank of Ceylon PLC. The bulk transfer file is built to
      the format Commercial Bank gives for its corporate bulk payments (asked from the bank
      before P2B-07), kept as a column mapping like the statement templates.
11. **Payslips.** Emailed, printed, or only on the self-service page? *Default: on the
    self-service page and emailed to those with an email address; printed on request.*
    (P2B-08)
    - Owner, 5 Nov 2026: yes, the default.
12. **Advances and loans.** Does the company give salary advances or loans, and how are they
    recovered? (P2B-10)
    - Owner, 5 Nov 2026: **loans** are recovered in equal monthly instalments over the loan
      period (LKR 240,000 over 24 months = LKR 10,000 a month). The answer on **advances**
      repeats the allowances answer (looks pasted by mistake); question 3 says advances are
      paid during the month and deducted at month end. Confirmed in follow-up question 4.
13. **Gratuity.** Should the gratuity liability (employees with 5 years or more) be
    provided for in the accounts each month or at year end? *Default: at year end, from a
    report.* (P2B-07)
    - Owner, 5 Nov 2026: follow the government's guidance. The Payment of Gratuity Act No. 12
      of 1983 applies (to be checked against its current text when P2B-07 is built). For the
      accounts, the accounting standard LKAS 19 expects the liability to be provided for; a
      monthly provision is recommended, confirmed with the auditors (follow-up question 9).

### Follow-up questions (sent 5 Nov 2026)

Where no answer comes, the default in italics is used and recorded, and can be changed.

1. **Day rate** for a no-pay day and the Wages Board quarter-day deduction: monthly pay ÷ 30,
   ÷ 26, or ÷ the working days in the period? Which parts of pay? *Default: (basic + fixed
   allowances) ÷ 30.* (P2B-16, P2B-06)
   - Owner, 5 Nov 2026: monthly pay ÷ 30. Which parts of pay was not answered: *default
     basic + fixed allowances*.
2. **Attendance bonus**: does approved leave count as absence? Late arrivals or short leave?
   All or nothing? *Default: only absence without approved leave counts; four half days (two
   full days) in the pay period → no bonus for that period.* (P2B-17, P2B-06)
   - Owner, 5 Nov 2026: yes, approved leave counts as absence too. Not answered: late
     arrivals and short leave do not count; all or nothing (defaults). Recommended and used
     as the default unless the owner says otherwise: maternity leave and holidays do not
     count (taking the leave the law gives should not cost a bonus).
3. **"The Admin"**: the HR and Payroll Officer enters pay settings and the Director approves
   (the System Admin has no payroll access by design). *Default: yes.* (P2B-17)
   - Owner, 5 Nov 2026: yes, the HR and Payroll Officer enters pay settings.
4. **Advances**: paid during the pay period and deducted in full from that period's salary?
   A limit? Who approves? *Default: deducted in full in the same period; paid through a
   payment voucher (all three levels).* (P2B-10)
   - Owner, 5 Nov 2026: every advance is approved by the Director. **The employee must
     receive more than 40% of the basic salary at month end**: an advance or loan that would
     leave less is refused. Not answered: deducted in full in the same period; paid through
     a payment voucher, all three levels (defaults).
5. **Loans**: interest-free? A maximum or approval rule? A leaver's balance? *Default:
   interest-free; the Director approves; the balance is deducted from the final salary as
   far as it goes.* (P2B-10)
   - Owner, 5 Nov 2026: the interest is agreed when the loan is given (recorded on each
     loan, 0 for none); every loan is approved by the Director. Not answered: a leaver's
     balance is deducted from the final salary as far as it goes (default).
6. **Wages Board annual leave 7 days**: the same first-year rule as Shop and Office (by the
   quarter of joining), or 7 days from the first full year? Which Wages Board (trade)?
   (P2B-16)
   - Owner, 5 Nov 2026: 7 days from the first full year by default (none in the year of
     joining); settable per employee, the Director approves. The trade's Wages Board was not
     named.
7. **EPF and APIT**: which allowances count for EPF/ETF and which are taxable? (the
   Accountant; today basic, fixed and attendance allowances count for EPF) (P2B-06)
   - Owner, 5 Nov 2026: set per employee, the Director approves. Each component keeps its
     EPF/APIT marks as the default; an employee's setting overrides them. The law decides
     what counts for EPF and APIT, so the Accountant confirms the defaults and any override.
8. **Joiners and leavers in the middle of a period**: *Default: pay × days employed in the
   period ÷ days in the period.* (P2B-06)
   - Owner, 5 Nov 2026: day rate = monthly salary ÷ 30. A part period pays calendar days
     employed × monthly pay ÷ 30, never more than the monthly pay.
9. **Gratuity in the accounts**: a monthly provision (LKAS 19) or at year end? (the
   auditors) (P2B-07)
   - Owner, 5 Nov 2026: gratuity settings per employee, entered by the Accountant, the
     Director approves. Never less than the Payment of Gratuity Act gives. Default (not
     answered): a monthly provision.
10. **Commercial Bank bulk transfer file**: the format, from the bank. (P2B-07)
    - Owner, 5 Nov 2026: requested from the bank.
