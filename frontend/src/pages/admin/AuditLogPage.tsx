import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { getAuditLog, type AuditFilters } from "../../api/audit";
import AuditTable from "../../components/AuditTable";

export default function AuditLogPage() {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<AuditFilters>({});
  const [filters, setFilters] = useState<AuditFilters>({});
  const log = useQuery({ queryKey: ["audit", filters], queryFn: () => getAuditLog(filters) });

  function submit(event: FormEvent) {
    event.preventDefault();
    setFilters(draft);
  }

  const field = (key: keyof AuditFilters) => ({
    value: (draft[key] as string | undefined) ?? "",
    onChange: (e: { target: { value: string } }) => setDraft({ ...draft, [key]: e.target.value }),
  });

  return (
    <main className="page">
      <p className="breadcrumb">
        <Link to="/">{t("app.name")}</Link>
      </p>
      <h1>{t("audit.title")}</h1>
      <p className="muted">{t("audit.help")}</p>
      <form className="inline-form panel" onSubmit={submit}>
        <label>
          {t("audit.who")}
          <input type="email" {...field("actor")} />
        </label>
        <label>
          {t("audit.from")}
          <input type="date" {...field("from")} />
        </label>
        <label>
          {t("audit.to")}
          <input type="date" {...field("to")} />
        </label>
        <button type="submit">{t("audit.filter")}</button>
      </form>
      {log.isPending && <p className="muted">{t("common.loading")}</p>}
      {log.data && <AuditTable rows={log.data} />}
    </main>
  );
}
