import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { getHealth } from "../api/health";
import FinancialDashboard from "../components/FinancialDashboard";
import ProductionDashboard from "../components/ProductionDashboard";
import PurchasingDashboard from "../components/PurchasingDashboard";
import WaitingPanel from "../components/WaitingPanel";
import SupervisorDashboard from "../components/SupervisorDashboard";
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

  // Owner, 11 Nov 2026: the Production Manager (and planner) see production on the home page, not the sales
  // and purchasing summaries they can only look at (they still open those pages from the menu).
  // Owner, 12 Nov 2026: the Production Planner gets the same panel instead of the sales figures.
  const production = can(user.access, "production_approvals", "approve") || can(user.access, "production_planning", "enter");
  const onlyViews = (area: string) => !can(user.access, area, "enter") && !can(user.access, area, "approve");

  return (
    <main className="page">
      <h1>{t("menu.dashboard")}</h1>
      <section className="panel">
        <p>{t("home.welcome", { name: user.full_name })}</p>
        <p role="status">{status}</p>
        {health.data && <p className="muted">{t("home.version", { version: health.data.version })}</p>}
      </section>
      {can(user.access, "financial_reports", "view") && <FinancialDashboard />}
      {can(user.access, "vouchers", "view") && <VouchersDashboard me={user} />}
      <WaitingPanel />
      {production && <ProductionDashboard />}
      {/* Owner, 12 Nov 2026: a shop-floor supervisor's own sections. */}
      {!production && can(user.access, "shop_floor", "enter") && <SupervisorDashboard />}
      {can(user.access, "sales", "view") && !(production && onlyViews("sales")) && <SalesDashboard />}
      {can(user.access, "purchasing", "view") && !(production && onlyViews("purchasing")) && <PurchasingDashboard />}
    </main>
  );
}
