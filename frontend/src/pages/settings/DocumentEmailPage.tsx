import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  getMailAccount,
  listTemplates,
  mailAccountKey,
  previewTemplate,
  saveTemplate,
  sendTestEmail,
  templatesKey,
  updateMailAccount,
  type EmailTemplate,
  type MailAccount,
  type Security,
} from "../../api/documentEmail";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Settings → Document email (spec 3B): the sending mailbox and the default messages. */
export default function DocumentEmailPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const account = useQuery({ queryKey: mailAccountKey, queryFn: getMailAccount });
  const templates = useQuery({ queryKey: templatesKey, queryFn: listTemplates });
  const canManage = can(me.access, "settings", "manage");

  return (
    <main className="page">
      <h1>{t("documentEmail.title")}</h1>
      <p className="muted">{t("documentEmail.help")}</p>
      {account.data && <AccountPanel key={account.data.from_address} account={account.data} canManage={canManage} />}
      {templates.data && <TemplatesPanel templates={templates.data} canManage={canManage} />}
      <ErrorLine error={account.error ?? templates.error} />
    </main>
  );
}

const SECURITY: Security[] = ["starttls", "ssl", "none"];

function AccountPanel({ account, canManage }: { account: MailAccount; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    from_name: account.from_name,
    from_address: account.from_address,
    reply_to: account.reply_to,
    copy_to: account.copy_to,
    host: account.host,
    port: String(account.port),
    security: account.security,
    username: account.username,
    password: "",
  });
  const [testTo, setTestTo] = useState("");
  const set = (key: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      updateMailAccount({
        ...values,
        port: Number(values.port),
        security: values.security as Security,
        password: values.password || undefined,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(mailAccountKey, data);
      setValues((now) => ({ ...now, password: "" }));
    },
  });
  const test = useMutation({
    mutationFn: () => sendTestEmail(testTo),
    onSuccess: (data) => queryClient.setQueryData(mailAccountKey, data),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const text = (key: keyof typeof values, label: string, type = "text") => (
    <label key={key}>
      {label}
      <input
        type={type}
        value={values[key]}
        disabled={!canManage}
        autoComplete={type === "password" ? "new-password" : "off"}
        onChange={(e) => set(key)(e.target.value)}
      />
    </label>
  );

  return (
    <section className="panel" aria-label={t("documentEmail.account")}>
      <h2>{t("documentEmail.account")}</h2>
      <p className="muted">{t("documentEmail.accountHelp")}</p>
      <form className="form-grid" onSubmit={submit} aria-label={t("documentEmail.account")}>
        {text("from_name", t("documentEmail.fromName"))}
        {text("from_address", t("documentEmail.fromAddress"), "email")}
        {text("reply_to", t("documentEmail.replyTo"), "email")}
        {text("copy_to", t("documentEmail.copyTo"), "email")}
        {text("host", t("documentEmail.host"))}
        {text("port", t("documentEmail.port"), "number")}
        <label>
          {t("documentEmail.security")}
          <select value={values.security} disabled={!canManage} onChange={(e) => set("security")(e.target.value)}>
            {SECURITY.map((s) => (
              <option key={s} value={s}>
                {t(`documentEmail.securities.${s}`)}
              </option>
            ))}
          </select>
        </label>
        {text("username", t("documentEmail.username"))}
        {canManage && text("password", account.has_password ? t("documentEmail.passwordKeep") : t("documentEmail.password"), "password")}
        {canManage && (
          <div className="wide">
            <button type="submit" disabled={save.isPending}>
              {t("documentEmail.save")}
            </button>
          </div>
        )}
      </form>
      <ErrorLine error={save.error} />
      <p role="status">
        {account.last_test_ok === true && t("documentEmail.testOk")}
        {account.last_test_ok === false && t("documentEmail.testFailed", { error: account.last_test_error })}
        {account.last_test_ok === null && account.is_ready && t("documentEmail.notTested")}
        {!account.is_ready && t("documentEmail.notReady")}
      </p>
      {canManage && account.is_ready && (
        <form
          className="inline-form"
          aria-label={t("documentEmail.test")}
          onSubmit={(e) => {
            e.preventDefault();
            test.mutate();
          }}
        >
          <label>
            {t("documentEmail.testTo")}
            <input type="email" value={testTo} required onChange={(e) => setTestTo(e.target.value)} />
          </label>
          <button type="submit" className="secondary" disabled={test.isPending}>
            {t("documentEmail.test")}
          </button>
        </form>
      )}
      <ErrorLine error={test.error} />
    </section>
  );
}

function TemplatesPanel({ templates, canManage }: { templates: EmailTemplate[]; canManage: boolean }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState(templates[0]?.kind ?? "");
  const current = templates.find((x) => x.kind === kind);

  return (
    <section className="panel" aria-label={t("documentEmail.messages")}>
      <h2>{t("documentEmail.messages")}</h2>
      <p className="muted">{t("documentEmail.messagesHelp")}</p>
      <label>
        {t("documentEmail.kind")}
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {templates.map((x) => (
            <option key={x.kind} value={x.kind}>
              {x.label}
            </option>
          ))}
        </select>
      </label>
      {current && <TemplateForm key={current.kind} template={current} canManage={canManage} />}
    </section>
  );
}

function TemplateForm({ template, canManage }: { template: EmailTemplate; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [subject, setSubject] = useState(template.subject);
  const [body, setBody] = useState(template.body);
  const save = useMutation({
    mutationFn: () => saveTemplate(template.kind, subject, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: templatesKey }),
  });
  const preview = useMutation({ mutationFn: () => previewTemplate(template.kind, subject, body) });

  return (
    <form
      className="form-grid"
      aria-label={t("documentEmail.messageOf", { name: template.label })}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="wide">
        {t("email.subject")}
        <input value={subject} disabled={!canManage} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
      </label>
      <label className="wide">
        {t("email.body")}
        <textarea value={body} disabled={!canManage} rows={12} onChange={(e) => setBody(e.target.value)} />
      </label>
      <div className="wide">
        <p className="muted">{t("documentEmail.placeholders")}</p>
        <ul className="changes">
          {template.placeholders.map((p) => (
            <li key={p.name}>
              <code>{`{${p.name}}`}</code> — {p.label}
            </li>
          ))}
        </ul>
      </div>
      <div className="wide row-actions">
        <button type="button" className="secondary" onClick={() => preview.mutate()}>
          {t("documentEmail.preview")}
        </button>
        {canManage && (
          <button type="submit" disabled={save.isPending}>
            {t("documentEmail.saveMessage")}
          </button>
        )}
      </div>
      {preview.data && (
        <div className="wide notice" role="status">
          <strong>{preview.data.subject}</strong>
          <p className="pre-line">{preview.data.body}</p>
        </div>
      )}
      {save.isSuccess && <p className="wide notice">{t("documentEmail.messageSaved")}</p>}
      <div className="wide">
        <ErrorLine error={save.error ?? preview.error} />
      </div>
    </form>
  );
}
