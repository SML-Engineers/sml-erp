import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  companyQueryKey,
  getCompany,
  logoUrl,
  removeLogo,
  updateCompany,
  uploadLogo,
  type Company,
  type CompanyChange,
} from "../../api/organisation";

const TEXT_FIELDS = [
  "name",
  "registration_no",
  "tin",
  "vat_no",
  "phone",
  "email",
  "website",
] as const;

const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

export default function CompanyPage({ me }: { me: CurrentUser }) {
  const { t, i18n } = useTranslation();
  const company = useQuery({ queryKey: companyQueryKey, queryFn: getCompany });
  const canManage = can(me.access, "settings", "manage");

  return (
    <main className="page">
      <h1>{t("company.title")}</h1>
      <p className="muted">{t("company.help")}</p>
      {company.isPending && <p className="muted">{t("common.loading")}</p>}
      {company.isError && <p className="form-error">{t("common.error")}</p>}
      {company.data && (
        <>
          <CompanyForm company={company.data} canManage={canManage} locale={i18n.language} />
          <LogoPanel company={company.data} canManage={canManage} />
        </>
      )}
    </main>
  );
}

function CompanyForm({
  company,
  canManage,
  locale,
}: {
  company: Company;
  canManage: boolean;
  locale: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = useState(company);
  const [reason, setReason] = useState("");
  useEffect(() => setForm(company), [company]);

  const save = useMutation({
    mutationFn: () => {
      const change: CompanyChange = { reason };
      for (const field of TEXT_FIELDS) change[field] = form[field];
      change.address = form.address;
      change.financial_year_start_month = form.financial_year_start_month;
      return updateCompany(change);
    },
    onSuccess: (data) => {
      setReason("");
      queryClient.setQueryData(companyQueryKey, data);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const monthName = (month: number) =>
    new Date(2000, month - 1, 1).toLocaleString(locale, { month: "long" });

  return (
    <section className="panel">
      <form className="form-grid" onSubmit={submit}>
        {TEXT_FIELDS.map((field) => (
          <label key={field}>
            {t(`company.field.${field}`)}
            <input
              value={form[field]}
              type={field === "email" ? "email" : "text"}
              required={field === "name"}
              disabled={!canManage}
              onChange={(e) => setForm({ ...form, [field]: e.target.value })}
            />
          </label>
        ))}
        <label className="wide">
          {t("company.field.address")}
          <textarea
            rows={3}
            value={form.address}
            disabled={!canManage}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
          />
        </label>
        <label>
          {t("company.field.base_currency")}
          <input value={form.base_currency} disabled readOnly />
          <span className="muted">{t("company.baseCurrencyFixed")}</span>
        </label>
        <label>
          {t("company.field.financial_year_start_month")}
          <select
            value={form.financial_year_start_month}
            disabled={!canManage}
            onChange={(e) =>
              setForm({ ...form, financial_year_start_month: Number(e.target.value) })
            }
          >
            {MONTHS.map((month) => (
              <option key={month} value={month}>
                {monthName(month)}
              </option>
            ))}
          </select>
        </label>
        {canManage && (
          <>
            <label className="wide">
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <div className="wide">
              <button type="submit" disabled={save.isPending}>
                {t("company.save")}
              </button>
            </div>
          </>
        )}
      </form>
      {save.isError && (
        <p className="form-error" role="alert">
          {errorText(save.error, t("common.error"))}
        </p>
      )}
      {save.isSuccess && (
        <p className="notice" role="status">
          {t("company.saved")}
        </p>
      )}
    </section>
  );
}

function LogoPanel({ company, canManage }: { company: Company; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const onSuccess = (data: Company) => queryClient.setQueryData(companyQueryKey, data);
  const upload = useMutation({ mutationFn: uploadLogo, onSuccess });
  const remove = useMutation({ mutationFn: removeLogo, onSuccess });
  const error = upload.error ?? remove.error;

  return (
    <section className="panel">
      <h2>{t("company.logo")}</h2>
      {company.has_logo ? (
        <img className="company-logo" src={logoUrl(company)} alt={t("company.logoAlt")} />
      ) : (
        <p className="muted">{t("company.noLogo")}</p>
      )}
      {canManage && (
        <div className="inline-form">
          <label>
            {t("company.chooseLogo")}
            <input
              type="file"
              accept="image/png,image/jpeg"
              disabled={upload.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
                e.target.value = "";
              }}
            />
          </label>
          {company.has_logo && (
            <button
              type="button"
              className="secondary"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {t("company.removeLogo")}
            </button>
          )}
        </div>
      )}
      <p className="muted">{t("company.logoRules")}</p>
      {error && (
        <p className="form-error" role="alert">
          {errorText(error, t("common.error"))}
        </p>
      )}
    </section>
  );
}
