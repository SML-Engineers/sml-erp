import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { createPlan, listPlans, plansKey, updatePlan, type Parameter, type Plan, type PlanList } from "../api/inspections";
import { itemsKey, listItems } from "../api/items";
import SearchSelect from "../components/SearchSelect";
import { formatQuantity } from "../lib/decimal";

const blankCheck: Parameter = { name: "", kind: "number", minimum: "", maximum: "", unit: "", critical: false };

/** Inspection plans (spec 6A.3): what QC checks per item, or per category of items. */
export default function InspectionPlansPage() {
  const { t } = useTranslation();
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Plan | "new" | null>(null);
  const plans = useQuery({ queryKey: [...plansKey, showInactive], queryFn: () => listPlans(showInactive) });
  const data = plans.data;
  const categoryName = (value: string) => data?.categories.find((c) => c.value === value)?.label ?? value;

  return (
    <main className="page">
      <h1>{t("plans.title")}</h1>
      <p className="muted">{t("plans.help")}</p>
      <div className="toolbar">
        {data?.can_edit && (
          <button type="button" onClick={() => setEditing("new")}>
            {t("plans.add")}
          </button>
        )}
        <label>
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> {t("plans.showInactive")}
        </label>
      </div>
      {editing && data && (
        <PlanForm key={editing === "new" ? "new" : editing.id} plan={editing === "new" ? null : editing} list={data} onDone={() => setEditing(null)} />
      )}
      {data && data.plans.length === 0 && <p className="muted">{t("plans.none")}</p>}
      {data?.plans.map((p) => (
        <section key={p.id} className="panel" aria-label={p.name}>
          <h2>
            {p.name} {!p.is_active && <span className="muted">({t("plans.inactive")})</span>}
          </h2>
          <p className="muted">
            {p.item ? `${p.item.code} ${p.item.name}` : t("plans.everyItemIn", { category: categoryName(p.category) })} ·{" "}
            {t(`plans.sampling.${p.sampling}`, { n: formatQuantity(p.sample_value) })}
          </p>
          {p.parameters.length > 0 && (
            <ul>
              {p.parameters.map((q, i) => (
                <li key={i}>
                  {q.name}
                  {q.kind === "number"
                    ? `: ${q.minimum ? formatQuantity(q.minimum) : "…"} – ${q.maximum ? formatQuantity(q.maximum) : "…"} ${q.unit}`
                    : `: ${t("qc.passFail")}`}
                  {q.critical && <strong> ({t("qc.critical")})</strong>}
                </li>
              ))}
            </ul>
          )}
          {data.can_edit && (
            <button type="button" className="secondary" onClick={() => setEditing(p)}>
              {t("plans.change")}
            </button>
          )}
        </section>
      ))}
    </main>
  );
}

function PlanForm({ plan, list, onDone }: { plan: Plan | null; list: PlanList; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const items = useQuery({ queryKey: [...itemsKey, "list", "", "", false], queryFn: () => listItems("", "", false) });
  const [values, setValues] = useState({
    name: plan?.name ?? "",
    target: plan?.item ? "item" : "category",
    item: plan?.item ? String(plan.item.id) : "",
    category: plan?.category || "raw_material",
    sampling: plan?.sampling ?? "all",
    sample_value: plan?.sample_value ?? "",
    notes: plan?.notes ?? "",
    is_active: plan?.is_active ?? true,
  });
  const [checks, setChecks] = useState<Parameter[]>(plan?.parameters.map((p) => ({ ...p, minimum: p.minimum ?? "", maximum: p.maximum ?? "" })) ?? []);
  const set = <K extends keyof typeof values>(field: K, value: (typeof values)[K]) => setValues((now) => ({ ...now, [field]: value }));
  const setCheck = (i: number, change: Partial<Parameter>) => setChecks((now) => now.map((c, j) => (j === i ? { ...c, ...change } : c)));
  const save = useMutation({
    mutationFn: () => {
      const input = {
        name: values.name,
        item: values.target === "item" && values.item ? Number(values.item) : null,
        category: values.target === "category" ? values.category : "",
        sampling: values.sampling,
        sample_value: values.sampling === "all" ? null : values.sample_value,
        notes: values.notes,
        is_active: values.is_active,
        parameters: checks,
      };
      return plan ? updatePlan(plan.id, input) : createPlan(input);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: plansKey });
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("plans.form")} onSubmit={submit}>
      <label className="wide">
        {t("plans.name")}
        <input value={values.name} maxLength={100} required onChange={(e) => set("name", e.target.value)} />
      </label>
      <label>
        {t("plans.for")}
        <select value={values.target} onChange={(e) => set("target", e.target.value)}>
          <option value="item">{t("plans.oneItem")}</option>
          <option value="category">{t("plans.aCategory")}</option>
        </select>
      </label>
      {values.target === "item" ? (
        <div className="wide">
          <SearchSelect
            label={t("po.item")}
            options={(items.data ?? []).map((i) => ({ value: String(i.id), label: `${i.code} ${i.name}` }))}
            value={values.item}
            onChange={(v) => set("item", v)}
          />
        </div>
      ) : (
        <label>
          {t("items.category")}
          <select value={values.category} onChange={(e) => set("category", e.target.value)}>
            {list.categories.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        {t("plans.samplingLabel")}
        <select value={values.sampling} onChange={(e) => set("sampling", e.target.value as Plan["sampling"])}>
          <option value="all">{t("plans.samplingAll")}</option>
          <option value="fixed">{t("plans.samplingFixed")}</option>
          <option value="percent">{t("plans.samplingPercent")}</option>
        </select>
      </label>
      {values.sampling !== "all" && (
        <label>
          {values.sampling === "fixed" ? t("plans.howMany") : t("plans.percent")}
          <input inputMode="decimal" value={values.sample_value} onChange={(e) => set("sample_value", e.target.value)} />
        </label>
      )}
      <div className="wide table-wrap">
        <table aria-label={t("plans.checks")}>
          <thead>
            <tr>
              <th>{t("qc.check")}</th>
              <th>{t("plans.kind")}</th>
              <th>{t("plans.min")}</th>
              <th>{t("plans.max")}</th>
              <th>{t("plans.unit")}</th>
              <th>{t("qc.critical")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {checks.map((c, i) => (
              <tr key={i}>
                <td>
                  <input aria-label={t("plans.checkName", { n: i + 1 })} value={c.name} maxLength={100} onChange={(e) => setCheck(i, { name: e.target.value })} />
                </td>
                <td>
                  <select aria-label={t("plans.kindOf", { n: i + 1 })} value={c.kind} onChange={(e) => setCheck(i, { kind: e.target.value as Parameter["kind"] })}>
                    <option value="number">{t("plans.measured")}</option>
                    <option value="pass_fail">{t("qc.passFail")}</option>
                  </select>
                </td>
                <td>
                  {c.kind === "number" && (
                    <input aria-label={t("plans.minOf", { n: i + 1 })} inputMode="decimal" value={c.minimum ?? ""} onChange={(e) => setCheck(i, { minimum: e.target.value })} />
                  )}
                </td>
                <td>
                  {c.kind === "number" && (
                    <input aria-label={t("plans.maxOf", { n: i + 1 })} inputMode="decimal" value={c.maximum ?? ""} onChange={(e) => setCheck(i, { maximum: e.target.value })} />
                  )}
                </td>
                <td>{c.kind === "number" && <input aria-label={t("plans.unitOf", { n: i + 1 })} value={c.unit} maxLength={20} onChange={(e) => setCheck(i, { unit: e.target.value })} />}</td>
                <td>
                  <input type="checkbox" aria-label={t("plans.criticalOf", { n: i + 1 })} checked={c.critical} onChange={(e) => setCheck(i, { critical: e.target.checked })} />
                </td>
                <td>
                  <button type="button" className="secondary" onClick={() => setChecks((now) => now.filter((_, j) => j !== i))}>
                    {t("grn.removePackage")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="secondary" onClick={() => setChecks((now) => [...now, { ...blankCheck }])}>
          {t("plans.addCheck")}
        </button>
      </div>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea value={values.notes} onChange={(e) => set("notes", e.target.value)} />
      </label>
      {plan && (
        <label className="check">
          <input type="checkbox" checked={values.is_active} onChange={(e) => set("is_active", e.target.checked)} /> {t("plans.active")}
        </label>
      )}
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {t("plans.save")}
        </button>{" "}
        <button type="button" className="secondary" onClick={onDone}>
          {t("common.cancel")}
        </button>
      </div>
      {save.error && (
        <p className="form-error wide" role="alert">
          {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
        </p>
      )}
    </form>
  );
}
