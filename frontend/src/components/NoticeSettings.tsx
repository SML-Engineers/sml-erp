import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { askNoticeChange, getNoticeAdmin, noticeAdminKey, withdrawNotice, type NoticeAdmin } from "../api/notice";
import { formatDateTime } from "../lib/time";

/** The top-bar notice on Security and logging (owner, 21 Nov 2026). The Admin asks to switch it
 * on or off or to change the words, with a reason; a Director approves it in Access to confirm.
 * The server checks who may do what. */
export default function NoticeSettings({ canChange }: { canChange: boolean }) {
  const data = useQuery({ queryKey: noticeAdminKey, queryFn: getNoticeAdmin });
  if (!data.data) return null;
  return <NoticeForm data={data.data} canChange={canChange} key={data.data.waiting?.id ?? "none"} />;
}

function NoticeForm({ data, canChange }: { data: NoticeAdmin; canChange: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const words = data.in_force ?? data.defaults;
  const [textEn, setTextEn] = useState(words.text_en || data.defaults.text_en);
  const [textSi, setTextSi] = useState(words.text_si || data.defaults.text_si);
  const [reason, setReason] = useState("");
  const [done, setDone] = useState("");
  const refresh = (message: string) => {
    setDone(message);
    setReason("");
    void queryClient.invalidateQueries({ queryKey: noticeAdminKey });
  };
  const ask = useMutation({
    mutationFn: (show: boolean) => askNoticeChange({ show, text_en: textEn, text_si: textSi, reason }),
    onSuccess: () => refresh(t("notice.asked")),
  });
  const withdraw = useMutation({
    mutationFn: (id: number) => withdrawNotice(id),
    onSuccess: () => refresh(t("notice.withdrawn")),
  });
  const error = ask.error ?? withdraw.error;
  const { current, waiting } = data;

  return (
    <section className="panel" aria-label={t("notice.title")}>
      <h2>{t("notice.title")}</h2>
      <p className="muted">{t("notice.help")}</p>
      <p role="status">
        <strong>{current.show ? t("notice.isOn") : t("notice.isOff")}</strong>
      </p>
      {current.show && (
        <div className="top-notice">
          <p lang="en">{current.text_en}</p>
          <p lang="si">{current.text_si}</p>
        </div>
      )}
      {done && <p className="notice">{done}</p>}
      {waiting ? (
        <div className="notice notice-warn" aria-label={t("notice.waiting")}>
          <strong>{t("notice.waiting")}</strong>: {waiting.show ? t("notice.switchOnAsked") : t("notice.switchOffAsked")} ·{" "}
          {waiting.requested_by} <span className="muted">{formatDateTime(waiting.requested_at)}</span> · {waiting.reason}
          {waiting.show && (
            <>
              <br />
              <span lang="en">{waiting.text_en}</span>
              <br />
              <span lang="si">{waiting.text_si}</span>
            </>
          )}
          {canChange && (
            <p>
              <button type="button" className="secondary" disabled={withdraw.isPending} onClick={() => withdraw.mutate(waiting.id)}>
                {t("notice.withdraw")}
              </button>
            </p>
          )}
        </div>
      ) : (
        canChange && (
          <div className="form-grid">
            <label>
              {t("notice.english")}
              <input value={textEn} maxLength={200} onChange={(e) => setTextEn(e.target.value)} />
            </label>
            <label>
              {t("notice.sinhala")}
              <input value={textSi} maxLength={200} lang="si" onChange={(e) => setTextSi(e.target.value)} />
            </label>
            <label>
              {t("security.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <p className="row-actions">
              <button
                type="button"
                disabled={ask.isPending || !reason.trim() || !textEn.trim() || !textSi.trim()}
                onClick={() => ask.mutate(true)}
              >
                {current.show ? t("notice.askChange") : t("notice.askOn")}
              </button>
              {current.show && (
                <button type="button" className="secondary" disabled={ask.isPending || !reason.trim()} onClick={() => ask.mutate(false)}>
                  {t("notice.askOff")}
                </button>
              )}
            </p>
          </div>
        )
      )}
      {error instanceof ApiError && error.detail && (
        <p className="form-error" role="alert">
          {error.detail}
        </p>
      )}
      {data.history.length > 0 && (
        <details>
          <summary>{t("notice.history")}</summary>
          <ul>
            {data.history.map((c) => (
              <li key={c.id}>
                {formatDateTime(c.requested_at)} · {c.show ? t("notice.switchOnAsked") : t("notice.switchOffAsked")} · {c.requested_by}:{" "}
                {c.reason} · <strong>{c.status_label}</strong>
                {c.decided_by && ` (${c.decided_by}${c.decision_reason ? `: ${c.decision_reason}` : ""})`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
