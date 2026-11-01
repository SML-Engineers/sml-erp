import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { createGoodsReceipt, grnKey, GRN_STATUSES, listGoodsReceipts, listReceivable } from "../api/goodsReceipts";
import DataTable from "../components/DataTable";

/** Goods receiving notes (spec 5A.2): the stores person receives against approved POs. */
export default function GoodsReceiptsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const waiting = params.get("waiting") ?? "";
  const purchaseOrder = params.get("purchase_order") ?? "";
  const rows = useQuery({
    queryKey: [...grnKey, "list", status, waiting, purchaseOrder],
    queryFn: () => listGoodsReceipts({ status, waiting, purchase_order: purchaseOrder }),
  });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("grn.title")}</h1>
      <p className="muted">{t("grn.help")}</p>
      {can(me.access, "stores", "enter") && <Receivable />}
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {GRN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`grn.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={waiting === "me"} onChange={(e) => set("waiting", e.target.checked ? "me" : "")} />{" "}
          {t("quotations.waitingForMe")}
        </label>
        {purchaseOrder && (
          <button type="button" className="secondary" onClick={() => set("purchase_order", "")}>
            {t("grn.allOrders")}
          </button>
        )}
      </div>
      {rows.data && (
        <DataTable
          label={t("grn.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("grn.none")}
          columns={[
            {
              id: "number",
              header: t("grn.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/goods-receipts/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.receipt_date },
            {
              id: "po",
              header: t("grn.po"),
              value: (r) => r.purchase_order.label,
              cell: (r) => <Link to={`/purchase-orders/${r.purchase_order.id}`}>{r.purchase_order.label}</Link>,
            },
            { id: "supplier", header: t("po.supplier"), value: (r) => r.supplier.name },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            { id: "note", header: t("grn.deliveryNote"), value: (r) => r.delivery_note_no },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`grn.statuses.${r.status}`) },
            { id: "by", header: t("grn.receivedBy"), value: (r) => r.created_by },
          ]}
        />
      )}
    </main>
  );
}

function Receivable() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const orders = useQuery({ queryKey: [...grnKey, "receivable"], queryFn: listReceivable });
  const make = useMutation({
    mutationFn: createGoodsReceipt,
    onSuccess: (grn) => {
      void queryClient.invalidateQueries({ queryKey: grnKey });
      navigate(`/goods-receipts/${grn.id}`);
    },
  });
  return (
    <section className="panel" aria-label={t("grn.receive")}>
      <h2>{t("grn.receive")}</h2>
      {orders.data && orders.data.length === 0 && <p className="muted">{t("grn.nothingToReceive")}</p>}
      {orders.data && orders.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("grn.ordersToReceive")}>
            <thead>
              <tr>
                <th>{t("grn.po")}</th>
                <th>{t("po.supplier")}</th>
                <th>{t("vouchers.division")}</th>
                <th>{t("po.deliveryDate")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {orders.data.map((o) => (
                <tr key={o.id}>
                  <td className="mono">{o.label}</td>
                  <td>{o.supplier.name}</td>
                  <td>{o.division}</td>
                  <td>{o.delivery_date ?? "—"}</td>
                  <td>
                    <button type="button" disabled={make.isPending} onClick={() => make.mutate(o.id)}>
                      {t("grn.receiveFrom", { po: o.label })}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {make.error && (
        <p className="form-error" role="alert">
          {make.error instanceof ApiError && make.error.detail ? make.error.detail : t("common.error")}
        </p>
      )}
    </section>
  );
}
