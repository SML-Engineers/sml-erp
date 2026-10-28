import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { can } from "../../api/access";
import { createUser, listUsers } from "../../api/admin";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";

export default function UsersPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => createUser(email, name),
    onSuccess: () => {
      setEmail("");
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const canManage = can(me.access, "users", "manage");

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <main className="page">
      <p className="breadcrumb">
        <Link to="/">{t("app.name")}</Link>
      </p>
      <h1>{t("users.title")}</h1>

      {canManage && (
        <section className="panel">
          <h2>{t("users.add")}</h2>
          <form className="inline-form" onSubmit={submit}>
            <label>
              {t("users.fullName")}
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label>
              {t("login.email")}
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <button type="submit" disabled={create.isPending}>
              {t("users.create")}
            </button>
          </form>
          {create.isError && (
            <p className="form-error" role="alert">
              {create.error instanceof ApiError && create.error.detail
                ? create.error.detail
                : t("common.error")}
            </p>
          )}
          {create.data && (
            <p className="notice" role="status">
              {t("users.created", { email: create.data.email })}{" "}
              <code>{create.data.temporary_password}</code>
            </p>
          )}
        </section>
      )}

      {users.isPending && <p className="muted">{t("common.loading")}</p>}
      {users.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("users.fullName")}</th>
                <th>{t("login.email")}</th>
                <th>{t("users.roles")}</th>
                <th>{t("users.divisions")}</th>
                <th>{t("users.status")}</th>
                <th>{t("users.lastSignIn")}</th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td>
                    <Link to={`/admin/users/${u.id}`}>{u.full_name}</Link>
                  </td>
                  <td>{u.email}</td>
                  <td>{u.roles.map((r) => r.name).join(", ") || "—"}</td>
                  <td>{u.all_divisions ? t("users.allDivisions") : u.divisions.join(", ") || "—"}</td>
                  <td>{u.is_active ? t("users.active") : t("users.inactive")}</td>
                  <td>{u.last_login ? new Date(u.last_login).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
