import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  addPayComponent,
  changePayComponent,
  listPayComponents,
  payComponentsKey,
  type ComponentValues,
  type PayComponent,
} from "../api/pay";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Pay components (P2B-02): the earnings and deductions on payslips, kept by HR. */
export default function PayComponentsPage() {
  const { t } = useTranslation();
  const list = useQuery({ queryKey: payComponentsKey, queryFn: listPayComponents });
  const [editing, setEditing] = useState<PayComponent | "new" | null>(null);
  const data = list.data;
  const yes = (v: boolean) => (v ? t("pc.yes") : "—");
  return (
    <main className="page">
      <h1>{t("pc.title")}</h1>
      <p className="muted">{t("pc.help")}</p>
      {data?.can_manage && (
        <div className="toolbar">
          <button type="button" onClick={() => setEditing("new")}>
            {t("pc.add")}
          </button>
        </div>
      )}
      {editing && (
        <ComponentForm
          key={editing === "new" ? "new" : editing.id}
          current={editing === "new" ? null : editing}
          onDone={() => setEditing(null)}
        />
      )}
      <ErrorLine error={list.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("pc.title")}>
            <thead>
              <tr>
                <th>{t("pc.code")}</th>
                <th>{t("pc.name")}</th>
                <th>{t("pc.kind")}</th>
                <th>{t("pc.basis")}</th>
                <th>{t("pc.epf")}</th>
                <th>{t("pc.apit")}</th>
                <th>{t("pc.allowance")}</th>
                <th>{t("pc.dayRate")}</th>
                <th>{t("pc.status")}</th>
                {data.can_manage && <th />}
              </tr>
            </thead>
            <tbody>
              {data.results.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.code}</td>
                  <td>{c.name}</td>
                  <td>{t(`pc.kinds.${c.kind}`)}</td>
                  <td>{t(`pc.bases.${c.basis}`)}</td>
                  <td>{yes(c.epf_liable)}</td>
                  <td>{yes(c.apit_taxable)}</td>
                  <td>{yes(c.is_allowance)}</td>
                  <td>{yes(c.in_day_rate)}</td>
                  <td>{c.is_active ? t("pc.inUse") : t("pc.notUsed")}</td>
                  {data.can_manage && (
                    <td>
                      <button type="button" className="small secondary" onClick={() => setEditing(c)}>
                        {t("pc.change")} {c.code}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

function ComponentForm({ current, onDone }: { current: PayComponent | null; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const start: ComponentValues = current ?? {
    code: "",
    name: "",
    kind: "earning",
    basis: "fixed",
    epf_liable: false,
    apit_taxable: false,
    is_allowance: false,
    in_day_rate: false,
    sort_order: 100,
    is_active: true,
  };
  const [values, setValues] = useState<ComponentValues>(start);
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => {
      if (!current) return addPayComponent(values);
      const changed = Object.fromEntries(
        Object.entries(values).filter(([k, v]) => k !== "id" && v !== current[k as keyof PayComponent]),
      ) as ComponentValues;
      return changePayComponent(current.id, changed, reason);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: payComponentsKey });
      onDone();
    },
  });
  const set = (change: ComponentValues) => setValues((v) => ({ ...v, ...change }));
  const deduction = values.kind === "deduction";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="panel form-grid" aria-label={current ? t("pc.changeTitle") : t("pc.add")} onSubmit={submit}>
      <h2 className="wide">{current ? `${t("pc.changeTitle")}: ${current.code}` : t("pc.add")}</h2>
      <label>
        {t("pc.code")}
        <input value={values.code ?? ""} readOnly={!!current} onChange={(e) => set({ code: e.target.value.toUpperCase() })} />
      </label>
      <label>
        {t("pc.name")}
        <input value={values.name ?? ""} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label>
        {t("pc.kind")}
        <select
          value={values.kind}
          disabled={!!current}
          onChange={(e) =>
            set(
              e.target.value === "deduction"
                ? { kind: "deduction", epf_liable: false, apit_taxable: false, is_allowance: false, in_day_rate: false }
                : { kind: "earning" },
            )
          }
        >
          <option value="earning">{t("pc.kinds.earning")}</option>
          <option value="deduction">{t("pc.kinds.deduction")}</option>
        </select>
      </label>
      <label>
        {t("pc.basis")}
        <select value={values.basis} onChange={(e) => set({ basis: e.target.value as ComponentValues["basis"] })}>
          <option value="fixed">{t("pc.bases.fixed")}</option>
          <option value="variable">{t("pc.bases.variable")}</option>
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={!!values.epf_liable}
          disabled={deduction}
          onChange={(e) => set({ epf_liable: e.target.checked })}
        />{" "}
        {t("pc.epf")}
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={!!values.apit_taxable}
          disabled={deduction}
          onChange={(e) => set({ apit_taxable: e.target.checked })}
        />{" "}
        {t("pc.apit")}
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={!!values.is_allowance}
          disabled={deduction}
          onChange={(e) => set({ is_allowance: e.target.checked })}
        />{" "}
        {t("pc.allowance")}
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={!!values.in_day_rate}
          disabled={deduction}
          onChange={(e) => set({ in_day_rate: e.target.checked })}
        />{" "}
        {t("pc.dayRate")}
      </label>
      <label>
        {t("pc.order")}
        <input
          inputMode="numeric"
          value={String(values.sort_order ?? "")}
          onChange={(e) => set({ sort_order: Number(e.target.value.replace(/\D/g, "") || 0) })}
        />
      </label>
      {current && (
        <label className="check">
          <input type="checkbox" checked={!!values.is_active} onChange={(e) => set({ is_active: e.target.checked })} />{" "}
          {t("pc.inUse")}
        </label>
      )}
      {current && (
        <label className="wide">
          {t("pc.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      <p className="muted wide">{t("pc.flagsHelp")}</p>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("pc.save")}
        </button>
        <button type="button" className="secondary" onClick={onDone}>
          {t("pc.cancel")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}
