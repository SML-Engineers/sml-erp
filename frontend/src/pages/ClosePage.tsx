import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { closeKey, closeMonth, getChecklist, getYear, tickItem, yearAction, type ChecklistItem } from "../api/close";
import { formatDecimal } from "../lib/decimal";

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Month-end checklist and year-end close (P2-23). */
export default function ClosePage() {
  const { t } = useTranslation();
  return (
    <main className="page">
      <h1>{t("close.title")}</h1>
      <p className="muted">{t("close.help")}</p>
      <MonthEnd />
      <YearEnd />
    </main>
  );
}

function MonthEnd() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(lastMonth());
  const list = useQuery({ queryKey: [...closeKey, "month", month], queryFn: () => getChecklist(month) });
  const close = useMutation({
    mutationFn: () => closeMonth(month),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: closeKey }),
  });
  const data = list.data;
  return (
    <section className="panel" aria-label={t("close.monthEnd")}>
      <h2>{t("close.monthEnd")}</h2>
      <div className="toolbar">
        <label>
          {t("close.month")}
          <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        </label>
      </div>
      <ErrorLine error={list.error} />
      {data && (
        <>
          {data.is_closed && <p className="badge">{t("close.monthClosed")}</p>}
          <ul className="checklist">
            {data.items.map((item) => (
              <ItemRow key={item.key} month={month} item={item} canTick={data.can_tick && !data.is_closed} />
            ))}
          </ul>
          {data.can_close && !data.is_closed && (
            <button type="button" disabled={!data.ready || close.isPending} onClick={() => close.mutate()}>
              {t("close.closeMonth", { month })}
            </button>
          )}
          {!data.ready && !data.is_closed && <p className="muted">{t("close.notReady")}</p>}
          <ErrorLine error={close.error} />
        </>
      )}
    </section>
  );
}

function ItemRow({ month, item, canTick }: { month: string; item: ChecklistItem; canTick: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const tick = useMutation({
    mutationFn: () => tickItem(month, item.key, note),
    onSuccess: (got) => {
      setNote("");
      queryClient.setQueryData([...closeKey, "month", month], got);
    },
  });
  return (
    <li aria-label={item.label}>
      <strong>{item.done ? "✓" : "○"}</strong> {item.label}
      <div className="muted">
        {item.note ? t("close.tickedBy", { by: item.ticked_by, note: item.note }) : item.detail}
      </div>
      {!item.done && canTick && (
        <div className="inline-form">
          <input
            aria-label={t("close.noteFor", { item: item.label })}
            placeholder={item.key === "accruals" ? t("close.accrualsHint") : t("close.otherHint")}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="button" className="small" disabled={tick.isPending} onClick={() => tick.mutate()}>
            {t("close.tick")}
          </button>
        </div>
      )}
      <ErrorLine error={tick.error} />
    </li>
  );
}

function YearEnd() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [year, setYear] = useState<number | undefined>(undefined);
  const [reason, setReason] = useState("");
  const info = useQuery({ queryKey: [...closeKey, "year", year ?? "last"], queryFn: () => getYear(year) });
  const data = info.data;
  const act = useMutation({
    mutationFn: (action: "close" | "reopen") => yearAction(data!.year, action, reason),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: closeKey });
    },
  });
  return (
    <section className="panel" aria-label={t("close.yearEnd")}>
      <h2>{t("close.yearEnd")}</h2>
      <p className="muted">{t("close.yearHelp")}</p>
      <div className="toolbar">
        <label>
          {t("close.yearStarting")}
          <input
            inputMode="numeric"
            placeholder={data ? String(data.year) : ""}
            onChange={(e) => {
              const v = e.target.value.replace(/\D/g, "");
              setYear(v.length === 4 ? Number(v) : undefined);
            }}
          />
        </label>
      </div>
      <ErrorLine error={info.error} />
      {data && (
        <>
          <p>
            <strong>{data.label}</strong> ·{" "}
            {data.closed
              ? t("close.yearClosed")
              : data.open_months.length
                ? t("close.monthsOpen", { months: data.open_months.join(", ") })
                : t("close.yearReady")}
          </p>
          {data.can_close && (
            <div className="inline-form">
              {data.closed && (
                <input aria-label={t("close.reopenReason")} placeholder={t("close.reopenReason")} value={reason} onChange={(e) => setReason(e.target.value)} />
              )}
              {data.closed ? (
                <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("reopen")}>
                  {t("close.reopenYear")}
                </button>
              ) : (
                <button type="button" disabled={act.isPending || data.open_months.length > 0} onClick={() => act.mutate("close")}>
                  {t("close.closeYear", { label: data.label })}
                </button>
              )}
            </div>
          )}
          <ErrorLine error={act.error} />
          {data.history.length > 0 && (
            <ul>
              {data.history.map((h) => (
                <li key={h.entry}>
                  {t("close.historyLine", {
                    entry: h.entry,
                    date: h.entry_date,
                    profit: formatDecimal(h.profit),
                    by: h.closed_by,
                  })}
                  {h.reopened && ` ${t("close.reopenedLine", { by: h.reopened_by, reason: h.reopen_reason, entry: h.reopen_entry })}`}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
