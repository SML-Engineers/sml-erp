import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { listCancellations, vouchersKey } from "../api/vouchers";
import DataTable from "../components/DataTable";

/** Cancellation requests (spec 4.2, P1-06): the Accountant asks, the Director decides on
 * the voucher's page. Waiting ones first by default. */
export default function CancellationsPage() {
  const { t } = useTranslation();
  const [pendingOnly, setPendingOnly] = useState(true);
  const rows = useQuery({
    queryKey: [...vouchersKey, "cancellations", pendingOnly],
    queryFn: () => listCancellations(pendingOnly),
  });
  return (
    <main className="page">
      <p>
        <Link to="/vouchers">{t("vouchers.backToList")}</Link>
      </p>
      <h1>{t("cancellations.title")}</h1>
      <p className="muted">{t("cancellations.help")}</p>
      <label className="inline-form">
        <input type="checkbox" checked={pendingOnly} onChange={(e) => setPendingOnly(e.target.checked)} />{" "}
        {t("cancellations.pendingOnly")}
      </label>
      {rows.data && (
        <DataTable
          label={t("cancellations.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          emptyText={t("cancellations.none")}
          columns={[
            {
              id: "voucher",
              header: t("vouchers.number"),
              value: (r) => r.voucher.number,
              cell: (r) => (
                <Link to={`/vouchers/${r.voucher.id}`} className="mono">
                  {r.voucher.number}
                </Link>
              ),
            },
            { id: "payee", header: t("vouchers.payee"), value: (r) => r.voucher.payee },
            { id: "total", header: t("vouchers.total"), value: (r) => r.voucher.total_amount, money: true },
            { id: "by", header: t("cancellations.by"), value: (r) => r.requested_by },
            { id: "reason", header: t("cancellations.reason"), value: (r) => r.reason },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`cancellations.statuses.${r.status}`) },
            {
              id: "decided",
              header: t("cancellations.decided"),
              value: (r) => r.decided_by ?? "",
              cell: (r) =>
                r.can_decide ? (
                  <Link to={`/vouchers/${r.voucher.id}`}>{t("cancellations.decide")}</Link>
                ) : (
                  [r.decided_by, r.decision_reason].filter(Boolean).join(": ")
                ),
            },
          ]}
        />
      )}
    </main>
  );
}
