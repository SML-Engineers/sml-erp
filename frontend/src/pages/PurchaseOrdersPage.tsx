import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { listPurchaseOrders, PO_STATUSES, poKey } from "../api/purchaseOrders";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

/** Purchase orders (spec 5A.1): raised by the Purchasing Officer, approved by the Director. */
export default function PurchaseOrdersPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const waiting = params.get("waiting") ?? "";
  const rows = useQuery({ queryKey: [...poKey, "list", status, waiting], queryFn: () => listPurchaseOrders({ status, waiting }) });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("po.title")}</h1>
      <p className="muted">{t("po.help")}</p>
      <div className="toolbar">
        {can(me.access, "purchasing", "enter") && (
          <Link className="button-link" to="/purchase-orders/new">
            {t("po.new")}
          </Link>
        )}
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {PO_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`po.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        {can(me.access, "purchasing", "approve") && (
          <label>
            <input type="checkbox" checked={waiting === "me"} onChange={(e) => set("waiting", e.target.checked ? "me" : "")} />{" "}
            {t("quotations.waitingForMe")}
          </label>
        )}
      </div>
      {rows.data && (
        <DataTable
          label={t("po.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("po.none")}
          columns={[
            {
              id: "number",
              header: t("po.number"),
              value: (r) => r.label,
              cell: (r) => (
                <Link to={`/purchase-orders/${r.id}`} className="mono">
                  {r.label}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.po_date },
            { id: "supplier", header: t("po.supplier"), value: (r) => r.supplier.name },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "delivery", header: t("po.deliveryDate"), value: (r) => r.delivery_date ?? "" },
            { id: "total", header: t("vouchers.total"), value: (r) => r.total_amount, cell: (r) => `${r.currency} ${formatDecimal(r.total_amount)}` },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`po.statuses.${r.status}`) },
            { id: "by", header: t("po.raisedBy"), value: (r) => r.created_by },
          ]}
        />
      )}
    </main>
  );
}
