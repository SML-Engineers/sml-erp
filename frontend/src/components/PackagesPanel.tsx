import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  goodsReceiptLabelsUrl,
  grnKey,
  saveGoodsReceiptPackages,
  type GRNDetail,
  type GRNLine,
  type PackageFields,
  type PackageType,
} from "../api/goodsReceipts";
import { formatQuantity } from "../lib/decimal";

type Field = Exclude<keyof PackageFields, "damaged">;

/** The columns typed for each way material arrives (spec 6A.2). */
const COLUMNS: Record<Exclude<PackageType, "none">, Field[]> = {
  bag: ["supplier_lot", "declared_weight", "gross_weight", "tare_weight"],
  coil: ["supplier_lot", "gross_weight", "tare_weight"],
  bar: ["supplier_lot", "pieces", "piece_length", "gross_weight"],
  plate: ["supplier_lot", "length_mm", "width_mm", "thickness_mm", "pieces", "gross_weight"],
  counted: ["supplier_lot", "pieces"],
};

const blank: PackageFields = {
  supplier_lot: "",
  gross_weight: "",
  tare_weight: "",
  declared_weight: "",
  pieces: "",
  piece_length: "",
  length_mm: "",
  width_mm: "",
  thickness_mm: "",
  damaged: false,
  notes: "",
};

function toRow(p: Partial<PackageFields>): PackageFields {
  const row = { ...blank };
  for (const key of Object.keys(blank) as (keyof PackageFields)[]) {
    const value = p[key];
    if (key === "damaged") row.damaged = Boolean(value);
    else if (value !== null && value !== undefined) row[key] = String(value);
  }
  return row;
}

/** Package by package entry for one GRN line: every bag, bundle, plate, coil or box with its
 * own lot number, weights and checks, plus fast entry for large deliveries. */
export default function PackagesPanel({ grn, line }: { grn: GRNDetail; line: GRNLine }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const type = line.item.package_type as Exclude<PackageType, "none">;
  const columns = COLUMNS[type];
  const editable = grn.can_edit;
  const [rows, setRows] = useState<PackageFields[]>(() => line.packages.map(toRow));
  const [fast, setFast] = useState({ count: "", each: "" });
  const save = useMutation({
    mutationFn: () => saveGoodsReceiptPackages(grn.id, line.line_no, rows),
    onSuccess: (latest) => {
      queryClient.setQueryData([...grnKey, "one", String(latest.id)], latest);
      const saved = latest.lines.find((l) => l.line_no === line.line_no);
      if (saved) setRows(saved.packages.map(toRow));
    },
  });
  const setRow = (index: number, change: Partial<PackageFields>) => setRows((now) => now.map((r, i) => (i === index ? { ...r, ...change } : r)));
  const eachField: Field = type === "bag" ? "declared_weight" : type === "counted" || type === "bar" ? "pieces" : "supplier_lot";

  function addMany() {
    const count = Math.min(Number.parseInt(fast.count, 10) || 0, 999 - rows.length);
    if (count <= 0) return;
    const template = { ...blank, [eachField]: fast.each };
    setRows((now) => [...now, ...Array.from({ length: count }, () => ({ ...template }))]);
    setFast({ count: "", each: "" });
  }

  const label = `${t("grn.packagesOf", { item: line.item.code })}`;
  const totals = line.package_totals;
  return (
    <section className="panel" aria-label={label}>
      <h2>{label}</h2>
      <p className="muted">
        {t(`grn.packageHelp.${type}`)} {t("grn.tolerance", { pct: line.weight_tolerance_pct })}
      </p>
      {totals.count > 0 && (
        <p>
          {t("grn.packageTotals", {
            count: totals.count,
            received: formatQuantity(line.received_quantity),
            unit: line.item.unit,
          })}
          {Number(totals.declared_weight) > 0 &&
            ` · ${t("grn.netVsDeclared", { net: formatQuantity(totals.net_of_declared), declared: formatQuantity(totals.declared_weight) })}`}
          {totals.outside > 0 && <strong className="form-error"> · {t("grn.outside", { count: totals.outside })}</strong>}{" "}
          <a href={goodsReceiptLabelsUrl(grn.id, line.line_no)} target="_blank" rel="noreferrer">
            {t("grn.printLabels")}
          </a>
        </p>
      )}
      {editable && (
        <div className="inline-form">
          <label>
            {t("grn.fastCount")}
            <input inputMode="numeric" value={fast.count} onChange={(e) => setFast({ ...fast, count: e.target.value })} />
          </label>
          <label>
            {t(`grn.fastEach.${eachField}`)}
            <input value={fast.each} onChange={(e) => setFast({ ...fast, each: e.target.value })} />
          </label>
          <button type="button" className="secondary" onClick={addMany}>
            {t("grn.addPackages")}
          </button>
          <button type="button" className="secondary" onClick={() => setRows((now) => [...now, { ...blank }])}>
            {t("grn.addOne")}
          </button>
        </div>
      )}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("grn.packageTable", { item: line.item.code })}>
            <thead>
              <tr>
                <th>#</th>
                {columns.map((c) => (
                  <th key={c} className={c === "supplier_lot" ? "" : "num"}>
                    {t(`grn.field.${c}`, { tare: line.item.package_tare })}
                  </th>
                ))}
                <th className="num">{t("grn.quantityIn", { unit: line.item.unit })}</th>
                <th>{t("grn.check")}</th>
                <th>{t("grn.damaged")}</th>
                {editable && <th />}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const saved = line.packages[i];
                return (
                  <tr key={i}>
                    <td className="mono">{saved?.lot_no ?? i + 1}</td>
                    {columns.map((c) => (
                      <td key={c} className={c === "supplier_lot" ? "" : "num"}>
                        {editable ? (
                          <input
                            aria-label={t("grn.fieldOf", { field: t(`grn.field.${c}`, { tare: "" }), n: i + 1 })}
                            inputMode={c === "supplier_lot" ? "text" : "decimal"}
                            value={row[c] ?? ""}
                            onChange={(e) => setRow(i, { [c]: e.target.value } as Partial<PackageFields>)}
                          />
                        ) : c === "supplier_lot" ? (
                          row[c]
                        ) : (
                          formatQuantity(row[c])
                        )}
                      </td>
                    ))}
                    <td className="num">{saved ? formatQuantity(saved.quantity) : ""}</td>
                    <td className={saved?.check.outside ? "form-error" : ""}>
                      {saved?.check.variance_pct !== null && saved?.check.variance_pct !== undefined
                        ? t(`grn.checkBasis.${saved.check.basis}`, {
                            actual: formatQuantity(saved.check.actual),
                            expected: formatQuantity(saved.check.expected),
                            pct: saved.check.variance_pct,
                          })
                        : ""}
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={t("grn.fieldOf", { field: t("grn.damaged"), n: i + 1 })}
                        checked={row.damaged}
                        disabled={!editable}
                        onChange={(e) => setRow(i, { damaged: e.target.checked })}
                      />
                    </td>
                    {editable && (
                      <td>
                        <button type="button" className="secondary" onClick={() => setRows((now) => now.filter((_, j) => j !== i))}>
                          {t("grn.removePackage")}
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {editable && (
        <p>
          <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
            {t("grn.savePackages")}
          </button>{" "}
          <span className="muted">{t("grn.savePackagesHelp")}</span>
        </p>
      )}
      {save.error && (
        <p className="form-error" role="alert">
          {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
        </p>
      )}
    </section>
  );
}
