import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { approvedReport, listVouchers, pendingReport, voucherHistory, vouchersKey } from "../api/vouchers";
import DataTable from "../components/DataTable";
import ExportLinks from "../components/ExportLinks";
import { formatDateTime } from "../lib/time";

type Tab = "approved" | "pending" | "history";
const TABS: Tab[] = ["approved", "pending", "history"];

/** Voucher reports (spec 4.4): the Approved List, vouchers pending by approver and age, and
 * the approval history of any voucher; each can be exported to Excel or PDF. */
export default function VoucherReportsPage() {
  const { t } = useTranslation();
  const [search] = useSearchParams();
  const asked = search.get("tab") as Tab | null;
  const [tab, setTab] = useState<Tab>(asked && TABS.includes(asked) ? asked : "approved");
  const division = search.get("division") ?? "";
  const level = search.get("level") ?? "";
  return (
    <main className="page">
      <p>
        <Link to="/vouchers">{t("vouchers.backToList")}</Link>
      </p>
      <h1>{t("voucherReports.title")}</h1>
      <div role="tablist" aria-label={t("voucherReports.title")} className="tabs">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            className={`tab ${tab === name ? "active" : ""}`}
            aria-selected={tab === name}
            onClick={() => setTab(name)}
          >
            {t(`voucherReports.${name}`)}
          </button>
        ))}
      </div>
      {tab === "approved" && <Approved division={division} />}
      {tab === "pending" && <Pending division={division} level={level} />}
      {tab === "history" && <History />}
    </main>
  );
}

function Approved(props: { division: string }) {
  const { t } = useTranslation();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [division, setDivision] = useState(props.division);
  const params = { from, to, division };
  const rows = useQuery({ queryKey: [...vouchersKey, "approved-report", params], queryFn: () => approvedReport(params) });
  return (
    <section className="panel" aria-label={t("voucherReports.approved")}>
      <p className="muted">{t("voucherReports.approvedHelp")}</p>
      <div className="toolbar">
        <label>
          {t("exports.from")}
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          {t("exports.to")}
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <label>
          {t("vouchers.division")}
          <input value={division} maxLength={2} size={3} onChange={(e) => setDivision(e.target.value.toUpperCase())} />
        </label>
        <ExportLinks path="/vouchers/reports/approved/" params={params} label={t("voucherReports.approved")} />
      </div>
      {rows.data && (
        <DataTable
          label={t("voucherReports.approved")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("voucherReports.none")}
          columns={[
            {
              id: "number",
              header: t("vouchers.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/vouchers/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "type", header: t("vouchers.type"), value: (r) => r.type },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "payee", header: t("vouchers.payee"), value: (r) => r.payee },
            {
              id: "approved",
              header: t("voucherReports.approvedOn"),
              value: (r) => r.approved_at ?? "",
              cell: (r) => (r.approved_at ? formatDateTime(r.approved_at) : ""),
            },
            { id: "by", header: t("voucherReports.approvedBy"), value: (r) => r.approved_by },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`vouchers.statuses.${r.status_code}`) },
            { id: "total", header: t("payments.approved"), value: (r) => r.total_amount, money: true },
            { id: "paid", header: t("payments.paid"), value: (r) => r.paid, money: true },
          ]}
        />
      )}
    </section>
  );
}

function Pending({ division, level }: { division: string; level: string }) {
  const { t } = useTranslation();
  const params = { division, level };
  const report = useQuery({ queryKey: [...vouchersKey, "pending-report", params], queryFn: () => pendingReport(params) });
  const bands = report.data?.summary[0] ? Object.keys(report.data.summary[0].bands) : [];
  return (
    <section className="panel" aria-label={t("voucherReports.pending")}>
      <p className="muted">{t("voucherReports.pendingHelp")}</p>
      {(division || level) && (
        <p>
          {[division && t("dashboard.divisionChip", { code: division }), level && `L${level}`].filter(Boolean).join(" · ")}{" "}
          <Link to="/vouchers/reports?tab=pending">{t("dashboard.showAll")}</Link>
        </p>
      )}
      <ExportLinks path="/vouchers/reports/pending/" params={params} label={t("voucherReports.pending")} />
      {report.data && report.data.summary.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("voucherReports.summary")}>
            <thead>
              <tr>
                <th>{t("voucherReports.waitingFor")}</th>
                <th className="num">{t("voucherReports.count")}</th>
                {bands.map((b) => (
                  <th key={b} className="num">
                    {b}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.data.summary.map((s) => (
                <tr key={s.waiting_for}>
                  <td>{s.waiting_for}</td>
                  <td className="num">{s.count}</td>
                  {bands.map((b) => (
                    <td key={b} className="num">
                      {s.bands[b]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {report.data && (
        <DataTable
          label={t("voucherReports.pending")}
          rows={report.data.rows}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("voucherReports.nonePending")}
          columns={[
            {
              id: "number",
              header: t("vouchers.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/vouchers/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "payee", header: t("vouchers.payee"), value: (r) => r.payee },
            { id: "waiting", header: t("voucherReports.waitingFor"), value: (r) => r.waiting_for },
            { id: "approvers", header: t("voucherReports.approvers"), value: (r) => r.approvers },
            {
              id: "since",
              header: t("voucherReports.since"),
              value: (r) => r.since,
              cell: (r) => formatDateTime(r.since),
            },
            { id: "days", header: t("voucherReports.days"), value: (r) => r.days },
            { id: "total", header: t("vouchers.total"), value: (r) => r.total_amount, money: true },
          ]}
        />
      )}
    </section>
  );
}

function History() {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [number, setNumber] = useState("");
  const found = useQuery({
    queryKey: [...vouchersKey, "find", number],
    queryFn: () => listVouchers({ q: number }),
    enabled: number !== "",
  });
  const voucher = found.data?.find((v) => v.number.toUpperCase() === number.toUpperCase());
  const rows = useQuery({
    queryKey: [...vouchersKey, "history", voucher?.id],
    queryFn: () => voucherHistory(voucher!.id),
    enabled: voucher !== undefined,
  });

  function search(event: FormEvent) {
    event.preventDefault();
    setNumber(text.trim());
  }

  return (
    <section className="panel" aria-label={t("voucherReports.history")}>
      <form className="toolbar" onSubmit={search}>
        <label>
          {t("voucherReports.voucherNumber")}
          <input value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <button type="submit">{t("voucherReports.show")}</button>
      </form>
      {found.data && !voucher && <p className="muted">{t("voucherReports.notFound")}</p>}
      {voucher && (
        <>
          <p>
            <Link to={`/vouchers/${voucher.id}`} className="mono">
              {voucher.number}
            </Link>{" "}
            · {voucher.payee?.name ?? voucher.voucher_type.name} · {t(`vouchers.statuses.${voucher.status}`)}{" "}
            <ExportLinks path={`/vouchers/${voucher.id}/history/`} label={t("voucherReports.history")} />
          </p>
          {rows.data && (
            <DataTable
              label={t("voucherReports.history")}
              rows={rows.data}
              rowKey={(r) => `${r.acted_at}-${r.action}`}
              searchable={false}
              pageSize="all"
              columns={[
                {
                  id: "when",
                  header: t("voucherReports.when"),
                  value: (r) => r.acted_at,
                  cell: (r) => formatDateTime(r.acted_at),
                },
                { id: "level", header: t("voucherReports.level"), value: (r) => `L${r.level}` },
                { id: "action", header: t("voucherReports.action"), value: (r) => r.action },
                { id: "user", header: t("voucherReports.by"), value: (r) => r.user },
                { id: "reason", header: t("voucherReports.reason"), value: (r) => r.reason },
              ]}
            />
          )}
        </>
      )}
    </section>
  );
}
