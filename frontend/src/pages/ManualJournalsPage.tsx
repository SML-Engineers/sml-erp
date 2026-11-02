import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { listManualJournals, manualJournalsExportUrl, MJ_STATUSES, mjKey } from "../api/manualJournals";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

/** Manual journals (P2-01): typed by the Accountant, posted only after the Director approves. */
export default function ManualJournalsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const waiting = params.get("waiting") ?? "";
  const rows = useQuery({ queryKey: [...mjKey, "list", status, waiting], queryFn: () => listManualJournals({ status, waiting }) });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("mj.title")}</h1>
      <p className="muted">{t("mj.help")}</p>
      <div className="toolbar">
        {can(me.access, "accounting", "enter") && (
          <Link className="button-link" to="/journals/manual/new">
            {t("mj.new")}
          </Link>
        )}
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {MJ_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`mj.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={waiting === "me"} onChange={(e) => set("waiting", e.target.checked ? "me" : "")} />{" "}
          {t("quotations.waitingForMe")}
        </label>
        <a className="button-link secondary" href={manualJournalsExportUrl("xlsx")}>
          Excel
        </a>
        <a className="button-link secondary" href={manualJournalsExportUrl("pdf")}>
          PDF
        </a>
      </div>
      {rows.data && (
        <DataTable
          label={t("mj.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("mj.none")}
          columns={[
            {
              id: "number",
              header: t("mj.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/journals/manual/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.entry_date },
            { id: "narration", header: t("mj.narration"), value: (r) => r.narration },
            { id: "amount", header: t("mj.amount"), value: (r) => r.total_debit, cell: (r) => formatDecimal(r.total_debit) },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`mj.statuses.${r.status}`) },
            { id: "by", header: t("mj.enteredBy"), value: (r) => r.created_by },
            { id: "entry", header: t("mj.postedAs"), value: (r) => r.journal_entry?.number ?? "" },
          ]}
        />
      )}
    </main>
  );
}
