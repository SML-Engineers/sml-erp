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
  quantity chosen by the Planner (one unit or a batch, e.g. 1000 pieces; for a family
  mould, shots). Lines: raw material, masterbatch, bought-out part, sub-assembly (its own BOM,
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

- [x] **P3-05 Production cost rates**
  Dated rates (rule 11), maintained by the Accountant: labour rate per section (by default
  the latest approved payroll's labour cost per hour, P2B-13, which the Accountant accepts
  or overrides), overhead rate per machine hour (0 until set; P3-23 later works it out from
  past data), regrind credit value per kg (**100% of the original material's cost**, owner;
  regrind is reused in the same part and in other parts), mould
  amortisation per shot for company moulds (mould cost ÷ expected life in shots). Machine
  hourly rates already exist (3A.1).
  Done: Production → **Cost rates**. Dated rates (from today or later, with a reason; a rate
  in force never changes or is deleted, a future one can be replaced or removed until its
  date: database). Kept by the **Accountant** (anyone who can enter in Accounting, checked
  in the service); the Production Planner, Manager and Director read them (area production
  planning). **Labour** per section (LKR an hour): the page offers the latest approved
  payroll's labour cost per hour for each section and the Accountant accepts it (one
  section or all) or enters another; the accepted rate remembers its payroll. A section
  with **fewer than three people** in the payroll is offered its **division's** rate, so a
  rate never shows one or two people's pay, and the payroll figures are shown only to the
  Accountant. With no rate, labour is listed as not costed. **Overhead** per machine hour
  for a section or for one machine (the machine's own rate beats its section's); **0 until
  set**. **Regrind** credit per kg: 100% of the material's stock average cost at the time,
  unless the Accountant sets a dated value per kg for the material (raw materials in kg or
  g). **Mould amortisation**: the mould's cost and expected life in shots give LKR a shot;
  **company moulds only** (database); 0 until entered. The BOM standard cost now adds,
  per unit, labour (routing run minutes × the section's labour rate) and overhead (run
  minutes × the overhead rate of the machine, or the average over the section's machines)
  to the machine time, plus the mould's amortisation (per shot over the pieces a shot
  makes; a family mould's BOM is per shot). Setup time is costed on the orders (P3-16);
  regrind credit is used when shift reports are approved (P3-09). Rates are kept in
  `production_costrate` (spec 7.7 `cost_rate`).

## B. Moulding (first)

- [x] **P3-06 Moulding production orders**
  A production order (spec 7.7): part, quantity, due dates, from a sales order line's
  delivery schedule or to replenish stock; numbered from the number series; the approved
  BOM copied on release (later BOM changes never alter it). Material requirements: order
  quantity × BOM against stock and open purchase orders gives a shortage list and suggested
  purchase requests (which follow their normal approval). Statuses Draft → Released →
  Completed → Closed; where-used and open orders per part.
  Done: Production → **Production orders** (number series "MO", e.g. MO26110001). A part
  (a finished item) and quantity, **for stock** (a due date) or **for a sales order line**
  (an open, non-tooling line of the same division; its delivery schedule becomes the due
  dates, and the line's orders, not cancelled, never add up to more than its quantity; the
  rest is made for stock). Due quantities add up to the order's. The **Production
  Planner** (production planning, Enter) makes, changes (drafts only), releases, completes
  and closes orders; the stores person and purchasing read them (menu also under Stores).
  **Release** needs the part's approved **moulding** BOM with a mould (not retired) and
  copies it to the order with each line's quantity for the whole order (quantity × (1 +
  scrap %) ÷ base); a part made in a **family mould** uses the family BOM by the shot
  (quantity ÷ the part's cavities, rounded up). The copy never changes, and later BOM
  revisions never alter it (database). **Materials:** per line, needed, in the division's
  main stores, ordered or requested (open purchase orders and purchase requests), needed by
  the other released orders, and the shortage; a draft shows what the BOM in force would
  need. On release the stores person and purchasing are notified of any shortage (new
  notification "A released production order is short of material"). **"Raise a purchase
  request"** (stores person or purchasing only) makes one draft purchase request for the
  bought materials short (raw material, masterbatch, bought-out, packing; never
  customer-supplied or sub-assemblies), needed by the first due date, which then follows
  its normal approval; what is requested counts as coming. **Statuses** Draft → Released →
  Completed → Closed, or Cancelled (draft or released) with a reason; never deleted, only
  forward, number and division fixed, part, quantity, due dates and BOM fixed once released
  (database). "Completed" is set by the Planner for now; P3-09 will count the good quantity
  from approved shift reports. **Where used**: the open orders making a part and the
  released orders needing a material; the list filters open orders per part.

- [x] **P3-07 Production plan**
  Which mould runs on which machine on which shift, for a date range (spec 7.3), from the
  production orders and the roster; drag or pick; warnings for a mould too big for the
  machine, a machine planned twice, a mould on two machines, a shift with no crew, and
  material short. The planned quantity per shift from cycle time × cavities × planned time.
  Shown to the supervisors on their entry page.
  Done: Production → **Production plan**: a grid per day (moulding machines × shifts) for
  1 to 14 days (the API allows up to 31). The **Production Planner** picks a released
  order, a date, a shift and a moulding machine (not retired), for the whole shift's
  working time or some minutes of it; the order brings its mould. A run is **moved** by
  picking another machine, shift or date (picking rather than dragging, which works the
  same on a phone), removed, or a whole day copied to another day. **Planned quantity** =
  whole shots in the planned minutes at the mould's standard cycle time × the part's
  cavities. **Warnings**, shown in red but never blocking: the mould too big for the machine
  (the 3A.1 sizes), machine or mould under maintenance, a machine planned twice on a shift
  or beyond the shift's working time, the mould on two machines in the same shift, no crew
  rostered on that shift in the machine's section (3A.2 roster), the order short of
  material, and the plan making more than the order. The released orders are listed with
  how much of each is planned. A plan is made for today or later; a past day's plan never
  changes, and only released orders are planned (database). Runs after today leave the
  plan when their order is completed or cancelled. **Supervisors** (shop floor) see the
  plan of their own sections, read only; `GET /production-plan/mine/` gives today's and
  tomorrow's runs for their entry page (P3-08).
  - Owner, 11 Nov 2026 (from his testing, T1): pressing Remove on a run while its Move box
    was open, then "Save the move", showed Django's "No PlanEntry matches the given query."
    Now removing the run closes its Move box, and a move or removal of a run that has gone
    (removed here or by someone else) says plainly "This run is no longer in the plan", closes
    the box and reloads the plan (English and Sinhala). Elsewhere in the API, Django's
    "No <record> matches the given query." is replaced by "This record is no longer here. It
    may have been removed; reload the page."
  - Owner, 11 Nov 2026 (from his testing, T4): a run planned on a machine whose section has
    no shift supervisor never reaches a work shift report, and the plan gave no sign of it.
    The plan board now marks such machines (`supervised` per machine: the section has an
    active supervisor), and the page says "No shift supervisor in section …: runs on this
    machine won't reach a work shift report." beside the machine and when it is chosen in
    the Plan or Move box (English and Sinhala). Planning there is still allowed.

- [x] **P3-08 Moulding shift report (supervisor)**
  Phone and tablet page (spec 7.4) for the sections assigned to the supervisor: per machine,
  the mould, material batch, shot counter at start and end, rejects by reason, operator;
  downtime log; material issued, returned and regrind generated; manpower (operators per
  machine, overtime hours); shift summary, then Submit. The system works out good quantity
  (shots × cavities − rejects), actual cycle time and material per good piece. Checks: shot
  counters never go down, rejects never exceed shots × cavities, times on one machine never
  overlap, entry only during the shift and the grace period. Large buttons, number pads,
  QR scanning of machines, moulds and material batches. Submitted reports are locked.
  Done: Production → **Shift report** (shop floor). A supervisor sees the shifts of **their
  own moulding sections** open for entry now (a night shift belongs to the day it starts)
  and starts or continues the report: one per section, day and shift. **Runs** per machine:
  production order (one tap from the shift's plan, which is listed at the top), material
  batch (a lot in the division's stock), operator (the section's employees), start and end
  time (HH:MM within the shift), shot counter at start and end, rejects by reject reason.
  The system works out **good quantity** = shots × the part's cavities − rejects, **actual
  cycle time** = run time less the machine's downtime in it ÷ shots (shown against the
  mould's standard), and, in the **shift summary**, good, made, rejects and reject %,
  downtime minutes by reason, material used (issued − returned) and grams per good piece,
  regrind made, people and overtime. **Downtime** per machine with a downtime reason;
  **material** issued and returned by batch, regrind by material; **manpower** per machine
  or for the section with overtime hours. **Checks:** shot counters never go down (within a
  run, and from the machine's previous run in any report), rejects never exceed shots ×
  cavities, times on one machine never overlap (runs, and downtime; also in the database),
  times within the shift, entry only from the shift's start to the end of the grace period
  (production settings), and only by a supervisor of the section. **Submit** (at least one
  run or downtime) locks the report (database) and marks the reasons used. The whole
  report is saved at once, ready for offline entry (P3-21). Large buttons and inputs,
  number pads (`inputMode`), and a **Scan** button for machines, moulds (picks the order
  using that mould) and batches using the browser's own barcode reader (Chrome on Android;
  no library); where a browser has none, a handheld scanner types into the field. The
  Production Manager and Planner read all reports of their divisions; supervisors their
  sections. The plan page now shows supervisors only their own sections' machines (fix to
  P3-07). Not yet: stock, mould shots and costs move on approval (P3-09); a family mould's
  other parts are counted when approved (P3-09); corrections after the grace period
  (P3-09); machining and support pages (P3-12).
  - Owner, 12 Nov 2026 (from his testing, R2): the Workshop supervisor could start every
    section's work shift report, moulding included, because his "All sections" tick (every
    person's default) widened his section scope. A Production Supervisor (shop-floor entry,
    not planning or approving) now gets only the sections they supervise or are assigned
    to, whatever the tick (`plan.own_sections` / `plan.work_sections`): on the work shift
    report, the production plan, the production reports and the report builder's shift
    data (spec 7.4: "Supervisor can enter data only for assigned sections").

- [x] **P3-09 Approving shift reports and corrections**
  The Production Manager approves or returns each submitted report (never their own).
  Approval: good quantity into finished stock, resin, masterbatch and packing backflushed
  for good and rejected quantity at their lot cost, regrind into stock at its credit value,
  the mould's shot count updated, costs posted to the production order (P3-16). After the
  grace period (4 hours) a change is a correction request approved by the Production
  Manager, the Director, or a person the Admin gives that authority with the Director's
  approval (owner, 7 Nov 2026); never the person who asked; the original stays on record.
  SML has a Production Manager (owner); the Director approves only while nobody holds the
  role.
  Done: on the **Shift report** page. Submitting sends the report to the approval engine
  ("shift_report", the Production Manager by default; the Admin can route it to the
  Director under Settings → Approvals); never the person who submitted it. **Returning**
  needs a reason; the supervisor corrects it (at any time) and submits again. **Approval**,
  in one transaction: (1) **backflush** on one stock issue from the division's main store
  to the section, at the weighted average cost: resin and masterbatch for everything moulded
  (good and rejected), without the BOM's reject allowance since the actual rejects are
  counted; packing and bought parts for the good pieces only; the run's material batch is
  used for its material; customer-supplied material and services are not taken (Dr Raw
  materials used, Cr inventory); a shortage stops the approval; (2) **regrind** into the
  main store (lot RG + report) at its credit value (P3-05); (3) **good pieces** into the
  main store (lot = the order's number) valued at the material they used less their share
  of the regrind credit, a family mould's other parts too (shots × their cavities, sharing
  the value by weight); Dr finished goods (the item's inventory account) and Dr the
  regrind's inventory, Cr Raw materials used; labour and overhead are added by order
  costing (P3-16); (4) each **mould's shot count** goes up. What went into stock is kept
  as production receipts (never changed, database); the production order shows how much
  has been made. The supervisor's own material issue and return lines stay a record for
  the consumption report (P3-20). **Corrections:** after the entry time a supervisor of the
  section asks for one (with a reason) for a late draft or an approved report, one at a
  time; the report as it stood is kept with the request. Approval engine
  "shift_correction": the **Production Manager or the Director**, or a person the Admin
  gives the new action **"Approve corrections to shift reports"** (a sensitive grant the
  Director confirms); never the person who asked. Approving reopens a late draft for one
  more grace period, or, for an approved report, reverses the journals, the stock (refused
  if the parts have been used or delivered) and the shot counts, marks the receipts
  undone, and returns the report to the supervisor to correct and submit again. Requests
  never change once decided (database). Approval engine: new `reopen` for this.

- [x] **P3-10 Mould maintenance**
  Preventive maintenance due when the shot count reaches the interval: alerts to the
  Production Manager, a list of moulds approaching it; maintenance records (planned or
  repair, date, work done, cost, by whom); repair history per mould. A repair done by the
  workshop is an internal job (P3-15).
  Done: Production → **Mould maintenance**. Every mould (not retired) with its shot count,
  shots since the last preventive maintenance, interval and state: **due** at the interval,
  **approaching** from 90% (chosen; owner's list of 8 Nov, item 8), moulds due first. When an
  approved shift report (P3-09) takes a mould to approaching or due, the **Production
  Manager** of the division is notified (new notification "A mould is near or at its
  preventive maintenance"), once per stage until the next preventive maintenance. **Records**
  (Production Manager or Planner): preventive maintenance or repair, date (not in the
  future), the shot count then, work done, cost (LKR), done by, "done by our workshop" (to
  become an internal job, P3-15), and optionally the mould put under maintenance or back in
  service. Preventive maintenance restarts the count. Records are never changed or deleted
  (database); history per mould with its total cost. The cost is for the mould's history;
  payment goes through a voucher.

## C. Machining

- [x] **P3-11 Job orders and material issue**
  A job order from a sales order line (part, drawing revision, quantity, due date) or an
  internal job (mould making or repair, tools); the approved routing and BOM copied and
  editable per job; numbered from the number series. Stores issues material against the
  job by lot; issuing more than the BOM allows needs a reason and the Production Manager's
  approval; returns credited.
  - Done: Production → Job orders. The Planner makes a job (JO{YY}{MM}{NNNN}) for a sales
    order line (its division; the line's jobs and production orders together never exceed
    its quantity; tooling lines are mould making jobs) or an internal job: mould making,
    mould repair (a mould from the register), tools and fixtures, other work, in a division
    of theirs. The part's approved routing and (non-moulding) BOM are copied when the job is
    made, each material as a quantity per piece with its scrap allowance; while a draft the
    Planner changes the quantity, due date, operations and materials, or copies them again;
    a job without a routing gets its operations by hand. Release needs one operation and fixes
    them (database). Stores issues from a main store of the job's division by lot (oldest first
    unless one is chosen), posted as any issue (P2-18), up to per piece × quantity less what
    came back; more, or a material not on the job, needs a request with a reason that the
    Production Manager approves ("job_excess", reminder after 1 day), which adds its quantity.
    Returns go back against their issue and lot and are credited. Draft → Released →
    Completed → Closed; cancelled with a reason only with no material out; closed only with
    no request waiting. Jobs never deleted, issue links insert-only, decided requests never
    change (database). Our choices: materials stay fixed after release (the extra goes
    through a request); the stores person or the Planner may ask for more.
  - Owner, 11 Nov 2026 (from his testing, W9): in "Ask to issue more", the item code was a
    typed box. It is now a list of the job's materials (code, name, how much is left), with
    "Another item…" opening the typed box for a material not on the job. A wrong code was
    already refused ("Choose the stock item.").

- [x] **P3-12 Job cards and operation entry**
  A printed job card per operation with a QR code (spec 7.2), travelling with the parts. The
  supervisor scans it and enters operation, machine, operator, start and end, quantity
  completed, rejected (reason) and for rework. Checks: completed never exceeds what the
  previous operation released; no overlapping times on a machine. Time per piece against
  standard; quantity available for the next operation. Reports approved as in P3-09.
  - Done: Job orders → "Print job cards" (a released job): one A5 card per operation with the
    part, drawing, quantity, due date, section and machine, standard times, the next
    operation and boxes for the floor, and a QR code "JO26110001/20". Machining sections now
    have shift reports too (same page, entry window, downtime, manpower, submit, approval,
    corrections as P3-08/P3-09): the supervisor scans the card (or picks the job and
    operation) and enters the machine of the section, operator, start and end, pieces
    completed, rejected by reason and for rework, and whether it includes the setup.
    Checks: a released job of the division; not a subcontract operation (P3-13); times in the
    shift and never overlapping on a machine (database too); completed + rejected at an
    operation never more than the operation before completed (the job's quantity for the
    first). Worked out: minutes per piece (less downtime in the entry, over completed +
    rejected) against the routing's standard; per operation on the job: received,
    completed, rejected, for rework, in hand and ready for the next operation. Approval of
    a machining report moves no stock (job costs come with P3-16). Our choices: rework
    pieces stay in hand at the operation until completed or rejected; until P3-13, a
    subcontract operation passes on what it received.

- [x] **P3-13 Subcontract operations**
  Parts sent out to a supplier for an operation and received back against the job (with
  the quantity checked), and the supplier's bill coded to the job: a new optional job or
  production order field on voucher lines and supplier invoice lines, filled by the
  Accountant (spec 7.7).
  - Done: on a released job (Production → Job orders), the Planner or the stores person sends
    parts out for a subcontract operation on a numbered note (SC{YY}{MM}{NNNN}, printed A5
    for the gate and the supplier, with a QR code): the routing's supplier or another, never
    more than the operation received from the one before less what is already out or back.
    Parts come back counted against their note: good, and rejected with the reason; never
    more than is still out (service and database). Good parts go on to the next operation
    (P3-12 now uses them in place of the stand-in); the job's progress shows what is at the
    supplier. Notes and receipts are never changed or deleted (database). Voucher lines (the
    Accountant's coding) and supplier invoice lines now take a job or production order
    number, checked to exist and to be released or completed, kept as the order itself
    (one at most, database); the job shows the bills coded to it. Costing reads them in
    P3-16. Our choices: the Planner or stores sends and receives; a draft, closed or
    cancelled order takes no bills.

- [x] **P3-14 Inspection on jobs**
  First-article, in-process and final inspection against the job with measurements, using
  the inspection plans of Phase 1.6 (parameters, limits); a failed inspection holds the job
  until the Production Manager decides (rework, scrap, accept under deviation).
  - Done: on a released job (Production → Job orders, Inspections), the QC Inspector starts a
    first-article, in-process (after an operation) or final (after the last operation)
    inspection on 1 to 50 pieces; the checks are copied from the part's inspection plan
    (Phase 1.6, item or category) and the inspector may add more (needed when there is no
    plan). Results per check and piece; one inspection at a time per job. Finished with all
    results entered: within limits it passes; otherwise the job is on hold (no job card
    work, nothing sent out, not completed) and the division's Production Managers are told
    ("job_on_hold"). The Production Manager, never the inspector, decides with a reason:
    rework N pieces (back at the operation, no longer completed there), scrap N pieces
    (rejected at the operation), or accept under deviation; a deviation on a failed critical
    check goes to the Director ("job_deviation", reminder after 1 day), who approves it or
    returns it (back on hold). Passed and decided inspections never change, results only
    while inspecting, nothing is deleted (database). Our choices: the Director rule follows
    the owner's 8 Nov answer for materials; first-article inspection is recorded but does
    not block later work.

- [x] **P3-15 Mould making and inter-division transfers**
  A workshop job for a new company mould is capitalised to the mould's fixed asset; a
  repair is charged to the Plastic Injection Moulding division, both through an
  inter-division transfer (spec 3.1, 7.3) at cost.
  - Done: a completed mould making or mould repair job (the mould chosen on the job, in
    another division) shows "Transfer at cost" on its page; the Accountant posts it once.
    Cost until P3-16: material issued less returned at its issue cost; supplier bills coded
    to the job (approved or paid voucher lines not paying an invoice, and posted supplier
    invoice lines of non-stock items, in LKR); labour and overhead for job card time in
    approved shift reports at the section's labour rate and the machine's or section's
    overhead rate that day (P3-05). New company mould: Dr Moulds and tooling (1530) in the
    mould's division, Cr Inter-division sales (new 4800) in the workshop, the mould
    registered as a fixed asset at that cost and linked, its depreciation terms sent to the
    Director. Repair: Dr Inter-division charges (new 5080, Cost of sales) in the mould's
    division, Cr 4800 in the workshop; repairs are left out of the company's total profit
    and loss (spec 3.1 elimination), a capitalised mould stays in as it offsets its costs.
    Refused: other jobs, not completed, already transferred, a customer's mould, a mould
    already in the register, a mould of the workshop's own division, no cost. Transfers are
    never changed or deleted (database). Our choices: at cost with no mark-up (spec allows
    a set %, not asked for); the Accountant posts.

## D. Costing and profitability

- [x] **P3-16 Order costs and work in progress**
  Every approved cost posts an order cost entry (spec 7.7: material by lot, machine time,
  labour, setup and mould change, subcontract, direct expenses, rejects, mould
  amortisation, overhead) and the ledger: open orders' costs in Work in progress per
  division; on completion to finished goods, then cost of sales when invoiced. Month-end
  WIP report reconciled with the WIP account; machine time charged to no order reported as
  unabsorbed overhead. On the month-end checklist.
  - Part 1 done (PR #180): order costs. Every job order and production order collects
    insert-only cost entries (`OrderCost`, each naming its source) from what is approved:
    material (job issues by lot less returns; moulding backflush per approved shift report
    at the good pieces' material value less the regrind credit); labour (job card hours,
    less the machine's downtime in them, × the section's labour rate; moulding run hours ×
    the people on the machine, at least 1); machine time and overhead (hours × the
    machine's or section's overhead rate); setup and mould change (job card setup up to the
    routing's setup minutes; SETUP and MOULD-CHANGE downtime charged to the order run next
    on the machine); mould amortisation (shots × the mould's rate); subcontract and direct
    bills (approved or paid voucher lines not paying an invoice, posted supplier invoice
    lines of non-stock items; subcontract when the supplier was sent the job's parts). Rates
    in force on the day (P3-05). A changed or undone source (a corrected shift report, a
    cancelled or amended voucher) gets an adjusting entry. Costs are brought up to date when
    issues, shift reports, vouchers and supplier invoices are approved, by the Accountant's
    "Bring the costs up to date" and by `manage.py sync_order_costs`. Job and production
    order pages show costs by element, cost per good piece, the cost spent on rejects,
    sections without a labour rate, and every entry (job profitability or accounting view).
  - Part 2 done (PR #181): the ledger. Cost entries are posted when brought up to date
    (one journal per order, source "order_cost"), against the account the cost came from
    (the item's expense account for issues, the voucher or invoice line's account, else
    5090 Production costs absorbed into orders). Machining jobs with a stock part: Dr 1220
    Work in progress of the job's division; on completion the WIP moves to the part's stock
    (a production receipt, lot = job number) at the cost of the finished pieces, anything
    not finished to 5005 Cost of finished goods sold; late costs go to the stock value if
    stock is left, else to 5005. Moulding orders: material is already in the parts' stock
    (P3-09); the other costs are added to the parts' stock value (a "costed" stock
    movement on lot = order number). Mould and tool jobs and jobs without a stock part are
    not posted (costs for information). **Deliveries now take finished parts out of
    stock**: each delivery note line names its part (filled from the line's production
    order or job, changeable while a draft); issuing the note takes the stock FIFO by lot
    from the order division's main store at weighted average, Dr 5005 Cr the item's stock
    account, and refuses when there is not enough stock; cancelling an issued note puts the
    stock back into the same lots and reverses the entry. Cost of sales is therefore posted
    at delivery, not at invoice (owner to confirm). The **Work in progress** report
    (Accounts menu) shows per division each open job's WIP against the 1220 balance at the
    month end, the difference, the production costs charged to orders, and downtime in
    approved shift reports charged to no order at the machine's overhead rate (unabsorbed).
    The month-end checklist has "Order costs up to date and Work in progress agreeing with
    the open jobs".
  - Owner, 12 Nov 2026 (from his testing, W15): issuing a delivery note with too little
    finished stock said "only 0.000 pcs of SH-600 is in WS-MAIN. Approve its production
    first." It now says "only 0 pcs of SH-600 are in WS-MAIN, not 21. Finish or approve
    more production first." (plain figures, the quantity asked for, and wording that fits a
    workshop job as well as a moulding report).

- [x] **P3-17 Live order profitability**
  For every order: estimate (from the accepted quotation), actual to date, forecast at
  completion, forecast margin, % complete, red/amber/green. Order dashboard with filters;
  drill-down to every cost line and its source document; alerts to the Production Manager
  and Director (cost overrun, margin below minimum, reject % over limit); daily snapshot of
  each open order; moulding view per machine and mould (cycle time, material per good
  piece, rejects, margin per 1,000 pieces).
  Done (PR #182): `production/profit.py`. **Estimate**: cost per piece from the accepted
  quotation's costing at the quoted quantity (tooling left out), else the BOM's standard
  cost, × the order quantity. **Revenue**: the sales line's net price (after discounts) in
  LKR at the sales order's rate × good pieces; orders for stock and internal jobs have none.
  **Forecast**: cost so far + remaining pieces × the estimate per piece (or the cost per
  good piece so far without an estimate); margin % on cost, as on quotations. **Status**:
  red for a forecast loss or cost over the estimate (for the good pieces) by more than the
  overrun limit; amber for a margin below the minimum or rejects over the limit (limits
  from the production settings in force; a blank minimum = the quotation limits' minimum
  for the division, 1% without one). **Alerts** (`order_profit_alert`) to the Production
  Manager and the Director of the division, once per order and kind (`ProfitAlert`,
  insert-only), checked after each cost sync and in the evening snapshot. **Daily snapshot**
  (`OrderProfitSnapshot`, one per open order per day, insert-only) by the Celery task at
  22:50. **Order profitability** page (Production menu; job profitability or accounting
  access): open or completed orders worst first, filters by division, customer, section,
  due date and status; the moulding view per machine and mould for a date range. Job and
  production order pages show the figures, alerts and the day-by-day forecast margin; each
  cost entry names its source document (shift report, voucher, supplier invoice) with a link.

- [x] **P3-18 Closing an order and variances**
  Closed when the last quantity is delivered; final report of estimate against actual by
  element with the variances (material price and usage, machine time, setup, rejects,
  subcontract and direct expenses). Closed orders feed the quotation rate tables: average
  actual cycle and setup times and material usage per part.
  Done (PR #184): `production/closing.py`. A completed job or production order for a sales
  line closes by itself when the line's last quantity is delivered (on issuing the
  delivery note, or on completion if delivery came first); orders for stock and internal
  work are closed by the Planner as before. Closing keeps an `OrderClose` report
  (insert-only): revenue = good pieces (up to the order quantity) at the average LKR price
  of the line's issued tax invoices, at their invoice-date rates (the sales order's price
  and rate before any invoice); estimate from the accepted quotation's costing flexed to
  the good pieces (setup and per-order extras once): material, machine time (quoted
  machining + overhead against labour, machine overhead and mould wear), setup, rejects
  (quoted allowance against the cost spent on the rejected pieces, the other rows taking
  the good pieces' share), subcontract, direct and packing; material split into price and
  usage where the kilograms are known (job issues by weight; moulding resin and masterbatch
  backflushed). Without a quotation costing: actuals by element and the total against the
  BOM's standard cost. The report also keeps kg and machine hours per good piece, setup
  hours and the moulding cycle time; **Actuals for quoting** on the Order profitability
  page averages them over a part's last 10 closed orders. Closed orders are listed on the
  dashboard ("Closed"); job and production order pages show the final report.

## E. Reports and the shop floor

- [x] **P3-19 OEE**
  Per moulding machine and shift, day, month: availability (run time ÷ planned time from
  the roster; off days and planned stops not counted as lost), performance (standard
  cycle ÷ actual), quality (good ÷ total); OEE = A × P × Q. Trend and comparison by machine.
  Done (PR #185): `production/oee.py`, Production → **Machine OEE** (production reports
  access). From approved shift reports: planned time = the shift's working minutes on every
  shift the roster runs for the section that day (the section's own roster replaces the
  division's) and on any other shift worked; planned stops (planned downtime reasons) come
  off it. Availability = run time (runs less downtime inside them) ÷ (planned − planned
  stops); a rostered shift with no run is all lost. Performance = mould standard cycle ×
  shots ÷ run time. Quality = good ÷ shots × cavities. Days, months and the range add the
  minutes and pieces before the ratios. Over 100% is shown as it is (a wrong standard shows).
  Machines compared for a date range and section; each machine by month, day (with a bar)
  and shift. Retired machines are left out.

- [x] **P3-20 Production reports**
  Spec 7.6: daily production by section, machine and shift; reject % by reason, part,
  mould and machine; downtime by reason and machine (Pareto); actual against estimated time
  and cost per job; on-time delivery; material consumption against standard and regrind
  use; moulds approaching maintenance. Production as a report builder source; profitability
  reports (spec 7.7: margin by order, customer, part, mould, division; estimate accuracy).
  - Split in two (as P3-16). Part 1 done (PR #186): `production/reports.py`, Production →
    **Production reports** (production reports access, the user's sections), from approved
    shift reports: daily production by day, section, machine and shift (good, rejected,
    reject %, run and stopped hours, moulding runs and machining job cards); rejects by
    reason, part, mould or machine (made, reject %, share of all rejects); downtime by reason
    and machine, largest first with the running total (Pareto), planned stops marked;
    machining jobs due in the dates: routing estimate (setup + run minutes × quantity, own
    operations) against job card hours, estimated against actual cost (only for those who
    see costs) and on-time delivery (completed by the due date; open jobs past due counted);
    moulding material issued less returned by the supervisors against the backflushed
    standard, regrind made and issued; moulds at 90% or more of their maintenance interval.
  - Owner, 10 Nov 2026: on-time for machining jobs = completed by the due date (delivery
    note dates not used): confirmed.
  - Part 2 done (PR #187): five new report builder sources: moulding runs (good, rejected,
    shots, run hours, cycle), downtime (hours, reason), job card entries (completed,
    rejected, hours), all from approved shift reports in the person's sections; order costs
    and closed orders (revenue, cost, margin, variance), only for those who see order costs.
    Three new ready-made reports. On the Order profitability page, **Closed orders**: closed
    in the dates, margin by customer, part, mould, division or order, most profitable first
    (orders for stock or internal work have no revenue and are counted apart); **estimate
    accuracy**: estimate against actual by element over the orders estimated from a
    quotation, with the variance and its %, and the material price and usage totals.
  - Owner, 11 Nov 2026 (from his testing): the Production Manager's home page showed the
    sales and purchasing summaries (the role may only view those areas). It now shows a
    Production panel instead: shift reports and corrections waiting for them, requests to
    issue more, inspection decisions, BOMs and routings to approve, good pieces made today
    (approved reports) and moulds due (`GET /api/v1/production-reports/dashboard/`). The
    panel shows to whoever may approve production; the sales and purchasing summaries are
    hidden from them only where they can just view those areas.
  - Owner, 12 Nov 2026 (from his testing, R1): the Production Planner's home page showed the
    sales and purchasing figures (order values). He now gets the same Production panel as
    the Production Manager instead: the panel shows to whoever may approve production or
    enter production planning.

- [x] **P3-21 Shop-floor languages and offline entry**
  The supervisor pages in Sinhala and Tamil (translations supplied or approved by the
  owner), and offline entry: saved on the device and synced when Wi-Fi returns, with a
  visible sync status and conflicts shown, never silently overwritten.
  - Owner, 8 Nov 2026: Sinhala by machine translation, written by us; **no Tamil**; a staff
    member who reads Sinhala checks it before go-live.
  - Split in two. Part 1 done (PR #188): Sinhala (`frontend/src/i18n/si.json`, about 250
    texts) for the shift report (moulding and machining job cards, approval and
    corrections), the production plan, the menu, sign-in, notifications, scanning and the
    shared tables; a **Language** choice on the sign-in page and in the side menu, kept on the
    device (a supervisor's phone stays in Sinhala). Anything not yet translated shows in
    English; names entered in the system (machines, reasons, items) and messages from the
    server stay as entered / in English. A test checks every Sinhala text has its English one
    with the same placeholders.
  - Part 2 done (PR #189): offline shift report entry (`frontend/src/lib/offline.ts`). A
    save that cannot reach the server is kept on the phone (browser storage) with the
    report's version it was made on, and a status line says so; it is sent when the report
    is opened with a connection and whenever the connection returns ("Send now" too).
    Shift reports carry a version (`updated_at`, production 0040); a save naming an older
    version is refused (409, with the current report) and the supervisor sees both side by
    side and chooses "Keep my version" (sent without the version) or "Keep the saved
    version": never silently overwritten. Submitting waits for a connection and for the
    kept save to be sent. The last copy of each open report and the signed-in user are kept
    on the device so the page opens without Wi-Fi (the server checks everything when
    reached); a service worker (`frontend/public/sw.js`, hand-written, no library) keeps the
    app's own files, never the API, and only in the built app on the servers. Signing out
    clears the kept sign-in and report copies (saves not yet sent stay). Starting a new
    shift's report still needs a connection (it is created when the shift opens).
  - Owner, 10 Nov 2026 (testing, PR #191): the page is renamed **Work shift report**
    (Sinhala **වැඩ මුර වාර්තාව**; the Sinhala uses මුරය for "shift" throughout); the whole
    side menu and the home page in Sinhala (other office pages stay English); the side-menu
    headings in black bold and a little larger.

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
  - Preparation done (PR #190): section 7A of `docs/uat-scripts.md` (Planner, moulding and
    workshop supervisors on phones, in Sinhala and offline, Production Manager, QC and
    stores, Accountant and Director: 28 steps); `load_demo_data` gains a "machining" part: a
    Workshop supervisor (`wssupervisor@demo.sml.lk`) for M-BSW and C-LAT, a bandsaw, the
    drive shaft SH-600 with an approved routing and BOM, EN8 bar in stock, cost rates, a won
    and costed quotation for Lanka Tea Machinery, the confirmed sales order and a released
    job with bar issued. On a PC with the earlier demo data, running it again adds only this.
  - Owner, 11 Nov 2026 (from his testing, T5): the demo plan covered only the load day and
    the next day, so on later days the shift report showed no "Planned for this shift".
    `load_demo_data` now plans CAP-38 on IMM-250, General shift, for the load day and the
    next six days (`DEMO_PLAN_DAYS = 7`). A PC that already has the demo keeps its plan.
  - Owner, 12 Nov 2026 (his answer to Q3): `load_demo_data` adds four made-up workshop
    operators (E201–E202 on M-BSW, E203–E204 on C-LAT), so the Operator list of a workshop
    shift report is not empty. They are their own demo part (`workshop_operators`, loaded
    when E201 is missing), so a PC with the earlier demo gets just them on the next run.
  - Owner, 13 Nov 2026 (from his testing, W10): the demo had no inspection plan for the drive
    shaft, so he typed the check in himself. `load_demo_data` now adds QC's plan for SH-600
    (Diameter 44.95–45.05 mm, critical) as its own part (`workshop_inspection`, loaded when
    no active SH-600 plan exists).

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

