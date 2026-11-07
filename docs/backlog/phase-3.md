# Backlog — Phase 3 (production)

Production in both divisions (spec 7): the moulding plant (repetitive production by machine
and shift) **first**, then the machining workshop (make-to-order job shop by job card), then
quality, OEE and job profitability (spec 8.2 roadmap). Same rules as before: work top to
bottom, one task per pull request, and a task is done when every acceptance criterion is a
passing test (or, for pure UI items, checked by the owner).

```
Masters: moulds, reason codes, routings, BOMs, cost rates
Moulding: production order → plan (mould × machine × shift) → supervisor shift report
     → Production Manager approves → finished stock in, resin backflushed, shot count, order cost
Machining: sales order line → job order (routing + BOM copied) → material issue → job cards (QR)
     → operations entered by scanning → subcontract out and back → inspection → completion
Both: order cost entries → WIP → finished goods → cost of sales; live profitability; OEE; reports
```

**Already built, used here:** divisions, sections (with supervisors and section type) and
machines with the moulding fields and dated machine rates (3A.1); shifts, roster patterns,
crews and roster assignments (3A.2); items, stores, stock movements at weighted average cost
by lot, stock issues, counts and adjustments, WIP and finished goods accounts (Phase 2);
goods receipt, incoming QC with inspection plans (Phase 1.6); sales orders with delivery
schedules, delivery notes and tax invoices (Phases 1.5, 2); quotations with their costing
sheet and the material, machine and costing rate tables (Phase 1.5); payment vouchers;
fixed assets with the mould shot count (P2-19); the approval engine, number series, journal,
audit log, report builder; the roles Production Planner, Production Supervisor and
Production Manager with the areas Production planning, Shop-floor entry, Production
approvals and Job profitability (P0); payroll's labour cost per hour per section (P2B-13).

**Rules carried over:** quantities and rates are `Decimal` with explicit precision (rule 1);
a supervisor enters data only for the sections assigned to them, and only within the shift
and its grace period (spec 7.4); submitted reports are locked and only approved data moves
stock, shot counts and costs; nobody approves their own report (rule 5); machines, moulds,
routings and BOMs with history are deactivated or made obsolete, never deleted (rule 9);
rates are dated (rule 11); a night shift belongs to the date it started.

Status: `[ ]` to do · `[x]` done

---

## A. Masters

- [x] **P3-01 Moulds**
  Mould master (spec 7.1): code, name, part(s) it makes with cavities per part (a family
  mould makes several parts), standard cycle time, shot and runner weight, required tonnage
  and size, compatible machines, owner (company or customer), the fixed asset it is (P2-19,
  company moulds), shot count and preventive maintenance interval in shots, status. Warning
  when a mould is set against a machine too small for it (tonnage, shot weight, tie-bar
  spacing, mould height and thickness). Admin page with Excel import and export like
  3A.1; QR label per mould.
  Done: a new `production` app; the Production Planner, Production Supervisor and
  Production Manager roles switched on. **Moulds** page (Production → Moulds; Production
  planning area, kept by the Planner and the Admin): code, name, division (IM by default),
  parts with cavities (a family mould lists several), owner (company, or a customer's: then
  the customer, and never a company asset), the fixed asset of a company mould (optional:
  none is in the register yet), standard cycle time (s), shot weight with the runner and
  runner weight (g), clamping force needed (t), width, height and closed thickness (mm),
  compatible moulding machines, maintenance interval in shots, shot count, status (active,
  under maintenance, retired), notes. **Fit warnings** (never refusals) per compatible
  machine: clamping force, shot weight, maximum mould thickness and height, tie-bar spacing
  either way round; an unknown measure is not checked. Excel export and import (checked
  first, all or nothing), QR labels (100 x 50 mm, the code in the QR). The code is fixed
  once a production document uses the mould, and a used mould is retired, never deleted
  (database, as sections and machines). Items get a new category **Finished part**
  (Finished goods account 1230) for the parts the factory makes.

- [x] **P3-02 Reason codes and production settings**
  Reject reasons and downtime reasons per division (spec 7.1, 7.4: breakdown, mould change,
  setup, power failure, no material, no operator, planned maintenance), each marked planned
  or unplanned for OEE; added and deactivated by the Admin. **Production settings page**
  (owner: limits set later by an authorised person in a control panel, not in code): the
  entry grace period after a shift (**4 hours**, owner), reject % alert limit (5%), cost
  overrun alert % (10%), minimum margin (the quotation's). Changing a setting is recorded
  and dated (rule 11).
  Done: Settings → **Production settings** (the Admin, who manages Settings). Reasons per
  division and kind with code, name, order, active, and for downtime planned or unplanned
  (only downtime can be planned: database). Starting lists: downtime for IM and WS
  (breakdown, setting up, power failure, no material, no operator, waiting for quality
  check, planned maintenance and nothing planned as planned stops; mould change for IM);
  rejects for IM (short shot, flash, sink, burn, warpage, colour, contamination, flow lines,
  start-up shots, other) and WS (out of dimension, surface finish, material defect,
  setting-up piece, tool breakage, other). A used reason keeps its code and is deactivated,
  never deleted (database). **Limits** dated from 1 Jan 2026 with the owner's values (4
  hours, 5% rejects, 10% overrun, the quotation's margin); a change applies from today or a
  later date with a reason, a future change can be replaced until its date, a setting in
  force never changes (database); `reasons.setting_on(day)` gives the limits for a shift or
  order date.

- [x] **P3-03 Routings**
  For machined parts (spec 7.1): ordered operations, each with section or machine type,
  standard setup time and run time per piece, and whether it is subcontracted (supplier,
  standard cost). Revisions linked to the drawing revision; the Production Planner prepares,
  the Production Manager approves; copy a routing; Excel import and export.
  Done: Production → **Routings**. Operations numbered 10, 20 ...: each in a section (the
  machining method, e.g. M-LAT Manual Lathe) and optionally one of its machines (the section
  then follows the machine), with setup minutes per batch and run minutes per piece; or sent
  out to a supplier at a cost per piece (database: a section or a supplier). Revisions:
  the Planner drafts (new, a new revision copied from the one in force, or a copy of another
  part's), sends it, the **Production Manager approves** or sends it back with a reason
  (approval engine "routing", no fixed final role so the Admin can route it to the Director
  if nobody holds the role; never the preparer); approval makes the earlier revision
  obsolete. One routing in force and one open draft per part; approved and obsolete
  routings and their operations never change and are never deleted (database). Totals per
  routing (setup, run, subcontract cost). Excel export (one row per operation) and import
  (each part a draft, all or nothing).

- [x] **P3-04 Bills of materials**
  Spec 7.1B in full: BOM per manufactured item (finished part, sub-assembly, mould, tool)
  for one unit or a batch; lines for raw material, masterbatch and additives (% of resin),
  bought-out parts, sub-assemblies (multi-level), subcontract services and packing, each
  with unit, scrap or yield %, the operation it is used at, issue method (manual or
  backflush) and customer-supplied flag. Machining calculator (stock size, cut length,
  allowances → pieces per bar or plate, weight per piece); moulding calculator (part weight
  + runner over cavities + reject allowance → resin per piece; masterbatch %; maximum
  regrind %); family moulds as one BOM with several outputs. Revision, effective date,
  status Draft → Approved (Production Manager) → Obsolete. Copy, compare two revisions,
  Excel import and export, where-used, standard cost rolled up through all levels.
  Done: Production → **Bills of materials**. Kinds machining, moulding and general; a base
  quantity (one unit or a batch; a moulding BOM is per 1000 pieces or, for a family mould,
  per shot). Lines: raw material, masterbatch, bought-out part, sub-assembly (its own BOM,
  never in a loop), subcontract service (supplier and cost) and packing, each with
  quantity, scrap %, operation number, manual or backflush issue and customer-supplied.
  Machining calculator: leave the quantity blank and give the cut length (plus bar length,
  facing and saw cut): length per piece, pieces per bar and the stock per piece (kg from
  the item's kg per metre, or metres). Moulding calculator: shot weight from the mould's
  parts (cavities × part weight) and runner, reject allowance → resin per piece;
  masterbatch as % of resin; maximum regrind %; family moulds list several parts. Draft →
  sent → **Production Manager approves** (approval engine "bom", never the preparer) →
  the earlier revision becomes obsolete; approved BOMs and their lines never change
  (database). New revision, copy to another part, compare two revisions, where-used, Excel
  export and import (all or nothing). Standard cost per unit: materials at their current
  stock cost, sub-assemblies through their own BOMs, services at their cost,
  customer-supplied at 0, plus machine time from the routing at the machine-hour rates;
  anything without a cost is listed rather than guessed. Overhead and labour rates come
  with P3-05.

- [ ] **P3-05 Production cost rates**
  Dated rates (rule 11), maintained by the Accountant: labour rate per section (by default
  the latest approved payroll's labour cost per hour, P2B-13, which the Accountant accepts
  or overrides), overhead rate per machine hour (0 until set; P3-23 later works it out from
  past data), regrind credit value per kg (**100% of the original material's cost**, owner;
  regrind is reused in the same part and in other parts), mould
  amortisation per shot for company moulds (mould cost ÷ expected life in shots). Machine
  hourly rates already exist (3A.1).

## B. Moulding (first)

- [ ] **P3-06 Moulding production orders**
  A production order (spec 7.7): part, quantity, due dates, from a sales order line's
  delivery schedule or to replenish stock; numbered from the number series; the approved
  BOM copied on release (later BOM changes never alter it). Material requirements: order
  quantity × BOM against stock and open purchase orders gives a shortage list and suggested
  purchase requests (which follow their normal approval). Statuses Draft → Released →
  Completed → Closed; where-used and open orders per part.

- [ ] **P3-07 Production plan**
  Which mould runs on which machine on which shift, for a date range (spec 7.3), from the
  production orders and the roster; drag or pick; warnings for a mould too big for the
  machine, a machine planned twice, a mould on two machines, a shift with no crew, and
  material short. The planned quantity per shift from cycle time × cavities × planned time.
  Shown to the supervisors on their entry page.

- [ ] **P3-08 Moulding shift report (supervisor)**
  Phone and tablet page (spec 7.4) for the sections assigned to the supervisor: per machine,
  the mould, material batch, shot counter at start and end, rejects by reason, operator;
  downtime log; material issued, returned and regrind generated; manpower (operators per
  machine, overtime hours); shift summary, then Submit. The system works out good quantity
  (shots × cavities − rejects), actual cycle time and material per good piece. Checks: shot
  counters never go down, rejects never exceed shots × cavities, times on one machine never
  overlap, entry only during the shift and the grace period. Large buttons, number pads,
  QR scanning of machines, moulds and material batches. Submitted reports are locked.

- [ ] **P3-09 Approving shift reports and corrections**
  The Production Manager approves or returns each submitted report (never their own).
  Approval: good quantity into finished stock, resin, masterbatch and packing backflushed
  for good and rejected quantity at their lot cost, regrind into stock at its credit value,
  the mould's shot count updated, costs posted to the production order (P3-16). After the
  grace period (4 hours) a change is a correction request approved by the Production
  Manager, the Director, or a person the Admin gives that authority with the Director's
  approval (owner, 7 Nov 2026); never the person who asked; the original stays on record.
  SML has a Production Manager (owner); the Director approves only while nobody holds the
  role.

- [ ] **P3-10 Mould maintenance**
  Preventive maintenance due when the shot count reaches the interval: alerts to the
  Production Manager, a list of moulds approaching it; maintenance records (planned or
  repair, date, work done, cost, by whom); repair history per mould. A repair done by the
  workshop is an internal job (P3-15).

## C. Machining

- [ ] **P3-11 Job orders and material issue**
  A job order from a sales order line (part, drawing revision, quantity, due date) or an
  internal job (mould making or repair, tools); the approved routing and BOM copied and
  editable per job; numbered from the number series. Stores issues material against the
  job by lot; issuing more than the BOM allows needs a reason and the Production Manager's
  approval; returns credited.

- [ ] **P3-12 Job cards and operation entry**
  A printed job card per operation with a QR code (spec 7.2), travelling with the parts. The
  supervisor scans it and enters operation, machine, operator, start and end, quantity
  completed, rejected (reason) and for rework. Checks: completed never exceeds what the
  previous operation released; no overlapping times on a machine. Time per piece against
  standard; quantity available for the next operation. Reports approved as in P3-09.

- [ ] **P3-13 Subcontract operations**
  Parts sent out to a supplier for an operation and received back against the job (with
  the quantity checked), and the supplier's bill coded to the job: a new optional job or
  production order field on voucher lines and supplier invoice lines, filled by the
  Accountant (spec 7.7).

- [ ] **P3-14 Inspection on jobs**
  First-article, in-process and final inspection against the job with measurements, using
  the inspection plans of Phase 1.6 (parameters, limits); a failed inspection holds the job
  until the Production Manager decides (rework, scrap, accept under deviation).

- [ ] **P3-15 Mould making and inter-division transfers**
  A workshop job for a new company mould is capitalised to the mould's fixed asset; a
  repair is charged to the Plastic Injection Moulding division, both through an
  inter-division transfer (spec 3.1, 7.3) at cost.

## D. Costing and profitability

- [ ] **P3-16 Order costs and work in progress**
  Every approved cost posts an order cost entry (spec 7.7: material by lot, machine time,
  labour, setup and mould change, subcontract, direct expenses, rejects, mould
  amortisation, overhead) and the ledger: open orders' costs in Work in progress per
  division; on completion to finished goods, then cost of sales when invoiced. Month-end
  WIP report reconciled with the WIP account; machine time charged to no order reported as
  unabsorbed overhead. On the month-end checklist.

- [ ] **P3-17 Live order profitability**
  For every order: estimate (from the accepted quotation), actual to date, forecast at
  completion, forecast margin, % complete, red/amber/green. Order dashboard with filters;
  drill-down to every cost line and its source document; alerts to the Production Manager
  and Director (cost overrun, margin below minimum, reject % over limit); daily snapshot of
  each open order; moulding view per machine and mould (cycle time, material per good
  piece, rejects, margin per 1,000 pieces).

- [ ] **P3-18 Closing an order and variances**
  Closed when the last quantity is delivered; final report of estimate against actual by
  element with the variances (material price and usage, machine time, setup, rejects,
  subcontract and direct expenses). Closed orders feed the quotation rate tables: average
  actual cycle and setup times and material usage per part.

## E. Reports and the shop floor

- [ ] **P3-19 OEE**
  Per moulding machine and shift, day, month: availability (run time ÷ planned time from
  the roster; off days and planned stops not counted as lost), performance (standard
  cycle ÷ actual), quality (good ÷ total); OEE = A × P × Q. Trend and comparison by machine.

- [ ] **P3-20 Production reports**
  Spec 7.6: daily production by section, machine and shift; reject % by reason, part,
  mould and machine; downtime by reason and machine (Pareto); actual against estimated time
  and cost per job; on-time delivery; material consumption against standard and regrind
  use; moulds approaching maintenance. Production as a report builder source; profitability
  reports (spec 7.7: margin by order, customer, part, mould, division; estimate accuracy).

- [ ] **P3-21 Shop-floor languages and offline entry**
  The supervisor pages in Sinhala and Tamil (translations supplied or approved by the
  owner), and offline entry: saved on the device and synced when Wi-Fi returns, with a
  visible sync status and conflicts shown, never silently overwritten.

- [ ] **P3-23 Overhead and machine-hour rates from past data**
  Asked for by the owner (7 Nov 2026): the overhead rate and the rate per machine hour
  worked out from the company's own figures, for each machine and each machining method
  (milling, lathe, shaping and so on) and for the moulding machines: the period's overhead
  costs from the ledger (by division and, where coded, section), spread over the machine
  hours actually run (from the approved shift reports and job cards), with depreciation
  and power of each machine where known; shown against the rates in use, so the Accountant
  can adopt them as new dated rates (P3-05). Needs a few months of production data, so it
  comes after costing (P3-16).

- [ ] **P3-22 User acceptance testing and go-live**
  Scripts in `docs/uat-scripts.md` run by the supervisors, the Production Manager, stores
  and the Accountant; moulding live first, then machining.

---

## Questions for the owner

Answers are needed before the task named in brackets. Where no answer comes, the default in
italics is used and recorded, and can be changed.

1. **Order of work.** The roadmap says moulding first, then machining. Still right?
   *Default: moulding first (P3-06 to P3-10), then machining.* (all)
2. **Production Manager.** Who will it be? Until then, who approves shift reports, BOMs and
   corrections? *Default: the Director, as for deviations today.* (P3-04, P3-09)
3. **Moulds.** How many moulds, and are some owned by customers? Does each company mould
   already have a fixed asset record? *Default: customer moulds tracked for shots and
   maintenance but not costed; company moulds linked to their asset.* (P3-01)
4. **Make to order or to stock (moulding).** Are parts moulded only against customer
   orders, or also to keep stock? *Default: both; a production order either links to a
   sales order line or says "for stock".* (P3-06)
5. **Regrind.** Is regrind reused in the same part, sold or scrapped, and what is it worth
   per kg? *Default: reused up to each part's maximum %, credited at a value per kg the
   Accountant sets.* (P3-05, P3-08)
6. **Rates.** Labour rate per section from the payroll (P2B-13) once payroll runs; overhead
   rate per machine hour set by the Accountant. *Default: as stated; overhead 0 until the
   Accountant sets it.* (P3-05)
7. **Alerts.** Cost overrun %, minimum margin, reject % limit? *Default: 10% overrun, the
   quotation's minimum margin, 5% rejects.* (P3-02, P3-17)
8. **Shift entry grace period.** *Default: 2 hours after the shift ends.* (P3-02)
9. **Job cards.** Printed on plain A4/A5 with a QR code, or on a label printer? Do the
   supervisors have phones or tablets on the floor, and Wi-Fi everywhere? *Default: plain
   A5 paper; supervisors' own phones; offline entry built last (P3-21).* (P3-12, P3-21)
10. **Languages.** Who will supply or check the Sinhala and Tamil wording? *Default: the
    owner arranges it; pages are built in English first.* (P3-21)

### Answers (owner, 7 Nov 2026)

1. Moulding first, then machining: **yes**.
2. **SML already has a Production Manager**, who approves; the Director only while nobody
   holds the role.
3. The number of moulds will come later. **Some moulds belong to customers.** Company moulds
   are **not yet in the fixed asset register**. Default accepted.
4. **Both** to order and to stock. Default accepted.
5. Regrind is **reused in the same part and in other parts**, valued at **100% of the
   original material's cost**.
6. Rates as stated (overhead 0 until the Accountant sets it); the owner also wants **a
   module that works out the overhead and machine-hour rates from past data** per machine
   and machining method: added as **P3-23**.
7. Alerts as proposed; they must be **changeable later by an authorised person in a
   control panel** (P3-02).
8. Grace period **4 hours**; after it, a change is approved by the Production Manager, or
   the Director, or a person the Admin gives that authority with the Director's approval.
9. Job cards on **A5 or A4 paper**; supervisors' phones; **Wi-Fi most of the time**; the
   owner wants entry to **work without Wi-Fi and upload later**: yes, in P3-21 (built after
   the online pages).
10. Sinhala and Tamil: the owner arranges them; English first. Default accepted.

