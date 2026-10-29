import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { listVoucherTypes, listVouchers, voucherTypesKey, vouchersKey, type VoucherStatus } from "../api/vouchers";
import DataTable from "../components/DataTable";
import ExportLinks from "../components/ExportLinks";
import VoucherActions from "../components/VoucherActions";

const STATUSES: VoucherStatus[] = [
  "draft",
  "submitted",
  "accountant_approved",
  "director_approved",
  "returned",
  "rejected",
  "partly_paid",
  "paid",
  "cancelled",
  "amended",
];

/** Payment vouchers: the list (spec 4.4). The Clerk sees their own, approvers all. */
export default function VouchersPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [search] = useSearchParams();
  const [status, setStatus] = useState(search.get("status") ?? "");
  const [division, setDivision] = useState(search.get("division") ?? "");
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [from, setFrom] = useState(search.get("from") ?? "");
  const [to, setTo] = useState(search.get("to") ?? "");
  const filter = { status, type, q, from, to, division };
  const vouchers = useQuery({ queryKey: [...vouchersKey, filter], queryFn: () => listVouchers(filter) });
  const types = useQuery({ queryKey: [...voucherTypesKey, false], queryFn: () => listVoucherTypes(false) });
  const canEnter = can(me.access, "vouchers", "enter");

  return (
    <main className="page">
      <h1>{t("vouchers.title")}</h1>
      <div className="toolbar">
        {canEnter && (
          <Link className="button-link" to="/vouchers/new">
            {t("vouchers.new")}
          </Link>
        )}
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("vouchers.allStatuses")}</option>
            <option value="director_approved,partly_paid">{t("dashboard.unpaidStatus")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`vouchers.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("vouchers.type")}
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">{t("vouchers.allTypes")}</option>
            {types.data?.map((x) => (
              <option key={x.code} value={x.code}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
        <Link to="/vouchers/reports">{t("voucherReports.title")}</Link>
        <Link to="/vouchers/amendments">{t("amendments.title")}</Link>
        <Link to="/vouchers/cancellations">{t("cancellations.title")}</Link>
        <Link to="/vouchers/deleted">{t("deletedVouchers.title")}</Link>
        <label>
          {t("vouchers.search")}
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          {t("exports.from")}
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          {t("exports.to")}
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        {division && (
          <button type="button" className="small secondary" onClick={() => setDivision("")}>
            {t("dashboard.divisionChip", { code: division })} ✕
          </button>
        )}
        <ExportLinks path="/vouchers/" params={filter} label={t("vouchers.title")} />
      </div>
      {vouchers.data && (
        <DataTable
          label={t("vouchers.title")}
          rows={vouchers.data}
          rowKey={(v) => v.id}
          searchable={false}
          emptyText={t("vouchers.none")}
          columns={[
            {
              id: "number",
              header: t("vouchers.number"),
              value: (v) => v.number,
              cell: (v) => (
                <Link to={`/vouchers/${v.id}`} className="mono">
                  {v.number}
                  {v.attachments > 0 && <span aria-label={t("vouchers.hasFiles")}> 📎</span>}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (v) => v.voucher_date },
            { id: "type", header: t("vouchers.type"), value: (v) => v.voucher_type.name },
            { id: "payee", header: t("vouchers.payee"), value: (v) => v.payee?.name ?? "" },
            { id: "total", header: t("vouchers.total"), value: (v) => v.total_amount, money: true },
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
