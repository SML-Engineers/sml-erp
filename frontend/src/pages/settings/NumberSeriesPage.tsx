import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  listNumberSeries,
  numberSeriesKey,
  previewNumberSeries,
  updateNumberSeries,
  type NextNumber,
  type NumberSeries,
  type ResetPeriod,
} from "../../api/organisation";
import DataTable from "../../components/DataTable";

const RESETS: ResetPeriod[] = ["daily", "monthly", "yearly", "never"];
const TOKENS = ["{PP}", "{YY}", "{YYYY}", "{MM}", "{DD}", "{XXX}", "{XXXX}"];

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

function NextNumbers({ numbers }: { numbers: NextNumber[] }) {
  return (
    <ul className="changes">
      {numbers.map((n) => (
        <li key={n.division ?? "all"}>
          <code>{n.next}</code>
        </li>
      ))}
    </ul>
  );
}

export default function NumberSeriesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const series = useQuery({ queryKey: numberSeriesKey, queryFn: listNumberSeries });
  const canManage = can(me.access, "settings", "manage");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = series.data?.find((s) => s.id === selectedId) ?? null;

  return (
    <main className="page">
      <h1>{t("numbering.title")}</h1>
      <p className="muted">{t("numbering.help")}</p>

      {selected && canManage && (
        <EditSeries key={selected.id} series={selected} onDone={() => setSelectedId(null)} />
      )}

      {series.isPending && <p className="muted">{t("common.loading")}</p>}
      {series.isError && <p className="form-error">{t("common.error")}</p>}
      {series.data && (
        <DataTable
          label={t("numbering.title")}
          rows={series.data}
          rowKey={(s) => s.id}
          pageSize="all"
          searchable={false}
          columns={[
            { id: "name", header: t("numbering.document"), value: (s) => s.name },
            {
              id: "format",
              header: t("numbering.format"),
              value: (s) => s.format,
              cell: (s) => <code>{s.format}</code>,
            },
            {
              id: "reset",
              header: t("numbering.reset"),
              value: (s) => t(`numbering.resets.${s.reset_period}`),
            },
            {
              id: "next",
              header: t("numbering.next"),
              sortable: false,
              value: (s) => s.next_numbers.map((n) => n.next).join(" "),
              cell: (s) => <NextNumbers numbers={s.next_numbers} />,
            },
            ...(canManage
              ? [
                  {
                    id: "edit",
                    header: "",
                    sortable: false,
                    value: () => "",
                    cell: (s: NumberSeries) => (
                      <button
                        type="button"
                        className="small secondary"
                        onClick={() => setSelectedId(s.id)}
                        aria-label={t("numbering.editOne", { name: s.name })}
                      >
                        {t("divisions.edit")}
                      </button>
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}
    </main>
  );
}

function EditSeries({ series, onDone }: { series: NumberSeries; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [format, setFormat] = useState(series.format);
  const [reset, setReset] = useState<ResetPeriod>(series.reset_period);
  const [reason, setReason] = useState("");

  const check = useMutation({
    mutationFn: () => previewNumberSeries(series.id, { format, reset_period: reset }),
  });
  const save = useMutation({
    mutationFn: () => updateNumberSeries(series.id, { format, reset_period: reset, reason }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: numberSeriesKey });
      onDone();
    },
  });
  const error = save.error ?? check.error;

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  function changed(next: () => void) {
    next();
    check.reset();
  }

  return (
    <section className="panel" aria-label={t("numbering.editOne", { name: series.name })}>
      <h2>{t("numbering.editOne", { name: series.name })}</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>
          {t("numbering.format")}
          <input
            className="mono"
            value={format}
            required
            onChange={(e) => changed(() => setFormat(e.target.value))}
          />
        </label>
        <label>
          {t("numbering.reset")}
          <select
            value={reset}
            onChange={(e) => changed(() => setReset(e.target.value as ResetPeriod))}
          >
            {RESETS.map((r) => (
              <option key={r} value={r}>
                {t(`numbering.resets.${r}`)}
              </option>
            ))}
          </select>
        </label>
        <div className="wide">
          <p className="muted">{t("numbering.tokens")}</p>
          <div className="row-actions">
            {TOKENS.map((token) => (
              <button
                key={token}
                type="button"
                className="small secondary mono"
                onClick={() => changed(() => setFormat((f) => f + token))}
              >
                {token}
              </button>
            ))}
          </div>
        </div>
        <label className="wide">
          {t("access.reason")}
          <input value={reason} required onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="wide row-actions">
          <button
            type="button"
            className="secondary"
            disabled={check.isPending}
            onClick={() => check.mutate()}
          >
            {t("numbering.check")}
          </button>
          <button type="submit" disabled={save.isPending}>
            {t("divisions.save")}
          </button>
          <button type="button" className="secondary" onClick={onDone}>
            {t("access.cancel")}
          </button>
        </div>
      </form>
      {check.data && (
        <div className="notice" role="status">
          {t("numbering.wouldGive")} <NextNumbers numbers={check.data.next_numbers} />
        </div>
      )}
      <p className="muted">{t("numbering.neverReused")}</p>
      {error && (
        <p className="form-error" role="alert">
          {errorText(error, t("common.error"))}
        </p>
      )}
    </section>
  );
}
