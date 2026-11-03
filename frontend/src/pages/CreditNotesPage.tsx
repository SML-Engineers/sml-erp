import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { cnKey, CN_STATUSES, listCreditNotes } from "../api/creditNotes";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

/** Credit notes (P2-06): corrections of issued tax invoices, approved by the Director or a
 * person given the right. New ones are made from the invoice. */
export default function CreditNotesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const waiting = params.get("waiting") ?? "";
  const rows = useQuery({ queryKey: [...cnKey, "list", status, waiting], queryFn: () => listCreditNotes({ status, waiting }) });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("cn.title")}</h1>
      <p className="muted">{t("cn.help")}</p>
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {CN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`cn.statuses.${s}`)}
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
          label={t("cn.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          emptyText={t("cn.none")}
          columns={[
            {
              id: "number",
              header: t("cn.number"),
              value: (r) => r.number || t("cn.draftNo", { id: r.id }),
              cell: (r) => (
                <Link to={`/credit-notes/${r.id}`} className="mono">
                  {r.number || t("cn.draftNo", { id: r.id })}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.credit_date },
            { id: "invoice", header: t("cn.invoice"), value: (r) => r.invoice.number },
            { id: "customer", header: t("dn.customer"), value: (r) => r.customer.name },
            { id: "kind", header: t("cn.kind"), value: (r) => t(`cn.kinds.${r.kind}`) },
            { id: "total", header: t("cn.total"), value: (r) => r.total_amount, cell: (r) => formatDecimal(r.total_amount) },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`cn.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}
