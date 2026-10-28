import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { splitAddresses, type EmailDraft, type EmailToSend } from "../api/documentEmail";

/**
 * The Email form every document and report uses (spec 3B): filled in from the Admin's
 * default message, and everything can be edited before sending. The document module passes
 * the draft and sends what comes back to its own send endpoint.
 */
export default function SendEmailForm(props: {
  draft: EmailDraft;
  attachmentName?: string;
  onSend: (email: EmailToSend) => Promise<unknown>;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const [to, setTo] = useState(props.draft.to.join(", "));
  const [cc, setCc] = useState(props.draft.cc.join(", "));
  const [subject, setSubject] = useState(props.draft.subject);
  const [body, setBody] = useState(props.draft.body);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setError(null);
    try {
      await props.onSend({ to: splitAddresses(to), cc: splitAddresses(cc), subject, body });
      setSent(true);
    } catch (caught) {
      setError(caught);
    } finally {
      setSending(false);
    }
  }

  if (!props.draft.ready) {
    return (
      <p className="form-error" role="alert">
        {t("email.notReady")}
      </p>
    );
  }
  if (sent) {
    return (
      <p className="notice" role="status">
        {t("email.sent", { to })}
      </p>
    );
  }
  return (
    <form className="form-grid" aria-label={t("email.title")} onSubmit={submit}>
      <p className="wide muted">{t("email.from", { from: props.draft.from })}</p>
      <label className="wide">
        {t("email.to")}
        <input value={to} required onChange={(e) => setTo(e.target.value)} />
      </label>
      <label className="wide">
        {t("email.cc")}
        <input value={cc} onChange={(e) => setCc(e.target.value)} />
      </label>
      <label className="wide">
        {t("email.subject")}
        <input value={subject} required maxLength={200} onChange={(e) => setSubject(e.target.value)} />
      </label>
      <label className="wide">
        {t("email.body")}
        <textarea value={body} required rows={12} onChange={(e) => setBody(e.target.value)} />
      </label>
      {props.attachmentName && <p className="wide">📎 {props.attachmentName}</p>}
      <div className="wide row-actions">
        <button type="submit" disabled={sending}>
          {t("email.send")}
        </button>
        {props.onCancel && (
          <button type="button" className="secondary" onClick={props.onCancel}>
            {t("email.cancel")}
          </button>
        )}
      </div>
      {Boolean(error) && (
        <p className="wide form-error" role="alert">
          {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
        </p>
      )}
    </form>
  );
}
