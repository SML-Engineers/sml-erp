import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { ApiError } from "../api/client";
import type { SalesOrderDetail, SalesOrderStatus } from "../api/salesOrders";
import AskAgain from "./AskAgain";

/** Sales orders made from a quotation or proforma, and the button to make one (P15-10). */
export default function OrderLinks(props: {
  orders: { id: number; number: string; status: SalesOrderStatus }[];
  canMake: boolean;
  /** `again`: yes, make another one although one exists (testing T17, 21 Nov 2026). */
  make: (again: boolean) => Promise<SalesOrderDetail>;
  source: "quotation" | "proforma";
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const make = useMutation({ mutationFn: props.make, onSuccess: (made) => navigate(`/sales-orders/${made.id}`) });
  const existing = props.orders.filter((o) => o.status !== "cancelled").map((o) => o.number);
  const [asking, setAsking] = useState(false);
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
      {props.canMake && !asking && (
        <button type="button" disabled={make.isPending} onClick={() => (existing.length > 0 ? setAsking(true) : make.mutate(false))}>
          {t("salesOrders.make")}
        </button>
      )}
      {asking && (
        <AskAgain
          question={t(`salesOrders.makeAgain_${props.source}`, { numbers: existing.join(", "), count: existing.length })}
          yes={t("salesOrders.makeAgainYes")}
          busy={make.isPending}
          onYes={() => make.mutate(true)}
          onNo={() => setAsking(false)}
        />
      )}
      {make.error ? (
        <p className="form-error" role="alert">
          {make.error instanceof ApiError && make.error.detail ? make.error.detail : t("common.error")}
        </p>
      ) : null}
    </section>
  );
}
