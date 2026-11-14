import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../api/client";
import { getSignInSecurity, setSignInSecurity, signInSecurityKey } from "../../api/signInSecurity";

/** The Admin's switch for two-factor sign-in (owner, 12 Nov 2026): off while testing, on before
 * go-live. Only the Admin can change it; the server checks this too. */
export default function SignInSecurityPage({ canChange }: { canChange: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const data = useQuery({ queryKey: signInSecurityKey, queryFn: getSignInSecurity });
  const [reason, setReason] = useState("");
  const change = useMutation({
    mutationFn: (on: boolean) => setSignInSecurity(on, reason),
    onSuccess: (result) => {
      queryClient.setQueryData(signInSecurityKey, result);
      setReason("");
    },
  });
  const on = data.data?.two_factor_on;

  return (
    <main className="page">
      <h1>{t("security.title")}</h1>
      <p className="muted">{t("security.help")}</p>
      {on !== undefined && (
        <section className="panel" aria-label={t("security.twoFactor")}>
          <h2>{t("security.twoFactor")}</h2>
          <p role="status" className={on ? undefined : "warning-text"}>
            <strong>{on ? t("security.isOn") : t("security.isOff")}</strong>
          </p>
          {!on && <p className="warning-text">{t("security.offWarning")}</p>}
          {canChange && (
            <div className="inline-form">
              <label>
                {t("security.reason")}
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button type="button" disabled={change.isPending || !reason.trim()} onClick={() => change.mutate(!on)}>
                {on ? t("security.switchOff") : t("security.switchOn")}
              </button>
            </div>
          )}
          {change.error instanceof ApiError && <p className="error">{change.error.detail}</p>}
        </section>
      )}
    </main>
  );
}
