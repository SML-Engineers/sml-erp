import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../api/client";
import type { LogLevel } from "../../api/signInSecurity";
import { getSignInSecurity, setLogLevel, setSignInSecurity, signInSecurityKey } from "../../api/signInSecurity";

const LEVELS: LogLevel[] = ["changes", "sensitive", "everything"];

/** Security and logging. The Admin's switch for two-factor sign-in (owner, 12 Nov 2026): off
 * while testing, on before go-live. The activity log level (owner, 14 Nov 2026): what people
 * looked at and downloaded is recorded as well as changes and sign-ins. Only the Admin can
 * change them, with a reason; the server checks this too. */
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
  const current = data.data?.activity_log_level;
  const [chosen, setChosen] = useState<LogLevel | null>(null);
  const [levelReason, setLevelReason] = useState("");
  const changeLevel = useMutation({
    mutationFn: (level: LogLevel) => setLogLevel(level, levelReason),
    onSuccess: (result) => {
      queryClient.setQueryData(signInSecurityKey, result);
      setLevelReason("");
      setChosen(null);
    },
  });
  const picked = chosen ?? current;

  return (
    <main className="page">
      <h1>{t("security.title")}</h1>
      <p className="muted">{t("security.help")}</p>
      {on !== undefined && (
        <section className="panel" aria-label={t("security.twoFactor")}>
          <h2>{t("security.twoFactor")}</h2>
          <p className="muted">{t("security.twoFactorHelp")}</p>
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
      {current !== undefined && (
        <section className="panel" aria-label={t("security.logLevel")}>
          <h2>{t("security.logLevel")}</h2>
          <p className="muted">{t("security.logHelp")}</p>
          <fieldset disabled={!canChange}>
            <legend>{t("security.chooseLevel")}</legend>
            {LEVELS.map((level) => (
              <label key={level} className="radio-row">
                <input type="radio" name="activity-log-level" value={level} checked={picked === level} onChange={() => setChosen(level)} />
                <span>
                  <strong>{t(`security.level.${level}`)}</strong>
                  {level === current && <> ({t("security.inForce")})</>}
                  <br />
                  <span className="muted">{t(`security.levelHelp.${level}`)}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {canChange && picked !== current && picked && (
            <div className="inline-form">
              <label>
                {t("security.reason")}
                <input value={levelReason} onChange={(e) => setLevelReason(e.target.value)} />
              </label>
              <button type="button" disabled={changeLevel.isPending || !levelReason.trim()} onClick={() => changeLevel.mutate(picked)}>
                {t("security.saveLevel")}
              </button>
            </div>
          )}
          {changeLevel.error instanceof ApiError && <p className="error">{changeLevel.error.detail}</p>}
        </section>
      )}
    </main>
  );
}
