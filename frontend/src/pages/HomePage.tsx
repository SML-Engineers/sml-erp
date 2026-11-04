import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { getHealth } from "../api/health";
import FinancialDashboard from "../components/FinancialDashboard";
import PurchasingDashboard from "../components/PurchasingDashboard";
import SalesDashboard from "../components/SalesDashboard";
import VouchersDashboard from "../components/VouchersDashboard";

/** The dashboard. Each module adds its summary tiles here as it is built. */
export default function HomePage({ user }: { user: CurrentUser }) {
  const { t } = useTranslation();
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, retry: false });

  let status: string;
  if (health.isPending) status = t("home.checking");
  else if (health.isError) status = t("home.unreachable");
  else status = health.data.status === "ok" ? t("home.ok") : t("home.degraded");

  return (
    <main className="page">
      <h1>{t("menu.dashboard")}</h1>
      <section className="panel">
        <p>{t("home.welcome", { name: user.full_name })}</p>
        <p role="status">{status}</p>
        {health.data && (
          <p className="muted">{t("home.version", { version: health.data.version })}</p>
        )}
      </section>
      {can(user.access, "financial_reports", "view") && <FinancialDashboard />}
      {can(user.access, "vouchers", "view") && <VouchersDashboard me={user} />}
      {can(user.access, "sales", "view") && <SalesDashboard />}
      {can(user.access, "purchasing", "view") && <PurchasingDashboard />}
    </main>
  );
}
