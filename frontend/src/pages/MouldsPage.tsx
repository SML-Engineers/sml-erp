import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  addMould,
  changeMould,
  getMoulds,
  importMoulds,
  mouldExportUrl,
  mouldLabelsUrl,
  mouldsKey,
  type ImportResult,
  type Mould,
  type MouldList,
  type MouldValues,
} from "../api/moulds";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const lines = error instanceof ApiError ? [error.detail, ...(((error.body as { errors?: string[] }) ?? {}).errors ?? [])] : [];
  const shown = lines.filter(Boolean);
  return (
    <div className="form-error" role="alert">
      {shown.length ? shown.map((line) => <div key={line}>{line}</div>) : t("common.error")}
    </div>
  );
}

const EMPTY: MouldValues = {
  code: "",
  name: "",
  division: "IM",
  parts: "",
  owner: "company",
  customer: "",
  asset: "",
  cycle_time_s: "",
  shot_weight_g: "",
  runner_weight_g: "",
  tonnage_t: "",
  width_mm: "",
  height_mm: "",
  thickness_mm: "",
  machines: [],
  pm_interval_shots: "",
  status: "active",
  notes: "",
};

function valuesOf(m: Mould): MouldValues {
  return {
    code: m.code,
    name: m.name,
    division: m.division,
    parts: m.parts.map((p) => `${p.item} x ${p.cavities}`).join("; "),
    owner: m.owner,
    customer: m.customer,
    asset: m.asset,
    cycle_time_s: m.cycle_time_s,
    shot_weight_g: m.shot_weight_g,
    runner_weight_g: m.runner_weight_g,
    tonnage_t: m.tonnage_t,
    width_mm: m.width_mm,
    height_mm: m.height_mm,
    thickness_mm: m.thickness_mm,
    machines: m.machines,
    pm_interval_shots: m.pm_interval_shots == null ? "" : String(m.pm_interval_shots),
    status: m.status,
    notes: m.notes,
  };
}

/** P3-01: moulds, their parts and cavities, and the machines they fit. */
export default function MouldsPage() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [editing, setEditing] = useState<Mould | "new" | null>(null);
  const found = useQuery({ queryKey: [...mouldsKey, q, status], queryFn: () => getMoulds(q, status) });
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("mould.title")}</h1>
      <p className="muted">{t("mould.help")}</p>
      <div className="inline-form">
        <label>
          {t("mould.search")}
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          {t("mould.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("mould.all")}</option>
            {d?.statuses.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {d?.can_edit && (
          <button type="button" onClick={() => setEditing("new")}>
            {t("mould.add")}
          </button>
        )}
        <a href={mouldExportUrl}>{t("mould.export")}</a>
        <a href={mouldLabelsUrl()} target="_blank" rel="noreferrer">
          {t("mould.labels")}
        </a>
      </div>
      <ErrorLine error={found.error} />
      {editing && d && (
        <MouldForm key={editing === "new" ? "new" : editing.id} mould={editing === "new" ? null : editing} list={d} onClose={() => setEditing(null)} />
      )}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("mould.title")}>
            <thead>
              <tr>
                <th>{t("mould.code")}</th>
                <th>{t("mould.name")}</th>
                <th>{t("mould.parts")}</th>
                <th>{t("mould.owner")}</th>
                <th className="num">{t("mould.cycle")}</th>
                <th>{t("mould.machines")}</th>
                <th className="num">{t("mould.shots")}</th>
                <th>{t("mould.status")}</th>
              </tr>
            </thead>
            <tbody>
              {d.results.map((m) => (
                <tr key={m.id}>
                  <td>
                    {d.can_edit ? (
                      <button type="button" className="link" onClick={() => setEditing(m)}>
                        {m.code}
                      </button>
                    ) : (
                      m.code
                    )}
                  </td>
                  <td>{m.name}</td>
                  <td>{m.parts.map((p) => `${p.item} × ${p.cavities}`).join(", ")}</td>
                  <td>{m.owner === "customer" ? m.customer_name : m.owner_label}</td>
                  <td className="num">{m.cycle_time_s}</td>
                  <td>
                    {m.machines.join(", ")}
                    {m.warnings.length > 0 && (
                      <span className="form-error" title={m.warnings.join("\n")}>
                        {" "}
                        {t("mould.fitWarning", { count: m.warnings.length })}
                      </span>
                    )}
                  </td>
                  <td className="num">
                    {m.shot_count.toLocaleString("en-LK")}
                    {m.pm_due_at != null && <div className="muted">{t("mould.pmDue", { at: m.pm_due_at.toLocaleString("en-LK") })}</div>}
                  </td>
                  <td>{m.status_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.results.length === 0 && <p className="muted">{t("mould.none")}</p>}
        </div>
      )}
      {d?.can_edit && <ImportPanel />}
    </main>
  );
}

const MEASURES = ["cycle_time_s", "shot_weight_g", "runner_weight_g", "tonnage_t", "width_mm", "height_mm", "thickness_mm", "pm_interval_shots"] as const;

function MouldForm({ mould, list, onClose }: { mould: Mould | null; list: MouldList; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<MouldValues>(mould ? valuesOf(mould) : EMPTY);
  const [saved, setSaved] = useState<Mould | null>(null);
  const save = useMutation({
    mutationFn: () => (mould ? changeMould(mould.id, values) : addMould(values)),
    onSuccess: (m) => {
      setSaved(m);
      void queryClient.invalidateQueries({ queryKey: mouldsKey });
      if (m.warnings.length === 0) onClose();
    },
  });
  const set = (key: keyof MouldValues) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const toggle = (code: string) =>
    setValues({
      ...values,
      machines: values.machines.includes(code) ? values.machines.filter((c) => c !== code) : [...values.machines, code],
    });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <section className="panel" aria-label={mould ? t("mould.edit", { code: mould.code }) : t("mould.add")}>
      <h2>{mould ? t("mould.edit", { code: mould.code }) : t("mould.add")}</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>
          {t("mould.code")}
          <input value={values.code} disabled={mould?.in_use} onChange={set("code")} />
        </label>
        <label>
          {t("mould.name")}
          <input value={values.name} onChange={set("name")} />
        </label>
        <label className="wide">
          {t("mould.partsInput")}
          <input value={values.parts} placeholder="CAP-28 x 8; LID-90 x 2" onChange={set("parts")} />
        </label>
        <label>
          {t("mould.owner")}
          <select value={values.owner} onChange={set("owner")}>
            <option value="company">{t("mould.company")}</option>
            <option value="customer">{t("mould.customer")}</option>
          </select>
        </label>
        {values.owner === "customer" ? (
          <label>
            {t("mould.customerCode")}
            <input value={values.customer} onChange={set("customer")} />
          </label>
        ) : (
          <label>
            {t("mould.asset")}
            <input value={values.asset} onChange={set("asset")} />
          </label>
        )}
        {MEASURES.map((key) => (
          <label key={key}>
            {t(`mould.f.${key}`)}
            <input inputMode="decimal" value={values[key]} onChange={set(key)} />
          </label>
        ))}
        <label>
          {t("mould.status")}
          <select value={values.status} onChange={set("status")}>
            {list.statuses.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="wide">
          <legend>{t("mould.machines")}</legend>
          {list.machines.length === 0 && <span className="muted">{t("mould.noMachines")}</span>}
          {list.machines.map((m) => (
            <label key={m.code} className="check">
              <input type="checkbox" checked={values.machines.includes(m.code)} onChange={() => toggle(m.code)} /> {m.code} {m.name}
            </label>
          ))}
        </fieldset>
        <label className="wide">
          {t("mould.notes")}
          <input value={values.notes} onChange={set("notes")} />
        </label>
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {t("mould.save")}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </div>
        {saved && saved.warnings.length > 0 && (
          <div className="wide notice" role="status">
            <strong>{t("mould.savedWithWarnings")}</strong>
            <ul>
              {saved.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="wide">
          <ErrorLine error={save.error} />
        </div>
      </form>
    </section>
  );
}

function ImportPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importMoulds(file!, dryRun),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) void queryClient.invalidateQueries({ queryKey: mouldsKey });
    },
  });
  return (
    <section className="panel" aria-label={t("mould.import")}>
      <h2>{t("mould.import")}</h2>
      <p className="muted">{t("mould.importHelp")}</p>
      <div className="inline-form">
        <label>
          {t("mould.file")}
          <input
            type="file"
            accept=".xlsx"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
        </label>
        <button type="button" className="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
          {t("mould.check")}
        </button>
        <button type="button" disabled={!file || run.isPending || !result || result.saved} onClick={() => run.mutate(false)}>
          {t("mould.importNow")}
        </button>
      </div>
      {result && (
        <p className="notice" role="status">
          {t(result.saved ? "mould.imported" : "mould.checked", { created: result.created, changed: result.changed })}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}
