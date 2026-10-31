import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import {
  attentionReport,
  openAdvancesReport,
  openOrdersReport,
  registerReport,
  salesReportsKey,
  winLossReport,
  type WinLossFigures,
} from "../api/salesReports";
import DataTable from "../components/DataTable";
import ExportLinks from "../components/ExportLinks";
import { formatDecimal } from "../lib/decimal";

type Tab = "register" | "winLoss" | "attention" | "orders" | "advances";
const TABS: Tab[] = ["register", "winLoss", "attention", "orders", "advances"];
const STATUSES = ["draft", "awaiting_approval", "approved", "sent", "accepted", "lost", "expired", "revised"];

const monthStart = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
};

/** Sales reports (P15-11): each can be filtered and exported to Excel or PDF, and each row
 * opens its document. A user sees only their divisions (a Sales Executive their own). */
export default function SalesReportsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useSearchParams();
  const asked = search.get("tab") as Tab | null;
  const tab: Tab = asked && TABS.includes(asked) ? asked : "register";
  const [division, setDivision] = useState(search.get("division") ?? "");
  return (
    <main className="page">
      <h1>{t("salesReports.title")}</h1>
      <div role="tablist" aria-label={t("salesReports.title")} className="tabs">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            className={`tab ${tab === name ? "active" : ""}`}
            aria-selected={tab === name}
            onClick={() => {
              const next = new URLSearchParams(search);
              next.set("tab", name);
              setSearch(next, { replace: true });
            }}
          >
            {t(`salesReports.${name}`)}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <label>
          {t("vouchers.division")}
          <input value={division} maxLength={2} size={3} onChange={(e) => setDivision(e.target.value.toUpperCase())} />
        </label>
      </div>
      {tab === "register" && <Register division={division} status={search.get("status") ?? ""} />}
      {tab === "winLoss" && <WinLoss division={division} />}
      {tab === "attention" && <Attention division={division} />}
      {tab === "orders" && <Orders division={division} />}
      {tab === "advances" && <Advances division={division} />}
    </main>
  );
}

function Period(props: { from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void }) {
  const { t } = useTranslation();
  return (
    <>
      <label>
        {t("exports.from")}
        <input type="date" value={props.from} onChange={(e) => props.setFrom(e.target.value)} />
      </label>
      <label>
        {t("exports.to")}
        <input type="date" value={props.to} onChange={(e) => props.setTo(e.target.value)} />
      </label>
    </>
  );
}

const quoteLink = (r: { id: number; label: string }) => (
  <Link to={`/quotations/${r.id}`} className="mono">
    {r.label}
  </Link>
);

function Register(props: { division: string; status: string }) {
  const { t } = useTranslation();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState(props.status);
  const [salesperson, setSalesperson] = useState("");
  const params = { from, to, status, salesperson, division: props.division };
  const report = useQuery({ queryKey: [...salesReportsKey, "register", params], queryFn: () => registerReport(params) });
  const data = report.data;
  return (
    <section className="panel" aria-label={t("salesReports.register")}>
      <p className="muted">{t("salesReports.registerHelp")}</p>
      <div className="toolbar">
        <Period from={from} to={to} setFrom={setFrom} setTo={setTo} />
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("quotations.allStatuses")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`quotations.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        {data && data.salespeople.length > 1 && (
          <label>
            {t("salesReports.salesperson")}
            <select value={salesperson} onChange={(e) => setSalesperson(e.target.value)}>
              <option value="">{t("salesReports.everyone")}</option>
              {data.salespeople.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <ExportLinks path="/sales/reports/register/" params={params} label={t("salesReports.register")} />
      </div>
      {data && data.summary.length > 0 && (
        <ul className="chips" aria-label={t("salesReports.byStatus")}>
          {data.summary.map((s) => (
            <li key={s.status_code}>
              {t(`quotations.statuses.${s.status_code}`)}: <strong>{s.count}</strong> · LKR {formatDecimal(s.total_lkr)}
            </li>
          ))}
        </ul>
      )}
      {data && (
        <DataTable
          label={t("salesReports.register")}
          rows={data.rows}
          rowKey={(r) => r.id}
          emptyText={t("salesReports.none")}
          columns={[
            { id: "label", header: t("quotations.quotation"), value: (r) => r.label, cell: quoteLink },
            { id: "date", header: t("vouchers.date"), value: (r) => r.quote_date },
            { id: "valid", header: t("salesReports.validUntil"), value: (r) => r.valid_until },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer },
            { id: "salesperson", header: t("salesReports.salesperson"), value: (r) => r.salesperson },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`quotations.statuses.${r.status_code}`) },
            { id: "reason", header: t("salesReports.reason"), value: (r) => r.reason },
            { id: "total", header: t("vouchers.total"), value: (r) => r.total },
            { id: "lkr", header: t("salesReports.totalLkr"), value: (r) => r.total_lkr, money: true },
          ]}
        />
      )}
    </section>
  );
}

function Rate({ figures }: { figures: WinLossFigures }) {
  return <>{figures.win_rate === null ? "—" : `${figures.win_rate}%`}</>;
}

function WinLoss({ division }: { division: string }) {
  const { t } = useTranslation();
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState("");
  const params = { from, to, division };
  const report = useQuery({ queryKey: [...salesReportsKey, "win-loss", params], queryFn: () => winLossReport(params) });
  const data = report.data;
  const total = data?.summary.total;
  return (
    <section className="panel" aria-label={t("salesReports.winLoss")}>
      <p className="muted">{t("salesReports.winLossHelp")}</p>
      <div className="toolbar">
        <Period from={from} to={to} setFrom={setFrom} setTo={setTo} />
        <ExportLinks path="/sales/reports/win-loss/" params={params} label={t("salesReports.winLoss")} />
      </div>
      {total && (
        <p>
          {t("salesReports.winSummary", {
            won: String(total.won),
            lost: String(total.lost),
            rate: total.win_rate ?? "—",
            valueRate: total.value_win_rate ?? "—",
          })}
        </p>
      )}
      {data && data.summary.by_reason.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("salesReports.byReason")}>
            <thead>
              <tr>
                <th>{t("salesReports.reason")}</th>
                <th className="num">{t("salesReports.won")}</th>
                <th className="num">{t("salesReports.wonLkr")}</th>
                <th className="num">{t("salesReports.lost")}</th>
                <th className="num">{t("salesReports.lostLkr")}</th>
              </tr>
            </thead>
            <tbody>
              {data.summary.by_reason.map((r) => (
                <tr key={r.reason_code}>
                  <td>{r.reason}</td>
                  <td className="num">{r.won}</td>
                  <td className="num">{formatDecimal(r.won_lkr)}</td>
                  <td className="num">{r.lost}</td>
                  <td className="num">{formatDecimal(r.lost_lkr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.summary.by_salesperson.length > 1 && (
        <div className="table-wrap">
          <table aria-label={t("salesReports.bySalesperson")}>
            <thead>
              <tr>
                <th>{t("salesReports.salesperson")}</th>
                <th className="num">{t("salesReports.won")}</th>
                <th className="num">{t("salesReports.lost")}</th>
                <th className="num">{t("salesReports.winRate")}</th>
                <th className="num">{t("salesReports.wonLkr")}</th>
              </tr>
            </thead>
            <tbody>
              {data.summary.by_salesperson.map((r) => (
                <tr key={r.salesperson}>
                  <td>{r.salesperson}</td>
                  <td className="num">{r.won}</td>
                  <td className="num">{r.lost}</td>
                  <td className="num">
                    <Rate figures={r} />
                  </td>
                  <td className="num">{formatDecimal(r.won_lkr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && (
        <DataTable
          label={t("salesReports.winLoss")}
          rows={data.rows}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("salesReports.noneDecided")}
          columns={[
            { id: "label", header: t("quotations.quotation"), value: (r) => r.label, cell: quoteLink },
            { id: "decided", header: t("salesReports.decided"), value: (r) => r.decided },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer },
            { id: "salesperson", header: t("salesReports.salesperson"), value: (r) => r.salesperson },
            { id: "outcome", header: t("salesReports.outcome"), value: (r) => (r.won ? t("salesReports.won") : t("salesReports.lost")) },
            { id: "reason", header: t("salesReports.reason"), value: (r) => r.reason },
            { id: "note", header: t("salesReports.note"), value: (r) => r.note },
            { id: "lkr", header: t("salesReports.totalLkr"), value: (r) => r.total_lkr, money: true },
          ]}
        />
      )}
    </section>
  );
}

function Attention({ division }: { division: string }) {
  const { t } = useTranslation();
  const params = { division };
  const rows = useQuery({ queryKey: [...salesReportsKey, "attention", params], queryFn: () => attentionReport(params) });
  return (
    <section className="panel" aria-label={t("salesReports.attention")}>
      <p className="muted">{t("salesReports.attentionHelp")}</p>
      <ExportLinks path="/sales/reports/attention/" params={params} label={t("salesReports.attention")} />
      {rows.data && (
        <DataTable
          label={t("salesReports.attention")}
          rows={rows.data}
          rowKey={(r) => `${r.kind}-${r.id}`}
          searchable={false}
          emptyText={t("salesReports.noneAttention")}
          columns={[
            { id: "label", header: t("quotations.quotation"), value: (r) => r.label, cell: quoteLink },
            {
              id: "why",
              header: t("salesReports.needs"),
              value: (r) => r.kind,
              cell: (r) =>
                r.kind === "approval"
                  ? t("salesReports.needsApproval", { days: String(r.days), who: r.approvers })
                  : t("salesReports.expires", { date: r.date, days: String(r.days) }),
            },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer },
            { id: "salesperson", header: t("salesReports.salesperson"), value: (r) => r.salesperson },
            { id: "lkr", header: t("salesReports.totalLkr"), value: (r) => r.total_lkr, money: true },
          ]}
        />
      )}
    </section>
  );
}

function Orders({ division }: { division: string }) {
  const { t } = useTranslation();
  const [until, setUntil] = useState("");
  const params = { division, until };
  const rows = useQuery({ queryKey: [...salesReportsKey, "orders", params], queryFn: () => openOrdersReport(params) });
  return (
    <section className="panel" aria-label={t("salesReports.orders")}>
      <p className="muted">{t("salesReports.ordersHelp")}</p>
      <div className="toolbar">
        <label>
          {t("salesReports.dueBy")}
          <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
        <ExportLinks path="/sales/reports/open-orders/" params={params} label={t("salesReports.orders")} />
      </div>
      {rows.data && (
        <DataTable
          label={t("salesReports.orders")}
          rows={rows.data}
          rowKey={(r) => `${r.id}-${r.due_date}-${r.item}-${r.quantity}`}
          searchable={false}
          emptyText={t("salesReports.noneOrders")}
          columns={[
            {
              id: "due",
              header: t("salesReports.due"),
              value: (r) => r.due_date,
              cell: (r) => <span className={r.overdue ? "danger-text" : ""}>{r.due_date}</span>,
            },
            {
              id: "number",
              header: t("salesOrders.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/sales-orders/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer },
            { id: "po", header: t("proformas.customerPo"), value: (r) => r.customer_po },
            { id: "item", header: t("quotations.description"), value: (r) => r.item },
            { id: "qty", header: t("quotations.quantity"), value: (r) => r.quantity },
            {
              id: "status",
              header: t("salesReports.dueStatus"),
              value: (r) => (r.overdue ? 0 : r.status ? 1 : 2),
              cell: (r) => (r.overdue ? t("salesReports.overdue") : r.status ? t("salesReports.thisWeek") : ""),
            },
            { id: "value", header: t("salesReports.valueLkr"), value: (r) => r.value_lkr, money: true },
          ]}
        />
      )}
    </section>
  );
}

function Advances({ division }: { division: string }) {
  const { t } = useTranslation();
  const params = { division };
  const rows = useQuery({ queryKey: [...salesReportsKey, "advances", params], queryFn: () => openAdvancesReport(params) });
  return (
    <section className="panel" aria-label={t("salesReports.advances")}>
      <p className="muted">{t("salesReports.advancesHelp")}</p>
      <ExportLinks path="/sales/reports/advances/" params={params} label={t("salesReports.advances")} />
      {rows.data && (
        <DataTable
          label={t("salesReports.advances")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("salesReports.noneAdvances")}
          columns={[
            {
              id: "number",
              header: t("advances.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/advances/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.receipt_date },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer },
            { id: "against", header: t("salesReports.against"), value: (r) => r.against },
            { id: "amount", header: t("salesReports.received"), value: (r) => r.amount },
            { id: "lkr", header: t("advances.amountLkr"), value: (r) => r.amount_lkr, money: true },
            { id: "setoff", header: t("salesReports.setOff"), value: (r) => r.set_off_lkr, money: true },
            { id: "balance", header: t("salesReports.balance"), value: (r) => r.balance_lkr, money: true },
          ]}
        />
      )}
    </section>
  );
}
