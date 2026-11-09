import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import {
  getClosedMargins,
  getEstimateAccuracy,
  getMouldingProfits,
  getOrderProfits,
  getPartActuals,
  orderProfitsKey,
  type MarginGroup,
  type Rag,
} from "../api/orderProfits";
import { RagTag } from "../components/OrderProfitPanel";
import { formatDecimal, formatQuantity } from "../lib/decimal";

const money = (value: string | null) => (value === null ? "–" : formatDecimal(value));

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function monthStart(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
}

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** P3-17: the order dashboard (every open order's value, cost, forecast margin and a red,
 * amber or green status) and the moulding view per machine and mould. */
export default function OrderProfitsPage() {
  const { t } = useTranslation();
  const [state, setState] = useState("open");
  const [division, setDivision] = useState("");
  const [dueBy, setDueBy] = useState("");
  const [customer, setCustomer] = useState("");
  const [section, setSection] = useState("");
  const [status, setStatus] = useState<"" | Rag>("");
  const found = useQuery({
    queryKey: [...orderProfitsKey, state, division, dueBy],
    queryFn: () => getOrderProfits({ state, division, due_by: dueBy }),
  });
  const all = found.data?.orders ?? [];
  const customers = [...new Set(all.map((r) => r.customer).filter(Boolean))].sort();
  const sections = [...new Set(all.flatMap((r) => r.sections))].sort();
  const rows = all.filter(
    (r) => (!customer || r.customer === customer) && (!section || r.sections.includes(section)) && (!status || r.status === status),
  );
  const [start, setStart] = useState(monthStart());
  const [end, setEnd] = useState(today());
  const moulding = useQuery({ queryKey: [...orderProfitsKey, "moulding", start, end], queryFn: () => getMouldingProfits(start, end) });
  return (
    <main className="page">
      <h1>{t("profit.pageTitle")}</h1>
      <p className="muted">{t("profit.help")}</p>
      <div className="toolbar">
        <label>
          {t("profit.show")}
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="open">{t("profit.open")}</option>
            <option value="completed">{t("profit.completed")}</option>
            <option value="closed">{t("profit.closed")}</option>
          </select>
        </label>
        <label>
          {t("wip.divisionCol")}
          <select value={division} onChange={(e) => setDivision(e.target.value)}>
            <option value="">{t("profit.all")}</option>
            <option value="WS">WS</option>
            <option value="IM">IM</option>
          </select>
        </label>
        <label>
          {t("profit.customer")}
          <select value={customer} onChange={(e) => setCustomer(e.target.value)}>
            <option value="">{t("profit.all")}</option>
            {customers.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          {t("profit.section")}
          <select value={section} onChange={(e) => setSection(e.target.value)}>
            <option value="">{t("profit.all")}</option>
            {sections.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          {t("profit.dueBy")}
          <input type="date" value={dueBy} onChange={(e) => setDueBy(e.target.value)} />
        </label>
      </div>
      <ErrorLine error={found.error} />
      {found.data && (
        <section className="panel" aria-label={t("profit.orders")}>
          <div className="row-actions" role="group" aria-label={t("profit.byStatus")}>
            {(["red", "amber", "green"] as Rag[]).map((s) => (
              <button
                key={s}
                type="button"
                className={status === s ? "small" : "secondary small"}
                aria-pressed={status === s}
                onClick={() => setStatus(status === s ? "" : s)}
              >
                {t(`profit.rag.${s}`)}: {found.data.counts[s]}
              </button>
            ))}
          </div>
          {rows.length === 0 ? (
            <p className="muted">{t("profit.none")}</p>
          ) : (
            <div className="table-wrap">
              <table aria-label={t("profit.orders")}>
                <thead>
                  <tr>
                    <th>{t("profit.status")}</th>
                    <th>{t("profit.order")}</th>
                    <th>{t("profit.customer")}</th>
                    <th>{t("profit.due")}</th>
                    <th className="num">{t("profit.completeCol")}</th>
                    <th className="num">{t("profit.value")}</th>
                    <th className="num">{t("profit.costToDate")}</th>
                    <th className="num">{t("profit.forecastMargin")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.kind}-${r.id}`}>
                      <td>
                        <RagTag status={r.status} />
                        {r.flags.length > 0 && <div className="muted">{r.flags.map((f) => t(`profit.flags.${f}`)).join(", ")}</div>}
                      </td>
                      <td>
                        <Link to={r.link}>{r.number}</Link>
                        <div className="muted">
                          {r.division} · {r.part || r.description}
                          {r.sales_order && ` · ${r.sales_order}`}
                        </div>
                      </td>
                      <td>{r.customer || t("profit.forStock")}</td>
                      <td>{r.due_date ?? "–"}</td>
                      <td className="num">{r.complete_pct}%</td>
                      <td className="num">{money(r.value)}</td>
                      <td className="num">{money(r.cost)}</td>
                      <td className="num">
                        {money(r.forecast_margin)}
                        {r.margin_pct !== null && <div className="muted">{r.margin_pct}%</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      <ClosedOrdersPanel />
      <PartActualsPanel />
      <section className="panel" aria-label={t("profit.moulding")}>
        <h2>{t("profit.moulding")}</h2>
        <p className="muted">{t("profit.mouldingHelp")}</p>
        <div className="toolbar">
          <label>
            {t("profit.from")}
            <input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} />
          </label>
          <label>
            {t("profit.to")}
            <input type="date" value={end} onChange={(e) => e.target.value && setEnd(e.target.value)} />
          </label>
        </div>
        <ErrorLine error={moulding.error} />
        {moulding.data &&
          (moulding.data.rows.length === 0 ? (
            <p className="muted">{t("wip.nothing")}</p>
          ) : (
            <div className="table-wrap">
              <table aria-label={t("profit.mouldingTable")}>
                <thead>
                  <tr>
                    <th>{t("wip.machine")}</th>
                    <th>{t("profit.mould")}</th>
                    <th className="num">{t("profit.goodPieces")}</th>
                    <th className="num">{t("profit.rejects")}</th>
                    <th className="num">{t("profit.cycle")}</th>
                    <th className="num">{t("profit.materialPerPiece")}</th>
                    <th className="num">{t("profit.costPer1000")}</th>
                    <th className="num">{t("profit.marginPer1000")}</th>
                  </tr>
                </thead>
                <tbody>
                  {moulding.data.rows.map((m) => (
                    <tr key={`${m.machine}-${m.mould}`}>
                      <td>{m.machine}</td>
                      <td>
                        {m.mould}
                        <div className="muted">{m.orders.join(", ")}</div>
                      </td>
                      <td className="num">{formatQuantity(m.good)}</td>
                      <td className="num">
                        {m.rejected} {m.reject_pct !== null && `(${m.reject_pct}%)`}
                      </td>
                      <td className="num">{t("profit.cycleValue", { actual: m.actual_cycle_s ?? "–", standard: m.standard_cycle_s })}</td>
                      <td className="num">{m.material_per_piece ?? "–"}</td>
                      <td className="num">{money(m.cost_per_1000)}</td>
                      <td className="num">{m.margin_per_1000 === null ? t("profit.forStock") : formatDecimal(m.margin_per_1000)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
      </section>
    </main>
  );
}

/** P3-18: what closed orders of a part actually took, for the next quotation. */
function PartActualsPanel() {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [asked, setAsked] = useState("");
  const found = useQuery({ queryKey: [...orderProfitsKey, "part", asked], queryFn: () => getPartActuals(asked), enabled: asked !== "" });
  function submit(event: FormEvent) {
    event.preventDefault();
    setAsked(code.trim().toUpperCase());
  }
  const d = found.data;
  return (
    <section className="panel" aria-label={t("partActuals.title")}>
      <h2>{t("partActuals.title")}</h2>
      <p className="muted">{t("partActuals.help")}</p>
      <form className="toolbar" onSubmit={submit}>
        <label>
          {t("partActuals.item")}
          <input value={code} maxLength={30} onChange={(e) => setCode(e.target.value)} />
        </label>
        <button type="submit" disabled={!code.trim()}>
          {t("partActuals.show")}
        </button>
      </form>
      <ErrorLine error={found.error} />
      {d &&
        (d.orders.length === 0 ? (
          <p className="muted">{t("partActuals.none", { item: d.item })}</p>
        ) : (
          <div className="table-wrap">
            <table aria-label={t("partActuals.table", { item: d.item })}>
              <thead>
                <tr>
                  <th>{t("profit.order")}</th>
                  <th className="num">{t("profit.goodPieces")}</th>
                  <th className="num">{t("partActuals.kg")}</th>
                  <th className="num">{t("partActuals.hours")}</th>
                  <th className="num">{t("partActuals.setup")}</th>
                  <th className="num">{t("partActuals.cycle")}</th>
                  <th className="num">{t("profit.margin")}</th>
                </tr>
              </thead>
              <tbody>
                {d.orders.map((o) => (
                  <tr key={o.number}>
                    <td>{o.number}</td>
                    <td className="num">{formatQuantity(o.good)}</td>
                    <td className="num">{o.kg_per_piece ?? "–"}</td>
                    <td className="num">{o.hours_per_1000 ?? "–"}</td>
                    <td className="num">{o.setup_hours ?? "–"}</td>
                    <td className="num">{o.cycle_s ?? "–"}</td>
                    <td className="num">{o.margin_pct === null ? "–" : `${o.margin_pct}%`}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={2}>{t("partActuals.average")}</th>
                  <td className="num">{d.average.kg_per_piece ?? "–"}</td>
                  <td className="num">{d.average.hours_per_1000 ?? "–"}</td>
                  <td className="num">{d.average.setup_hours ?? "–"}</td>
                  <td className="num">{d.average.cycle_s ?? "–"}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        ))}
    </section>
  );
}

/** P3-20: closed orders' margin grouped as chosen (most profitable first) and how far the
 * quotations were from the actual costs. */
function ClosedOrdersPanel() {
  const { t } = useTranslation();
  const now = new Date();
  const [by, setBy] = useState<MarginGroup>("customer");
  const [start, setStart] = useState(`${now.getFullYear()}-01-01`);
  const [end, setEnd] = useState(today());
  const margins = useQuery({ queryKey: [...orderProfitsKey, "margins", by, start, end], queryFn: () => getClosedMargins(by, start, end) });
  const accuracy = useQuery({ queryKey: [...orderProfitsKey, "accuracy", start, end], queryFn: () => getEstimateAccuracy(start, end) });
  const m = margins.data;
  const a = accuracy.data;
  return (
    <section className="panel" aria-label={t("closedOrders.title")}>
      <h2>{t("closedOrders.title")}</h2>
      <p className="muted">{t("closedOrders.help")}</p>
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
          {t("prodReports.groupBy")}
          <select value={by} onChange={(e) => setBy(e.target.value as MarginGroup)}>
            {(["customer", "part", "mould", "division", "order"] as MarginGroup[]).map((g) => (
              <option key={g} value={g}>
                {t(`closedOrders.by.${g}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorLine error={margins.error ?? accuracy.error} />
      {m &&
        (m.rows.length === 0 ? (
          <p className="muted">{t("closedOrders.none")}</p>
        ) : (
          <div className="table-wrap">
            <table aria-label={t("closedOrders.marginBy", { by: t(`closedOrders.by.${m.by}`) })}>
              <thead>
                <tr>
                  <th>{t(`closedOrders.by.${m.by}`)}</th>
                  <th className="num">{t("closedOrders.orders")}</th>
                  <th className="num">{t("profit.revenue")}</th>
                  <th className="num">{t("profit.cost")}</th>
                  <th className="num">{t("profit.margin")}</th>
                </tr>
              </thead>
              <tbody>
                {m.rows.map((r) => (
                  <tr key={r.key}>
                    <td>
                      {r.key}
                      {r.name && <div className="muted">{r.name}</div>}
                    </td>
                    <td className="num">{r.orders}</td>
                    <td className="num">{money(r.revenue)}</td>
                    <td className="num">{money(r.cost)}</td>
                    <td className="num">
                      {money(r.margin)}
                      {r.margin_pct !== null && <div className="muted">{r.margin_pct}%</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={2}>{t("closeReport.total")}</th>
                  <td className="num">{money(m.total.revenue)}</td>
                  <td className="num">{money(m.total.cost)}</td>
                  <td className="num">
                    {money(m.total.margin)}
                    {m.total.margin_pct !== null && <div className="muted">{m.total.margin_pct}%</div>}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        ))}
      {m && m.without_revenue > 0 && <p className="muted">{t("closedOrders.withoutRevenue", { count: m.without_revenue })}</p>}
      {a && a.orders > 0 && (
        <>
          <h3>{t("closedOrders.accuracy")}</h3>
          <p className="muted">{t("closedOrders.accuracyHelp", { count: a.orders })}</p>
          <div className="table-wrap">
            <table aria-label={t("closedOrders.accuracy")}>
              <thead>
                <tr>
                  <th />
                  <th className="num">{t("closeReport.estimate")}</th>
                  <th className="num">{t("profit.actual")}</th>
                  <th className="num">{t("closeReport.variance")}</th>
                </tr>
              </thead>
              <tbody>
                {a.rows.map((r) => (
                  <tr key={r.key}>
                    <th>{t(`closeReport.rows.${r.key}`)}</th>
                    <td className="num">{money(r.estimate)}</td>
                    <td className="num">{money(r.actual)}</td>
                    <td className="num">
                      {money(r.variance)} {r.variance_pct !== null && `(${r.variance_pct}%)`}
                    </td>
                  </tr>
                ))}
                <tr>
                  <td>{t("closeReport.materialPrice")}</td>
                  <td />
                  <td />
                  <td className="num">{money(a.material_price)}</td>
                </tr>
                <tr>
                  <td>{t("closeReport.materialUsage")}</td>
                  <td />
                  <td />
                  <td className="num">{money(a.material_usage)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
