import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { createInvoice, invoicesKey, listInvoices, ordersToInvoice } from "../api/taxInvoices";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

/** Tax invoices (P2-05): prepared from delivered quantities, issued by the Accountant. */
export default function TaxInvoicesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const rows = useQuery({ queryKey: [...invoicesKey, "list", status], queryFn: () => listInvoices({ status }) });

  return (
    <main className="page">
      <h1>{t("ti.title")}</h1>
      <p className="muted">{t("ti.help")}</p>
      <Prepare />
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
            <option value="draft">{t("ti.statuses.draft")}</option>
            <option value="issued">{t("ti.statuses.issued")}</option>
          </select>
        </label>
      </div>
      {rows.data && (
        <DataTable
          label={t("ti.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          emptyText={t("ti.none")}
          columns={[
            {
              id: "number",
              header: t("ti.number"),
              value: (r) => r.number || t("ti.draftNo", { id: r.id }),
              cell: (r) => (
                <Link to={`/tax-invoices/${r.id}`} className="mono">
                  {r.number || t("ti.draftNo", { id: r.id })}
                </Link>
              ),
            },
            { id: "date", header: t("ti.invoiceDate"), value: (r) => r.invoice_date },
            { id: "customer", header: t("dn.customer"), value: (r) => r.customer.name },
            { id: "order", header: t("dn.order"), value: (r) => r.order.number },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "total", header: t("ti.total"), value: (r) => r.total_amount, cell: (r) => formatDecimal(r.total_amount) },
            { id: "due", header: t("ti.dueDate"), value: (r) => r.due_date },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`ti.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}

/** Orders with delivered quantities not yet invoiced: tick the delivery notes to invoice. */
function Prepare() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const todo = useQuery({ queryKey: [...invoicesKey, "orders"], queryFn: ordersToInvoice });
  const [chosen, setChosen] = useState<Record<number, boolean>>({});
  const make = useMutation({
    mutationFn: ({ order, notes }: { order: number; notes: number[] }) => createInvoice(order, notes),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: invoicesKey });
      navigate(`/tax-invoices/${made.id}`);
    },
  });
  if (!todo.data || todo.data.length === 0) return null;
  return (
    <section className="panel" aria-label={t("ti.waiting")}>
      <h2>{t("ti.waiting")}</h2>
      {todo.data.map((o) => {
        const notes = o.delivery_notes.filter((n) => chosen[n.id] ?? true).map((n) => n.id);
        return (
          <div key={o.id} className="inline-form">
            <strong>{o.number}</strong> {o.customer}
            {o.customer_po && ` · ${t("dn.customerPo")} ${o.customer_po}`}
            {o.delivery_notes.map((n) => (
              <label key={n.id}>
                <input type="checkbox" checked={chosen[n.id] ?? true} onChange={(e) => setChosen((now) => ({ ...now, [n.id]: e.target.checked }))} />{" "}
                {n.number} ({n.delivery_date})
              </label>
            ))}
            <button type="button" disabled={make.isPending || notes.length === 0} onClick={() => make.mutate({ order: o.id, notes })}>
              {t("ti.prepare")}
            </button>
          </div>
        );
      })}
      {make.error && (
        <p className="form-error" role="alert">
          {make.error instanceof ApiError && make.error.detail ? make.error.detail : t("common.error")}
        </p>
      )}
    </section>
  );
}
