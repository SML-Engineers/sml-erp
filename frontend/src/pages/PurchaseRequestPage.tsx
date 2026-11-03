import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import { listPayees } from "../api/payees";
import {
  getRequest,
  orderRequest,
  requestAction,
  requestsKey,
  type RequestDetail,
} from "../api/purchaseRequests";
import { formatDecimal, formatQuantity } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** One purchase request (P2-13): send it, approve or return it, cancel it, or make it into a
 * draft purchase order. */
export default function PurchaseRequestPage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const key = [...requestsKey, "one", id];
  const found = useQuery({ queryKey: key, queryFn: () => getRequest(id) });
  if (!found.data) return <ErrorLine error={found.error} />;
  const r = found.data;
  return (
    <main className="page">
      <h1>
        {t("prq.one")} <span className="mono">{r.number}</span>
      </h1>
      <p>
        <strong>{t(`prq.statuses.${r.status}`)}</strong> · {r.division}
        {r.store && ` · ${r.store}`} · {t("prq.raisedByName", { name: r.created_by })}
        {r.from_reorder && ` · ${t("prq.fromReorder")}`}
      </p>
      <dl className="details">
        <dt>{t("reorder.supplier")}</dt>
        <dd>{r.supplier?.name ?? "—"}</dd>
        <dt>{t("prq.neededBy")}</dt>
        <dd>{r.needed_by ?? "—"}</dd>
        <dt>{t("prq.reason")}</dt>
        <dd>{r.reason || "—"}</dd>
        {r.end_reason && (
          <>
            <dt>{t("prq.endReason")}</dt>
            <dd>{r.end_reason}</dd>
          </>
        )}
        {r.purchase_order && (
          <>
            <dt>{t("prq.order")}</dt>
            <dd>
              <Link to={`/purchase-orders/${r.purchase_order.id}`}>{r.purchase_order.label}</Link>
            </dd>
          </>
        )}
      </dl>
      <div className="table-wrap">
        <table aria-label={t("prq.lines")}>
          <thead>
            <tr>
              <th>#</th>
              <th>{t("reorder.item")}</th>
              <th className="num">{t("prq.quantity")}</th>
              <th className="num">{t("prq.lastPrice")}</th>
            </tr>
          </thead>
          <tbody>
            {r.lines.map((line) => (
              <tr key={line.line_no}>
                <td>{line.line_no}</td>
                <td>
                  <span className="mono">{line.item.code}</span> {line.item.name}
                  {line.notes && <div className="muted">{line.notes}</div>}
                </td>
                <td className="num">
                  {formatQuantity(line.quantity)} {line.unit}
                </td>
                <td className="num">{line.last_price ? formatDecimal(line.last_price) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Actions request={r} />
      {r.can_order && <MakeOrder request={r} />}
      {r.approvals.length > 0 && (
        <section className="panel" aria-label={t("prq.history")}>
          <h2>{t("prq.history")}</h2>
          <ol className="changes">
            {r.approvals.map((a, i) => (
              <li key={i}>
                {a.acted_at.slice(0, 16).replace("T", " ")} · {a.user} · {a.action}
                {a.reason && `: ${a.reason}`}
              </li>
            ))}
          </ol>
        </section>
      )}
    </main>
  );
}

function Actions({ request }: { request: RequestDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const act = useMutation({
    mutationFn: (action: "submit" | "approve" | "return" | "reject" | "cancel") => requestAction(request.id, action, text),
    onSuccess: (data) => {
      setText("");
      queryClient.setQueryData([...requestsKey, "one", request.id], data);
      void queryClient.invalidateQueries({ queryKey: requestsKey });
    },
  });
  const can = request.can_edit || request.can_approve || request.can_cancel;
  if (!can) return null;
  return (
    <section className="panel" aria-label={t("prq.actions")}>
      <label className="inline-form">
        {t("prq.commentOrReason")}
        <input value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="row-actions">
        {request.can_edit && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate("submit")}>
            {t("prq.submit")}
          </button>
        )}
        {request.can_approve && (
          <>
            <button type="button" disabled={act.isPending} onClick={() => act.mutate("approve")}>
              {t("prq.approve")}
            </button>
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("return")}>
              {t("prq.return")}
            </button>
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("reject")}>
              {t("prq.reject")}
            </button>
          </>
        )}
        {request.can_cancel && (
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("cancel")}>
            {t("prq.cancel")}
          </button>
        )}
      </div>
      <ErrorLine error={act.error} />
    </section>
  );
}

function MakeOrder({ request }: { request: RequestDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const suppliers = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false) });
  const [supplier, setSupplier] = useState(request.supplier ? String(request.supplier.id) : "");
  const [prices, setPrices] = useState<Record<string, string>>({});
  const order = useMutation({
    mutationFn: () =>
      orderRequest(request.id, {
        supplier: supplier ? Number(supplier) : null,
        prices: Object.fromEntries(Object.entries(prices).filter(([, v]) => v)),
      }),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: requestsKey });
      if (data.purchase_order) navigate(`/purchase-orders/${data.purchase_order.id}`);
    },
  });
  return (
    <section className="panel form-grid" aria-label={t("prq.makeOrder")}>
      <h2 className="wide">{t("prq.makeOrder")}</h2>
      <p className="muted wide">{t("prq.makeOrderHelp")}</p>
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
      {request.lines.map((line) => (
        <label key={line.line_no}>
          {t("prq.priceOf", { n: String(line.line_no), item: line.item.code })}
          <input
            inputMode="decimal"
            placeholder={line.last_price ?? ""}
            value={prices[String(line.line_no)] ?? ""}
            onChange={(e) => setPrices((now) => ({ ...now, [String(line.line_no)]: e.target.value }))}
          />
        </label>
      ))}
      <div className="wide row-actions">
        <button type="button" disabled={order.isPending} onClick={() => order.mutate()}>
          {t("prq.makeOrderButton")}
        </button>
      </div>
      <ErrorLine error={order.error} />
    </section>
  );
}
