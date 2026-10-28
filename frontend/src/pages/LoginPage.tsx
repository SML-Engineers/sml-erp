import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { meQueryKey, signIn, verifyCode, type SignInResponse } from "../api/auth";
import { ApiError } from "../api/client";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<"password" | "code">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function finish(response: SignInResponse) {
    if (response.status === "two_factor_required") {
      setStep("code");
      setPassword("");
      return;
    }
    await queryClient.invalidateQueries({ queryKey: meQueryKey });
    navigate("/", { replace: true });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await finish(step === "password" ? await signIn(email, password) : await verifyCode(code));
    } catch (err) {
      setError(err instanceof ApiError && err.detail ? err.detail : t("login.failed"));
      if (step === "code") setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-card">
      <h1>{t("app.name")}</h1>
      <form onSubmit={submit} noValidate>
        {step === "password" ? (
          <>
            <h2>{t("login.title")}</h2>
            <label>
              {t("login.email")}
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </label>
            <label>
              {t("login.password")}
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
          </>
        ) : (
          <>
            <h2>{t("login.codeTitle")}</h2>
            <p className="muted">{t("login.codeHelp")}</p>
            <label>
              {t("login.code")}
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoFocus
              />
            </label>
          </>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {step === "password" ? t("login.submit") : t("login.verify")}
        </button>
      </form>
    </main>
  );
}
