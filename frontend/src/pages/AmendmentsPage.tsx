import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { listAmendments, vouchersKey } from "../api/vouchers";
import DataTable from "../components/DataTable";
import ExportLinks from "../components/ExportLinks";
import VoucherActions from "../components/VoucherActions";
import { formatDecimal, sumDecimal } from "../lib/decimal";

/** The Amendments List (spec 4.2, 4.4): every revision of an approved voucher, the voucher
 * it amends, why, and how the amount changed. */
export default function AmendmentsPage() {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: [...vouchersKey, "amendments"], queryFn: listAmendments });
  return (
    <main className="page">
      <p>
        <Link to="/vouchers">{t("vouchers.backToList")}</Link>
      </p>
      <h1>{t("amendments.title")}</h1>
      <p className="muted">{t("amendments.help")}</p>
      <ExportLinks path="/vouchers/amendments/" label={t("amendments.title")} />
      {rows.data && (
        <DataTable
          label={t("amendments.title")}
          rows={rows.data}
          rowKey={(v) => v.id}
          emptyText={t("amendments.none")}
          columns={[
            {
              id: "number",
              header: t("amendments.amendment"),
              value: (v) => v.number,
              cell: (v) => (
                <Link to={`/vouchers/${v.id}`} className="mono">
                  {v.number}
                </Link>
              ),
            },
            {
              id: "original",
              header: t("amendments.original"),
              value: (v) => v.parent.number,
              cell: (v) => (
                <Link to={`/vouchers/${v.parent.id}`} className="mono">
                  {v.parent.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (v) => v.voucher_date },
            { id: "payee", header: t("vouchers.payee"), value: (v) => v.payee?.name ?? "" },
            { id: "reason", header: t("amendments.reason"), value: (v) => v.amendment_reason },
            {
              id: "was",
              header: t("amendments.was"),
              value: (v) => v.parent.total_amount,
              cell: (v) => formatDecimal(v.parent.total_amount),
            },
            { id: "total", header: t("vouchers.total"), value: (v) => v.total_amount, cell: (v) => formatDecimal(v.total_amount) },
            {
              id: "change",
              header: t("amendments.change"),
              value: (v) => sumDecimal([v.total_amount, `-${v.parent.total_amount}`]),
              cell: (v) => formatDecimal(sumDecimal([v.total_amount, `-${v.parent.total_amount}`])),
            },
            { id: "status", header: t("vouchers.status"), value: (v) => t(`vouchers.statuses.${v.status}`) },
            {
              id: "actions",
              header: t("voucherActions.header"),
              value: () => "",
              sortable: false,
              cell: (v) => <VoucherActions voucher={v} />,
            },
          ]}
        />
      )}
    </main>
  );
}
