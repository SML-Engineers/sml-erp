import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { changePassword, meQueryKey } from "../api/auth";
import { ApiError } from "../api/client";

export default function ChangePasswordPage({ firstTime = false }: { firstTime?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (next !== repeat) {
      setError(t("password.mismatch"));
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
      await queryClient.invalidateQueries({ queryKey: meQueryKey });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.detail ? err.detail : t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-card">
      <h2>{t("password.title")}</h2>
      {firstTime && <p>{t("password.firstTime")}</p>}
      <p className="muted">{t("password.rules")}</p>
      <form onSubmit={submit} noValidate>
        <label>
          {t("password.current")}
          <input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </label>
        <label>
          {t("password.new")}
          <input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </label>
        <label>
          {t("password.repeat")}
          <input
            type="password"
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            required
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {t("password.submit")}
        </button>
      </form>
    </main>
  );
}
