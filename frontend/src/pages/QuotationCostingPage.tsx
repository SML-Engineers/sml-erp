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
  TOOLING_MODES,
  type CostingExtra,
  type CostingInput,
  type CostingMethod,
  type CostingLine,
  type CostingPage,
  type CostingResult,
  type PackingPer,
  type ToolingMode,
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

/** A stored "0.00" shown as an empty box, so the default reads as "nothing entered". */
const nonZero = (value: string | null | undefined) => (value && Number(value) !== 0 ? value : "");

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
    method: c?.method ?? page.default_method,
    masterbatch: c?.masterbatch ? String(c.masterbatch.id) : "",
    masterbatch_pct: nonZero(c?.masterbatch_pct),
    part_weight_g: c?.part_weight_g ?? "",
    runner_weight_g: c?.runner_weight_g ?? "",
    cavities: c?.cavities ? String(c.cavities) : "",
    machine: c?.machine ? String(c.machine.id) : "",
    cycle_time_s: c?.cycle_time_s ?? "",
    reject_pct: nonZero(c?.reject_pct),
    packing_amount: nonZero(c?.packing_amount),
    packing_per: c?.packing_per ?? "piece",
    pcs_per_carton: c?.pcs_per_carton ? String(c.pcs_per_carton) : "",
    tooling: c?.tooling ?? "none",
    tooling_cost: nonZero(c?.tooling_cost),
    tooling_qty: c?.tooling_qty ?? "",
  });
  const moulding = values.method === "moulding";
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
    materials.push({ ...c.material, kind: "", form: c.form, density: c.density, rate: c.material_rate ?? "" });
  }
  if (c?.masterbatch && !materials.some((m) => m.id === c.masterbatch!.id)) {
    materials.push({ ...c.masterbatch, kind: "masterbatch", form: "granules", density: null, rate: c.masterbatch_rate ?? "" });
  }
  const resins = materials.filter((m) => m.kind !== "masterbatch");
  const masterbatches = materials.filter((m) => m.kind === "masterbatch");
  const machines = [...page.machines];
  for (const op of c?.operations ?? []) {
    if (!machines.some((m) => m.id === op.machine.id)) machines.push({ ...op.machine, rate: op.rate });
  }
  if (c?.machine && !machines.some((m) => m.id === c.machine!.id)) machines.push({ ...c.machine, rate: c.machine_rate ?? "" });
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
        operations: (moulding ? [] : operations).map((op) => ({ machine: op.machine ? Number(op.machine) : null, minutes: op.minutes, description: op.description })),
        extras,
        method: values.method as CostingMethod,
        masterbatch: moulding && values.masterbatch ? Number(values.masterbatch) : null,
        masterbatch_pct: blank(values.masterbatch_pct),
        part_weight_g: blank(values.part_weight_g),
        runner_weight_g: blank(values.runner_weight_g),
        cavities: blank(values.cavities),
        machine: moulding && values.machine ? Number(values.machine) : null,
        cycle_time_s: blank(values.cycle_time_s),
        reject_pct: blank(values.reject_pct),
        packing_amount: blank(values.packing_amount),
        packing_per: values.packing_per as PackingPer,
        pcs_per_carton: blank(values.pcs_per_carton),
        tooling: values.tooling as ToolingMode,
        tooling_cost: blank(values.tooling_cost),
        tooling_qty: blank(values.tooling_qty),
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
      <label>
        {t("quoteCosting.method")}
        <select value={values.method} onChange={(e) => set("method")(e.target.value)}>
          <option value="machining">{t("quoteCosting.methods.machining")}</option>
          <option value="moulding">{t("quoteCosting.methods.moulding")}</option>
        </select>
      </label>
      {moulding ? (
        <>
          <h3 className="wide">{t("quoteCosting.material")}</h3>
          <label>
            {t("quoteCosting.resin")}
            <select value={values.material} onChange={(e) => set("material")(e.target.value)}>
              <option value="">—</option>
              {resins.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.code} {m.name} ({t("quoteCosting.perKg", { rate: formatDecimal(m.rate) })})
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("quoteCosting.partWeight")}
            <input inputMode="decimal" className="num" value={values.part_weight_g} onChange={(e) => set("part_weight_g")(e.target.value)} />
          </label>
          <label>
            {t("quoteCosting.runnerWeight")}
            <input inputMode="decimal" className="num" value={values.runner_weight_g} onChange={(e) => set("runner_weight_g")(e.target.value)} />
          </label>
          <label>
            {t("quoteCosting.cavities")}
            <input inputMode="numeric" className="num" value={values.cavities} onChange={(e) => set("cavities")(e.target.value)} />
          </label>
          <label>
            {t("quoteCosting.masterbatch")}
            <select value={values.masterbatch} onChange={(e) => set("masterbatch")(e.target.value)}>
              <option value="">{t("quoteCosting.noMasterbatch")}</option>
              {masterbatches.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.code} {m.name} ({t("quoteCosting.perKg", { rate: formatDecimal(m.rate) })})
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("quoteCosting.masterbatchPct")}
            <input inputMode="decimal" className="num" value={values.masterbatch_pct} onChange={(e) => set("masterbatch_pct")(e.target.value)} />
          </label>

          <h3 className="wide">{t("quoteCosting.press")}</h3>
          <label>
            {t("quoteCosting.machine")}
            <select value={values.machine} onChange={(e) => set("machine")(e.target.value)}>
              <option value="">—</option>
              {machines.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.code} {m.name} ({t("quoteCosting.perHour", { rate: formatDecimal(m.rate) })})
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("quoteCosting.cycleTime")}
            <input inputMode="decimal" className="num" value={values.cycle_time_s} onChange={(e) => set("cycle_time_s")(e.target.value)} />
          </label>
          <label>
            {t("quoteCosting.rejectPct")}
            <input inputMode="decimal" className="num" value={values.reject_pct} onChange={(e) => set("reject_pct")(e.target.value)} />
          </label>

          <h3 className="wide">{t("quoteCosting.packing")}</h3>
          <label>
            {t("quoteCosting.packingAmount")}
            <input inputMode="decimal" className="num" value={values.packing_amount} onChange={(e) => set("packing_amount")(e.target.value)} />
          </label>
          <label>
            {t("quoteCosting.packingPer")}
            <select value={values.packing_per} onChange={(e) => set("packing_per")(e.target.value)}>
              <option value="piece">{t("quoteCosting.perPieceOption")}</option>
              <option value="carton">{t("quoteCosting.perCartonOption")}</option>
            </select>
          </label>
          {values.packing_per === "carton" && (
            <label>
              {t("quoteCosting.pcsPerCarton")}
              <input inputMode="numeric" className="num" value={values.pcs_per_carton} onChange={(e) => set("pcs_per_carton")(e.target.value)} />
            </label>
          )}

          <h3 className="wide">{t("quoteCosting.toolingTitle")}</h3>
          <label>
            {t("quoteCosting.toolingMode")}
            <select value={values.tooling} onChange={(e) => set("tooling")(e.target.value)}>
              {TOOLING_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {t(`quoteCosting.toolingModes.${mode}`)}
                </option>
              ))}
            </select>
          </label>
          {values.tooling !== "none" && (
            <label>
              {t("quoteCosting.toolingCost")}
              <input inputMode="decimal" className="num" value={values.tooling_cost} onChange={(e) => set("tooling_cost")(e.target.value)} />
            </label>
          )}
          {values.tooling === "amortised" && (
            <label>
              {t("quoteCosting.toolingQty")}
              <input inputMode="decimal" className="num" value={values.tooling_qty} onChange={(e) => set("tooling_qty")(e.target.value)} />
            </label>
          )}
          {values.tooling === "separate" && !page.lines.some((l) => l.is_tooling) && (
            <p className="notice wide">{t("quoteCosting.noToolingLine")}</p>
          )}
        </>
      ) : (
        <>
        <h3 className="wide">{t("quoteCosting.material")}</h3>
        <label>
          {t("quoteCosting.material")}
          <select value={values.material} onChange={(e) => set("material")(e.target.value)}>
            <option value="">{t("quoteCosting.noMaterial")}</option>
            {resins.map((m) => (
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
        </>
      )}
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
        {c.method === "moulding"
          ? t("quoteCosting.resinUsed", { material: `${c.material?.code ?? ""} ${c.material?.name ?? ""}`, rate: formatDecimal(c.material_rate ?? "0") })
          : c.material
          ? t("quoteCosting.materialUsed", {
              material: `${c.material.code} ${c.material.name}`,
              kg: c.weight_kg,
              rate: formatDecimal(c.material_rate ?? "0"),
            })
          : t("quoteCosting.noMaterial")}
      </p>
      {c.method === "moulding" && (
        <p>
          {t("quoteCosting.mouldingSummary", {
            part: formatQuantity(c.part_weight_g),
            runner: formatQuantity(c.runner_weight_g ?? "0"),
            cavities: String(c.cavities ?? 1),
            machine: c.machine?.code ?? "",
            cycle: formatQuantity(c.cycle_time_s),
            rejects: c.reject_pct,
          })}
          {c.masterbatch && ` ${t("quoteCosting.masterbatchSummary", { code: c.masterbatch.code, pct: c.masterbatch_pct })}`}
          {c.tooling !== "none" && ` ${t(`quoteCosting.toolingModes.${c.tooling}`)}${Number(c.tooling_cost) ? `: LKR ${formatDecimal(c.tooling_cost)}` : ""}.`}
        </p>
      )}
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
  const moulding = line.costing?.method === "moulding";
  const someNonZero = (pick: (r: CostingResult) => string) => results.some((r) => Number(pick(r)) !== 0);
  const rows: [string, (r: CostingResult) => string, boolean?][] = [
    ["material", (r) => formatDecimal(r.material)],
    [moulding ? "machine" : "machining", (r) => formatDecimal(r.machining)],
  ];
  if (moulding) rows.push(["rejects", (r) => formatDecimal(r.rejects)]);
  rows.push(["setup", (r) => formatDecimal(r.setup)]);
  if (someNonZero((r) => r.packing)) rows.push(["packing", (r) => formatDecimal(r.packing)]);
  rows.push(
    ["subcontract", (r) => formatDecimal(r.subcontract)],
    ["directCost", (r) => formatDecimal(r.direct_cost)],
    ["overheadAmount", (r) => formatDecimal(r.overhead)],
    ["cost", (r) => formatDecimal(r.cost), true],
    ["marginAmount", (r) => formatDecimal(r.margin)],
  );
  if (someNonZero((r) => r.tooling)) rows.push(["tooling", (r) => formatDecimal(r.tooling)]);
  rows.push(["suggested", (r) => formatDecimal(r.suggested_price_lkr), true]);
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
      {moulding && results[0].hours_per_1000 && (
        <p className="muted">{t("quoteCosting.hoursPer1000", { hours: results[0].hours_per_1000 })}</p>
      )}
      {results.some((r) => r.below_cost) && (
        <p className="form-error" role="status">
          ⚠ {t("quoteCosting.belowCost", { quantities: results.filter((r) => r.below_cost).map((r) => formatQuantity(r.quantity)).join(", ") })}
        </p>
      )}
    </div>
  );
}
