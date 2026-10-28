import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  createVoucherType,
  deleteVoucherType,
  listVoucherTypes,
  PAYEE_CATEGORIES,
  PAYMENT_METHODS,
  updateVoucherType,
  voucherTypesKey,
  type PaymentMethod,
  type VoucherType,
} from "../../api/vouchers";
import DataTable from "../../components/DataTable";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Settings → Voucher types (spec 4.1): master data kept by the Admin. */
export default function VoucherTypesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [inactive, setInactive] = useState(false);
  const [selected, setSelected] = useState<number | "new" | null>(null);
  const types = useQuery({ queryKey: [...voucherTypesKey, inactive], queryFn: () => listVoucherTypes(inactive) });
  const canManage = can(me.access, "settings", "manage");
  const current = typeof selected === "number" ? types.data?.find((x) => x.id === selected) : undefined;

  return (
    <main className="page">
      <h1>{t("voucherTypes.title")}</h1>
      <p className="muted">{t("voucherTypes.help")}</p>
      <div className="toolbar">
        <label className="check">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
          {t("voucherTypes.showOff")}
        </label>
        {canManage && (
          <button type="button" onClick={() => setSelected("new")}>
            {t("voucherTypes.add")}
          </button>
        )}
      </div>
      {types.data && (
        <DataTable
          label={t("voucherTypes.title")}
          rows={types.data}
          rowKey={(x) => x.id}
          pageSize="all"
          searchable={false}
          columns={[
            {
              id: "code",
              header: t("voucherTypes.code"),
              value: (x) => x.code,
              cell: (x) => (
                <button type="button" className="link-button" onClick={() => setSelected(x.id)}>
                  {x.code}
                </button>
              ),
            },
            { id: "name", header: t("voucherTypes.name"), value: (x) => x.name },
            { id: "method", header: t("voucherTypes.method"), value: (x) => t(`voucherTypes.methods.${x.payment_method}`) },
            {
              id: "payee",
              header: t("voucherTypes.payee"),
              value: (x) =>
                !x.needs_payee
                  ? t("voucherTypes.noPayee")
                  : x.payee_category
                    ? t(`voucherTypes.categories.${x.payee_category}`)
                    : t("voucherTypes.anyPayee"),
            },
            { id: "notes", header: t("voucherTypes.notes"), value: (x) => x.notes },
            {
              id: "status",
              header: t("users.status"),
              value: (x) => (x.is_active ? t("voucherTypes.on") : t("voucherTypes.off")),
            },
          ]}
        />
      )}
      <ErrorLine error={types.error} />
      {selected === "new" && canManage && <TypeForm onDone={(id) => setSelected(id)} />}
      {current && <TypeForm key={current.id} type={current} canManage={canManage} onDone={() => undefined} />}
    </main>
  );
}

function TypeForm(props: { type?: VoucherType; canManage?: boolean; onDone: (id: number) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { type } = props;
  const editable = props.canManage ?? true;
  const [values, setValues] = useState({
    code: type?.code ?? "",
    name: type?.name ?? "",
    payment_method: type?.payment_method ?? ("cheque" as PaymentMethod),
    payee_category: type?.payee_category ?? "",
    is_advance: type?.is_advance ?? false,
    notes: type?.notes ?? "",
    sort_order: String(type?.sort_order ?? 100),
  });
  const [reason, setReason] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: voucherTypesKey });
  const internal = values.payment_method === "internal";
  const locked = Boolean(type?.in_use);
  const save = useMutation({
    mutationFn: () => {
      const change = {
        ...values,
        sort_order: Number(values.sort_order) || 0,
        needs_payee: !internal,
        payee_category: internal ? "" : values.payee_category,
        is_advance: internal ? false : values.is_advance,
        reason,
      };
      return type ? updateVoucherType(type.id, change) : createVoucherType(change);
    },
    onSuccess: (saved) => {
      refresh();
      props.onDone(saved.id);
    },
  });
  const toggle = useMutation({
    mutationFn: () => updateVoucherType(type!.id, { is_active: !type!.is_active, reason }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: () => deleteVoucherType(type!.id, reason), onSuccess: refresh });
  const title = type ? `${type.code} ${type.name}` : t("voucherTypes.add");

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      {locked && <p className="muted">{t("voucherTypes.inUse")}</p>}
      <form className="form-grid" aria-label={t("voucherTypes.details")} onSubmit={submit}>
        <label>
          {t("voucherTypes.code")}
          <input
            value={values.code}
            required
            maxLength={10}
            disabled={!editable || locked}
            onChange={(e) => setValues((v) => ({ ...v, code: e.target.value }))}
          />
        </label>
        <label>
          {t("voucherTypes.name")}
          <input
            value={values.name}
            required
            maxLength={50}
            disabled={!editable}
            onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
          />
        </label>
        <label>
          {t("voucherTypes.method")}
          <select
            value={values.payment_method}
            disabled={!editable || locked}
            onChange={(e) => setValues((v) => ({ ...v, payment_method: e.target.value as PaymentMethod }))}
          >
            {PAYMENT_METHODS.map((m) => (
              <option key={m} value={m}>
                {t(`voucherTypes.methods.${m}`)}
              </option>
            ))}
          </select>
        </label>
        {!internal && (
          <label>
            {t("voucherTypes.payee")}
            <select
              value={values.payee_category}
              disabled={!editable}
              onChange={(e) => setValues((v) => ({ ...v, payee_category: e.target.value }))}
            >
              {PAYEE_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c ? t(`voucherTypes.categories.${c}`) : t("voucherTypes.anyPayee")}
                </option>
              ))}
            </select>
          </label>
        )}
        {!internal && (
          <label className="check">
            <input
              type="checkbox"
              checked={values.is_advance}
              disabled={!editable || locked}
              onChange={(e) => setValues((v) => ({ ...v, is_advance: e.target.checked }))}
            />
            {t("voucherTypes.advance")}
          </label>
        )}
        <label>
          {t("voucherTypes.order")}
          <input
            type="number"
            min={0}
            value={values.sort_order}
            disabled={!editable}
            onChange={(e) => setValues((v) => ({ ...v, sort_order: e.target.value }))}
          />
        </label>
        <label className="wide">
          {t("voucherTypes.notes")}
          <input value={values.notes} maxLength={300} disabled={!editable} onChange={(e) => setValues((v) => ({ ...v, notes: e.target.value }))} />
        </label>
        {editable && (
          <>
            <label>
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <div className="wide row-actions">
              <button type="submit" disabled={save.isPending}>
                {type ? t("voucherTypes.save") : t("voucherTypes.add")}
              </button>
              {type && (
                <button type="button" className="secondary" onClick={() => toggle.mutate()}>
                  {type.is_active ? t("voucherTypes.switchOff") : t("voucherTypes.switchOn")}
                </button>
              )}
              {type && !type.in_use && (
                <button type="button" className="danger" onClick={() => remove.mutate()}>
                  {t("voucherTypes.delete")}
                </button>
              )}
            </div>
          </>
        )}
      </form>
      <ErrorLine error={save.error ?? toggle.error ?? remove.error} />
    </section>
  );
}
