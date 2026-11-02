import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  addJournalFile,
  approveManualJournal,
  createManualJournal,
  deleteManualJournal,
  getManualJournal,
  journalFileUrl,
  mjKey,
  rejectManualJournal,
  removeJournalFile,
  returnManualJournal,
  submitManualJournal,
  updateManualJournal,
  type MJDetail,
  type MJInput,
} from "../api/manualJournals";
import JournalLines, { JournalTotals, linesFrom, toInputs, useJournalAccounts, type LineState } from "../components/JournalLines";
import { formatDecimal } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function today() {
  return new Date().toLocaleDateString("en-CA");
}

/** One manual journal (P2-01): entering it, the Director's approval, and what it posted. */
export default function ManualJournalPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const isNew = id === "new";
  const journal = useQuery({
    queryKey: [...mjKey, "one", id],
    queryFn: () => getManualJournal(Number(id)),
    enabled: !isNew,
  });
  const data = journal.data;

  return (
    <main className="page">
      <p>
        <Link to="/journals/manual">{t("mj.backToList")}</Link>
      </p>
      <h1>{isNew ? t("mj.new") : `${t("mj.one")} ${data?.number ?? ""}`}</h1>
      {isNew && <JournalForm />}
      {data && (
        <>
          <p className="muted">
            {t(`mj.statuses.${data.status}`)} · {data.entry_date} · {t("mj.enteredBy")} {data.created_by}
            {data.reverse_on && ` · ${t("mj.reversesOn", { date: data.reverse_on })}`}
            {data.recurring && (
              <>
                {" · "}
                {t("mj.fromRecurring")} <Link to={`/journals/recurring/${data.recurring.id}`}>{data.recurring.name}</Link>
              </>
            )}
            {data.journal_entry && (
              <>
                {" · "}
                {t("mj.postedAs")}{" "}
                <Link to={`/journal?q=${encodeURIComponent(data.journal_entry.number)}`} className="mono">
                  {data.journal_entry.number}
                </Link>
              </>
            )}
          </p>
          {data.can_edit ? <JournalForm key={`${data.id}-${data.total_debit}-${data.narration}`} journal={data} /> : <ReadOnly journal={data} />}
          <Files journal={data} />
          <Actions journal={data} />
        </>
      )}
      <ErrorLine error={journal.error} />
    </main>
  );
}

function JournalForm({ journal }: { journal?: MJDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accountList = useJournalAccounts();
  const [values, setValues] = useState({
    entry_date: journal?.entry_date ?? today(),
    narration: journal?.narration ?? "",
    reverse_next_month: Boolean(journal?.reverse_on),
  });
  const [lines, setLines] = useState<LineState[]>(linesFrom(journal?.lines));

  const save = useMutation({
    mutationFn: () => {
      const input: MJInput = { ...values, lines: toInputs(lines, accountList) };
      return journal ? updateManualJournal(journal.id, input) : createManualJournal(input);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...mjKey, "one", String(saved.id)], saved);
      void queryClient.invalidateQueries({ queryKey: [...mjKey, "list"] });
      if (!journal) navigate(`/journals/manual/${saved.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("mj.form")} onSubmit={submit}>
      <label>
        {t("mj.date")}
        <input type="date" value={values.entry_date} required onChange={(e) => setValues({ ...values, entry_date: e.target.value })} />
      </label>
      <label className="wide">
        {t("mj.narration")}
        <input value={values.narration} maxLength={500} required onChange={(e) => setValues({ ...values, narration: e.target.value })} />
      </label>
      <label className="wide">
        <input type="checkbox" checked={values.reverse_next_month} onChange={(e) => setValues({ ...values, reverse_next_month: e.target.checked })} />{" "}
        {t("mj.reverseNextMonth")}
      </label>

      <JournalLines lines={lines} setLines={setLines} accountList={accountList} />
      <div className="wide">
        <JournalTotals lines={lines} />
        <p className="muted">{t("mj.formHelp")}</p>
        <button type="submit" disabled={save.isPending}>
          {journal ? t("vouchers.saveDraft") : t("mj.makeDraft")}
        </button>
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function ReadOnly({ journal }: { journal: MJDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("mj.details")}>
      <p>{journal.narration}</p>
      <div className="table-wrap">
        <table aria-label={t("mj.lines")}>
          <thead>
            <tr>
              <th>{t("mj.account")}</th>
              <th>{t("vouchers.division")}</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("mj.debit")}</th>
              <th className="num">{t("mj.credit")}</th>
            </tr>
          </thead>
          <tbody>
            {journal.lines.map((l) => (
              <tr key={l.line_no}>
                <td>
                  <span className="mono">{l.account.number}</span> {l.account.name}
                  {l.supplier && <div className="muted">{`${l.supplier.code} ${l.supplier.name}`}</div>}
                </td>
                <td>{l.division ?? ""}</td>
                <td>{l.description}</td>
                <td className="num">{l.debit === "0.00" ? "" : formatDecimal(l.debit)}</td>
                <td className="num">{l.credit === "0.00" ? "" : formatDecimal(l.credit)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={3}>{t("vouchers.total")}</th>
              <th className="num">{formatDecimal(journal.total_debit)}</th>
              <th className="num">{formatDecimal(journal.total_credit)}</th>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function useDone() {
  const queryClient = useQueryClient();
  return (latest: MJDetail) => {
    queryClient.setQueryData([...mjKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...mjKey, "list"] });
  };
}

function Files({ journal }: { journal: MJDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const add = useMutation({ mutationFn: (file: File) => addJournalFile(journal.id, file), onSuccess: done });
  const remove = useMutation({ mutationFn: (file: number) => removeJournalFile(journal.id, file), onSuccess: done });
  if (!journal.can_edit && journal.attachments.length === 0) return null;
  return (
    <section className="panel" aria-label={t("mj.files")}>
      <h2>{t("mj.files")}</h2>
      <ul>
        {journal.attachments.map((a) => (
          <li key={a.id}>
            <a href={journalFileUrl(journal.id, a.id)} target="_blank" rel="noreferrer">
              {a.file_name}
            </a>{" "}
            <span className="muted">{a.uploaded_by}</span>{" "}
            {journal.can_edit && (
              <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate(a.id)}>
                {t("grn.removePhoto")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {journal.can_edit && (
        <label>
          {t("mj.addFile")}
          <input
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) add.mutate(file);
              e.target.value = "";
            }}
          />
        </label>
      )}
      <ErrorLine error={add.error ?? remove.error} />
    </section>
  );
}

function Actions({ journal }: { journal: MJDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const done = useDone();
  const [text, setText] = useState("");
  const act = useMutation({
    mutationFn: (call: () => Promise<MJDetail>) => call(),
    onSuccess: (latest) => {
      done(latest);
      setText("");
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteManualJournal(journal.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...mjKey, "list"] });
      navigate("/journals/manual");
    },
  });
  if (!journal.can_edit && !journal.can_approve && !journal.approval) return null;

  return (
    <section className="panel" aria-label={t("mj.actions")}>
      {journal.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => submitManualJournal(journal.id))}>
            {t("mj.send")}
          </button>{" "}
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("mj.delete")}
          </button>{" "}
          <span className="muted">{t("mj.sendHelp")}</span>
        </p>
      )}
      {journal.can_approve && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveManualJournal(journal.id, text))}>
            {t("mj.approve")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnManualJournal(journal.id, text))}>
            {t("salesOrders.sendBack")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => rejectManualJournal(journal.id, text))}>
            {t("mj.reject")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error ?? remove.error} />
      {journal.approval && journal.approval.history.length > 0 && (
        <ul className="changes" aria-label={t("salesOrders.approvalHistory")}>
          {journal.approval.history.map((h, i) => (
            <li key={i}>
              {h.at.slice(0, 16).replace("T", " ")} · {h.action_label} · {h.by}
              {h.reason ? ` · ${h.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
