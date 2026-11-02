import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { chartKey, listLedgerAccounts } from "../api/accounts";
import { listDivisions } from "../api/admin";
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
import { listPayees } from "../api/payees";
import SearchSelect from "../components/SearchSelect";
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

function today() {
  return new Date().toLocaleDateString("en-CA");
}

/** Exact totals of what is typed; anything that is not a number counts as nothing yet. */
function total(values: string[]): string {
  const clean = values.map((v) => v.replace(/,/g, "").trim()).filter((v) => /^\d+(\.\d{1,2})?$/.test(v));
  return sumDecimal(clean);
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

type LineState = { account: string; debit: string; credit: string; division: string; supplier: string; description: string };
const blankLine: LineState = { account: "", debit: "", credit: "", division: "", supplier: "", description: "" };

function JournalForm({ journal }: { journal?: MJDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false) });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const suppliers = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false) });
  const [values, setValues] = useState({ entry_date: journal?.entry_date ?? today(), narration: journal?.narration ?? "" });
  const [lines, setLines] = useState<LineState[]>(
    journal
      ? journal.lines.map((l) => ({
          account: String(l.account.id),
          debit: l.debit === "0.00" ? "" : l.debit,
          credit: l.credit === "0.00" ? "" : l.credit,
          division: l.division ?? "",
          supplier: l.supplier ? String(l.supplier.id) : "",
          description: l.description,
        }))
      : [{ ...blankLine }, { ...blankLine }],
  );
  const setLine = (index: number, change: Partial<LineState>) => setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const accountList = (accounts.data ?? []).filter((a) => a.is_active && !a.merged_into && a.account_type !== "accounts_receivable");
  const accountOptions = accountList.map((a) => ({ value: String(a.id), label: `${a.number ? `${a.number} ` : ""}${a.full_name}` }));
  const typeOf = (accountId: string) => accountList.find((a) => String(a.id) === accountId)?.account_type ?? "";
  const supplierOptions = (suppliers.data ?? []).map((s) => ({ value: String(s.id), label: `${s.code} ${s.name}` }));
  const debits = total(lines.map((l) => l.debit));
  const credits = total(lines.map((l) => l.credit));
  const difference = sumDecimal([debits, `-${credits}`]);

  const save = useMutation({
    mutationFn: () => {
      const input: MJInput = {
        ...values,
        lines: lines.map((l) => ({
          account: Number(l.account),
          debit: l.debit,
          credit: l.credit,
          division: l.division || null,
          supplier: typeOf(l.account) === "accounts_payable" && l.supplier ? Number(l.supplier) : null,
          description: l.description,
        })),
      };
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

      <div className="wide">
        <h2>{t("mj.lines")}</h2>
        {lines.map((l, index) => {
          const n = String(index + 1);
          return (
            <fieldset key={index} className="quote-line">
              <legend>{t("quotations.lineN", { n })}</legend>
              <div className="form-grid">
                <div className="wide">
                  <SearchSelect label={t("mj.accountOf", { n })} options={accountOptions} value={l.account} onChange={(value) => setLine(index, { account: value })} />
                </div>
                <label>
                  {t("mj.debit")}
                  <input inputMode="decimal" className="num" aria-label={t("mj.debitOf", { n })} value={l.debit} onChange={(e) => setLine(index, { debit: e.target.value })} />
                </label>
                <label>
                  {t("mj.credit")}
                  <input inputMode="decimal" className="num" aria-label={t("mj.creditOf", { n })} value={l.credit} onChange={(e) => setLine(index, { credit: e.target.value })} />
                </label>
                <label>
                  {t("vouchers.division")}
                  <select aria-label={t("mj.divisionOf", { n })} value={l.division} onChange={(e) => setLine(index, { division: e.target.value })}>
                    <option value="">—</option>
                    {(divisions.data ?? []).map((d) => (
                      <option key={d.code} value={d.code}>
                        {d.code} {d.name}
                      </option>
                    ))}
                  </select>
                </label>
                {typeOf(l.account) === "accounts_payable" && (
                  <div className="wide">
                    <SearchSelect label={t("mj.supplierOf", { n })} options={supplierOptions} value={l.supplier} onChange={(value) => setLine(index, { supplier: value })} />
                  </div>
                )}
                <label className="wide">
                  {t("quotations.description")}
                  <input aria-label={t("mj.descriptionOf", { n })} value={l.description} maxLength={500} onChange={(e) => setLine(index, { description: e.target.value })} />
                </label>
              </div>
              {lines.length > 2 && (
                <button type="button" className="small secondary" onClick={() => setLines((now) => now.filter((_, i) => i !== index))}>
                  {t("quotations.removeLine")}
                </button>
              )}
            </fieldset>
          );
        })}
        <button type="button" className="small secondary" onClick={() => setLines((now) => [...now, { ...blankLine }])}>
          {t("quotations.addLine")}
        </button>
      </div>
      <div className="wide">
        <p aria-label={t("mj.totals")}>
          {t("mj.debit")}: <strong>{formatDecimal(debits)}</strong> · {t("mj.credit")}: <strong>{formatDecimal(credits)}</strong>
          {difference !== "0.00" && <span className="form-error"> · {t("mj.outBy", { amount: formatDecimal(difference.replace("-", "")) })}</span>}
        </p>
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
