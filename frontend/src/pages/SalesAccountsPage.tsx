import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { chartKey, listLedgerAccounts } from "../api/accounts";
import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { listSalesAccounts, setSalesAccount, type SalesAccountRow } from "../api/taxInvoices";

const key = ["sales-accounts"];

/** The income account each division's invoice lines are credited to (P2-05). */
export default function SalesAccountsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: key, queryFn: listSalesAccounts });
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false) });
  const income = (accounts.data ?? []).filter((a) => a.is_active && !a.merged_into && (a.account_type === "income" || a.account_type === "other_income"));
  const canChange = can(me.access, "accounting", "manage");
  return (
    <main className="page">
      <h1>{t("sa.title")}</h1>
      <p className="muted">{t("sa.help")}</p>
      <div className="table-wrap">
        <table aria-label={t("sa.title")}>
          <thead>
            <tr>
              <th>{t("vouchers.division")}</th>
              <th>{t("sa.goods")}</th>
              <th>{t("sa.tooling")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(rows.data ?? []).map((r) => (
              <Row key={`${r.division.code}-${r.account?.id}-${r.tooling_account?.id}`} row={r} income={income} canChange={canChange} />
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

function Row({ row, income, canChange }: { row: SalesAccountRow; income: { id: number; number: string; full_name: string }[]; canChange: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [account, setAccount] = useState(String(row.account?.id ?? ""));
  const [tooling, setTooling] = useState(String(row.tooling_account?.id ?? ""));
  const save = useMutation({
    mutationFn: () => setSalesAccount(row.division.code, Number(account), Number(tooling)),
    onSuccess: (latest) => queryClient.setQueryData(key, latest),
  });
  const select = (value: string, change: (v: string) => void, label: string) => (
    <select aria-label={label} value={value} disabled={!canChange} onChange={(e) => change(e.target.value)}>
      <option value="">—</option>
      {income.map((a) => (
        <option key={a.id} value={a.id}>
          {a.number} {a.full_name}
        </option>
      ))}
    </select>
  );
  return (
    <tr>
      <td>
        {row.division.code} {row.division.name}
      </td>
      <td>{select(account, setAccount, t("sa.goodsOf", { code: row.division.code }))}</td>
      <td>{select(tooling, setTooling, t("sa.toolingOf", { code: row.division.code }))}</td>
      <td>
        {canChange && (
          <button type="button" className="small" disabled={save.isPending || !account || !tooling} onClick={() => save.mutate()}>
            {t("sa.save")}
          </button>
        )}
        {save.error && (
          <span className="form-error" role="alert">
            {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
          </span>
        )}
      </td>
    </tr>
  );
}
