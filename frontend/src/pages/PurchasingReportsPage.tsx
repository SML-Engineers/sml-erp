import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { getReport, prKey, reportExportUrl, type ReportName, type Row } from "../api/purchasingReports";
import DataTable, { type Column } from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

const TABS: { id: string; report: ReportName; filters?: Record<string, string>; period?: boolean }[] = [
  { id: "open", report: "open-orders" },
  { id: "overdue", report: "open-orders", filters: { overdue: "1" } },
  { id: "grni", report: "grni" },
  { id: "held", report: "held-invoices" },
  { id: "exceptions", report: "exceptions", period: true },
  { id: "suppliers", report: "suppliers", period: true },
];

const money = (key: string, header: string): Column<Row> => ({ id: key, header, value: (r) => String(r[key] ?? ""), cell: (r) => formatDecimal(String(r[key] ?? "")) });
const text = (key: string, header: string): Column<Row> => ({ id: key, header, value: (r) => (r[key] === null || r[key] === undefined ? "" : String(r[key])) });

/** Purchasing and stores reports (spec 5A.7): open POs and overdue deliveries, GRNI, invoices
 * held, exceptions approved, and receipts and rejections by supplier; Excel and PDF. */
export default function PurchasingReportsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = TABS.find((x) => x.id === params.get("tab")) ?? TABS[0];
  const filters: Record<string, string> = { ...(tab.filters ?? {}) };
  for (const name of ["division", "from", "to"]) if (params.get(name)) filters[name] = params.get(name)!;
  const data = useQuery({ queryKey: [...prKey, tab.id, filters], queryFn: () => getReport<Row[] | { rows: Row[]; ledger_balance: string }>(tab.report, filters) });
  const rows = Array.isArray(data.data) ? data.data : (data.data?.rows ?? []);
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  const columns: Record<string, Column<Row>[]> = {
    open: [
      { id: "label", header: t("po.number"), value: (r) => String(r.label), cell: (r) => <Link to={`/purchase-orders/${r.id}`}>{String(r.label)}</Link> },
      text("supplier", t("po.supplier")),
      text("delivery_date", t("po.deliveryDate")),
      { id: "late", header: t("pr.daysLate"), value: (r) => Number(r.days_late ?? 0), cell: (r) => (r.days_late ? <span className="form-error">{String(r.days_late)}</span> : "") },
      text("status", t("vouchers.status")),
      text("received_pct", t("pr.receivedPct")),
      money("outstanding_lkr", t("pr.stillToCome")),
    ],
    grni: [
      { id: "grn", header: t("grn.number"), value: (r) => String(r.grn), cell: (r) => <Link to={`/goods-receipts/${r.grn_id}`}>{String(r.grn)}</Link> },
      text("receipt_date", t("vouchers.date")),
      text("supplier", t("po.supplier")),
      text("item", t("po.item")),
      text("quantity", t("pr.notInvoiced")),
      money("value", t("stock.value")),
    ],
    held: [
      { id: "no", header: t("si.invoiceNo"), value: (r) => String(r.invoice_no), cell: (r) => <Link to={`/supplier-invoices/${r.id}`}>{String(r.invoice_no)}</Link> },
      text("supplier", t("po.supplier")),
      text("status", t("vouchers.status")),
      text("days_held", t("pr.days")),
      { id: "differences", header: t("si.differences"), value: (r) => String(r.differences), cell: (r) => <span className="pre-line">{String(r.differences)}</span> },
      money("total", t("vouchers.total")),
    ],
    exceptions: [
      { id: "at", header: t("pr.approved"), value: (r) => String(r.approved_at), cell: (r) => String(r.approved_at).slice(0, 16).replace("T", " ") },
      text("kind", t("pr.exception")),
      text("document", t("pr.document")),
      text("supplier", t("po.supplier")),
      text("reason", t("pr.reason")),
      text("approved_by", t("pr.approvedBy")),
    ],
    suppliers: [
      text("supplier", t("po.supplier")),
      text("grns", t("pr.grns")),
      text("late", t("pr.late")),
      money("received_value", t("pr.received")),
      money("rejected_value", t("pr.rejected")),
      text("rejection_rate", t("pr.rejectedPct")),
      text("returned", t("pr.returns")),
    ],
  };

  return (
    <main className="page">
      <h1>{t("pr.title")}</h1>
      <div role="tablist" className="tabs">
        {TABS.map((x) => (
          <button key={x.id} type="button" role="tab" aria-selected={x.id === tab.id} className={`tab ${x.id === tab.id ? "active" : ""}`} onClick={() => set("tab", x.id)}>
            {t(`pr.tabs.${x.id}`)}
          </button>
        ))}
      </div>
      <p className="muted">{t(`pr.help.${tab.id}`)}</p>
      <div className="toolbar">
        <label>
          {t("vouchers.division")}
          <input value={params.get("division") ?? ""} maxLength={2} onChange={(e) => set("division", e.target.value.toUpperCase())} />
        </label>
        {tab.period && (
          <>
            <label>
              {t("pr.from")}
              <input type="date" value={params.get("from") ?? ""} onChange={(e) => set("from", e.target.value)} />
            </label>
            <label>
              {t("pr.to")}
              <input type="date" value={params.get("to") ?? ""} onChange={(e) => set("to", e.target.value)} />
            </label>
          </>
        )}
        <span className="export-links">
          <a href={reportExportUrl(tab.report, filters, "xlsx")}>Excel</a> · <a href={reportExportUrl(tab.report, filters, "pdf")}>PDF</a>
        </span>
      </div>
      {!Array.isArray(data.data) && data.data && (
        <p>{t("pr.ledgerBalance", { amount: formatDecimal(data.data.ledger_balance) })}</p>
      )}
      {data.data && (
        <DataTable label={t(`pr.tabs.${tab.id}`)} rows={rows} rowKey={(r) => JSON.stringify(r)} searchable={false} emptyText={t("pr.none")} columns={columns[tab.id]} />
      )}
    </main>
  );
}
