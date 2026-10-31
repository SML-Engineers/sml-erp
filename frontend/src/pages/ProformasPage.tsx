import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { listProformas, proformasKey } from "../api/proformas";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

/** Proforma invoices (spec 5.2): made from accepted quotations. */
export default function ProformasPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const rows = useQuery({ queryKey: [...proformasKey, "list", status], queryFn: () => listProformas({ status }) });

  return (
    <main className="page">
      <h1>{t("proformas.title")}</h1>
      <p className="muted">{t("proformas.help")}</p>
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
            {["draft", "issued", "cancelled"].map((s) => (
              <option key={s} value={s}>
                {t(`proformas.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {rows.data && (
        <DataTable
          label={t("proformas.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("proformas.none")}
          columns={[
            {
              id: "number",
              header: t("proformas.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/proformas/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.issue_date },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer.name },
            { id: "quotation", header: t("quotations.quotation"), value: (r) => r.quotation.label },
            {
              id: "total",
              header: t("vouchers.total"),
              value: (r) => r.total_amount,
              cell: (r) => `${r.currency} ${formatDecimal(r.total_amount)}`,
            },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`proformas.statuses.${r.status}`) },
            { id: "by", header: t("quotations.madeBy"), value: (r) => r.created_by },
          ]}
        />
      )}
    </main>
  );
}
