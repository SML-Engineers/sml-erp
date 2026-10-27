import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { getHealth } from "../api/health";

export default function HomePage() {
  const { t } = useTranslation();
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, retry: false });

  let status: string;
  if (health.isPending) status = t("home.checking");
  else if (health.isError) status = t("home.unreachable");
  else status = health.data.status === "ok" ? t("home.ok") : t("home.degraded");

  return (
    <main className="home">
      <h1>{t("app.name")}</h1>
      <p role="status">{status}</p>
      {health.data && (
        <p className="muted">{t("home.version", { version: health.data.version })}</p>
      )}
    </main>
  );
}
