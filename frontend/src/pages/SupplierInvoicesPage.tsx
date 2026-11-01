import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { INVOICE_STATUSES, listSupplierInvoices, siKey } from "../api/supplierInvoices";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

/** Supplier invoices (spec 5A.4): entered by Accounts and matched against the PO and GRN. */
export default function SupplierInvoicesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const waiting = params.get("waiting") ?? "";
  const rows = useQuery({ queryKey: [...siKey, "list", status, waiting], queryFn: () => listSupplierInvoices({ status, waiting }) });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };
  return (
    <main className="page">
      <h1>{t("si.title")}</h1>
      <p className="muted">{t("si.help")}</p>
      <div className="toolbar">
        {can(me.access, "vouchers", "enter") && (
          <Link className="button-link" to="/supplier-invoices/new">
            {t("si.new")}
          </Link>
        )}
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {INVOICE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`si.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={waiting === "me"} onChange={(e) => set("waiting", e.target.checked ? "me" : "")} />{" "}
          {t("quotations.waitingForMe")}
        </label>
      </div>
      {rows.data && (
        <DataTable
          label={t("si.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("si.none")}
          columns={[
            {
              id: "no",
              header: t("si.invoiceNo"),
              value: (r) => r.invoice_no,
              cell: (r) => <Link to={`/supplier-invoices/${r.id}`}>{r.invoice_no}</Link>,
            },
            { id: "number", header: t("si.number"), value: (r) => r.number },
            { id: "date", header: t("vouchers.date"), value: (r) => r.invoice_date },
            { id: "supplier", header: t("po.supplier"), value: (r) => r.supplier.name },
            { id: "due", header: t("si.due"), value: (r) => r.due_date },
            { id: "total", header: t("vouchers.total"), value: (r) => r.total_amount, cell: (r) => `${r.currency} ${formatDecimal(r.total_amount)}` },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`si.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}
