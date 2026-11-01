import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { grnKey } from "../api/goodsReceipts";
import {
  addInspectionFile,
  approveDeviation,
  decideInspection,
  getInspection,
  inspectionFileUrl,
  qcKey,
  removeInspectionFile,
  returnDeviation,
  saveInspection,
  type Decision,
  type InspectionDetail,
} from "../api/inspections";
import { formatQuantity } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function limits(r: { minimum: string | null; maximum: string | null; unit: string }) {
  const unit = r.unit ? ` ${r.unit}` : "";
  if (r.minimum && r.maximum) return `${formatQuantity(r.minimum)} – ${formatQuantity(r.maximum)}${unit}`;
  if (r.minimum) return `≥ ${formatQuantity(r.minimum)}${unit}`;
  if (r.maximum) return `≤ ${formatQuantity(r.maximum)}${unit}`;
  return "";
}

/** One incoming inspection (spec 6A.3, 6A.4): results, packages rejected, certificates, the
 * decision, and the Director's approval of a deviation. */
export default function InspectionPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const inspection = useQuery({ queryKey: [...qcKey, "one", id], queryFn: () => getInspection(Number(id)) });
  const data = inspection.data;
  return (
    <main className="page">
      <p>
        <Link to="/inspections">{t("qc.backToList")}</Link>
      </p>
      <h1>{data ? t("qc.oneTitle", { item: data.item.code, grn: data.grn.number }) : t("qc.title")}</h1>
      {data && (
        <>
          <p className="muted">
            {data.decision ? t(`qc.decisions.${data.decision}`) : t(`qc.statuses.${data.status}`)} · {data.item.name} ·{" "}
            {data.supplier.name} · <Link to={`/goods-receipts/${data.grn.id}`}>{data.grn.number}</Link> · {t("qc.received")}{" "}
            {formatQuantity(data.received_quantity)} {data.item.unit}
            {Number(data.damaged_quantity) > 0 && ` (${t("qc.damaged", { qty: formatQuantity(data.damaged_quantity) })})`}
          </p>
          <p className="muted">
            {data.plan ? t("qc.plan", { name: data.plan.name, n: data.sample_size }) : t("qc.noPlan")}
            {data.inspector && ` · ${t("qc.inspectedBy", { name: data.inspector })}`}
          </p>
          {data.reason && <p className="notice">{t("qc.reasonGiven", { reason: data.reason })}</p>}
          {data.can_edit ? <Form key={`${data.id}-${data.status}`} data={data} /> : <ReadOnly data={data} />}
          <Approval data={data} />
          <Files data={data} />
        </>
      )}
      <ErrorLine error={inspection.error} />
    </main>
  );
}

function useDone() {
  const queryClient = useQueryClient();
  return (latest: InspectionDetail) => {
    queryClient.setQueryData([...qcKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...qcKey, "list"] });
    void queryClient.invalidateQueries({ queryKey: [...qcKey, "queue"] });
    void queryClient.invalidateQueries({ queryKey: grnKey });
  };
}

function Form({ data }: { data: InspectionDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const [results, setResults] = useState(
    data.results.map((r) => ({ position: r.position, value: r.value ?? "", passed: r.passed, notes: r.notes })),
  );
  const [rejected, setRejected] = useState<number[]>(data.packages.filter((p) => p.rejected).map((p) => p.package_no));
  const [accepted, setAccepted] = useState(data.accepted_quantity);
  const [notes, setNotes] = useState(data.notes);
  const [reason, setReason] = useState("");
  const byPackage = data.packages.length > 0;
  const input = () => ({
    results: results.map((r) => ({ ...r, value: r.value || null })),
    notes,
    ...(byPackage ? { rejected_packages: rejected } : { accepted_quantity: accepted }),
  });
  const save = useMutation({ mutationFn: () => saveInspection(data.id, input()), onSuccess: done });
  const decide = useMutation({
    mutationFn: async (decision: Decision) => {
      await saveInspection(data.id, input());
      return decideInspection(data.id, decision, reason);
    },
    onSuccess: done,
  });
  const setResult = (i: number, change: Partial<(typeof results)[number]>) => setResults((now) => now.map((r, j) => (j === i ? { ...r, ...change } : r)));

  return (
    <section className="panel" aria-label={t("qc.form")}>
      {data.results.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("qc.checks")}>
            <thead>
              <tr>
                <th>{t("qc.check")}</th>
                <th>{t("qc.limits")}</th>
                <th>{t("qc.result")}</th>
                <th>{t("grn.lineNotes")}</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r, i) => (
                <tr key={r.position}>
                  <td>
                    {r.name} {r.critical && <strong>({t("qc.critical")})</strong>}
                  </td>
                  <td>{r.kind === "number" ? limits(r) : t("qc.passFail")}</td>
                  <td className={r.within_limits === false ? "form-error" : ""}>
                    {r.kind === "number" ? (
                      <input
                        aria-label={t("qc.resultOf", { name: r.name })}
                        inputMode="decimal"
                        value={results[i].value}
                        onChange={(e) => setResult(i, { value: e.target.value })}
                      />
                    ) : (
                      <select
                        aria-label={t("qc.resultOf", { name: r.name })}
                        value={results[i].passed === null ? "" : results[i].passed ? "pass" : "fail"}
                        onChange={(e) => setResult(i, { passed: e.target.value === "" ? null : e.target.value === "pass" })}
                      >
                        <option value="">—</option>
                        <option value="pass">{t("qc.pass")}</option>
                        <option value="fail">{t("qc.fail")}</option>
                      </select>
                    )}
                  </td>
                  <td>
                    <input
                      aria-label={t("qc.notesOf", { name: r.name })}
                      maxLength={300}
                      value={results[i].notes}
                      onChange={(e) => setResult(i, { notes: e.target.value })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {byPackage ? (
        <fieldset>
          <legend>{t("qc.rejectPackages")}</legend>
          {data.packages.map((p) => (
            <label key={p.package_no} className="check">
              <input
                type="checkbox"
                disabled={p.damaged}
                checked={p.damaged || rejected.includes(p.package_no)}
                onChange={(e) =>
                  setRejected((now) => (e.target.checked ? [...now, p.package_no] : now.filter((n) => n !== p.package_no)))
                }
              />
              <span className="mono">{p.lot_no}</span> {formatQuantity(p.quantity)} {data.item.unit}
              {p.supplier_lot && ` · ${p.supplier_lot}`}
              {p.damaged && ` · ${t("qc.damagedAtReceipt")}`}
            </label>
          ))}
        </fieldset>
      ) : (
        <label>
          {t("qc.acceptedQuantity", { unit: data.item.unit, good: formatQuantity(data.good_quantity) })}
          <input inputMode="decimal" value={accepted} onChange={(e) => setAccepted(e.target.value)} />
        </label>
      )}
      <label className="wide">
        {t("customers.field.notes")}
        <textarea value={notes} maxLength={5000} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <p>
        <button type="button" className="secondary" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("qc.save")}
        </button>
      </p>
      <div className="inline-form">
        <label>
          {t("qc.reason")}
          <input value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="button" disabled={decide.isPending} onClick={() => decide.mutate("accepted")}>
          {t("qc.accept")}
        </button>
        <button type="button" className="secondary" disabled={decide.isPending} onClick={() => decide.mutate("deviation")}>
          {t("qc.askDeviation")}
        </button>
        <button type="button" className="secondary" disabled={decide.isPending} onClick={() => decide.mutate("rejected")}>
          {t("qc.reject")}
        </button>
      </div>
      <p className="muted">{t("qc.decideHelp")}</p>
      <ErrorLine error={save.error ?? decide.error} />
    </section>
  );
}

function ReadOnly({ data }: { data: InspectionDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("qc.form")}>
      <p>
        {t("qc.acceptedRejected", {
          accepted: formatQuantity(data.accepted_quantity),
          rejected: formatQuantity(data.rejected_quantity),
          unit: data.item.unit,
        })}
      </p>
      {data.results.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("qc.checks")}>
            <thead>
              <tr>
                <th>{t("qc.check")}</th>
                <th>{t("qc.limits")}</th>
                <th>{t("qc.result")}</th>
                <th>{t("grn.lineNotes")}</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r) => (
                <tr key={r.position}>
                  <td>
                    {r.name} {r.critical && <strong>({t("qc.critical")})</strong>}
                  </td>
                  <td>{r.kind === "number" ? limits(r) : t("qc.passFail")}</td>
                  <td className={r.within_limits === false ? "form-error" : ""}>
                    {r.kind === "number" ? formatQuantity(r.value) : r.passed === null ? "—" : r.passed ? t("qc.pass") : t("qc.fail")}
                  </td>
                  <td>{r.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.packages.some((p) => p.rejected) && (
        <p>
          {t("qc.packagesRejected")}{" "}
          {data.packages
            .filter((p) => p.rejected)
            .map((p) => p.lot_no)
            .join(", ")}
        </p>
      )}
      {data.notes && <p className="pre-line">{data.notes}</p>}
    </section>
  );
}

function Approval({ data }: { data: InspectionDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const [text, setText] = useState("");
  const act = useMutation({ mutationFn: (call: () => Promise<InspectionDetail>) => call(), onSuccess: done });
  if (!data.can_approve && data.history.length === 0) return null;
  return (
    <section className="panel" aria-label={t("qc.deviation")}>
      <h2>{t("qc.deviation")}</h2>
      {data.can_approve && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveDeviation(data.id, text))}>
            {t("qc.approveDeviation")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnDeviation(data.id, text))}>
            {t("salesOrders.sendBack")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error} />
      <ul className="changes">
        {data.history.map((h, i) => (
          <li key={i}>
            {h.at.slice(0, 16).replace("T", " ")} · {h.action_label} · {h.by}
            {h.reason ? ` · ${h.reason}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Files({ data }: { data: InspectionDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const add = useMutation({ mutationFn: (file: File) => addInspectionFile(data.id, file), onSuccess: done });
  const remove = useMutation({ mutationFn: (file: number) => removeInspectionFile(data.id, file), onSuccess: done });
  if (!data.can_attach && data.attachments.length === 0) return null;
  return (
    <section className="panel" aria-label={t("qc.files")}>
      <h2>{t("qc.files")}</h2>
      <ul>
        {data.attachments.map((a) => (
          <li key={a.id}>
            <a href={inspectionFileUrl(data.id, a.id)} target="_blank" rel="noreferrer">
              {a.file_name}
            </a>{" "}
            <span className="muted">
              {a.uploaded_by} · {a.uploaded_at.slice(0, 16).replace("T", " ")}
            </span>{" "}
            {data.can_edit && (
              <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate(a.id)}>
                {t("grn.removePhoto")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {data.can_attach && (
        <label>
          {t("qc.addFile")}
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
