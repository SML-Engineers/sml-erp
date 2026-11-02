import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { listOpeningStock, loadOpeningStock, osKey } from "../api/openingStock";
import DataTable from "../components/DataTable";
import OpeningStockUpload from "../components/OpeningStockUpload";
import { formatDecimal } from "../lib/decimal";

/** Opening stock (P16-15): the stores counted at go-live, loaded from Excel, approved by the Director. */
export default function OpeningStocksPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const rows = useQuery({ queryKey: [...osKey, "list"], queryFn: () => listOpeningStock() });

  return (
    <main className="page">
      <h1>{t("os.title")}</h1>
      <p className="muted">{t("os.help")}</p>
      {can(me.access, "accounting", "enter") && (
        <OpeningStockUpload
          send={loadOpeningStock}
          onLoaded={(saved) => {
            queryClient.setQueryData([...osKey, "one", String(saved.id)], saved);
            void queryClient.invalidateQueries({ queryKey: [...osKey, "list"] });
            navigate(`/opening-stock/${saved.id}`);
          }}
        />
      )}
      {rows.data && (
        <DataTable
          label={t("os.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("os.none")}
          columns={[
            {
              id: "number",
              header: t("os.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/opening-stock/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("os.countDate"), value: (r) => r.count_date },
            { id: "lines", header: t("os.lines"), value: (r) => r.lines },
            { id: "value", header: t("os.value"), value: (r) => r.value, cell: (r) => formatDecimal(r.value) },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`os.statuses.${r.status}`) },
            { id: "by", header: t("os.enteredBy"), value: (r) => r.created_by },
          ]}
        />
      )}
    </main>
  );
}
