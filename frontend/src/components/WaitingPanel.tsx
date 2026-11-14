import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { getWaiting, WAITING_PAGES, waitingKey } from "../api/waiting";

/** "Waiting for your approval" at the top of everyone's dashboard (owner, 12 Nov 2026): each
 * kind of document waiting at a level this person approves, with a link to where it is done.
 * Nothing shows when nothing waits. */
export default function WaitingPanel() {
  const { t } = useTranslation();
  const data = useQuery({ queryKey: waitingKey, queryFn: getWaiting });
  const kinds = data.data ?? [];
  if (kinds.length === 0) return null;
  const total = kinds.reduce((sum, k) => sum + k.count, 0);
  return (
    <section className="dashboard" aria-label={t("waiting.title")}>
      <h2>{t("waiting.title", { count: total })}</h2>
      <div className="tiles">
        {kinds.map((k) => (
          <Link key={k.document_type} className="tile attention" to={WAITING_PAGES[k.document_type] ?? "/"}>
            <span className="tile-label">{k.label}</span>
            <strong className="tile-figure">{k.count}</strong>
            <span className="muted">{t("waiting.open")}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
