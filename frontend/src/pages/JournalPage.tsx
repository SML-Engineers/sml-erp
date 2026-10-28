import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { getJournal, journalKey, listJournal, reverseJournal, type JournalFilter } from "../api/journal";
import DataTable from "../components/DataTable";
import { formatDecimal, sumDecimal } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Posted journal entries. Entries never change; a mistake is corrected by a reversal. */
export default function JournalPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<JournalFilter>({});
  const [filter, setFilter] = useState<JournalFilter>({});
  const [selected, setSelected] = useState<number | null>(null);
  const entries = useQuery({ queryKey: [...journalKey, filter], queryFn: () => listJournal(filter) });
  const canReverse = can(me.access, "accounting", "manage");
  const field = (key: keyof JournalFilter) => (value: string) => setDraft((now) => ({ ...now, [key]: value }));

  return (
    <main className="page">
      <h1>{t("journal.title")}</h1>
      <p className="muted">{t("journal.help")}</p>
      <form
        className="toolbar"
        aria-label={t("journal.filter")}
        onSubmit={(e) => {
          e.preventDefault();
          setFilter(draft);
        }}
      >
        <label>
          {t("journal.from")}
          <input type="date" value={draft.from ?? ""} onChange={(e) => field("from")(e.target.value)} />
        </label>
        <label>
          {t("journal.to")}
          <input type="date" value={draft.to ?? ""} onChange={(e) => field("to")(e.target.value)} />
        </label>
        <label>
          {t("journal.search")}
          <input value={draft.q ?? ""} onChange={(e) => field("q")(e.target.value)} />
        </label>
        <button type="submit">{t("journal.show")}</button>
      </form>

      {entries.data && (
        <DataTable
          label={t("journal.title")}
          rows={entries.data}
          rowKey={(e) => e.id}
          emptyText={t("journal.none")}
          columns={[
            {
              id: "number",
              header: t("journal.number"),
              value: (e) => e.number,
              cell: (e) => (
                <button type="button" className="link-button mono" onClick={() => setSelected(e.id)}>
                  {e.number}
                </button>
              ),
            },
            { id: "date", header: t("journal.date"), value: (e) => e.entry_date },
            { id: "narration", header: t("journal.narration"), value: (e) => e.narration },
            { id: "source", header: t("journal.source"), value: (e) => e.source_type },
            {
              id: "amount",
              header: t("journal.amount"),
              value: (e) => e.amount,
              cell: (e) => <span className="num">{formatDecimal(e.amount)}</span>,
            },
            {
              id: "status",
              header: t("users.status"),
              value: (e) =>
                e.reversed_by
                  ? t("journal.reversedBy", { number: e.reversed_by.number })
                  : e.reversal_of
                    ? t("journal.reversalOf", { number: e.reversal_of.number })
                    : "",
            },
          ]}
        />
      )}
      <ErrorLine error={entries.error} />
      {selected !== null && <EntryPanel key={selected} id={selected} canReverse={canReverse} />}
    </main>
  );
}

function EntryPanel({ id, canReverse }: { id: number; canReverse: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const entry = useQuery({ queryKey: [...journalKey, "entry", id], queryFn: () => getJournal(id) });
  const [reason, setReason] = useState("");
  const reverse = useMutation({
    mutationFn: () => reverseJournal(id, reason),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: journalKey }),
  });
  if (!entry.data) return <ErrorLine error={entry.error} />;
  const e = entry.data;
  const title = `${e.number} · ${e.entry_date}`;

  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <p>{e.narration}</p>
      <p className="muted">
        {t("journal.postedBy", { name: e.posted_by })}
        {e.source_id && ` · ${e.source_type} ${e.source_id}`}
      </p>
      <div className="table-wrap">
        <table aria-label={t("journal.lines")}>
          <thead>
            <tr>
              <th>{t("journal.account")}</th>
              <th>{t("journal.division")}</th>
              <th>{t("journal.description")}</th>
              <th className="num">{t("journal.debit")}</th>
              <th className="num">{t("journal.credit")}</th>
            </tr>
          </thead>
          <tbody>
            {e.lines.map((line) => (
              <tr key={line.line_no}>
                <td>
                  {`${line.account.number} ${line.account.name}`.trim()}
                  {line.supplier && <span className="muted"> · {line.supplier.name}</span>}
                </td>
                <td>{line.division ?? ""}</td>
                <td>{line.description}</td>
                <td className="num">{line.debit === "0.00" ? "" : formatDecimal(line.debit)}</td>
                <td className="num">{line.credit === "0.00" ? "" : formatDecimal(line.credit)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={3}>{t("journal.total")}</th>
              <th className="num">{formatDecimal(sumDecimal(e.lines.map((l) => l.debit)))}</th>
              <th className="num">{formatDecimal(sumDecimal(e.lines.map((l) => l.credit)))}</th>
            </tr>
          </tfoot>
        </table>
      </div>
      {e.reversed_by && <p className="notice">{t("journal.reversedBy", { number: e.reversed_by.number })}</p>}
      {canReverse && !e.reversed_by && !e.reversal_of && (
        <form
          className="inline-form"
          aria-label={t("journal.reverse")}
          onSubmit={(event) => {
            event.preventDefault();
            reverse.mutate();
          }}
        >
          <label>
            {t("access.reason")}
            <input value={reason} required onChange={(event) => setReason(event.target.value)} />
          </label>
          <button type="submit" className="danger" disabled={reverse.isPending}>
            {t("journal.reverse")}
          </button>
          <p className="muted">{t("journal.reverseHelp")}</p>
        </form>
      )}
      <ErrorLine error={reverse.error} />
    </section>
  );
}
