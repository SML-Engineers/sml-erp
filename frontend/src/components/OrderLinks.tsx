import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { ApiError } from "../api/client";
import type { SalesOrderDetail, SalesOrderStatus } from "../api/salesOrders";

/** Sales orders made from a quotation or proforma, and the button to make one (P15-10). */
export default function OrderLinks(props: {
  orders: { id: number; number: string; status: SalesOrderStatus }[];
  canMake: boolean;
  make: () => Promise<SalesOrderDetail>;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const make = useMutation({ mutationFn: props.make, onSuccess: (made) => navigate(`/sales-orders/${made.id}`) });
  return (
    <section className="panel" aria-label={t("salesOrders.title")}>
      <h2>{t("salesOrders.title")}</h2>
      {props.orders.length > 0 && (
        <ul className="changes">
          {props.orders.map((o) => (
            <li key={o.id}>
              <Link to={`/sales-orders/${o.id}`}>{o.number}</Link> <span className="muted">({t(`salesOrders.statuses.${o.status}`)})</span>
            </li>
          ))}
        </ul>
      )}
      {props.canMake && (
        <button type="button" disabled={make.isPending} onClick={() => make.mutate()}>
          {t("salesOrders.make")}
        </button>
      )}
      {make.error ? (
        <p className="form-error" role="alert">
          {make.error instanceof ApiError && make.error.detail ? make.error.detail : t("common.error")}
        </p>
      ) : null}
    </section>
  );
}
