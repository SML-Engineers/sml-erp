import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { BUCKETS, getAging, receivablesKey, type AgingRow } from "../api/receivables";
import DataTable from "../components/DataTable";
import ExportLinks from "../components/ExportLinks";

/** Receivables aging (P2-08): what each customer owes on its invoices by days past due, next
 * to its ledger balance. Each customer opens its statement. */
export default function ReceivablesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const asAt = params.get("as_at") ?? "";
  const aging = useQuery({ queryKey: [...receivablesKey, "aging", asAt], queryFn: () => getAging(asAt) });

  return (
    <main className="page">
      <h1>{t("ar.title")}</h1>
      <p className="muted">{t("ar.help")}</p>
      <div className="toolbar">
        <label>
          {t("ar.asAt")}
          <input
            type="date"
            value={asAt}
            onChange={(e) => {
              const next = new URLSearchParams(params);
              if (e.target.value) next.set("as_at", e.target.value);
              else next.delete("as_at");
              setParams(next, { replace: true });
            }}
          />
        </label>
        <ExportLinks path="/receivables/aging/" params={{ as_at: asAt }} label={t("ar.title")} />{" "}
        <Link to="/credit-holds">{t("holds.title")}</Link>
      </div>
      {aging.data && (
        <DataTable<AgingRow>
          label={t("ar.title")}
          rows={aging.data.rows}
          rowKey={(r) => r.customer_id}
          emptyText={t("ar.none")}
          columns={[
            {
              id: "customer",
              header: t("quotations.customer"),
              value: (r) => `${r.code} ${r.customer}`,
              cell: (r) => <Link to={`/receivables/${r.customer_id}`}>{`${r.code} ${r.customer}`}</Link>,
            },
            ...BUCKETS.map((b) => ({ id: b, header: t(`ar.buckets.${b}`), value: (r: AgingRow) => r[b], money: true })),
            { id: "total", header: t("ar.total"), value: (r) => r.total, money: true },
            { id: "ledger", header: t("ar.ledger"), value: (r) => r.ledger, money: true },
          ]}
        />
      )}
    </main>
  );
}
