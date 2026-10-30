import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../api/access";
import { listDivisions } from "../api/admin";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import {
  MATERIAL_FORMS,
  MATERIAL_KINDS,
  addDivisionRate,
  addMaterialRate,
  costingKey,
  createMaterial,
  listDivisionRates,
  listMaterialRates,
  listMaterials,
  removeDivisionRate,
  removeMaterialRate,
  updateMaterial,
  type Material,
  type MaterialForm,
  type MaterialKind,
} from "../api/costing";
import DataTable from "../components/DataTable";
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

/** Today in the user's time zone, as YYYY-MM-DD. */
const today = () => new Date().toLocaleDateString("en-CA");

/** Costing rates (spec 5.1): material prices per kg and each division's overhead, margin
 * and setup rate, all from a date. Kept by the Accountant; used by quotation costing. */
export default function CostingRatesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const canManage = can(me.access, "accounting", "manage");
  return (
    <main className="page">
      <h1>{t("costing.title")}</h1>
      <p className="muted">{t("costing.help")}</p>
      <DivisionRates canManage={canManage} />
      <Materials canManage={canManage} />
    </main>
  );
}

// --- Division rates ----------------------------------------------------------------------

function DivisionRates({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const rates = useQuery({ queryKey: [...costingKey, "divisions"], queryFn: listDivisionRates });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions, enabled: canManage });
  const [values, setValues] = useState({ division: "", effective_from: today(), overhead_pct: "", margin_pct: "", setup_rate: "", reason: "" });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: [...costingKey, "divisions"] });
  const add = useMutation({
    mutationFn: () => addDivisionRate(values),
    onSuccess: () => {
      setValues((now) => ({ ...now, overhead_pct: "", margin_pct: "", setup_rate: "", reason: "" }));
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => removeDivisionRate(id, reason),
    onSuccess: refresh,
  });
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <section className="panel" aria-label={t("costing.divisionRates")}>
      <h2>{t("costing.divisionRates")}</h2>
      <p className="muted">{t("costing.divisionHelp")}</p>
      {rates.data && (
        <DataTable
          label={t("costing.divisionRates")}
          rows={rates.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("costing.noDivisionRates")}
          columns={[
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "from", header: t("costing.from"), value: (r) => r.effective_from },
            { id: "overhead", header: t("costing.overhead"), value: (r) => `${formatDecimal(r.overhead_pct)}%` },
            { id: "margin", header: t("costing.margin"), value: (r) => `${formatDecimal(r.margin_pct)}%` },
            { id: "setup", header: t("costing.setupRate"), value: (r) => r.setup_rate, money: true },
            {
              id: "state",
              header: t("users.status"),
              value: (r) => (r.current ? t("costing.inForce") : r.in_force ? t("costing.replaced") : t("costing.future")),
            },
            {
              id: "actions",
              header: "",
              value: () => "",
              cell: (r) =>
                canManage && !r.in_force ? (
                  <button
                    type="button"
                    className="small secondary"
                    title={t("costing.removeReason")}
                    onClick={() => remove.mutate({ id: r.id, reason: values.reason })}
                  >
                    {t("costing.remove")}
                  </button>
                ) : null,
            },
          ]}
        />
      )}
      {canManage && (
        <form className="form-grid" aria-label={t("costing.addDivisionRates")} onSubmit={submit}>
          <h3 className="wide">{t("costing.addDivisionRates")}</h3>
          <label>
            {t("vouchers.division")}
            <select value={values.division} required onChange={(e) => set("division")(e.target.value)}>
              <option value="">—</option>
              {divisions.data?.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.code} {d.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("costing.from")}
            <input type="date" value={values.effective_from} min={today()} required onChange={(e) => set("effective_from")(e.target.value)} />
          </label>
          <label>
            {t("costing.overhead")}
            <input inputMode="decimal" className="num" value={values.overhead_pct} required onChange={(e) => set("overhead_pct")(e.target.value)} />
          </label>
          <label>
            {t("costing.margin")}
            <input inputMode="decimal" className="num" value={values.margin_pct} required onChange={(e) => set("margin_pct")(e.target.value)} />
          </label>
          <label>
            {t("costing.setupRate")}
            <input inputMode="decimal" className="num" value={values.setup_rate} required onChange={(e) => set("setup_rate")(e.target.value)} />
          </label>
          <label className="wide">
            {t("access.reason")}
            <input value={values.reason} onChange={(e) => set("reason")(e.target.value)} />
          </label>
          <div className="wide">
            <button type="submit" disabled={add.isPending}>
              {t("costing.add")}
            </button>
          </div>
        </form>
      )}
      <ErrorLine error={add.error ?? remove.error ?? rates.error} />
    </section>
  );
}

// --- Materials ---------------------------------------------------------------------------

function Materials({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const [inactive, setInactive] = useState(false);
  const [selected, setSelected] = useState<number | "new" | null>(null);
  const materials = useQuery({ queryKey: [...costingKey, "materials", inactive], queryFn: () => listMaterials(inactive) });
  const current = typeof selected === "number" ? materials.data?.find((m) => m.id === selected) : undefined;

  return (
    <section className="panel" aria-label={t("costing.materials")}>
      <h2>{t("costing.materials")}</h2>
      <div className="toolbar">
        <label className="check">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
          {t("costing.showInactive")}
        </label>
        {canManage && (
          <button type="button" onClick={() => setSelected("new")}>
            {t("costing.addMaterial")}
          </button>
        )}
      </div>
      {selected === "new" && <MaterialForm onDone={(id) => setSelected(id)} />}
      {current && canManage && <MaterialForm key={current.id} material={current} onDone={() => setSelected(null)} />}
      {current && <MaterialPrices key={`prices-${current.id}`} material={current} canManage={canManage} />}
      {materials.data && (
        <DataTable
          label={t("costing.materials")}
          rows={materials.data}
          rowKey={(m) => m.id}
          emptyText={t("costing.noMaterials")}
          columns={[
            {
              id: "code",
              header: t("customers.code"),
              value: (m) => m.code,
              cell: (m) => (
                <button type="button" className="link-button mono" onClick={() => setSelected(m.id)}>
                  {m.code}
                </button>
              ),
            },
            { id: "name", header: t("costing.name"), value: (m) => m.name },
            { id: "kind", header: t("costing.kind"), value: (m) => t(`costing.kinds.${m.kind}`) },
            { id: "form", header: t("costing.form"), value: (m) => t(`costing.forms.${m.form}`) },
            { id: "grade", header: t("costing.grade"), value: (m) => m.grade },
            { id: "price", header: t("costing.priceToday"), value: (m) => m.current_rate ?? "", money: true },
            {
              id: "status",
              header: t("users.status"),
              value: (m) => (m.is_active ? t("users.active") : t("users.inactive")),
            },
          ]}
        />
      )}
      <ErrorLine error={materials.error} />
    </section>
  );
}

function MaterialForm(props: { material?: Material; onDone: (id: number | null) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { material } = props;
  const [values, setValues] = useState({
    code: material?.code ?? "",
    name: material?.name ?? "",
    kind: (material?.kind ?? "metal") as MaterialKind,
    form: (material?.form ?? "round_bar") as MaterialForm,
    grade: material?.grade ?? "",
    density: material?.density ?? "",
    notes: material?.notes ?? "",
  });
  const [reason, setReason] = useState("");
  const done = (saved: Material) => {
    void queryClient.invalidateQueries({ queryKey: costingKey });
    props.onDone(material ? null : saved.id);
  };
  const save = useMutation({
    mutationFn: () => {
      const change = { ...values, density: values.density.trim() || null, reason };
      return material ? updateMaterial(material.id, { ...change, code: undefined }) : createMaterial(change);
    },
    onSuccess: done,
  });
  const toggle = useMutation({
    mutationFn: () => updateMaterial(material!.id, { is_active: !material!.is_active, reason }),
    onSuccess: done,
  });
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const title = material ? `${material.code} ${material.name}` : t("costing.addMaterial");
  return (
    <form className="form-grid panel" aria-label={title} onSubmit={submit}>
      <h3 className="wide">{title}</h3>
      <label>
        {t("customers.code")}
        <input value={values.code} required disabled={!!material} placeholder="EN8-BAR" onChange={(e) => set("code")(e.target.value)} />
      </label>
      <label>
        {t("costing.name")}
        <input value={values.name} required onChange={(e) => set("name")(e.target.value)} />
      </label>
      <label>
        {t("costing.kind")}
        <select value={values.kind} onChange={(e) => set("kind")(e.target.value)}>
          {MATERIAL_KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`costing.kinds.${k}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("costing.form")}
        <select value={values.form} onChange={(e) => set("form")(e.target.value)}>
          {MATERIAL_FORMS.map((f) => (
            <option key={f} value={f}>
              {t(`costing.forms.${f}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("costing.grade")}
        <input value={values.grade} onChange={(e) => set("grade")(e.target.value)} />
      </label>
      <label>
        {t("costing.density")}
        <input inputMode="decimal" className="num" value={values.density} placeholder="7.850" onChange={(e) => set("density")(e.target.value)} />
      </label>
      <label className="wide">
        {t("customers.field.notes")}
        <input value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>
      {material && (
        <label className="wide">
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("divisions.save")}
        </button>
        {material && (
          <button type="button" className={material.is_active ? "danger" : "secondary"} onClick={() => toggle.mutate()}>
            {material.is_active ? t("divisions.deactivate") : t("divisions.reactivate")}
          </button>
        )}
        <button type="button" className="secondary" onClick={() => props.onDone(null)}>
          {t("access.cancel")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error ?? toggle.error} />
      </div>
    </form>
  );
}

function MaterialPrices({ material, canManage }: { material: Material; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = [...costingKey, "materials", material.id, "rates"];
  const rates = useQuery({ queryKey: key, queryFn: () => listMaterialRates(material.id) });
  const [values, setValues] = useState({ effective_from: today(), rate: "", reason: "" });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: costingKey });
  const add = useMutation({
    mutationFn: () => addMaterialRate(material.id, values),
    onSuccess: () => {
      setValues({ effective_from: today(), rate: "", reason: "" });
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => removeMaterialRate(material.id, id, reason),
    onSuccess: refresh,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  const title = t("costing.pricesOf", { code: material.code });
  return (
    <div className="panel" role="group" aria-label={title}>
      <h3>{title}</h3>
      {rates.data?.length === 0 && <p className="muted">{t("costing.noPrices")}</p>}
      {rates.data && rates.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={title}>
            <thead>
              <tr>
                <th>{t("costing.from")}</th>
                <th className="num">{t("costing.pricePerKg")}</th>
                <th>{t("access.reason")}</th>
                <th>{t("users.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rates.data.map((r) => (
                <tr key={r.id}>
                  <td>{r.effective_from}</td>
                  <td className="num">{formatDecimal(r.rate)}</td>
                  <td>{r.reason}</td>
                  <td>{r.in_force ? t("costing.started") : t("costing.future")}</td>
                  <td>
                    {canManage && !r.in_force && (
                      <button
                        type="button"
                        className="small secondary"
                        title={t("costing.removeReason")}
                        onClick={() => remove.mutate({ id: r.id, reason: values.reason })}
                      >
                        {t("costing.remove")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canManage && (
        <form className="inline-form" aria-label={t("costing.addPrice")} onSubmit={submit}>
          <label>
            {t("costing.from")}
            <input
              type="date"
              value={values.effective_from}
              min={today()}
              required
              onChange={(e) => setValues((now) => ({ ...now, effective_from: e.target.value }))}
            />
          </label>
          <label>
            {t("costing.pricePerKg")}
            <input
              inputMode="decimal"
              className="num"
              value={values.rate}
              required
              onChange={(e) => setValues((now) => ({ ...now, rate: e.target.value }))}
            />
          </label>
          <label>
            {t("access.reason")}
            <input value={values.reason} onChange={(e) => setValues((now) => ({ ...now, reason: e.target.value }))} />
          </label>
          <button type="submit" disabled={add.isPending}>
            {t("costing.addPrice")}
          </button>
        </form>
      )}
      <ErrorLine error={add.error ?? remove.error} />
    </div>
  );
}
