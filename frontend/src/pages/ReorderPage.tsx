import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { ApiError } from "../api/client";
import { itemsKey, listItems, listStores, storesKey } from "../api/items";
import { listPayees } from "../api/payees";
import {
  listReorder,
  removeReorder,
  requestFromReorder,
  requestsKey,
  saveReorder,
  type ReorderRow,
} from "../api/purchaseRequests";
import SearchSelect from "../components/SearchSelect";
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

/** Reorder levels per item and main store, with the stock, what is coming and a one-click
 * purchase request for those at or below their level (P2-13). */
export default function ReorderPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [lowOnly, setLowOnly] = useState(true);
  const rows = useQuery({ queryKey: [...requestsKey, "reorder", lowOnly], queryFn: () => listReorder(lowOnly) });
  const raise = useMutation({
    mutationFn: (row: ReorderRow) => requestFromReorder(row.id),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: requestsKey });
      navigate(`/purchase-requests/${made.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: (row: ReorderRow) => removeReorder(row.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: requestsKey }),
  });

  return (
    <main className="page">
      <h1>{t("reorder.title")}</h1>
      <p className="muted">{t("reorder.help")}</p>
      <div className="toolbar">
        <label className="check">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />
          {t("reorder.lowOnly")}
        </label>
      </div>
      {rows.data?.length === 0 && <p className="muted">{lowOnly ? t("reorder.noneLow") : t("reorder.none")}</p>}
      {rows.data && rows.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("reorder.title")}>
            <thead>
              <tr>
                <th>{t("reorder.item")}</th>
                <th>{t("reorder.store")}</th>
                <th className="num">{t("reorder.onHand")}</th>
                <th className="num">{t("reorder.coming")}</th>
                <th className="num">{t("reorder.level")}</th>
                <th className="num">{t("reorder.quantity")}</th>
                <th>{t("reorder.supplier")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.map((row) => (
                <tr key={row.id} className={row.low ? "warning-row" : undefined}>
                  <td>
                    <span className="mono">{row.item.code}</span> {row.item.name}
                    {row.low && <div className="form-error">{t("reorder.low")}</div>}
                  </td>
                  <td>{row.store.code}</td>
                  <td className="num">
                    {formatQuantity(row.on_hand)} {row.unit}
                  </td>
                  <td className="num">{formatQuantity(String(Number(row.on_order) + Number(row.requested)))}</td>
                  <td className="num">{formatQuantity(row.level)}</td>
                  <td className="num">{formatQuantity(row.quantity)}</td>
                  <td>{row.suggested_supplier?.name ?? "—"}</td>
                  <td>
                    {row.low && (
                      <button type="button" className="small" disabled={raise.isPending} onClick={() => raise.mutate(row)}>
                        {t("reorder.raise")}
                      </button>
                    )}{" "}
                    <button type="button" className="small secondary" disabled={remove.isPending} onClick={() => remove.mutate(row)}>
                      {t("reorder.remove")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorLine error={rows.error ?? raise.error ?? remove.error} />
      <LevelForm />
    </main>
  );
}

function LevelForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const items = useQuery({ queryKey: [...itemsKey, "list", "", "", false], queryFn: () => listItems("", "", false) });
  const stores = useQuery({ queryKey: storesKey, queryFn: listStores });
  const suppliers = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false) });
  const [item, setItem] = useState("");
  const [store, setStore] = useState("");
  const [level, setLevel] = useState("");
  const [quantity, setQuantity] = useState("");
  const [supplier, setSupplier] = useState("");
  const save = useMutation({
    mutationFn: () =>
      saveReorder({ item: Number(item), store: Number(store), level, quantity, usual_supplier: supplier ? Number(supplier) : null }),
    onSuccess: () => {
      setLevel("");
      setQuantity("");
      void queryClient.invalidateQueries({ queryKey: requestsKey });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const mainStores = (stores.data ?? []).filter((s) => s.kind === "main" && s.is_active);

  return (
    <form className="panel form-grid" aria-label={t("reorder.set")} onSubmit={submit}>
      <h2 className="wide">{t("reorder.set")}</h2>
      <p className="muted wide">{t("reorder.setHelp")}</p>
      <SearchSelect
        label={t("reorder.item")}
        options={(items.data ?? []).filter((i) => i.is_stock).map((i) => ({ value: String(i.id), label: `${i.code} ${i.name} (${i.unit})` }))}
        value={item}
        onChange={setItem}
      />
      <label>
        {t("reorder.store")}
        <select value={store} required onChange={(e) => setStore(e.target.value)}>
          <option value="">—</option>
          {mainStores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("reorder.level")}
        <input inputMode="decimal" required value={level} onChange={(e) => setLevel(e.target.value)} />
      </label>
      <label>
        {t("reorder.quantity")}
        <input inputMode="decimal" required value={quantity} onChange={(e) => setQuantity(e.target.value)} />
      </label>
      <label>
        {t("reorder.usualSupplier")}
        <select value={supplier} onChange={(e) => setSupplier(e.target.value)}>
          <option value="">{t("reorder.lastSupplier")}</option>
          {(suppliers.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </select>
      </label>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending || !item}>
          {t("reorder.save")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </form>
  );
}
