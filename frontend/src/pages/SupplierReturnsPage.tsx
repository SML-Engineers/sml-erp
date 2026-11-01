import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { listGoodsReceipts } from "../api/goodsReceipts";
import { createReturn, getReturnLots, listReturns, rtnKey, type ReturnKind } from "../api/supplierReturns";
import DataTable from "../components/DataTable";
import { formatQuantity } from "../lib/decimal";

/** Supplier returns (P16-12): rejected goods, or goods QC had accepted, sent back. */
export default function SupplierReturnsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const waiting = params.get("waiting") ?? "";
  const rows = useQuery({ queryKey: [...rtnKey, "list", waiting], queryFn: () => listReturns({ waiting }) });
  const [adding, setAdding] = useState(false);
  return (
    <main className="page">
      <h1>{t("rtn.title")}</h1>
      <p className="muted">{t("rtn.help")}</p>
      <div className="toolbar">
        {can(me.access, "stores", "enter") && (
          <button type="button" onClick={() => setAdding((v) => !v)}>
            {t("rtn.new")}
          </button>
        )}
        <label>
          <input type="checkbox" checked={waiting === "me"} onChange={(e) => setParams(e.target.checked ? { waiting: "me" } : {}, { replace: true })} />{" "}
          {t("quotations.waitingForMe")}
        </label>
      </div>
      {adding && <NewReturn />}
      {rows.data && (
        <DataTable
          label={t("rtn.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("rtn.none")}
          columns={[
            {
              id: "number",
              header: t("rtn.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/supplier-returns/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.return_date },
            { id: "grn", header: t("grn.number"), value: (r) => r.grn.number },
            { id: "supplier", header: t("po.supplier"), value: (r) => r.supplier.name },
            { id: "kind", header: t("rtn.kind"), value: (r) => t(`rtn.kinds.${r.kind}`) },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`rtn.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}

function NewReturn() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const grns = useQuery({ queryKey: ["goods-receipts", "list", "confirmed"], queryFn: () => listGoodsReceipts({ status: "confirmed" }) });
  const [grn, setGrn] = useState("");
  const [kind, setKind] = useState<ReturnKind>("rejected");
  const lots = useQuery({ queryKey: [...rtnKey, "lots", grn, kind], queryFn: () => getReturnLots(Number(grn), kind), enabled: Boolean(grn) });
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [vehicle, setVehicle] = useState("");
  const make = useMutation({
    mutationFn: () =>
      createReturn({
        grn: Number(grn),
        kind,
        reason,
        vehicle_no: vehicle,
        lines: (lots.data ?? [])
          .filter((l) => Number(quantities[`${l.grn_line}|${l.lot_no}`] || 0) > 0)
          .map((l) => ({ grn_line: l.grn_line, lot_no: l.lot_no, quantity: quantities[`${l.grn_line}|${l.lot_no}`] })),
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: rtnKey });
      navigate(`/supplier-returns/${made.id}`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    make.mutate();
  }
  return (
    <form className="panel form-grid" aria-label={t("rtn.form")} onSubmit={submit}>
      <label>
        {t("grn.number")}
        <select value={grn} required onChange={(e) => setGrn(e.target.value)}>
          <option value="">—</option>
          {(grns.data ?? []).map((g) => (
            <option key={g.id} value={g.id}>
              {g.number} · {g.supplier.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("rtn.kind")}
        <select value={kind} onChange={(e) => setKind(e.target.value as ReturnKind)}>
          <option value="rejected">{t("rtn.kinds.rejected")}</option>
          <option value="accepted">{t("rtn.kinds.accepted")}</option>
        </select>
      </label>
      {kind === "accepted" && <p className="wide notice">{t("rtn.acceptedHelp")}</p>}
      {lots.data && lots.data.length === 0 && <p className="wide muted">{t("rtn.noLots")}</p>}
      {lots.data && lots.data.length > 0 && (
        <div className="wide table-wrap">
          <table aria-label={t("rtn.lots")}>
            <thead>
              <tr>
                <th>{t("stock.lot")}</th>
                <th>{t("po.item")}</th>
                <th className="num">{t("rtn.inStore")}</th>
                <th className="num">{t("rtn.toReturn")}</th>
              </tr>
            </thead>
            <tbody>
              {lots.data.map((l) => {
                const key = `${l.grn_line}|${l.lot_no}`;
                return (
                  <tr key={key}>
                    <td className="mono">{l.lot_no}</td>
                    <td>
                      <span className="mono">{l.item.code}</span> {l.item.name}
                    </td>
                    <td className="num">
                      {formatQuantity(l.quantity)} {l.item.unit}
                    </td>
                    <td className="num">
                      <input
                        aria-label={t("rtn.toReturnOf", { lot: l.lot_no })}
                        inputMode="decimal"
                        value={quantities[key] ?? ""}
                        onChange={(e) => setQuantities((now) => ({ ...now, [key]: e.target.value }))}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <label className="wide">
        {t("rtn.reason")}
        <input value={reason} maxLength={2000} required onChange={(e) => setReason(e.target.value)} />
      </label>
      <label>
        {t("grn.vehicle")}
        <input value={vehicle} maxLength={30} onChange={(e) => setVehicle(e.target.value)} />
      </label>
      <div className="wide">
        <button type="submit" disabled={make.isPending}>
          {t("rtn.make")}
        </button>
      </div>
      {make.error && (
        <p className="form-error wide" role="alert">
          {make.error instanceof ApiError && make.error.detail ? make.error.detail : t("common.error")}
        </p>
      )}
    </form>
  );
}
