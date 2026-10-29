import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { listDeletedVouchers, vouchersKey } from "../api/vouchers";
import DataTable from "../components/DataTable";
import VoucherActions from "../components/VoucherActions";

/** Deleted vouchers (spec 4.4): gone from the working lists, kept here with who deleted
 * them, when and why. Open one to see its full history; its number is never reused. */
export default function DeletedVouchersPage() {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: [...vouchersKey, "deleted"], queryFn: listDeletedVouchers });
  return (
    <main className="page">
      <p>
        <Link to="/vouchers">{t("vouchers.backToList")}</Link>
      </p>
      <h1>{t("deletedVouchers.title")}</h1>
      <p className="muted">{t("deletedVouchers.help")}</p>
      {rows.data && (
        <DataTable
          label={t("deletedVouchers.title")}
          rows={rows.data}
          rowKey={(v) => v.id}
          emptyText={t("deletedVouchers.none")}
          columns={[
            {
              id: "number",
              header: t("vouchers.number"),
              value: (v) => v.number,
              cell: (v) => (
                <Link to={`/vouchers/${v.id}`} className="mono">
                  {v.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (v) => v.voucher_date },
            { id: "type", header: t("vouchers.type"), value: (v) => v.voucher_type.name },
            { id: "payee", header: t("vouchers.payee"), value: (v) => v.payee?.name ?? "" },
            { id: "total", header: t("vouchers.total"), value: (v) => v.total_amount, money: true },
            { id: "by", header: t("deletedVouchers.by"), value: (v) => v.deleted?.by ?? "" },
            {
              id: "at",
              header: t("deletedVouchers.at"),
              value: (v) => v.deleted?.at ?? "",
              cell: (v) => (v.deleted ? new Date(v.deleted.at).toLocaleString() : ""),
            },
            { id: "reason", header: t("deletedVouchers.reason"), value: (v) => v.deleted?.reason ?? "" },
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
