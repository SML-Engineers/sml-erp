import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { openingTemplateUrl, type OSCheck, type OSDetail } from "../api/openingStock";
import { formatDecimal } from "../lib/decimal";

function today() {
  return new Date().toLocaleDateString("en-CA");
}

/** The Excel sheet of the counted stock: checked first, then loaded as a draft (or into one). */
export default function OpeningStockUpload({
  send,
  onLoaded,
  start,
}: {
  send: (file: File, countDate: string, notes: string, dryRun: boolean) => Promise<OSDetail | OSCheck>;
  onLoaded: (saved: OSDetail) => void;
  start?: { count_date: string; notes: string };
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [countDate, setCountDate] = useState(start?.count_date ?? today());
  const [notes, setNotes] = useState(start?.notes ?? "");
  const [checked, setChecked] = useState<OSCheck | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => send(file!, countDate, notes, dryRun),
    onSuccess: (reply) => {
      if ("dry_run" in reply) setChecked(reply);
      else {
        setChecked(null);
        onLoaded(reply);
      }
    },
    onError: () => setChecked(null),
  });
  const errors = run.error instanceof ApiError ? ((run.error.body as { errors?: string[] } | null)?.errors ?? []) : [];

  function submit(event: FormEvent) {
    event.preventDefault();
    run.mutate(false);
  }

  return (
    <form className="panel form-grid" aria-label={t("os.load")} onSubmit={submit}>
      <p className="wide">
        <a href={openingTemplateUrl}>{t("os.template")}</a>
      </p>
      <label>
        {t("os.countDate")}
        <input type="date" value={countDate} required onChange={(e) => setCountDate(e.target.value)} />
      </label>
      <label>
        {t("os.file")}
        <input
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setChecked(null);
          }}
        />
      </label>
      <label className="wide">
        {t("os.notes")}
        <input value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="wide">
        <button type="button" className="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
          {t("os.check")}
        </button>{" "}
        <button type="submit" disabled={!file || run.isPending}>
          {start ? t("os.loadAgain") : t("os.make")}
        </button>
        {checked && <p role="status">{t("os.checked", { rows: checked.rows, value: formatDecimal(checked.value) })}</p>}
        {run.error && (
          <div className="form-error" role="alert">
            <p>{run.error instanceof ApiError && run.error.detail ? run.error.detail : t("common.error")}</p>
            {errors.length > 0 && (
              <ul aria-label={t("os.errors")}>
                {errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </form>
  );
}
