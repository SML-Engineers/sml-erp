import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  createDivision,
  deleteDivision,
  divisionsAdminKey,
  listDivisionsAdmin,
  updateDivision,
  type DivisionAdmin,
  type DivisionType,
} from "../../api/organisation";
import DataTable from "../../components/DataTable";

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

/** Every page that picks or filters by division reads this list, so refresh it too. */
function useRefreshDivisions() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: divisionsAdminKey });
    void queryClient.invalidateQueries({ queryKey: ["divisions"] });
  };
}

export default function DivisionsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const divisions = useQuery({ queryKey: divisionsAdminKey, queryFn: listDivisionsAdmin });
  const canManage = can(me.access, "settings", "manage");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = divisions.data?.find((d) => d.id === selectedId) ?? null;

  return (
    <main className="page">
      <h1>{t("divisions.title")}</h1>
      <p className="muted">{t("divisions.help")}</p>

      {canManage && <AddDivision />}
      {selected && canManage && (
        <EditDivision key={selected.id} division={selected} onDone={() => setSelectedId(null)} />
      )}

      {divisions.isPending && <p className="muted">{t("common.loading")}</p>}
      {divisions.isError && <p className="form-error">{t("common.error")}</p>}
      {divisions.data && (
        <DataTable
          label={t("divisions.title")}
          rows={divisions.data}
          rowKey={(d) => d.id}
          pageSize="all"
          columns={[
            { id: "code", header: t("divisions.code"), value: (d) => d.code },
            { id: "name", header: t("divisions.name"), value: (d) => d.name },
            {
              id: "invoice",
              header: t("divisions.taxInvoiceCode"),
              value: (d) => d.tax_invoice_code || "—",
            },
            {
              id: "type",
              header: t("divisions.type"),
              value: (d) => t(`divisions.types.${d.division_type}`),
            },
            {
              id: "status",
              header: t("users.status"),
              value: (d) => (d.is_active ? t("users.active") : t("users.inactive")),
            },
            {
              id: "used",
              header: t("divisions.codeLocked"),
              value: (d) => (d.in_use ? t("divisions.locked") : t("divisions.notYetUsed")),
            },
            { id: "users", header: t("divisions.users"), value: (d) => d.users },
            ...(canManage
              ? [
                  {
                    id: "edit",
                    header: "",
                    sortable: false,
                    value: () => "",
                    cell: (d: DivisionAdmin) => (
                      <button
                        type="button"
                        className="small secondary"
                        onClick={() => setSelectedId(d.id)}
                        aria-label={t("divisions.editOne", { code: d.code })}
                      >
                        {t("divisions.edit")}
                      </button>
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}
    </main>
  );
}

function TypeSelect({
  value,
  onChange,
}: {
  value: DivisionType;
  onChange: (value: DivisionType) => void;
}) {
  const { t } = useTranslation();
  return (
    <label>
      {t("divisions.type")}
      <select value={value} onChange={(e) => onChange(e.target.value as DivisionType)}>
        <option value="production">{t("divisions.types.production")}</option>
        <option value="shared">{t("divisions.types.shared")}</option>
      </select>
    </label>
  );
}

function InvoiceCodeInput(props: {
  value: string;
  onChange: (value: string) => void;
  locked?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <label>
      {t("divisions.taxInvoiceCode")}
      <input
        className="code-input wide-code"
        value={props.value}
        maxLength={15}
        disabled={props.locked}
        title={t("divisions.taxInvoiceCodeHelp")}
        onChange={(e) => props.onChange(e.target.value.toUpperCase())}
      />
    </label>
  );
}

function AddDivision() {
  const { t } = useTranslation();
  const refresh = useRefreshDivisions();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<DivisionType>("production");
  const [invoiceCode, setInvoiceCode] = useState("");
  const [reason, setReason] = useState("");
  const add = useMutation({
    mutationFn: () =>
      createDivision({ code, name, division_type: type, tax_invoice_code: invoiceCode, reason }),
    onSuccess: () => {
      setCode("");
      setName("");
      setInvoiceCode("");
      setReason("");
      refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <section className="panel">
      <h2>{t("divisions.add")}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>
          {t("divisions.code")}
          <input
            className="code-input"
            value={code}
            maxLength={2}
            required
            onChange={(e) => setCode(e.target.value.toUpperCase())}
          />
        </label>
        <label>
          {t("divisions.name")}
          <input value={name} required onChange={(e) => setName(e.target.value)} />
        </label>
        <TypeSelect value={type} onChange={setType} />
        <InvoiceCodeInput value={invoiceCode} onChange={setInvoiceCode} />
        <label>
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" disabled={add.isPending}>
          {t("divisions.create")}
        </button>
      </form>
      <p className="muted">{t("divisions.codeHelp")}</p>
      {add.isError && (
        <p className="form-error" role="alert">
          {errorText(add.error, t("common.error"))}
        </p>
      )}
      {add.data && (
        <p className="notice" role="status">
          {t("divisions.created", { code: add.data.code, name: add.data.name })}
        </p>
      )}
    </section>
  );
}

function EditDivision({ division, onDone }: { division: DivisionAdmin; onDone: () => void }) {
  const { t } = useTranslation();
  const refresh = useRefreshDivisions();
  const [code, setCode] = useState(division.code);
  const [name, setName] = useState(division.name);
  const [type, setType] = useState<DivisionType>(division.division_type);
  const [invoiceCode, setInvoiceCode] = useState(division.tax_invoice_code);
  const [reason, setReason] = useState("");
  const done = () => {
    refresh();
    onDone();
  };

  const save = useMutation({
    mutationFn: () =>
      updateDivision(division.id, {
        ...(division.in_use ? {} : { code }),
        ...(division.tax_invoice_code_in_use ? {} : { tax_invoice_code: invoiceCode }),
        name,
        division_type: type,
        reason,
      }),
    onSuccess: done,
  });
  const toggle = useMutation({
    mutationFn: () => updateDivision(division.id, { is_active: !division.is_active, reason }),
    onSuccess: done,
  });
  const remove = useMutation({
    mutationFn: () => deleteDivision(division.id, reason),
    onSuccess: done,
  });
  const error = save.error ?? toggle.error ?? remove.error;
  const busy = save.isPending || toggle.isPending || remove.isPending;
  const canDelete = !division.in_use && division.users === 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel" aria-label={t("divisions.editOne", { code: division.code })}>
      <h2>{t("divisions.editOne", { code: division.code })}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>
          {t("divisions.code")}
          <input
            className="code-input"
            value={code}
            maxLength={2}
            required
            disabled={division.in_use}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
          />
        </label>
        <label>
          {t("divisions.name")}
          <input value={name} required onChange={(e) => setName(e.target.value)} />
        </label>
        <TypeSelect value={type} onChange={setType} />
        <InvoiceCodeInput
          value={invoiceCode}
          onChange={setInvoiceCode}
          locked={division.tax_invoice_code_in_use}
        />
        <label>
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" disabled={busy}>
          {t("divisions.save")}
        </button>
      </form>
      {division.in_use && <p className="muted">{t("divisions.lockedHelp")}</p>}
      {division.tax_invoice_code_in_use && (
        <p className="muted">{t("divisions.taxInvoiceCodeLocked")}</p>
      )}
      <div className="row-actions">
        <button
          type="button"
          className={division.is_active ? "danger" : "secondary"}
          disabled={busy}
          onClick={() => toggle.mutate()}
        >
          {division.is_active ? t("divisions.deactivate") : t("divisions.reactivate")}
        </button>
        {canDelete && (
          <button type="button" className="danger" disabled={busy} onClick={() => remove.mutate()}>
            {t("divisions.delete")}
          </button>
        )}
        <button type="button" className="secondary" onClick={onDone}>
          {t("access.cancel")}
        </button>
      </div>
      {division.is_active && <p className="muted">{t("divisions.reasonNeeded")}</p>}
      {error && (
        <p className="form-error" role="alert">
          {errorText(error, t("common.error"))}
        </p>
      )}
    </section>
  );
}
