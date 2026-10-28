import { useTranslation } from "react-i18next";

import type { AuditEvent } from "../api/audit";

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

/** Audit rows, newest first: when, who, what, and each field's old → new value. */
export default function AuditTable({ rows }: { rows: AuditEvent[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) return <p className="muted">{t("audit.none")}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{t("audit.when")}</th>
            <th>{t("audit.who")}</th>
            <th>{t("audit.what")}</th>
            <th>{t("audit.changes")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{new Date(row.occurred_at).toLocaleString()}</td>
              <td>
                {row.actor_email}
                {row.ip_address && <div className="muted">{row.ip_address}</div>}
              </td>
              <td>
                <strong>{row.event ? t(`audit.event.${row.event}`, row.event) : t(`audit.action.${row.action}`)}</strong>
                <div>{row.object_repr}</div>
                {row.reason && <div className="muted">{t("audit.reason", { reason: row.reason })}</div>}
              </td>
              <td>
                <ul className="changes">
                  {Object.entries(row.changes).map(([field, [before, after]]) => (
                    <li key={field}>
                      <code>{field}</code>: {show(before)} → {show(after)}
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
