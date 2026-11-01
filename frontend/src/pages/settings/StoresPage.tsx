import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import { listDivisions } from "../../api/admin";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import { createStore, listStores, storesKey, updateStore, type Store } from "../../api/items";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Stores per division (spec 5A.2, 6A): main stores, and the quarantine where received goods
 * wait for QC and the rejected store for goods going back. Set by the Admin. */
export default function StoresPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const stores = useQuery({ queryKey: storesKey, queryFn: listStores });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const canManage = can(me.access, "settings", "manage");
  const [values, setValues] = useState({ code: "", name: "", division: "", kind: "main" });
  const [reason, setReason] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: storesKey });
  const add = useMutation({
    mutationFn: () => createStore(values),
    onSuccess: () => {
      setValues({ code: "", name: "", division: "", kind: "main" });
      refresh();
    },
  });
  const change = useMutation({
    mutationFn: ({ store, active }: { store: Store; active: boolean }) => updateStore(store.id, { is_active: active, reason }),
    onSuccess: () => {
      setReason("");
      refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <main className="page">
      <h1>{t("stores.title")}</h1>
      <p className="muted">{t("stores.help")}</p>
      {stores.data && (
        <div className="table-wrap panel">
          <table aria-label={t("stores.title")}>
            <thead>
              <tr>
                <th>{t("stores.code")}</th>
                <th>{t("stores.name")}</th>
                <th>{t("vouchers.division")}</th>
                <th>{t("stores.kind")}</th>
                <th>{t("users.status")}</th>
                {canManage && <th />}
              </tr>
            </thead>
            <tbody>
              {stores.data.map((s) => (
                <tr key={s.id}>
                  <td className="mono">{s.code}</td>
                  <td>{s.name}</td>
                  <td>{s.division}</td>
                  <td>{t(`stores.kinds.${s.kind}`)}</td>
                  <td>{s.is_active ? t("users.active") : t("users.inactive")}</td>
                  {canManage && (
                    <td>
                      {s.kind === "main" && (
                        <button type="button" className="small secondary" onClick={() => change.mutate({ store: s, active: !s.is_active })}>
                          {s.is_active ? t("items.deactivate") : t("items.reactivate")}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canManage && (
        <>
          <label className="inline-form">
            {t("stores.reasonToDeactivate")}
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <ErrorLine error={change.error} />
          <form className="panel form-grid" aria-label={t("stores.add")} onSubmit={submit}>
            <h2 className="wide">{t("stores.add")}</h2>
            <label>
              {t("stores.code")}
              <input value={values.code} maxLength={20} required onChange={(e) => setValues({ ...values, code: e.target.value.toUpperCase() })} />
            </label>
            <label>
              {t("stores.name")}
              <input value={values.name} maxLength={100} required onChange={(e) => setValues({ ...values, name: e.target.value })} />
            </label>
            <label>
              {t("vouchers.division")}
              <select value={values.division} required onChange={(e) => setValues({ ...values, division: e.target.value })}>
                <option value="">—</option>
                {(divisions.data ?? [])
                  .filter((d) => d.division_type !== "shared")
                  .map((d) => (
                    <option key={d.code} value={d.code}>
                      {d.code} {d.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              {t("stores.kind")}
              <select value={values.kind} onChange={(e) => setValues({ ...values, kind: e.target.value })}>
                {(["main", "quarantine", "rejected"] as const).map((k) => (
                  <option key={k} value={k}>
                    {t(`stores.kinds.${k}`)}
                  </option>
                ))}
              </select>
            </label>
            <div className="wide">
              <button type="submit" disabled={add.isPending}>
                {t("stores.add")}
              </button>
              <ErrorLine error={add.error} />
            </div>
          </form>
        </>
      )}
    </main>
  );
}
