import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canDo } from "../../api/access";
import { getReview, recordReview } from "../../api/admin";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import { formatDate } from "../../lib/time";

export default function AccessReviewPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const review = useQuery({ queryKey: ["access-review"], queryFn: getReview });
  const record = useMutation({
    mutationFn: (args: { user: number; outcome: "confirmed" | "changed" }) =>
      recordReview(args.user, args.outcome),
    onSuccess: (data) => queryClient.setQueryData(["access-review"], data),
  });
  const canRecord = canDo(me.access, "confirm_sensitive_grants");

  return (
    <main className="page">
      <p className="breadcrumb">
        <Link to="/">{t("app.name")}</Link>
      </p>
      <h1>{t("review.title", { period: review.data?.period ?? "" })}</h1>
      <p className="muted">{t("review.help")}</p>
      {record.isError && (
        <p className="form-error" role="alert">
          {record.error instanceof ApiError && record.error.detail
            ? record.error.detail
            : t("common.error")}
        </p>
      )}
      {review.isPending && <p className="muted">{t("common.loading")}</p>}
      {review.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("users.fullName")}</th>
                <th>{t("users.roles")}</th>
                <th>{t("review.sensitive")}</th>
                <th>{t("access.overrides")}</th>
                <th>{t("users.lastSignIn")}</th>
                <th>{t("review.reviewed")}</th>
              </tr>
            </thead>
            <tbody>
              {review.data.rows.map((row) => (
                <tr key={row.user_id} className={row.pending_sensitive ? "flagged" : undefined}>
                  <td>
                    <Link to={`/admin/users/${row.user_id}`}>{row.full_name}</Link>
                    <div className="muted">{row.email}</div>
                  </td>
                  <td>
                    {row.roles.join(", ") || "—"}
                    {row.conflicts.map((c) => (
                      <div key={c} className="warning-text">
                        {c}
                      </div>
                    ))}
                  </td>
                  <td>{row.sensitive_access.join(", ") || "—"}</td>
                  <td>
                    {row.overrides.length === 0
                      ? "—"
                      : row.overrides.map((o) => (
                          <div key={o.id}>
                            {o.effect === "grant" ? "+" : "−"} {o.target}
                            {o.status === "pending" && ` (${t("access.status.pending")})`}
                          </div>
                        ))}
                  </td>
                  <td>{row.last_login ? formatDate(row.last_login) : "—"}</td>
                  <td>
                    {row.review ? (
                      t(`review.outcome.${row.review.outcome}`)
                    ) : canRecord && row.email !== me.email ? (
                      <span className="row-actions">
                        <button
                          type="button"
                          className="small"
                          onClick={() => record.mutate({ user: row.user_id, outcome: "confirmed" })}
                        >
                          {t("review.confirm")}
                        </button>
                        <button
                          type="button"
                          className="small secondary"
                          onClick={() => record.mutate({ user: row.user_id, outcome: "changed" })}
                        >
                          {t("review.changed")}
                        </button>
                      </span>
                    ) : (
                      t("review.notYet")
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
