import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { getPayables, PAYABLE_BUCKETS, payablesKey, type PayableItem, type PayableRow } from "../api/payables";
import DataTable from "../components/DataTable";
import ExportLinks from "../components/ExportLinks";

/** Payables aging (P2-10): what we owe each supplier by days past due, from matched supplier
 * invoices and invoices on vouchers, less what has been paid. A supplier opens its items. */
export default function PayablesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const asAt = params.get("as_at") ?? "";
  const supplier = params.get("supplier") ?? "";
  const data = useQuery({ queryKey: [...payablesKey, asAt, supplier], queryFn: () => getPayables(asAt, supplier) });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("ap.title")}</h1>
      <p className="muted">{t("ap.help")}</p>
      <div className="toolbar">
        <label>
          {t("ar.asAt")}
          <input type="date" value={asAt} onChange={(e) => set("as_at", e.target.value)} />
        </label>
        <ExportLinks path="/payables/aging/" params={{ as_at: asAt }} label={t("ap.title")} />{" "}
        <Link to="/supplier-statements">{t("ap.statements")}</Link>
        {supplier && (
          <button type="button" className="secondary" onClick={() => set("supplier", "")}>
            {t("ap.allSuppliers")}
          </button>
        )}
      </div>
      {data.data && (
        <DataTable<PayableRow>
          label={t("ap.title")}
          rows={data.data.rows}
          rowKey={(r) => r.supplier_id}
          emptyText={t("ap.none")}
          columns={[
            {
              id: "supplier",
              header: t("ap.supplier"),
              value: (r) => `${r.code} ${r.supplier}`,
              cell: (r) => (
                <button type="button" className="link-button" onClick={() => set("supplier", String(r.supplier_id))}>
                  {`${r.code} ${r.supplier}`}
                </button>
              ),
            },
            ...PAYABLE_BUCKETS.map((b) => ({ id: b, header: t(`ar.buckets.${b}`), value: (r: PayableRow) => r[b], money: true })),
            { id: "total", header: t("ap.total"), value: (r) => r.total, money: true },
          ]}
        />
      )}
      {supplier && data.data && (
        <section className="panel" aria-label={t("ap.items")}>
          <h2>{t("ap.items")}</h2>
          <DataTable<PayableItem>
            label={t("ap.items")}
            rows={data.data.items}
            rowKey={(r) => `${r.kind}-${r.document}-${r.reference}`}
            searchable={false}
            emptyText={t("ap.none")}
            columns={[
              { id: "reference", header: t("ap.invoiceNo"), value: (r) => r.reference },
              {
                id: "document",
                header: t("ap.document"),
                value: (r) => r.document,
                cell: (r) => (
                  <Link to={r.link} className="mono">
                    {r.document}
                  </Link>
                ),
              },
              { id: "division", header: t("vouchers.division"), value: (r) => r.division },
              { id: "date", header: t("vouchers.date"), value: (r) => r.date },
              { id: "due", header: t("receipts.due"), value: (r) => r.due_date },
              { id: "days", header: t("ar.daysOverdue"), value: (r) => r.days_overdue || "" },
              { id: "total", header: t("receipts.total"), value: (r) => r.total, money: true, noTotal: true },
              { id: "open", header: t("ap.open"), value: (r) => r.open, money: true },
            ]}
          />
        </section>
      )}
    </main>
  );
}
