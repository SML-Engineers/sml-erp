import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  decidePasswordReset,
  issuePasswordReset,
  listPasswordResets,
  requestPasswordReset,
  type PasswordResetRow,
} from "../api/admin";
import { ApiError } from "../api/client";

/** Password reset on a user's page (owner's decision, 31 Oct 2026): the Admin asks with a
 * reason, the Director approves or refuses, then the Admin makes a temporary password that is
 * shown once. */
export default function PasswordResetPanel({ userId, name }: { userId: number; name: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["password-resets", userId];
  const data = useQuery({ queryKey: key, queryFn: () => listPasswordResets(userId) });
  const [reason, setReason] = useState("");
  const [authenticator, setAuthenticator] = useState(false);
  const [decisionReason, setDecisionReason] = useState("");
  const [shown, setShown] = useState<string | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const ask = useMutation({
    mutationFn: () => requestPasswordReset(userId, reason, authenticator),
    onSuccess: () => {
      setReason("");
      setAuthenticator(false);
      refresh();
    },
  });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) => decidePasswordReset(id, approve, decisionReason),
    onSuccess: () => {
      setDecisionReason("");
      refresh();
    },
  });
  const issue = useMutation({
    mutationFn: (id: number) => issuePasswordReset(id),
    onSuccess: (made) => {
      setShown(made.temporary_password);
      refresh();
    },
  });
  const error = ask.error ?? decide.error ?? issue.error;
  const rows = data.data?.resets ?? [];
  const open = rows.find((r) => r.status === "waiting" || r.status === "approved");
  if (!data.data || (!data.data.can_request && rows.length === 0)) return null;

  return (
    <section className="panel" aria-label={t("resets.title")}>
      <h2>{t("resets.title")}</h2>
      <p className="muted">{t("resets.help")}</p>
      {shown && (
        <p className="notice" role="status">
          {t("resets.shown", { name })} <code>{shown}</code>
        </p>
      )}
      {data.data.can_request && !open && (
        <div className="inline-form">
          <label>
            {t("resets.reason")}
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="check">
            <input type="checkbox" checked={authenticator} onChange={(e) => setAuthenticator(e.target.checked)} /> {t("resets.withAuthenticator")}
          </label>
          <button type="button" disabled={ask.isPending} onClick={() => ask.mutate()}>
            {t("resets.request")}
          </button>
        </div>
      )}
      {open?.can_decide && (
        <div className="inline-form">
          <label>
            {t("resets.decisionReason")}
            <input value={decisionReason} maxLength={500} onChange={(e) => setDecisionReason(e.target.value)} />
          </label>
          <button type="button" disabled={decide.isPending} onClick={() => decide.mutate({ id: open.id, approve: true })}>
            {t("resets.approve")}
          </button>
          <button type="button" className="secondary" disabled={decide.isPending} onClick={() => decide.mutate({ id: open.id, approve: false })}>
            {t("resets.refuse")}
          </button>
        </div>
      )}
      {open?.can_issue && (
        <p>
          <button type="button" disabled={issue.isPending} onClick={() => issue.mutate(open.id)}>
            {t("resets.issue")}
          </button>{" "}
          <span className="muted">{t("resets.issueHelp")}</span>
        </p>
      )}
      {error ? (
        <p className="form-error" role="alert">
          {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
        </p>
      ) : null}
      {rows.length > 0 && (
        <ul className="changes" aria-label={t("resets.history")}>
          {rows.map((r: PasswordResetRow) => (
            <li key={r.id}>
              {r.requested_at.slice(0, 16).replace("T", " ")} · {t(`resets.statuses.${r.status}`)}
              {r.with_authenticator ? ` · ${t("resets.andAuthenticator")}` : ""} · {t("resets.askedBy", { name: r.requested_by })}: {r.reason}
              {r.decided_by ? ` · ${t("resets.decidedBy", { name: r.decided_by })}` : ""}
              {r.decision_reason ? `: ${r.decision_reason}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
