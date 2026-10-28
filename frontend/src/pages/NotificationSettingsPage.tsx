import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { getPreferences, preferencesKey, setPreference } from "../api/notifications";

/** Each person chooses which notifications reach them under the bell and by email. */
export default function NotificationSettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const rows = useQuery({ queryKey: preferencesKey, queryFn: getPreferences });
  const save = useMutation({
    mutationFn: (args: { event: string; in_app?: boolean; email?: boolean }) =>
      setPreference(args.event, { in_app: args.in_app, email: args.email }),
    onSuccess: (data) => queryClient.setQueryData(preferencesKey, data),
  });

  return (
    <main className="page">
      <h1>{t("bell.settingsTitle")}</h1>
      <p className="muted">{t("bell.settingsHelp")}</p>
      {rows.data && (
        <div className="table-wrap">
          <table aria-label={t("bell.settingsTitle")}>
            <thead>
              <tr>
                <th>{t("bell.event")}</th>
                <th>{t("bell.inApp")}</th>
                <th>{t("bell.email")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((row) => (
                <tr key={row.event}>
                  <td>{t(`bell.events.${row.event}`, { defaultValue: row.label })}</td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t("bell.inAppFor", { event: row.label })}
                      checked={row.in_app}
                      onChange={(e) => save.mutate({ event: row.event, in_app: e.target.checked })}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t("bell.emailFor", { event: row.label })}
                      checked={row.email}
                      onChange={(e) => save.mutate({ event: row.event, email: e.target.checked })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {save.error && (
        <p className="form-error" role="alert">
          {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
        </p>
      )}
    </main>
  );
}
