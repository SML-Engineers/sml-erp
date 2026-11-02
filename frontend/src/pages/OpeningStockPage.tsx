import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  approveOpeningStock,
  deleteOpeningStock,
  getOpeningStock,
  osKey,
  rejectOpeningStock,
  reloadOpeningStock,
  returnOpeningStock,
  submitOpeningStock,
  type OSDetail,
} from "../api/openingStock";
import OpeningStockUpload from "../components/OpeningStockUpload";
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

/** One opening stock (P16-15): its counted lines, loading the sheet again, and the Director's approval. */
export default function OpeningStockPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: [...osKey, "one", id], queryFn: () => getOpeningStock(Number(id)) });
  const data = found.data;
  const done = (latest: OSDetail) => {
    queryClient.setQueryData([...osKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...osKey, "list"] });
  };

  return (
    <main className="page">
      <p>
        <Link to="/opening-stock">{t("os.backToList")}</Link>
      </p>
      <h1>
        {t("os.one")} {data?.number ?? ""}
      </h1>
      {data && (
        <>
          <p className="muted">
            {t(`os.statuses.${data.status}`)} · {t("os.countDate")} {data.count_date} · {t("os.enteredBy")} {data.created_by} · LKR{" "}
            {formatDecimal(data.value)}
            {data.journal_entry && (
              <>
                {" · "}
                {t("os.postedAs")}{" "}
                <Link to={`/journal?q=${encodeURIComponent(data.journal_entry.number)}`} className="mono">
                  {data.journal_entry.number}
                </Link>
              </>
            )}
          </p>
          {data.notes && <p>{data.notes}</p>}
          {data.can_edit && (
            <OpeningStockUpload
              key={`${data.id}-${data.value}`}
              start={{ count_date: data.count_date, notes: data.notes }}
              send={(file, date, notes, dryRun) => reloadOpeningStock(data.id, file, date, notes, dryRun)}
              onLoaded={done}
            />
          )}
          <Rows data={data} />
          <Actions data={data} done={done} />
        </>
      )}
      <ErrorLine error={found.error} />
    </main>
  );
}

function Rows({ data }: { data: OSDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("os.rows")}>
      <div className="table-wrap">
        <table aria-label={t("os.rows")}>
          <thead>
            <tr>
              <th>{t("os.item")}</th>
              <th>{t("os.store")}</th>
              <th>{t("os.lot")}</th>
              <th className="num">{t("os.quantity")}</th>
              <th className="num">{t("os.unitCost")}</th>
              <th className="num">{t("os.value")}</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.line_no}>
                <td>
                  <span className="mono">{r.item.code}</span> {r.item.name}
                </td>
                <td>{r.store}</td>
                <td className="mono">{r.lot_no}</td>
                <td className="num">
                  {formatQuantity(r.quantity)} {r.unit}
                </td>
                <td className="num">{formatDecimal(r.unit_cost)}</td>
                <td className="num">{formatDecimal(r.value)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={5}>{t("vouchers.total")}</th>
              <th className="num">{formatDecimal(data.value)}</th>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function Actions({ data, done }: { data: OSDetail; done: (latest: OSDetail) => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const act = useMutation({
    mutationFn: (call: () => Promise<OSDetail>) => call(),
    onSuccess: (latest) => {
      done(latest);
      setText("");
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteOpeningStock(data.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [...osKey, "list"] });
      navigate("/opening-stock");
    },
  });
  if (!data.can_edit && !data.can_approve && !data.approval) return null;

  return (
    <section className="panel" aria-label={t("os.actions")}>
      {data.can_edit && (
        <p>
          <button type="button" disabled={act.isPending || data.lines === 0} onClick={() => act.mutate(() => submitOpeningStock(data.id))}>
            {t("os.send")}
          </button>{" "}
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("os.delete")}
          </button>{" "}
          <span className="muted">{t("os.sendHelp")}</span>
        </p>
      )}
      {data.can_approve && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveOpeningStock(data.id, text))}>
            {t("os.approve")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnOpeningStock(data.id, text))}>
            {t("salesOrders.sendBack")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => rejectOpeningStock(data.id, text))}>
            {t("os.reject")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error ?? remove.error} />
      {data.approval && data.approval.history.length > 0 && (
        <ul className="changes" aria-label={t("salesOrders.approvalHistory")}>
          {data.approval.history.map((h, i) => (
            <li key={i}>
              {h.at.slice(0, 16).replace("T", " ")} · {h.action_label} · {h.by}
              {h.reason ? ` · ${h.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
