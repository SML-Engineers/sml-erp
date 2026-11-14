import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { can } from "../../api/access";
import { createUser, listUsers } from "../../api/admin";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import DataTable from "../../components/DataTable";
import { formatDate } from "../../lib/time";

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
              <code>{create.data.temporary_password}</code>{" "}
              {t("users.thenActivate")}{" "}
              <Link to={`/admin/users/${create.data.id}`}>{t("users.setUp", { name: create.data.full_name })}</Link>
            </p>
          )}
        </section>
      )}

      {users.isPending && <p className="muted">{t("common.loading")}</p>}
      {users.data && (
        <DataTable
          label={t("users.title")}
          rows={users.data}
          rowKey={(u) => u.id}
          columns={[
            {
              id: "name",
              header: t("users.fullName"),
              value: (u) => u.full_name,
              cell: (u) => <Link to={`/admin/users/${u.id}`}>{u.full_name}</Link>,
            },
            { id: "email", header: t("login.email"), value: (u) => u.email },
            {
              id: "roles",
              header: t("users.roles"),
              value: (u) => u.roles.map((r) => r.name).join(", ") || "—",
            },
            {
              id: "divisions",
              header: t("users.divisions"),
              value: (u) => (u.all_divisions ? t("users.allDivisions") : u.divisions.join(", ") || "—"),
            },
            {
              id: "status",
              header: t("users.status"),
              value: (u) => (u.is_active ? t("users.active") : u.last_login ? t("users.inactive") : t("users.notYetActive")),
            },
            {
              id: "last",
              header: t("users.lastSignIn"),
              value: (u) => u.last_login ?? "",
              cell: (u) => (u.last_login ? formatDate(u.last_login) : "—"),
            },
          ]}
        />
      )}
    </main>
  );
}
