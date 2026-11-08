import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { getMaintenance, maintenanceKey, recordMaintenance, type MaintenanceOverview, type RecordValues } from "../api/mouldMaintenance";
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

/** P3-10: moulds due for preventive maintenance, maintenance records and repair history. */
export default function MouldMaintenancePage() {
  const { t } = useTranslation();
  const [mould, setMould] = useState("");
  const found = useQuery({ queryKey: [...maintenanceKey, mould], queryFn: () => getMaintenance(mould) });
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("mouldMaint.title")}</h1>
      <p className="muted">{t("mouldMaint.help")}</p>
      <ErrorLine error={found.error} />
      {d && (
        <>
          <Moulds data={d} onHistory={setMould} />
          {d.can_record && <RecordForm data={d} />}
          <History data={d} mould={mould} onAll={() => setMould("")} />
        </>
      )}
    </main>
  );
}

function Moulds({ data, onHistory }: { data: MaintenanceOverview; onHistory: (code: string) => void }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("mouldMaint.moulds")}>
      <h2>{t("mouldMaint.moulds")}</h2>
      <div className="table-wrap">
        <table aria-label={t("mouldMaint.moulds")}>
          <thead>
            <tr>
              <th>{t("mouldMaint.mould")}</th>
              <th className="num">{t("mouldMaint.shots")}</th>
              <th className="num">{t("mouldMaint.since")}</th>
              <th className="num">{t("mouldMaint.interval")}</th>
              <th>{t("mouldMaint.state")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.moulds.map((m) => (
              <tr key={m.code}>
                <td>
                  {m.code} <span className="muted small">{m.name}</span>
                  {m.status === "maintenance" && <span className="muted small"> ({m.status_label})</span>}
                </td>
                <td className="num">{formatDecimal(String(m.shot_count))}</td>
                <td className="num">{formatDecimal(String(m.since))}</td>
                <td className="num">{m.interval === null ? "—" : formatDecimal(String(m.interval))}</td>
                <td className={m.state === "due" ? "form-error" : undefined}>
                  {m.state ? t(`mouldMaint.states.${m.state}`, { left: formatDecimal(String(m.left ?? 0)) }) : t("mouldMaint.noInterval")}
                </td>
                <td>
                  <button
                    type="button"
                    className="secondary small"
                    aria-label={t("mouldMaint.historyOf", { code: m.code })}
                    onClick={() => onHistory(m.code)}
                  >
                    {t("mouldMaint.history")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const EMPTY: RecordValues = {
  mould: "",
  kind: "planned",
  done_on: "",
  work_done: "",
  cost: "",
  done_by: "",
  by_workshop: false,
  status: "",
};

function RecordForm({ data }: { data: MaintenanceOverview }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<RecordValues>(EMPTY);
  const save = useMutation({
    mutationFn: () => recordMaintenance(values),
    onSuccess: () => {
      setValues(EMPTY);
      queryClient.invalidateQueries({ queryKey: maintenanceKey });
    },
  });
  const set = (key: keyof RecordValues) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <section className="panel" aria-label={t("mouldMaint.record")}>
      <h2>{t("mouldMaint.record")}</h2>
      <form className="form-grid" aria-label={t("mouldMaint.record")} onSubmit={submit}>
        <label>
          {t("mouldMaint.mould")}
          <select value={values.mould} onChange={set("mould")}>
            <option value="">{t("mouldMaint.choose")}</option>
            {data.moulds.map((m) => (
              <option key={m.code} value={m.code}>
                {m.code} {m.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("mouldMaint.kind")}
          <select value={values.kind} onChange={set("kind")}>
            <option value="planned">{t("mouldMaint.kinds.planned")}</option>
            <option value="repair">{t("mouldMaint.kinds.repair")}</option>
          </select>
        </label>
        <label>
          {t("mouldMaint.doneOn")}
          <input type="date" value={values.done_on} onChange={set("done_on")} />
        </label>
        <label>
          {t("mouldMaint.cost")}
          <input inputMode="decimal" value={values.cost} onChange={set("cost")} />
        </label>
        <label>
          {t("mouldMaint.doneBy")}
          <input value={values.done_by} onChange={set("done_by")} />
        </label>
        <label className="check">
          <input type="checkbox" checked={values.by_workshop} onChange={(e) => setValues({ ...values, by_workshop: e.target.checked })} />{" "}
          {t("mouldMaint.byWorkshop")}
        </label>
        <label>
          {t("mouldMaint.statusAfter")}
          <select value={values.status} onChange={set("status")}>
            <option value="">{t("mouldMaint.statusSame")}</option>
            <option value="maintenance">{t("mouldMaint.statusMaintenance")}</option>
            <option value="active">{t("mouldMaint.statusActive")}</option>
          </select>
        </label>
        <label className="wide">
          {t("mouldMaint.workDone")}
          <textarea value={values.work_done} onChange={set("work_done")} />
        </label>
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {t("mouldMaint.save")}
          </button>
        </div>
        <p className="muted wide">{t("mouldMaint.recordHelp")}</p>
        <div className="wide">
          <ErrorLine error={save.error} />
        </div>
      </form>
    </section>
  );
}

function History({ data, mould, onAll }: { data: MaintenanceOverview; mould: string; onAll: () => void }) {
  const { t } = useTranslation();
  const title = mould ? t("mouldMaint.historyFor", { code: mould }) : t("mouldMaint.allHistory");
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      {mould && (
        <button type="button" className="secondary" onClick={onAll}>
          {t("mouldMaint.showAll")}
        </button>
      )}
      {data.history.length === 0 ? (
        <p className="muted">{t("mouldMaint.none")}</p>
      ) : (
        <div className="table-wrap">
          <table aria-label={title}>
            <thead>
              <tr>
                <th>{t("mouldMaint.doneOn")}</th>
                <th>{t("mouldMaint.mould")}</th>
                <th>{t("mouldMaint.kind")}</th>
                <th className="num">{t("mouldMaint.shotsThen")}</th>
                <th>{t("mouldMaint.workDone")}</th>
                <th className="num">{t("mouldMaint.cost")}</th>
                <th>{t("mouldMaint.doneBy")}</th>
              </tr>
            </thead>
            <tbody>
              {data.history.map((h) => (
                <tr key={h.id}>
                  <td>{h.done_on}</td>
                  <td>{h.mould}</td>
                  <td>{h.kind_label}</td>
                  <td className="num">{formatDecimal(String(h.shot_count))}</td>
                  <td>{h.work_done}</td>
                  <td className="num">{formatDecimal(h.cost)}</td>
                  <td>
                    {h.done_by}
                    {h.by_workshop && <span className="muted small"> {t("mouldMaint.workshop")}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">{t("mouldMaint.totalCost", { cost: formatDecimal(data.total_cost) })}</p>
        </div>
      )}
    </section>
  );
}
