import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { can } from "../api/access";
import { listDivisions } from "../api/admin";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { listCustomers } from "../api/customers";
import { createDirectOrder, listSalesOrders, SALES_ORDER_STATUSES, salesOrdersKey } from "../api/salesOrders";
import DataTable from "../components/DataTable";
import SearchSelect from "../components/SearchSelect";
import { formatDecimal } from "../lib/decimal";

/** Sales orders (spec 5.3): confirmed customer orders, from a quotation, a proforma or typed in. */
export default function SalesOrdersPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const waiting = params.get("waiting") ?? "";
  const [adding, setAdding] = useState(false);
  const rows = useQuery({
    queryKey: [...salesOrdersKey, "list", status, waiting],
    queryFn: () => listSalesOrders({ status, waiting }),
  });

  return (
    <main className="page">
      <h1>{t("salesOrders.title")}</h1>
      <p className="muted">{t("salesOrders.help")}</p>
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
            {SALES_ORDER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`salesOrders.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        {can(me.access, "sales", "approve") && (
          <label>
            <input
              type="checkbox"
              checked={waiting === "me"}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                if (e.target.checked) next.set("waiting", "me");
                else next.delete("waiting");
                setParams(next, { replace: true });
              }}
            />{" "}
            {t("quotations.waitingForMe")}
          </label>
        )}
        {can(me.access, "sales", "enter") && !adding && (
          <button type="button" onClick={() => setAdding(true)}>
            {t("salesOrders.newRepeat")}
          </button>
        )}
      </div>
      {adding && <NewRepeatOrder onClose={() => setAdding(false)} />}
      {rows.data && (
        <DataTable
          label={t("salesOrders.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("salesOrders.none")}
          columns={[
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
            { id: "date", header: t("vouchers.date"), value: (r) => r.order_date },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer.name },
            { id: "po", header: t("proformas.customerPo"), value: (r) => r.customer_po },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            {
              id: "total",
              header: t("vouchers.total"),
              value: (r) => r.total_amount,
              cell: (r) => `${r.currency} ${formatDecimal(r.total_amount)}`,
            },
            { id: "next", header: t("salesOrders.nextDelivery"), value: (r) => r.next_delivery ?? "" },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`salesOrders.statuses.${r.status}`) },
            { id: "by", header: t("quotations.madeBy"), value: (r) => r.created_by },
          ]}
        />
      )}
    </main>
  );
}

const today = () => new Date().toISOString().slice(0, 10);

/** A repeat order typed in directly (no quotation): it goes to the Director before it is open. */
function NewRepeatOrder({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const customers = useQuery({ queryKey: ["customers", "", false], queryFn: () => listCustomers("", false) });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const [values, setValues] = useState({
    customer: "",
    division: "",
    customer_po: "",
    description: "",
    quantity: "",
    unit_price: "",
    due_date: today(),
  });
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const production = (divisions.data ?? []).filter((d) => d.division_type !== "shared");
  const save = useMutation({
    mutationFn: () =>
      createDirectOrder({
        customer: Number(values.customer),
        division: values.division,
        customer_po: values.customer_po,
        lines: [
          {
            description: values.description,
            quantity: values.quantity,
            unit_price: values.unit_price,
            schedule: [{ due_date: values.due_date, quantity: values.quantity }],
          },
        ],
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: [...salesOrdersKey, "list"] });
      navigate(`/sales-orders/${made.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("salesOrders.newRepeat")} onSubmit={submit}>
      <h2 className="wide">{t("salesOrders.newRepeat")}</h2>
      <p className="wide muted">{t("salesOrders.repeatHelp")}</p>
      <div className="wide">
        <SearchSelect
          label={t("quotations.customer")}
          options={(customers.data ?? []).map((c) => ({ value: String(c.id), label: `${c.code} ${c.name}` }))}
          value={values.customer}
          onChange={set("customer")}
        />
      </div>
      <label>
        {t("vouchers.division")}
        <select value={values.division} required onChange={(e) => set("division")(e.target.value)}>
          <option value="">—</option>
          {production.map((d) => (
            <option key={d.code} value={d.code}>
              {d.code} {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("proformas.customerPo")}
        <input value={values.customer_po} maxLength={50} onChange={(e) => set("customer_po")(e.target.value)} />
      </label>
      <label className="wide">
        {t("quotations.description")}
        <input value={values.description} required onChange={(e) => set("description")(e.target.value)} />
      </label>
      <label>
        {t("quotations.quantity")}
        <input inputMode="decimal" className="num" value={values.quantity} required onChange={(e) => set("quantity")(e.target.value)} />
      </label>
      <label>
        {t("quotations.unitPrice")}
        <input inputMode="decimal" className="num" value={values.unit_price} required onChange={(e) => set("unit_price")(e.target.value)} />
      </label>
      <label>
        {t("salesOrders.deliveryDate")}
        <input type="date" value={values.due_date} required onChange={(e) => set("due_date")(e.target.value)} />
      </label>
      <div className="wide">
        <button type="submit" disabled={save.isPending || !values.customer}>
          {t("salesOrders.makeDraft")}
        </button>{" "}
        <button type="button" className="secondary" onClick={onClose}>
          {t("quotations.cancel")}
        </button>
        {save.error ? (
          <p className="form-error" role="alert">
            {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
          </p>
        ) : null}
      </div>
    </form>
  );
}
