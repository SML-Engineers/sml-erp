import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { confirmTwoFactor, meQueryKey, startTwoFactorSetup } from "../api/auth";
import { ApiError } from "../api/client";

export default function TwoFactorSetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  const setup = useMutation({ mutationFn: startTwoFactorSetup });
  const confirm = useMutation({
    mutationFn: confirmTwoFactor,
    onSuccess: (data) => setRecoveryCodes(data.recovery_codes),
  });

  // Start once, even when React runs effects twice in development; a second start would
  // replace the secret behind the QR code already on screen.
  const started = useRef(false);
  const start = setup.mutate;
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    start();
  }, [start]);

  function submit(event: FormEvent) {
    event.preventDefault();
    confirm.mutate(code);
  }

  async function done() {
    await queryClient.invalidateQueries({ queryKey: meQueryKey });
    navigate("/", { replace: true });
  }

  const errorText = (error: unknown) =>
    error instanceof ApiError && error.detail ? error.detail : t("common.error");

  if (recoveryCodes) {
    return (
      <main className="auth-card">
        <h2>{t("twoFactor.recoveryTitle")}</h2>
        <p>{t("twoFactor.recoveryHelp")}</p>
        <ul className="recovery-codes" aria-label={t("twoFactor.recoveryTitle")}>
          {recoveryCodes.map((c) => (
            <li key={c}>
              <code>{c}</code>
            </li>
          ))}
        </ul>
        <button type="button" onClick={done}>
          {t("twoFactor.saved")}
        </button>
      </main>
    );
  }

  return (
    <main className="auth-card">
      <h2>{t("twoFactor.title")}</h2>
      <p>{t("twoFactor.help")}</p>
      {setup.isPending && <p className="muted">{t("common.loading")}</p>}
      {setup.isError && (
        <p className="form-error" role="alert">
          {errorText(setup.error)}
        </p>
      )}
      {setup.data && (
        <>
          <img className="qr" src={setup.data.qr_svg_data_uri} alt={t("twoFactor.qrAlt")} />
          <p className="muted">
            {t("twoFactor.manual")} <code>{setup.data.secret}</code>
          </p>
          <form onSubmit={submit} noValidate>
            <label>
              {t("login.code")}
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
              />
            </label>
            {confirm.isError && (
              <p className="form-error" role="alert">
                {errorText(confirm.error)}
              </p>
            )}
            <button type="submit" disabled={confirm.isPending}>
              {t("twoFactor.confirm")}
            </button>
          </form>
        </>
      )}
    </main>
  );
}
