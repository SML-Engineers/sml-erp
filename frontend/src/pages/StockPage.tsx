import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { getStock, listMovements, stockKey, type StockRow } from "../api/stock";
import DataTable from "../components/DataTable";
import { formatDecimal, formatQuantity } from "../lib/decimal";

/** Stock on hand (spec 5A.3): balances worked out from the stock movements, with their value
 * at the PO price, and the movements behind them. */
export default function StockPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const lots = params.get("lots") ?? "";
  const item = params.get("item") ?? "";
  const stock = useQuery({ queryKey: [...stockKey, "on-hand", lots], queryFn: () => getStock({ lots }) });
  const moves = useQuery({ queryKey: [...stockKey, "movements", item], queryFn: () => listMovements({ item }), enabled: Boolean(item) });
  const set = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <h1>{t("stock.title")}</h1>
      <p className="muted">{t("stock.help")}</p>
      <div className="toolbar">
        <label>
          <input type="checkbox" checked={lots === "1"} onChange={(e) => set("lots", e.target.checked ? "1" : "")} /> {t("stock.byLot")}
        </label>
        {stock.data?.sees_values && <strong>{t("stock.totalValue", { value: formatDecimal(stock.data.total_value) })}</strong>}
        <span className="export-links">
          <a href={`/api/v1/stock/?export=xlsx${lots ? "&lots=1" : ""}`}>Excel</a> · <a href={`/api/v1/stock/?export=pdf${lots ? "&lots=1" : ""}`}>PDF</a>
        </span>
      </div>
      {stock.data && (
        <DataTable
          label={t("stock.title")}
          rows={stock.data.rows}
          rowKey={(r) => `${r.item.id}-${r.store.id}-${r.lot_no ?? ""}`}
          emptyText={t("stock.none")}
          columns={[
            {
              id: "item",
              header: t("po.item"),
              value: (r) => `${r.item.code} ${r.item.name}`,
              cell: (r) => (
                <button type="button" className="link-button" onClick={() => set("item", String(r.item.id))}>
                  <span className="mono">{r.item.code}</span> {r.item.name}
                </button>
              ),
            },
            { id: "store", header: t("stock.store"), value: (r) => `${r.store.code} · ${t(`stock.kinds.${r.store.kind}`)}` },
            ...(lots === "1" ? [{ id: "lot", header: t("stock.lot"), value: (r: StockRow) => r.lot_no ?? "" }] : []),
            { id: "quantity", header: t("quotations.quantity"), value: (r) => r.quantity, cell: (r) => `${formatQuantity(r.quantity)} ${r.item.unit}` },
            // Owner, 12 Nov 2026: values only for people who may see costs.
            ...(stock.data.sees_values
              ? [
                  {
                    id: "cost",
                    header: t("stock.averageCost"),
                    value: (r: StockRow) => r.average_cost ?? "",
                    cell: (r: StockRow) => (r.average_cost ? formatDecimal(r.average_cost) : ""),
                  },
                  { id: "value", header: t("stock.value"), value: (r: StockRow) => r.value ?? "", cell: (r: StockRow) => formatDecimal(r.value) },
                ]
              : []),
          ]}
        />
      )}
      {item && moves.data && (
        <section className="panel" aria-label={t("stock.movements")}>
          <h2>
            {t("stock.movements")}{" "}
            <button type="button" className="secondary" onClick={() => set("item", "")}>
              {t("stock.close")}
            </button>
          </h2>
          <div className="table-wrap">
            <table aria-label={t("stock.movements")}>
              <thead>
                <tr>
                  <th>{t("vouchers.date")}</th>
                  <th>{t("stock.what")}</th>
                  <th>{t("stock.store")}</th>
                  <th>{t("stock.lot")}</th>
                  <th className="num">{t("quotations.quantity")}</th>
                  {stock.data?.sees_values && <th className="num">{t("stock.value")}</th>}
                  <th>{t("stock.source")}</th>
                </tr>
              </thead>
              <tbody>
                {moves.data.map((m) => (
                  <tr key={m.id}>
                    <td>{m.date}</td>
                    <td>{t(`stock.movementKinds.${m.kind}`)}</td>
                    <td>{m.store}</td>
                    <td className="mono">{m.lot_no}</td>
                    <td className="num">{formatQuantity(m.quantity)}</td>
                    {stock.data?.sees_values && <td className="num">{Number(m.value) !== 0 ? formatDecimal(m.value) : ""}</td>}
                    <td>
                      {m.grn && <Link to={`/goods-receipts/${m.grn.id}`}>{m.grn.number}</Link>}
                      {m.opening && <Link to={`/opening-stock/${m.opening.id}`}>{m.opening.number}</Link>}
                      {m.journal && ` · ${m.journal}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
