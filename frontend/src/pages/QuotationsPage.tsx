import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { listQuotations, quotationsKey } from "../api/quotations";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

const STATUSES = ["draft", "awaiting_approval", "approved", "sent", "accepted", "lost", "expired"];

/** Quotations (spec 5.1): a Sales Executive sees their own, managers see all. */
export default function QuotationsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(params.get("q") ?? "");
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  const rows = useQuery({ queryKey: [...quotationsKey, "list", q, status], queryFn: () => listQuotations({ q, status }) });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("quotations.title")}</h1>
      <div className="toolbar">
        {can(me.access, "sales", "enter") && (
          <Link className="button-link" to="/quotations/new">
            {t("quotations.new")}
          </Link>
        )}
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("quotations.allStatuses")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`quotations.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            set("q", text.trim());
          }}
        >
          <label>
            {t("table.search")}
            <input type="search" value={text} placeholder={t("quotations.searchHint")} onChange={(e) => setText(e.target.value)} />
          </label>
        </form>
      </div>
      {rows.data && (
        <DataTable
          label={t("quotations.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("quotations.none")}
          columns={[
            {
              id: "number",
              header: t("quotations.number"),
              value: (r) => `${r.number} Rev ${r.revision}`,
              cell: (r) => (
                <Link to={`/quotations/${r.id}`} className="mono">
                  {r.number}
                  {r.revision > 0 && ` Rev ${r.revision}`}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.quote_date },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer.name },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "enquiry", header: t("quotations.enquiryRef"), value: (r) => r.enquiry_ref },
            {
              id: "total",
              header: t("vouchers.total"),
              value: (r) => r.total_amount,
              cell: (r) => `${r.currency} ${formatDecimal(r.total_amount)}`,
            },
            { id: "lkr", header: t("quotations.totalLkr"), value: (r) => r.total_lkr, money: true },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`quotations.statuses.${r.status}`) },
            { id: "by", header: t("quotations.madeBy"), value: (r) => r.created_by },
          ]}
        />
      )}
    </main>
  );
}
