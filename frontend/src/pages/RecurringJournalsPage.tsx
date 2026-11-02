import { useQuery } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { listRecurringJournals, rjKey, type RecurringJournal } from "../api/recurringJournals";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

export function scheduleText(t: TFunction, r: Pick<RecurringJournal, "frequency" | "day_of_month">) {
  const day = r.day_of_month === 31 ? t("rj.lastDay") : t("rj.dayN", { n: r.day_of_month });
  return `${t(`rj.frequencies.${r.frequency}`)}, ${day}`;
}

/** Recurring journals (P2-02): templates that make a draft journal on their date. */
export default function RecurringJournalsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: [...rjKey, "list"], queryFn: listRecurringJournals });

  return (
    <main className="page">
      <h1>{t("rj.title")}</h1>
      <p className="muted">{t("rj.help")}</p>
      <div className="toolbar">
        {can(me.access, "accounting", "enter") && (
          <Link className="button-link" to="/journals/recurring/new">
            {t("rj.new")}
          </Link>
        )}
        <Link to="/journals/manual">{t("mj.title")}</Link>
      </div>
      {rows.data && (
        <DataTable
          label={t("rj.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("rj.none")}
          columns={[
            { id: "name", header: t("rj.name"), value: (r) => r.name, cell: (r) => <Link to={`/journals/recurring/${r.id}`}>{r.name}</Link> },
            { id: "schedule", header: t("rj.schedule"), value: (r) => scheduleText(t, r) },
            { id: "amount", header: t("mj.amount"), value: (r) => r.amount, cell: (r) => formatDecimal(r.amount) },
            { id: "accrual", header: t("rj.accrual"), value: (r) => (r.reverse_next_month ? t("rj.yes") : "") },
            { id: "next", header: t("rj.next"), value: (r) => (r.is_active ? r.next_date : t("rj.stopped")) },
            { id: "by", header: t("rj.owner"), value: (r) => r.created_by },
          ]}
        />
      )}
    </main>
  );
}
