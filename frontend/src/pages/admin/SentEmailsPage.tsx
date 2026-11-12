import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { listSentEmails } from "../../api/documentEmail";
import DataTable from "../../components/DataTable";
import { formatDateTime } from "../../lib/time";

/** Every document and report emailed from the finance mailbox, exactly as sent (spec 3B). */
export default function SentEmailsPage() {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: ["sent-emails"], queryFn: listSentEmails });
  const [open, setOpen] = useState<number | null>(null);
  const current = rows.data?.find((r) => r.id === open);

  return (
    <main className="page">
      <h1>{t("sentEmails.title")}</h1>
      <p className="muted">{t("sentEmails.help")}</p>
      {rows.data && (
        <DataTable
          label={t("sentEmails.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          columns={[
            { id: "sent_at", header: t("sentEmails.when"), value: (r) => formatDateTime(r.sent_at) },
            {
              id: "document",
              header: t("sentEmails.document"),
              value: (r) => r.document_label,
              cell: (r) => (
                <button type="button" className="link-button" onClick={() => setOpen(r.id)}>
                  {r.document_label}
                </button>
              ),
            },
            { id: "to", header: t("email.to"), value: (r) => r.to },
            { id: "by", header: t("sentEmails.by"), value: (r) => r.sent_by },
            {
              id: "status",
              header: t("users.status"),
              value: (r) => (r.status === "sent" ? t("sentEmails.sent") : t("sentEmails.failed")),
            },
          ]}
        />
      )}
      {current && (
        <section className="panel" aria-label={current.subject}>
          <h2>{current.subject}</h2>
          <p className="muted">
            {t("email.from", { from: current.from })} · {t("email.to")}: {current.to}
            {current.cc && ` · ${t("email.cc")}: ${current.cc}`}
          </p>
          <p className="pre-line">{current.body}</p>
          {current.attachment_name && (
            <p>
              📎 {current.attachment_name} <span className="muted mono">SHA-256 {current.attachment_sha256}</span>
            </p>
          )}
          {current.error && <p className="form-error">{current.error}</p>}
        </section>
      )}
    </main>
  );
}
