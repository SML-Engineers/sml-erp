import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import { itemsKey, listItems } from "../api/items";
import { listPayees } from "../api/payees";
import { createRequest, listRequests, requestsKey } from "../api/purchaseRequests";
import SearchSelect from "../components/SearchSelect";

const STATUSES = ["draft", "awaiting_approval", "approved", "rejected", "ordered", "cancelled"] as const;

/** Purchase requests (P2-13): raised by the stores person or purchasing, approved, then made
 * into a draft purchase order. */
export default function PurchaseRequestsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const rows = useQuery({ queryKey: [...requestsKey, "list", status], queryFn: () => listRequests(status) });

  return (
    <main className="page">
      <h1>{t("prq.title")}</h1>
      <p className="muted">{t("prq.help")}</p>
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {}, { replace: true })}>
            <option value="">{t("advances.allStatuses")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`prq.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <Link className="button-link secondary" to="/reorder">
          {t("reorder.title")}
        </Link>
      </div>
      {rows.data?.length === 0 && <p className="muted">{t("prq.none")}</p>}
      {rows.data && rows.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("prq.title")}>
            <thead>
              <tr>
                <th>{t("prq.number")}</th>
                <th>{t("prq.status")}</th>
                <th>{t("vouchers.division")}</th>
                <th>{t("reorder.supplier")}</th>
                <th>{t("prq.neededBy")}</th>
                <th>{t("prq.raisedBy")}</th>
                <th>{t("prq.order")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link className="mono" to={`/purchase-requests/${r.id}`}>
                      {r.number}
                    </Link>
                    {r.from_reorder && <div className="muted">{t("prq.fromReorder")}</div>}
                  </td>
                  <td>{t(`prq.statuses.${r.status}`)}</td>
                  <td>{r.division}</td>
                  <td>{r.supplier?.name ?? "—"}</td>
                  <td>{r.needed_by ?? ""}</td>
                  <td>{r.created_by}</td>
                  <td>{r.purchase_order ? <Link to={`/purchase-orders/${r.purchase_order.id}`}>{r.purchase_order.label}</Link> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <NewRequest />
    </main>
  );
}

interface LineRow {
  item: string;
  quantity: string;
}

function NewRequest() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const items = useQuery({ queryKey: [...itemsKey, "list", "", "", false], queryFn: () => listItems("", "", false) });
  const suppliers = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false) });
  const [division, setDivision] = useState("");
  const [supplier, setSupplier] = useState("");
  const [neededBy, setNeededBy] = useState("");
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<LineRow[]>([{ item: "", quantity: "" }]);
  const setLine = (index: number, change: Partial<LineRow>) =>
    setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const save = useMutation({
    mutationFn: () =>
      createRequest({
        division,
        supplier: supplier ? Number(supplier) : null,
        needed_by: neededBy || null,
        reason,
        lines: lines.filter((l) => l.item).map((l) => ({ item: Number(l.item), quantity: l.quantity })),
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: requestsKey });
      navigate(`/purchase-requests/${made.id}`);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const itemOptions = (items.data ?? [])
    .filter((i) => i.is_stock)
    .map((i) => ({ value: String(i.id), label: `${i.code} ${i.name} (${i.unit})` }));

  return (
    <form className="panel form-grid" aria-label={t("prq.new")} onSubmit={submit}>
      <h2 className="wide">{t("prq.new")}</h2>
      <label>
        {t("vouchers.division")}
        <select value={division} required onChange={(e) => setDivision(e.target.value)}>
          <option value="">—</option>
          {divisions.data
            ?.filter((d) => d.code !== "HO")
            .map((d) => (
              <option key={d.code} value={d.code}>
                {d.code} {d.name}
              </option>
            ))}
        </select>
      </label>
      <label>
        {t("reorder.supplier")}
        <select value={supplier} onChange={(e) => setSupplier(e.target.value)}>
          <option value="">—</option>
          {(suppliers.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("prq.neededBy")}
        <input type="date" value={neededBy} onChange={(e) => setNeededBy(e.target.value)} />
      </label>
      <label className="wide">
        {t("prq.reason")}
        <input value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
      </label>
      {lines.map((line, index) => (
        <div key={index} className="wide split-row">
          <SearchSelect
            label={t("prq.itemOf", { n: String(index + 1) })}
            options={itemOptions}
            value={line.item}
            onChange={(value) => setLine(index, { item: value })}
          />
          <label>
            {t("prq.quantityOf", { n: String(index + 1) })}
            <input inputMode="decimal" value={line.quantity} onChange={(e) => setLine(index, { quantity: e.target.value })} />
          </label>
        </div>
      ))}
      <div className="wide row-actions">
        <button type="button" className="secondary" onClick={() => setLines((now) => [...now, { item: "", quantity: "" }])}>
          {t("prq.addLine")}
        </button>
        <button type="submit" disabled={save.isPending}>
          {t("prq.saveDraft")}
        </button>
      </div>
      {save.error ? (
        <p className="form-error wide" role="alert">
          {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
        </p>
      ) : null}
    </form>
  );
}
