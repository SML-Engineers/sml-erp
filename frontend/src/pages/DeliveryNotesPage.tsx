import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { dnKey, DN_STATUSES, listDeliveryNotes, ordersToDeliver } from "../api/deliveryNotes";
import DataTable from "../components/DataTable";
import SearchSelect from "../components/SearchSelect";

/** Delivery notes (P2-04): what left the factory against each sales order. */
export default function DeliveryNotesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const rows = useQuery({ queryKey: [...dnKey, "list", status], queryFn: () => listDeliveryNotes({ status }) });
  const todo = useQuery({ queryKey: [...dnKey, "orders"], queryFn: ordersToDeliver });
  const [order, setOrder] = useState("");
  const options = (todo.data ?? []).map((o) => ({
    value: String(o.id),
    label: `${o.number} · ${o.customer}${o.customer_po ? ` · PO ${o.customer_po}` : ""}`,
  }));

  return (
    <main className="page">
      <h1>{t("dn.title")}</h1>
      <p className="muted">{t("dn.help")}</p>
      {options.length > 0 && (
        <div className="toolbar" aria-label={t("dn.new")}>
          <SearchSelect label={t("dn.chooseOrder")} options={options} value={order} onChange={setOrder} />
          <button type="button" disabled={!order} onClick={() => navigate(`/delivery-notes/new?order=${order}`)}>
            {t("dn.new")}
          </button>
        </div>
      )}
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select
            value={status}
            onChange={(e) => {
              const next = new URLSearchParams(params);
              if (e.target.value) next.set("status", e.target.value);
              else next.delete("status");
              setParams(next, { replace: true });
            }}
          >
            <option value="">{t("advances.allStatuses")}</option>
            {DN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`dn.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {rows.data && (
        <DataTable
          label={t("dn.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          emptyText={t("dn.none")}
          columns={[
            {
              id: "number",
              header: t("dn.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/delivery-notes/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.delivery_date },
            { id: "customer", header: t("dn.customer"), value: (r) => r.customer.name },
            { id: "order", header: t("dn.order"), value: (r) => r.order.number },
            { id: "po", header: t("dn.customerPo"), value: (r) => r.order.customer_po },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "vehicle", header: t("dn.vehicle"), value: (r) => r.vehicle_no },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`dn.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}
