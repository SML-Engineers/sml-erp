import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  createRecurringJournal,
  FREQUENCIES,
  getRecurringJournal,
  LAST_DAY,
  rjKey,
  setRecurringActive,
  updateRecurringJournal,
  type Frequency,
  type RecurringJournal,
} from "../api/recurringJournals";
import JournalLines, { JournalTotals, linesFrom, toInputs, useJournalAccounts, type LineState } from "../components/JournalLines";
import { scheduleText } from "./RecurringJournalsPage";
import { factoryToday } from "../lib/time";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const DAYS = [...Array.from({ length: 28 }, (_, i) => i + 1), LAST_DAY];

/** One recurring journal template (P2-02). Each draft it makes goes through the normal
 * approval of a manual journal. */
export default function RecurringJournalPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const isNew = id === "new";
  const template = useQuery({
    queryKey: [...rjKey, "one", id],
    queryFn: () => getRecurringJournal(Number(id)),
    enabled: !isNew,
  });
  const data = template.data;

  return (
    <main className="page">
      <p>
        <Link to="/journals/recurring">{t("rj.backToList")}</Link>
      </p>
      <h1>{isNew ? t("rj.new") : data?.name ?? ""}</h1>
      {isNew && <TemplateForm />}
      {data && (
        <>
          <p className="muted">
            {scheduleText(t, data)} · {data.is_active ? t("rj.nextOn", { date: data.next_date }) : t("rj.stopped")} · {t("rj.owner")} {data.created_by}
          </p>
          <Switch template={data} />
          <TemplateForm key={`${data.id}-${data.amount}-${data.name}-${data.next_date}`} template={data} />
          <Made template={data} />
        </>
      )}
      <ErrorLine error={template.error} />
    </main>
  );
}

function TemplateForm({ template }: { template?: RecurringJournal }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accountList = useJournalAccounts();
  const [values, setValues] = useState({
    name: template?.name ?? "",
    narration: template?.narration ?? "",
    frequency: template?.frequency ?? ("monthly" as Frequency),
    day_of_month: template?.day_of_month ?? LAST_DAY,
    start_date: template?.start_date ?? factoryToday(),
    end_date: template?.end_date ?? "",
    reverse_next_month: template?.reverse_next_month ?? false,
  });
  const [lines, setLines] = useState<LineState[]>(linesFrom(template?.lines));

  const save = useMutation({
    mutationFn: () => {
      const input = { ...values, end_date: values.end_date || null, lines: toInputs(lines, accountList) };
      return template ? updateRecurringJournal(template.id, input) : createRecurringJournal(input);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...rjKey, "one", String(saved.id)], saved);
      void queryClient.invalidateQueries({ queryKey: [...rjKey, "list"] });
      if (!template) navigate(`/journals/recurring/${saved.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("rj.form")} onSubmit={submit}>
      <label>
        {t("rj.name")}
        <input value={values.name} maxLength={100} required onChange={(e) => setValues({ ...values, name: e.target.value })} />
      </label>
      <label className="wide">
        {t("mj.narration")}
        <input value={values.narration} maxLength={400} required onChange={(e) => setValues({ ...values, narration: e.target.value })} />
      </label>
      <label>
        {t("rj.frequency")}
        <select value={values.frequency} onChange={(e) => setValues({ ...values, frequency: e.target.value as Frequency })}>
          {FREQUENCIES.map((f) => (
            <option key={f} value={f}>
              {t(`rj.frequencies.${f}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("rj.day")}
        <select value={values.day_of_month} onChange={(e) => setValues({ ...values, day_of_month: Number(e.target.value) })}>
          {DAYS.map((d) => (
            <option key={d} value={d}>
              {d === LAST_DAY ? t("rj.lastDay") : d}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("rj.start")}
        <input type="date" value={values.start_date} required onChange={(e) => setValues({ ...values, start_date: e.target.value })} />
      </label>
      <label>
        {t("rj.end")}
        <input type="date" value={values.end_date} onChange={(e) => setValues({ ...values, end_date: e.target.value })} />
      </label>
      <label className="wide">
        <input type="checkbox" checked={values.reverse_next_month} onChange={(e) => setValues({ ...values, reverse_next_month: e.target.checked })} />{" "}
        {t("mj.reverseNextMonth")}
      </label>

      <JournalLines lines={lines} setLines={setLines} accountList={accountList} />
      <div className="wide">
        <JournalTotals lines={lines} />
        <p className="muted">{t("rj.formHelp")}</p>
        <button type="submit" disabled={save.isPending}>
          {template ? t("rj.save") : t("rj.make")}
        </button>
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function Switch({ template }: { template: RecurringJournal }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const change = useMutation({
    mutationFn: () => setRecurringActive(template.id, !template.is_active),
    onSuccess: (saved) => {
      queryClient.setQueryData([...rjKey, "one", String(saved.id)], saved);
      void queryClient.invalidateQueries({ queryKey: [...rjKey, "list"] });
    },
  });
  return (
    <p>
      <button type="button" className="secondary" disabled={change.isPending} onClick={() => change.mutate()}>
        {template.is_active ? t("rj.stop") : t("rj.restart")}
      </button>
      <ErrorLine error={change.error} />
    </p>
  );
}

function Made({ template }: { template: RecurringJournal }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("rj.made")}>
      <h2>{t("rj.made")}</h2>
      {template.made.length === 0 ? (
        <p className="muted">{t("rj.noneMade")}</p>
      ) : (
        <ul>
          {template.made.map((j) => (
            <li key={j.id}>
              <Link to={`/journals/manual/${j.id}`} className="mono">
                {j.number}
              </Link>{" "}
              · {j.entry_date} · {t(`mj.statuses.${j.status}`)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
