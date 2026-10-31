import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  getCosting,
  quotationsKey,
  removeLineCosting,
  saveLineCosting,
  type CostingExtra,
  type CostingInput,
  type CostingLine,
  type CostingPage,
  type CostingResult,
} from "../api/quotations";
import { formatDecimal, formatQuantity } from "../lib/decimal";

/** The sizes asked for each form of stock; other forms are weighed. */
const SIZES: Record<string, string[]> = {
  round_bar: ["diameter"],
  hex_bar: ["acrossFlats"],
  flat_bar: ["width", "thickness"],
  plate: ["width", "thickness"],
  tube: ["outside", "inside"],
};

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Machining costing of a quotation's lines (spec 5.1). Internal: never sent to the customer. */
export default function QuotationCostingPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const costing = useQuery({ queryKey: [...quotationsKey, "costing", id], queryFn: () => getCosting(Number(id)) });
  const data = costing.data;

  return (
    <main className="page">
      <p>
        <Link to={`/quotations/${id}`}>{t("quoteCosting.back")}</Link>
      </p>
      <h1>
        {t("quoteCosting.title")}
        {data && ` ${data.number}${data.revision ? ` Rev ${data.revision}` : ""}`}
      </h1>
      <p className="notice">{t("quoteCosting.internalOnly")}</p>
      {data && (
        <p className="muted">
          {t("quoteCosting.ratesOf", { date: data.quote_date })}
          {data.defaults &&
            ` ${t("quoteCosting.divisionDefaults", {
              division: data.division,
              overhead: data.defaults.overhead_pct,
              margin: data.defaults.margin_pct,
              setup: formatDecimal(data.defaults.setup_rate),
            })}`}
          {data.currency !== "LKR" && ` ${t("quoteCosting.inLkr", { currency: data.currency, rate: data.exchange_rate })}`}
        </p>
      )}
      {data?.can_edit && !data.defaults && <p className="form-error">{t("quoteCosting.noDefaults", { division: data.division })}</p>}
      {data?.can_edit && <p className="muted">{t("quoteCosting.savedLines")}</p>}
      {data?.lines.map((line) => (
        <LineSection key={line.line_no} page={data} line={line} />
      ))}
      <ErrorLine error={costing.error} />
    </main>
  );
}

function LineSection({ page, line }: { page: CostingPage; line: CostingLine }) {
  const { t } = useTranslation();
  const n = String(line.line_no);
  return (
    <section className="panel" aria-label={t("quoteCosting.lineN", { n })}>
      <h2>
        {t("quotations.lineN", { n })}: {line.description}
      </h2>
      <p className="muted">
        {line.drawing_no && `${line.drawing_no} · `}
        {formatQuantity(line.quantity)} {line.unit} @ {page.currency} {formatDecimal(line.unit_price)}
      </p>
      {page.can_edit ? (
        <CostingForm key={line.costing?.updated_at ?? "none"} page={page} line={line} />
      ) : line.costing ? (
        <CostingSummary line={line} />
      ) : (
        <p className="muted">{t("quoteCosting.notCosted")}</p>
      )}
      {line.results && <Results page={page} line={line} results={line.results} />}
    </section>
  );
}

function CostingForm({ page, line }: { page: CostingPage; line: CostingLine }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const c = line.costing;
  const n = String(line.line_no);
  const [values, setValues] = useState({
    material: c?.material ? String(c.material.id) : "",
    size_a_mm: c?.size_a_mm ?? "",
    size_b_mm: c?.size_b_mm ?? "",
    length_mm: c?.length_mm ?? "",
    cutting_allowance_mm: c && c.cutting_allowance_mm !== "0.00" ? c.cutting_allowance_mm : "",
    weight_kg: c?.entered_weight_kg ?? "",
    setup_hours: c && c.setup_hours !== "0.00" ? c.setup_hours : "",
    overhead_pct: c?.overhead_pct ?? "",
    margin_pct: c?.margin_pct ?? "",
    notes: c?.notes ?? "",
  });
  const [operations, setOperations] = useState(
    c?.operations.map((op) => ({ machine: String(op.machine.id), minutes: op.minutes, description: op.description })) ?? [],
  );
  const [extras, setExtras] = useState<CostingExtra[]>(c?.extras ?? []);
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const material = page.materials.find((m) => String(m.id) === values.material);
  const sizes = material && material.density ? (SIZES[material.form] ?? []) : [];
  // A material the costing uses but that has no price today can still be shown.
  const materials = [...page.materials];
  if (c?.material && !materials.some((m) => m.id === c.material!.id)) {
    materials.push({ ...c.material, form: c.form, density: c.density, rate: c.material_rate ?? "" });
  }
  const machines = [...page.machines];
  for (const op of c?.operations ?? []) {
    if (!machines.some((m) => m.id === op.machine.id)) machines.push({ ...op.machine, rate: op.rate });
  }
  const done = (latest: CostingPage) => queryClient.setQueryData([...quotationsKey, "costing", String(page.quotation_id)], latest);

  const save = useMutation({
    mutationFn: () => {
      const blank = (value: string) => (value.trim() ? value.trim() : null);
      const input: CostingInput = {
        material: values.material ? Number(values.material) : null,
        size_a_mm: blank(values.size_a_mm),
        size_b_mm: blank(values.size_b_mm),
        length_mm: blank(values.length_mm),
        cutting_allowance_mm: blank(values.cutting_allowance_mm),
        weight_kg: blank(values.weight_kg),
        setup_hours: blank(values.setup_hours),
        overhead_pct: blank(values.overhead_pct),
        margin_pct: blank(values.margin_pct),
        notes: values.notes,
        operations: operations.map((op) => ({ machine: op.machine ? Number(op.machine) : null, minutes: op.minutes, description: op.description })),
        extras,
      };
      return saveLineCosting(page.quotation_id, line.line_no, input);
    },
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: () => removeLineCosting(page.quotation_id, line.line_no), onSuccess: done });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="form-grid" aria-label={t("quoteCosting.formOf", { n })} onSubmit={submit}>
      <h3 className="wide">{t("quoteCosting.material")}</h3>
      <label>
        {t("quoteCosting.material")}
        <select value={values.material} onChange={(e) => set("material")(e.target.value)}>
          <option value="">{t("quoteCosting.noMaterial")}</option>
          {materials.map((m) => (
            <option key={m.id} value={m.id}>
              {m.code} {m.name} ({t("quoteCosting.perKg", { rate: formatDecimal(m.rate) })})
            </option>
          ))}
        </select>
      </label>
      {material && (
        <>
          {sizes.map((size, i) => {
            const field = i === 0 ? "size_a_mm" : "size_b_mm";
            return (
              <label key={size}>
                {t(`quoteCosting.sizes.${size}`)}
                <input inputMode="decimal" className="num" value={values[field]} onChange={(e) => set(field)(e.target.value)} />
              </label>
            );
          })}
          {sizes.length > 0 && (
            <>
              <label>
                {t("quoteCosting.length")}
                <input inputMode="decimal" className="num" value={values.length_mm} onChange={(e) => set("length_mm")(e.target.value)} />
              </label>
              <label>
                {t("quoteCosting.allowance")}
                <input inputMode="decimal" className="num" value={values.cutting_allowance_mm} onChange={(e) => set("cutting_allowance_mm")(e.target.value)} />
              </label>
            </>
          )}
          <label>
            {sizes.length > 0 ? t("quoteCosting.weightOrSize") : t("quoteCosting.weight")}
            <input inputMode="decimal" className="num" value={values.weight_kg} onChange={(e) => set("weight_kg")(e.target.value)} />
          </label>
          {c && c.material?.id === material.id && (
            <p className="muted wide">{t("quoteCosting.weightUsed", { kg: c.weight_kg, rate: formatDecimal(c.material_rate ?? "0") })}</p>
          )}
        </>
      )}

      <h3 className="wide">{t("quoteCosting.operations")}</h3>
      <div className="wide" role="group" aria-label={t("quoteCosting.operationsOf", { n })}>
        {operations.length === 0 && <p className="muted">{t("quoteCosting.noOperations")}</p>}
        {operations.map((op, row) => {
          const change = (patch: Partial<typeof op>) => setOperations((now) => now.map((x, r) => (r === row ? { ...x, ...patch } : x)));
          const r = String(row + 1);
          return (
            <div key={row} className="inline-form">
              <label>
                {t("quoteCosting.machine")}
                <select aria-label={t("quoteCosting.machineOf", { r })} value={op.machine} onChange={(e) => change({ machine: e.target.value })}>
                  <option value="">—</option>
                  {machines.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.code} {m.name} ({t("quoteCosting.perHour", { rate: formatDecimal(m.rate) })})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("quoteCosting.operation")}
                <input aria-label={t("quoteCosting.operationOf", { r })} value={op.description} maxLength={100} onChange={(e) => change({ description: e.target.value })} />
              </label>
              <label>
                {t("quoteCosting.minutes")}
                <input inputMode="decimal" className="num" aria-label={t("quoteCosting.minutesOf", { r })} value={op.minutes} onChange={(e) => change({ minutes: e.target.value })} />
              </label>
              <button type="button" className="small secondary" onClick={() => setOperations((now) => now.filter((_, i) => i !== row))}>
                {t("vouchers.removeLine")}
              </button>
            </div>
          );
        })}
        <button type="button" className="small secondary" onClick={() => setOperations((now) => [...now, { machine: "", minutes: "", description: "" }])}>
          {t("quoteCosting.addOperation")}
        </button>
      </div>
      <label>
        {t("quoteCosting.setupHours")}
        <input inputMode="decimal" className="num" value={values.setup_hours} onChange={(e) => set("setup_hours")(e.target.value)} />
      </label>

      <h3 className="wide">{t("quoteCosting.subcontract")}</h3>
      <div className="wide" role="group" aria-label={t("quoteCosting.subcontractOf", { n })}>
        <p className="muted">{t("quoteCosting.subcontractHelp")}</p>
        {extras.map((extra, row) => {
          const change = (patch: Partial<CostingExtra>) => setExtras((now) => now.map((x, r) => (r === row ? { ...x, ...patch } : x)));
          const r = String(row + 1);
          return (
            <div key={row} className="inline-form">
              <label>
                {t("quoteCosting.what")}
                <input aria-label={t("quoteCosting.whatOf", { r })} value={extra.description} maxLength={100} onChange={(e) => change({ description: e.target.value })} />
              </label>
              <label>
                {t("quoteCosting.amount")}
                <input inputMode="decimal" className="num" aria-label={t("quoteCosting.amountOf", { r })} value={extra.amount} onChange={(e) => change({ amount: e.target.value })} />
              </label>
              <label>
                <input type="checkbox" checked={extra.per_order} onChange={(e) => change({ per_order: e.target.checked })} />{" "}
                {t("quoteCosting.perOrder")}
              </label>
              <button type="button" className="small secondary" onClick={() => setExtras((now) => now.filter((_, i) => i !== row))}>
                {t("vouchers.removeLine")}
              </button>
            </div>
          );
        })}
        <button type="button" className="small secondary" onClick={() => setExtras((now) => [...now, { description: "", amount: "", per_order: false }])}>
          {t("quoteCosting.addSubcontract")}
        </button>
      </div>

      <h3 className="wide">{t("quoteCosting.overheadAndMargin")}</h3>
      <label>
        {t("quoteCosting.overhead")}
        <input inputMode="decimal" className="num" value={values.overhead_pct} placeholder={page.defaults?.overhead_pct} onChange={(e) => set("overhead_pct")(e.target.value)} />
      </label>
      <label>
        {t("quoteCosting.margin")}
        <input inputMode="decimal" className="num" value={values.margin_pct} placeholder={page.defaults?.margin_pct} onChange={(e) => set("margin_pct")(e.target.value)} />
      </label>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {t("quoteCosting.save")}
        </button>{" "}
        {c && (
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("quoteCosting.remove")}
          </button>
        )}
        <ErrorLine error={save.error ?? remove.error} />
      </div>
    </form>
  );
}

function CostingSummary({ line }: { line: CostingLine }) {
  const { t } = useTranslation();
  const c = line.costing!;
  return (
    <div>
      <p>
        {c.material
          ? t("quoteCosting.materialUsed", {
              material: `${c.material.code} ${c.material.name}`,
              kg: c.weight_kg,
              rate: formatDecimal(c.material_rate ?? "0"),
            })
          : t("quoteCosting.noMaterial")}
      </p>
      {c.operations.length > 0 && (
        <ul className="changes">
          {c.operations.map((op, i) => (
            <li key={i}>
              {op.machine.code} {op.description && `– ${op.description}`}: {t("quoteCosting.minutesAt", { minutes: formatQuantity(op.minutes), rate: formatDecimal(op.rate) })}
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        {t("quoteCosting.setupSummary", { hours: c.setup_hours, rate: formatDecimal(c.setup_rate) })} ·{" "}
        {t("quoteCosting.pctSummary", { overhead: c.overhead_pct, margin: c.margin_pct })}
        {c.extras.length > 0 && ` · ${c.extras.map((e) => `${e.description} ${formatDecimal(e.amount)}${e.per_order ? ` ${t("quoteCosting.perOrderShort")}` : ""}`).join(", ")}`}
      </p>
      <p className="muted">{t("quoteCosting.updatedBy", { name: c.updated_by })}</p>
      {c.notes && <p>{c.notes}</p>}
    </div>
  );
}

/** The build-up of one piece: one column for the line's quantity and one per quantity break. */
function Results({ page, line, results }: { page: CostingPage; line: CostingLine; results: CostingResult[] }) {
  const { t } = useTranslation();
  const foreign = page.currency !== "LKR";
  const rows: [string, (r: CostingResult) => string, boolean?][] = [
    ["material", (r) => formatDecimal(r.material)],
    ["machining", (r) => formatDecimal(r.machining)],
    ["setup", (r) => formatDecimal(r.setup)],
    ["subcontract", (r) => formatDecimal(r.subcontract)],
    ["directCost", (r) => formatDecimal(r.direct_cost)],
    ["overheadAmount", (r) => formatDecimal(r.overhead)],
    ["cost", (r) => formatDecimal(r.cost), true],
    ["marginAmount", (r) => formatDecimal(r.margin)],
    ["suggested", (r) => formatDecimal(r.suggested_price_lkr), true],
  ];
  if (foreign) rows.push(["suggestedIn", (r) => `${page.currency} ${formatDecimal(r.suggested_price)}`, true]);
  rows.push(["quoted", (r) => (foreign ? `${page.currency} ${formatDecimal(r.quoted_price)} = ${formatDecimal(r.quoted_price_lkr)}` : formatDecimal(r.quoted_price_lkr))]);
  rows.push(["quotedMargin", (r) => (r.quoted_margin_pct === null ? "—" : `${r.quoted_margin_pct}%`), true]);

  return (
    <div className="table-wrap">
      <table aria-label={t("quoteCosting.resultsOf", { n: String(line.line_no) })}>
        <thead>
          <tr>
            <th>{t("quoteCosting.perPiece")}</th>
            {results.map((r) => (
              <th key={r.quantity} className="num">
                {formatQuantity(r.quantity)} {line.unit}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, value, strong]) => (
            <tr key={key}>
              <th scope="row">{t(`quoteCosting.rows.${key}`, { currency: page.currency })}</th>
              {results.map((r) => (
                <td key={r.quantity} className="num">
                  {strong ? <strong>{value(r)}</strong> : value(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {results.some((r) => r.below_cost) && (
        <p className="form-error" role="status">
          ⚠ {t("quoteCosting.belowCost", { quantities: results.filter((r) => r.below_cost).map((r) => formatQuantity(r.quantity)).join(", ") })}
        </p>
      )}
    </div>
  );
}
