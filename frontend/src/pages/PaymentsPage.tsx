import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { listPayments, listToPay, paymentsKey } from "../api/payments";
import DataTable from "../components/DataTable";
import ExportLinks from "../components/ExportLinks";

/** Supplier payments (spec 4.4, Cashier): vouchers approved by the Director and not yet
 * fully paid, and the payments made. A payment always starts from a voucher. */
export default function PaymentsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const canPay = me.access.actions.includes("record_payment");
  const [search] = useSearchParams();
  const division = search.get("division") ?? "";
  const toPay = useQuery({ queryKey: [...paymentsKey, "to-pay", division], queryFn: () => listToPay(division) });
  const [from, setFrom] = useState(search.get("from") ?? "");
  const [to, setTo] = useState(search.get("to") ?? "");
  const made = useQuery({
    queryKey: [...paymentsKey, "made", from, to, division],
    queryFn: () => listPayments({ from, to, division }),
  });
  return (
    <main className="page">
      <h1>{t("payments.title")}</h1>
      <p className="muted">{t("payments.help")}</p>
      {division && (
        <p>
          {t("dashboard.divisionChip", { code: division })} <Link to="/payments">{t("dashboard.showAll")}</Link>
        </p>
      )}
      <section className="panel" aria-label={t("payments.toPay")}>
        <h2>{t("payments.toPay")}</h2>
        {toPay.data && (
          <DataTable
            label={t("payments.toPay")}
            rows={toPay.data}
            rowKey={(v) => v.id}
            emptyText={t("payments.nothingToPay")}
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
              { id: "payee", header: t("vouchers.payee"), value: (v) => v.payee?.name ?? v.transfer_to ?? "" },
              { id: "division", header: t("vouchers.division"), value: (v) => v.division },
              { id: "total", header: t("payments.approved"), value: (v) => v.total_amount, money: true },
              { id: "paid", header: t("payments.paid"), value: (v) => v.paid, money: true },
              { id: "remaining", header: t("payments.remaining"), value: (v) => v.remaining, money: true },
              {
                id: "pay",
                header: "",
                value: () => "",
                sortable: false,
                cell: (v) =>
                  canPay ? (
                    <Link className="button-link small" to={`/payments/new?voucher=${v.id}`}>
                      {t("payments.pay")}
                    </Link>
                  ) : null,
              },
            ]}
          />
        )}
      </section>
      {can(me.access, "payments", "view") && (
        <section className="panel" aria-label={t("payments.made")}>
          <h2>{t("payments.made")}</h2>
          <div className="toolbar">
            <label>
              {t("exports.from")}
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label>
              {t("exports.to")}
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </label>
            <ExportLinks path="/payments/" params={{ from, to, division }} label={t("payments.made")} />
          </div>
          {made.data && (
            <DataTable
              label={t("payments.made")}
              rows={made.data}
              rowKey={(p) => p.id}
              emptyText={t("payments.none")}
              columns={[
                { id: "number", header: t("payments.number"), value: (p) => p.number },
                { id: "date", header: t("payments.date"), value: (p) => p.payment_date },
                {
                  id: "voucher",
                  header: t("payments.voucher"),
                  value: (p) => p.voucher.number,
                  cell: (p) => (
                    <Link to={`/vouchers/${p.voucher.id}`} className="mono">
                      {p.voucher.number}
                    </Link>
                  ),
                },
                { id: "payee", header: t("vouchers.payee"), value: (p) => p.payee },
                { id: "account", header: t("payments.account"), value: (p) => p.account.code },
                { id: "method", header: t("payments.method"), value: (p) => t(`payments.methods.${p.method}`) },
                { id: "reference", header: t("payments.reference"), value: (p) => p.reference },
                { id: "amount", header: t("payments.amount"), value: (p) => p.amount, money: true },
                { id: "entry", header: t("payments.entry"), value: (p) => p.journal_entry },
              ]}
            />
          )}
        </section>
      )}
    </main>
  );
}
