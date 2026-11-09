import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { getOee, oeeKey, type OeeFigures, type OeeMachine } from "../api/oee";
import { formatQuantity } from "../lib/decimal";

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const pct = (value: string | null) => (value === null ? "–" : `${value}%`);

/** A bar for the OEE: the number is always written too. */
function Bar({ value }: { value: string | null }) {
  const width = value === null ? 0 : Math.max(0, Math.min(100, Number(value)));
  return (
    <span className="oee-bar" aria-hidden="true">
      <span style={{ width: `${width}%` }} />
    </span>
  );
}

function Cells({ f }: { f: OeeFigures }) {
  return (
    <>
      <td className="num">{pct(f.availability)}</td>
      <td className="num">{pct(f.performance)}</td>
      <td className="num">{pct(f.quality)}</td>
      <td className="num">
        <strong>{pct(f.oee)}</strong> <Bar value={f.oee} />
      </td>
    </>
  );
}

function Heads() {
  const { t } = useTranslation();
  return (
    <>
      <th className="num">{t("oee.availability")}</th>
      <th className="num">{t("oee.performance")}</th>
      <th className="num">{t("oee.quality")}</th>
      <th className="num">{t("oee.oee")}</th>
    </>
  );
}

function MachineDetail({ m }: { m: OeeMachine }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("oee.machineTitle", { machine: m.machine })}>
      <h2>{t("oee.machineTitle", { machine: m.machine })}</h2>
      {m.months.length > 1 && (
        <div className="table-wrap">
          <table aria-label={t("oee.byMonth", { machine: m.machine })}>
            <thead>
              <tr>
                <th>{t("oee.month")}</th>
                <Heads />
              </tr>
            </thead>
            <tbody>
              {m.months.map((x) => (
                <tr key={x.month}>
                  <td>{x.month}</td>
                  <Cells f={x} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-wrap">
        <table aria-label={t("oee.byDay", { machine: m.machine })}>
          <thead>
            <tr>
              <th>{t("oee.day")}</th>
              <th className="num">{t("oee.plannedH")}</th>
              <th className="num">{t("oee.runH")}</th>
              <Heads />
            </tr>
          </thead>
          <tbody>
            {m.days.map((x) => (
              <tr key={x.day}>
                <td>{x.day}</td>
                <td className="num">{x.planned_h}</td>
                <td className="num">{x.run_h}</td>
                <Cells f={x} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details>
        <summary>{t("oee.byShift", { count: m.shifts.length })}</summary>
        <div className="table-wrap">
          <table aria-label={t("oee.shiftTable", { machine: m.machine })}>
            <thead>
              <tr>
                <th>{t("oee.day")}</th>
                <th>{t("oee.shift")}</th>
                <th className="num">{t("oee.plannedH")}</th>
                <th className="num">{t("oee.stopsH")}</th>
                <th className="num">{t("oee.runH")}</th>
                <Heads />
              </tr>
            </thead>
            <tbody>
              {m.shifts.map((x) => (
                <tr key={`${x.day}-${x.shift}`}>
                  <td>{x.day}</td>
                  <td>{x.shift}</td>
                  <td className="num">{x.planned_h}</td>
                  <td className="num">{x.planned_stops_h}</td>
                  <td className="num">{x.run_h}</td>
                  <Cells f={x} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

/** P3-19: OEE of the moulding machines, compared, with each machine's trend by day. */
export default function OeePage() {
  const { t } = useTranslation();
  const now = new Date();
  const [start, setStart] = useState(iso(new Date(now.getFullYear(), now.getMonth(), 1)));
  const [end, setEnd] = useState(iso(now));
  const [section, setSection] = useState("");
  const [open, setOpen] = useState("");
  const found = useQuery({ queryKey: [...oeeKey, start, end, section], queryFn: () => getOee(start, end, section) });
  const r = found.data;
  const chosen = r?.machines.find((m) => m.machine === open);
  return (
    <main className="page">
      <h1>{t("oee.title")}</h1>
      <p className="muted">{t("oee.help")}</p>
      <div className="toolbar">
        <label>
          {t("profit.from")}
          <input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} />
        </label>
        <label>
          {t("profit.to")}
          <input type="date" value={end} onChange={(e) => e.target.value && setEnd(e.target.value)} />
        </label>
        <label>
          {t("profit.section")}
          <select value={section} onChange={(e) => setSection(e.target.value)}>
            <option value="">{t("profit.all")}</option>
            {(r?.sections ?? []).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      {found.error && (
        <p className="form-error" role="alert">
          {found.error instanceof ApiError && found.error.detail ? found.error.detail : t("common.error")}
        </p>
      )}
      {r && (
        <section className="panel" aria-label={t("oee.compare")}>
          {r.machines.length === 0 ? (
            <p className="muted">{t("oee.none")}</p>
          ) : (
            <div className="table-wrap">
              <table aria-label={t("oee.compare")}>
                <thead>
                  <tr>
                    <th>{t("wip.machine")}</th>
                    <th className="num">{t("oee.plannedH")}</th>
                    <th className="num">{t("oee.runH")}</th>
                    <th className="num">{t("oee.lostH")}</th>
                    <th className="num">{t("profit.goodPieces")}</th>
                    <Heads />
                  </tr>
                </thead>
                <tbody>
                  {r.machines.map((m) => (
                    <tr key={m.machine}>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          aria-pressed={open === m.machine}
                          onClick={() => setOpen(open === m.machine ? "" : m.machine)}
                        >
                          {m.machine}
                        </button>
                        <div className="muted">
                          {m.name} · {m.section}
                        </div>
                      </td>
                      <td className="num">{m.planned_h}</td>
                      <td className="num">{m.run_h}</td>
                      <td className="num">{m.unplanned_stops_h}</td>
                      <td className="num">{formatQuantity(m.good)}</td>
                      <Cells f={m} />
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th>{t("closeReport.total")}</th>
                    <td className="num">{r.total.planned_h}</td>
                    <td className="num">{r.total.run_h}</td>
                    <td className="num">{r.total.unplanned_stops_h}</td>
                    <td className="num">{formatQuantity(r.total.good)}</td>
                    <Cells f={r.total} />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </section>
      )}
      {chosen && <MachineDetail m={chosen} />}
    </main>
  );
}
