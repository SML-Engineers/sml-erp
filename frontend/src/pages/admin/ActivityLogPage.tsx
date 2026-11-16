import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityFilters } from "../../api/activityLog";
import { listActivity } from "../../api/activityLog";
import DataTable from "../../components/DataTable";
import { formatDateTime } from "../../lib/time";

/** Views and downloads (owner, 14 Nov 2026): who opened payslips, salaries and bank details,
 * who downloaded what, and at "everything" every page opened. Read only, like the audit log;
 * the level is set on Security and logging. */
export default function ActivityLogPage() {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ActivityFilters>({});
  const [filters, setFilters] = useState<ActivityFilters>({});
  const rows = useQuery({ queryKey: ["activity-log", filters], queryFn: () => listActivity(filters) });
  const set = (key: keyof ActivityFilters) => (e: { target: { value: string } }) => setDraft({ ...draft, [key]: e.target.value });

  return (
    <main className="page">
      <h1>{t("activity.title")}</h1>
      <p className="muted">{t("activity.help")}</p>
      <form
        className="inline-form"
        aria-label={t("activity.filters")}
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        <label>
          {t("activity.person")}
          <input type="email" value={draft.person ?? ""} onChange={set("person")} />
        </label>
        <label>
          {t("activity.kind")}
          <select value={draft.kind ?? ""} onChange={set("kind")}>
            <option value="">{t("activity.all")}</option>
            <option value="view">{t("activity.kinds.view")}</option>
            <option value="download">{t("activity.kinds.download")}</option>
          </select>
        </label>
        <label>
          {t("activity.category")}
          <select value={draft.category ?? ""} onChange={set("category")}>
            <option value="">{t("activity.all")}</option>
            {(["payslip", "salary", "bank", "other"] as const).map((c) => (
              <option key={c} value={c}>
                {t(`activity.categories.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("activity.from")}
          <input type="date" value={draft.from ?? ""} onChange={set("from")} />
        </label>
        <label>
          {t("activity.to")}
          <input type="date" value={draft.to ?? ""} onChange={set("to")} />
        </label>
        <button type="submit">{t("activity.show")}</button>
      </form>
      {rows.data?.length === 0 && <p className="muted">{t("activity.none")}</p>}
      {rows.data && rows.data.length > 0 && (
        <DataTable
          label={t("activity.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          columns={[
            { id: "when", header: t("activity.when"), value: (r) => formatDateTime(r.occurred_at) },
            { id: "person", header: t("activity.person"), value: (r) => r.user_email },
            { id: "kind", header: t("activity.kind"), value: (r) => t(`activity.kinds.${r.kind}`) },
            { id: "category", header: t("activity.category"), value: (r) => t(`activity.categories.${r.category}`) },
            { id: "what", header: t("activity.what"), value: (r) => r.file_name || r.path },
            { id: "ip", header: t("activity.ip"), value: (r) => r.ip_address ?? "" },
          ]}
        />
      )}
    </main>
  );
}
