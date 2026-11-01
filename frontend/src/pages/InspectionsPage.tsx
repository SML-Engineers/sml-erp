import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { getQueue, listInspections, qcKey, startInspection } from "../api/inspections";
import DataTable from "../components/DataTable";
import { formatQuantity } from "../lib/decimal";

/** QC inspection (spec 6A.3): received goods waiting for QC, and the inspections done. */
export default function InspectionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const waiting = params.get("waiting") ?? "";
  const queue = useQuery({ queryKey: [...qcKey, "queue"], queryFn: getQueue });
  const rows = useQuery({ queryKey: [...qcKey, "list", status, waiting], queryFn: () => listInspections({ status, waiting }) });
  const start = useMutation({
    mutationFn: startInspection,
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: qcKey });
      navigate(`/inspections/${made.id}`);
    },
  });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("qc.title")}</h1>
      <p className="muted">{t("qc.help")}</p>
      <section className="panel" aria-label={t("qc.waiting")}>
        <h2>{t("qc.waiting")}</h2>
        {queue.data && queue.data.lines.length === 0 && <p className="muted">{t("qc.nothingWaiting")}</p>}
        {queue.data && queue.data.lines.length > 0 && (
          <div className="table-wrap">
            <table aria-label={t("qc.waiting")}>
              <thead>
                <tr>
                  <th>{t("grn.number")}</th>
                  <th>{t("po.item")}</th>
                  <th>{t("po.supplier")}</th>
                  <th className="num">{t("qc.toInspect")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {queue.data.lines.map((l) => (
                  <tr key={l.line}>
                    <td>
                      <Link to={`/goods-receipts/${l.grn.id}`} className="mono">
                        {l.grn.number}
                      </Link>
                    </td>
                    <td>
                      <span className="mono">{l.item.code}</span> {l.item.name}
                    </td>
                    <td>{l.supplier}</td>
                    <td className="num">
                      {formatQuantity(l.good_quantity)} {l.item.unit}
                      {l.packages > 0 && ` · ${t("qc.packages", { count: l.packages })}`}
                    </td>
                    <td>
                      {l.inspection ? (
                        <Link to={`/inspections/${l.inspection.id}`}>{t("qc.continue")}</Link>
                      ) : (
                        queue.data.can_inspect && (
                          <button type="button" disabled={start.isPending} onClick={() => start.mutate(l.line)}>
                            {t("qc.inspect", { item: l.item.code })}
                          </button>
                        )
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {start.error && (
          <p className="form-error" role="alert">
            {start.error instanceof ApiError && start.error.detail ? start.error.detail : t("common.error")}
          </p>
        )}
      </section>
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {(["draft", "deviation_requested", "decided"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`qc.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={waiting === "me"} onChange={(e) => set("waiting", e.target.checked ? "me" : "")} />{" "}
          {t("quotations.waitingForMe")}
        </label>
      </div>
      {rows.data && (
        <DataTable
          label={t("qc.done")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("qc.none")}
          columns={[
            {
              id: "grn",
              header: t("grn.number"),
              value: (r) => r.grn.number,
              cell: (r) => (
                <Link to={`/inspections/${r.id}`} className="mono">
                  {r.grn.number}
                </Link>
              ),
            },
            { id: "item", header: t("po.item"), value: (r) => r.item.code },
            { id: "supplier", header: t("po.supplier"), value: (r) => r.supplier.name },
            { id: "accepted", header: t("qc.accepted"), value: (r) => r.accepted_quantity, cell: (r) => formatQuantity(r.accepted_quantity) },
            { id: "rejected", header: t("qc.rejected"), value: (r) => r.rejected_quantity, cell: (r) => formatQuantity(r.rejected_quantity) },
            {
              id: "status",
              header: t("vouchers.status"),
              value: (r) => (r.decision ? t(`qc.decisions.${r.decision}`) : t(`qc.statuses.${r.status}`)),
            },
            { id: "by", header: t("qc.inspector"), value: (r) => r.inspector ?? "" },
          ]}
        />
      )}
    </main>
  );
}
