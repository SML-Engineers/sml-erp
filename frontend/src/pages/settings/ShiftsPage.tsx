import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import { listSections } from "../../api/factory";
import { divisionsAdminKey, listDivisionsAdmin } from "../../api/organisation";
import {
  createAssignment,
  createCrew,
  createPattern,
  createShift,
  deleteAssignment,
  getPreview,
  listAssignments,
  listCrews,
  listPatterns,
  listShifts,
  rosterKeys,
  updateAssignment,
  updateCrew,
  updateShift,
  type RosterAssignment,
  type Shift,
} from "../../api/rosters";
import DataTable from "../../components/DataTable";
import { factoryToday } from "../../lib/time";
import TimeInput from "../../components/TimeInput";

type Tab = "shifts" | "patterns" | "crews" | "calendar";
const TABS: Tab[] = ["shifts", "patterns", "crews", "calendar"];

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {errorText(error, t("common.error"))}
    </p>
  );
}

const hhmm = (time: string) => time.slice(0, 5);
const hours = (minutes: number) => (minutes / 60).toFixed(2).replace(/\.?0+$/, "");

function localToday() {
  return factoryToday();
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: ["settings"] });
}

export default function ShiftsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("shifts");
  const canManage = can(me.access, "settings", "manage");

  return (
    <main className="page">
      <h1>{t("shifts.title")}</h1>
      <p className="muted">{t("shifts.help")}</p>
      <div className="tabs" role="tablist" aria-label={t("shifts.title")}>
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? "tab active" : "tab"}
            onClick={() => setTab(name)}
          >
            {t(`shifts.tab.${name}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={t(`shifts.tab.${tab}`)}>
        {tab === "shifts" && <ShiftsTab canManage={canManage} />}
        {tab === "patterns" && <PatternsTab canManage={canManage} />}
        {tab === "crews" && <CrewsTab canManage={canManage} />}
        {tab === "calendar" && <CalendarTab canManage={canManage} />}
      </div>
    </main>
  );
}

// --- Shifts ------------------------------------------------------------------------------

function ShiftsTab({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const shifts = useQuery({ queryKey: rosterKeys.shifts, queryFn: listShifts });
  const [editing, setEditing] = useState<Shift | null>(null);

  return (
    <>
      {canManage && <ShiftForm key={editing?.id ?? "new"} shift={editing} onDone={() => setEditing(null)} />}
      {shifts.data && (
        <DataTable
          label={t("shifts.tab.shifts")}
          rows={shifts.data}
          rowKey={(s) => s.id}
          pageSize="all"
          searchable={false}
          columns={[
            { id: "code", header: t("divisions.code"), value: (s) => s.code },
            { id: "name", header: t("divisions.name"), value: (s) => s.name },
            {
              id: "times",
              header: t("shifts.times"),
              value: (s) => `${hhmm(s.start_time)}–${hhmm(s.end_time)}`,
              cell: (s) => (
                <>
                  {hhmm(s.start_time)}–{hhmm(s.end_time)}
                  {s.crosses_midnight && <span className="tag">{t("shifts.overnight")}</span>}
                </>
              ),
            },
            { id: "break", header: t("shifts.break"), value: (s) => s.break_minutes },
            { id: "hours", header: t("shifts.workingHours"), value: (s) => hours(s.working_minutes) },
            {
              id: "status",
              header: t("users.status"),
              value: (s) => (s.is_active ? t("users.active") : t("users.inactive")),
            },
            ...(canManage
              ? [
                  {
                    id: "edit",
                    header: "",
                    sortable: false,
                    value: () => "",
                    cell: (s: Shift) => (
                      <button
                        type="button"
                        className="small secondary"
                        aria-label={t("shifts.editShift", { code: s.code })}
                        onClick={() => setEditing(s)}
                      >
                        {t("divisions.edit")}
                      </button>
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}
    </>
  );
}

function ShiftForm({ shift, onDone }: { shift: Shift | null; onDone: () => void }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [code, setCode] = useState(shift?.code ?? "");
  const [name, setName] = useState(shift?.name ?? "");
  const [start, setStart] = useState(shift ? hhmm(shift.start_time) : "");
  const [end, setEnd] = useState(shift ? hhmm(shift.end_time) : "");
  const [breakMinutes, setBreakMinutes] = useState(String(shift?.break_minutes ?? 0));
  const [reason, setReason] = useState("");
  const change = () => ({
    code,
    name,
    start_time: start,
    end_time: end,
    break_minutes: Number(breakMinutes),
    reason,
  });
  const save = useMutation({
    mutationFn: () => (shift ? updateShift(shift.id, change()) : createShift(change())),
    onSuccess: () => {
      refresh();
      onDone();
      if (!shift) {
        setCode("");
        setName("");
        setStart("");
        setEnd("");
        setBreakMinutes("0");
        setReason("");
      }
    },
  });
  const toggle = useMutation({
    mutationFn: () => updateShift(shift!.id, { is_active: !shift!.is_active, reason }),
    onSuccess: () => {
      refresh();
      onDone();
    },
  });
  const overnight = start !== "" && end !== "" && end <= start;

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const title = shift ? t("shifts.editShift", { code: shift.code }) : t("shifts.addShift");
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>
          {t("divisions.code")}
          <input className="code-input" value={code} maxLength={5} required onChange={(e) => setCode(e.target.value.toUpperCase())} />
        </label>
        <label>
          {t("divisions.name")}
          <input value={name} required onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          {t("shifts.start")}
          <TimeInput value={start} required onChange={setStart} />
        </label>
        <label>
          {t("shifts.end")}
          <TimeInput value={end} required onChange={setEnd} />
        </label>
        <label>
          {t("shifts.breakMinutes")}
          <input type="number" min={0} value={breakMinutes} onChange={(e) => setBreakMinutes(e.target.value)} />
        </label>
        <label>
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" disabled={save.isPending}>
          {shift ? t("divisions.save") : t("shifts.addShift")}
        </button>
        {shift && (
          <>
            <button type="button" className={shift.is_active ? "danger" : "secondary"} onClick={() => toggle.mutate()}>
              {shift.is_active ? t("factory.makeInactive") : t("divisions.reactivate")}
            </button>
            <button type="button" className="secondary" onClick={onDone}>
              {t("access.cancel")}
            </button>
          </>
        )}
      </form>
      {overnight && <p className="muted">{t("shifts.overnightHelp")}</p>}
      <ErrorLine error={save.error ?? toggle.error} />
    </section>
  );
}

// --- Patterns ----------------------------------------------------------------------------

function PatternsTab({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const patterns = useQuery({ queryKey: rosterKeys.patterns, queryFn: listPatterns });
  const shifts = useQuery({ queryKey: rosterKeys.shifts, queryFn: listShifts });
  const [name, setName] = useState("");
  const [days, setDays] = useState<string[]>(["", ""]);
  const add = useMutation({
    mutationFn: () => createPattern(name, days.map((d) => d || null)),
    onSuccess: () => {
      refresh();
      setName("");
      setDays(["", ""]);
    },
  });
  const active = shifts.data?.filter((s) => s.is_active) ?? [];

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <>
      {canManage && (
        <section className="panel" aria-label={t("shifts.addPattern")}>
          <h2>{t("shifts.addPattern")}</h2>
          <form onSubmit={submit}>
            <div className="inline-form">
              <label>
                {t("divisions.name")}
                <input value={name} required onChange={(e) => setName(e.target.value)} />
              </label>
            </div>
            <ol className="cycle">
              {days.map((day, i) => (
                <li key={i}>
                  <label>
                    {t("shifts.cycleDay", { n: i + 1 })}
                    <select
                      value={day}
                      onChange={(e) => setDays((now) => now.map((d, j) => (j === i ? e.target.value : d)))}
                    >
                      <option value="">{t("shifts.off")}</option>
                      {active.map((s) => (
                        <option key={s.code} value={s.code}>
                          {s.code} {s.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </li>
              ))}
            </ol>
            <div className="row-actions">
              <button type="button" className="secondary small" onClick={() => setDays((now) => [...now, ""])}>
                {t("shifts.addDay")}
              </button>
              <button
                type="button"
                className="secondary small"
                disabled={days.length <= 1}
                onClick={() => setDays((now) => now.slice(0, -1))}
              >
                {t("shifts.removeDay")}
              </button>
              <button type="submit" disabled={add.isPending}>
                {t("shifts.savePattern")}
              </button>
            </div>
          </form>
          <ErrorLine error={add.error} />
        </section>
      )}
      {patterns.data && (
        <DataTable
          label={t("shifts.tab.patterns")}
          rows={patterns.data}
          rowKey={(p) => p.id}
          pageSize="all"
          searchable={false}
          columns={[
            { id: "name", header: t("divisions.name"), value: (p) => p.name },
            {
              id: "cycle",
              header: t("shifts.cycle"),
              value: (p) => p.days.map((d) => d ?? t("shifts.off")).join(" "),
              cell: (p) => (
                <span className="cycle-chips">
                  {p.days.map((d, i) => (
                    <span key={i} className={d ? "chip" : "chip off"}>
                      {d ?? t("shifts.off")}
                    </span>
                  ))}
                </span>
              ),
            },
            { id: "days", header: t("shifts.cycleDays"), value: (p) => p.summary.cycle_days },
            { id: "week", header: t("shifts.hoursPerWeek"), value: (p) => p.summary.average_hours_per_week },
            {
              id: "status",
              header: t("users.status"),
              value: (p) => (p.is_active ? t("users.active") : t("users.inactive")),
            },
          ]}
        />
      )}
    </>
  );
}

// --- Crews -------------------------------------------------------------------------------

function CrewsTab({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const crews = useQuery({ queryKey: rosterKeys.crews, queryFn: listCrews });
  const divisions = useQuery({ queryKey: divisionsAdminKey, queryFn: listDivisionsAdmin });
  const [division, setDivision] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const chosen = division || divisions.data?.find((d) => d.is_active)?.code || "";
  const add = useMutation({
    mutationFn: () => createCrew(chosen, code, name),
    onSuccess: () => {
      refresh();
      setCode("");
      setName("");
    },
  });
  const toggle = useMutation({
    mutationFn: (crew: { id: number; is_active: boolean }) =>
      updateCrew(crew.id, { is_active: !crew.is_active, reason }),
    onSuccess: refresh,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <>
      {canManage && (
        <section className="panel" aria-label={t("shifts.addCrew")}>
          <h2>{t("shifts.addCrew")}</h2>
          <form className="inline-form" onSubmit={submit}>
            <label>
              {t("factory.division")}
              <select value={chosen} onChange={(e) => setDivision(e.target.value)}>
                {divisions.data
                  ?.filter((d) => d.is_active)
                  .map((d) => (
                    <option key={d.code} value={d.code}>
                      {d.code} {d.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              {t("divisions.code")}
              <input className="code-input" value={code} maxLength={10} required onChange={(e) => setCode(e.target.value.toUpperCase())} />
            </label>
            <label>
              {t("divisions.name")}
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <button type="submit" disabled={add.isPending}>
              {t("shifts.addCrew")}
            </button>
          </form>
          <p className="muted">{t("shifts.crewMembersLater")}</p>
          <ErrorLine error={add.error ?? toggle.error} />
        </section>
      )}
      {crews.data && (
        <DataTable
          label={t("shifts.tab.crews")}
          rows={crews.data}
          rowKey={(c) => c.id}
          pageSize="all"
          searchable={false}
          columns={[
            { id: "division", header: t("factory.division"), value: (c) => c.division },
            { id: "code", header: t("divisions.code"), value: (c) => c.code },
            { id: "name", header: t("divisions.name"), value: (c) => c.name },
            {
              id: "status",
              header: t("users.status"),
              value: (c) => (c.is_active ? t("users.active") : t("users.inactive")),
            },
            ...(canManage
              ? [
                  {
                    id: "toggle",
                    header: "",
                    sortable: false,
                    value: () => "",
                    cell: (c: { id: number; code: string; is_active: boolean }) => (
                      <button type="button" className="small secondary" onClick={() => toggle.mutate(c)}>
                        {c.is_active ? t("factory.makeInactive") : t("divisions.reactivate")}
                      </button>
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}
    </>
  );
}

// --- Roster calendar ---------------------------------------------------------------------

function CalendarTab({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const divisions = useQuery({ queryKey: divisionsAdminKey, queryFn: listDivisionsAdmin });
  const assignments = useQuery({ queryKey: rosterKeys.rosters, queryFn: listAssignments });
  const [division, setDivision] = useState("");
  const chosen = division || divisions.data?.find((d) => d.is_active)?.code || "";

  return (
    <>
      <div className="inline-form">
        <label>
          {t("factory.division")}
          <select value={chosen} onChange={(e) => setDivision(e.target.value)}>
            {divisions.data?.map((d) => (
              <option key={d.code} value={d.code}>
                {d.code} {d.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {canManage && chosen && <AssignForm key={chosen} division={chosen} />}
      {assignments.data && (
        <section className="panel">
          <h2>{t("shifts.rosters")}</h2>
          <AssignmentList
            rows={assignments.data.filter((a) => a.division === chosen)}
            canManage={canManage}
          />
        </section>
      )}
      {chosen && <Preview key={`p-${chosen}`} division={chosen} />}
    </>
  );
}

function AssignForm({ division }: { division: string }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const patterns = useQuery({ queryKey: rosterKeys.patterns, queryFn: listPatterns });
  const crews = useQuery({ queryKey: rosterKeys.crews, queryFn: listCrews });
  const sections = useQuery({ queryKey: ["settings", "sections"], queryFn: listSections });
  const [pattern, setPattern] = useState("");
  const [section, setSection] = useState("");
  const [start, setStart] = useState(localToday());
  const [end, setEnd] = useState("");
  const [startDays, setStartDays] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const activePatterns = patterns.data?.filter((p) => p.is_active) ?? [];
  const patternId = pattern || String(activePatterns[0]?.id ?? "");
  const cycle = activePatterns.find((p) => String(p.id) === patternId)?.summary.cycle_days ?? 1;
  const divisionCrews = crews.data?.filter((c) => c.division === division && c.is_active) ?? [];
  const add = useMutation({
    mutationFn: () =>
      createAssignment({
        pattern: Number(patternId),
        division,
        section: section || null,
        start_date: start,
        end_date: end || null,
        crews: Object.entries(startDays)
          .filter(([, day]) => day !== "")
          .map(([crew, day]) => ({ crew, start_day: Number(day) })),
        reason,
      }),
    onSuccess: () => {
      refresh();
      setStartDays({});
      setReason("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <section className="panel" aria-label={t("shifts.assign")}>
      <h2>{t("shifts.assign")}</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>
          {t("shifts.pattern")}
          <select value={patternId} onChange={(e) => setPattern(e.target.value)}>
            {activePatterns.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("factory.section")}
          <select value={section} onChange={(e) => setSection(e.target.value)}>
            <option value="">{t("shifts.wholeDivision")}</option>
            {sections.data
              ?.filter((s) => s.division === division && s.is_active)
              .map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} {s.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("shifts.from")}
          <input type="date" value={start} min={localToday()} required onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          {t("shifts.to")}
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <fieldset className="wide">
          <legend>{t("shifts.crewsStart")}</legend>
          <p className="muted">{t("shifts.crewsStartHelp")}</p>
          <div className="checks">
            {divisionCrews.map((c) => (
              <label key={c.code}>
                {t("shifts.crewStartsOn", { crew: c.code })}
                <select
                  value={startDays[c.code] ?? ""}
                  onChange={(e) => setStartDays((now) => ({ ...now, [c.code]: e.target.value }))}
                >
                  <option value="">{t("shifts.notOnRoster")}</option>
                  {Array.from({ length: cycle }, (_, i) => (
                    <option key={i} value={i + 1}>
                      {t("shifts.cycleDay", { n: i + 1 })}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="wide">
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="wide">
          <button type="submit" disabled={add.isPending || !patternId}>
            {t("shifts.assign")}
          </button>
        </div>
      </form>
      <ErrorLine error={add.error} />
    </section>
  );
}

function AssignmentList({ rows, canManage }: { rows: RosterAssignment[]; canManage: boolean }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [ends, setEnds] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const setEnd = useMutation({
    mutationFn: (a: RosterAssignment) => updateAssignment(a.id, { end_date: ends[a.id] || null, reason }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (a: RosterAssignment) => deleteAssignment(a.id, reason),
    onSuccess: refresh,
  });

  if (rows.length === 0) return <p className="muted">{t("shifts.noRosters")}</p>;
  return (
    <>
      {canManage && (
        <label className="inline-form">
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("shifts.pattern")}</th>
              <th>{t("factory.section")}</th>
              <th>{t("shifts.from")}</th>
              <th>{t("shifts.to")}</th>
              <th>{t("shifts.tab.crews")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td>{a.pattern}</td>
                <td>{a.section ?? t("shifts.wholeDivision")}</td>
                <td>{a.start_date}</td>
                <td>
                  {canManage ? (
                    <input
                      type="date"
                      aria-label={t("shifts.endOf", { pattern: a.pattern })}
                      value={ends[a.id] ?? a.end_date ?? ""}
                      onChange={(e) => setEnds((now) => ({ ...now, [a.id]: e.target.value }))}
                    />
                  ) : (
                    (a.end_date ?? t("shifts.untilChanged"))
                  )}
                </td>
                <td>{a.crews.map((c) => `${c.crew} (${t("shifts.dayN", { n: c.start_day })})`).join(", ") || "—"}</td>
                <td>
                  {canManage && (
                    <div className="row-actions">
                      <button type="button" className="small" onClick={() => setEnd.mutate(a)}>
                        {t("shifts.saveEnd")}
                      </button>
                      {!a.started && (
                        <button type="button" className="small danger" onClick={() => remove.mutate(a)}>
                          {t("divisions.delete")}
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ErrorLine error={setEnd.error ?? remove.error} />
    </>
  );
}

function Preview({ division }: { division: string }) {
  const { t } = useTranslation();
  const [start, setStart] = useState(localToday());
  const preview = useQuery({
    queryKey: [...rosterKeys.preview, division, start],
    queryFn: () => getPreview(division, "", start),
  });
  const rows = Array.from(
    new Set(preview.data?.days.flatMap((d) => d.shifts.map((s) => s.crew ?? "")) ?? []),
  ).sort();

  return (
    <section className="panel" aria-label={t("shifts.preview")}>
      <h2>{t("shifts.preview")}</h2>
      <label className="inline-form">
        {t("shifts.from")}
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
      </label>
      {preview.data && preview.data.warnings.length > 0 && (
        <ul className="warning-list" role="alert">
          {preview.data.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {preview.data && rows.length === 0 && <p className="muted">{t("shifts.noRosters")}</p>}
      {preview.data && rows.length > 0 && (
        <div className="table-wrap">
          <table className="roster-grid">
            <thead>
              <tr>
                <th>{t("shifts.crew")}</th>
                {preview.data.days.map((d) => (
                  <th key={d.date}>{d.date.slice(5)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((crew) => (
                <tr key={crew || "everyone"}>
                  <th scope="row">{crew || t("shifts.everyone")}</th>
                  {preview.data!.days.map((d) => {
                    const on = d.shifts.filter((s) => (s.crew ?? "") === crew).map((s) => s.shift);
                    return (
                      <td key={d.date} className={on.length ? "on" : "off"} title={on.join(", ")}>
                        {on.join(" ") || "·"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
