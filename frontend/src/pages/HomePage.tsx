import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { can } from "../api/access";
import { signOut, type CurrentUser } from "../api/auth";
import { getHealth } from "../api/health";

export default function HomePage({ user }: { user: CurrentUser }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, retry: false });

  let status: string;
  if (health.isPending) status = t("home.checking");
  else if (health.isError) status = t("home.unreachable");
  else status = health.data.status === "ok" ? t("home.ok") : t("home.degraded");

  async function handleSignOut() {
    await signOut().catch(() => undefined);
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  return (
    <main className="home">
      <div className="home-header">
        <h1>{t("app.name")}</h1>
        <button type="button" className="secondary" onClick={handleSignOut}>
          {t("home.signOut")}
        </button>
      </div>
      <p>{t("home.welcome", { name: user.full_name })}</p>
      <p role="status">{status}</p>
      {health.data && (
        <p className="muted">{t("home.version", { version: health.data.version })}</p>
      )}
      {can(user.access, "users", "view") && (
        <nav aria-label={t("home.administration")}>
          <h2>{t("home.administration")}</h2>
          <ul>
            <li>
              <Link to="/admin/users">{t("users.title")}</Link>
            </li>
            <li>
              <Link to="/admin/access-review">{t("review.link")}</Link>
            </li>
          </ul>
        </nav>
      )}
    </main>
  );
}
