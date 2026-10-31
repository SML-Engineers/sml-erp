import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import {
  createItem,
  deleteItem,
  getItemOptions,
  importItems,
  itemsExportUrl,
  itemsKey,
  listItems,
  setItemActive,
  updateItem,
  type Item,
  type ItemChange,
  type ItemOptions,
} from "../api/items";
import DataTable from "../components/DataTable";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  let text = t("common.error");
  if (error instanceof ApiError) {
    const rows = (error.body as { errors?: string[] } | null)?.errors;
    text = rows?.length ? [error.detail, ...rows].filter(Boolean).join("\n") : (error.detail ?? text);
  }
  return (
    <p className="form-error pre-line" role="alert">
      {text}
    </p>
  );
}

/** The item master (spec 5A.3): everything SML buys and keeps or uses, with how it arrives,
 * whether QC inspects it, and the account it is valued in. */
export default function ItemsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [inactive, setInactive] = useState(false);
  const [selected, setSelected] = useState<number | "new" | "import" | null>(null);
  const options = useQuery({ queryKey: [...itemsKey, "options"], queryFn: getItemOptions });
  const rows = useQuery({
    queryKey: [...itemsKey, "list", search, category, inactive],
    queryFn: () => listItems(search, category, inactive),
  });
  const o = options.data;
  const current = typeof selected === "number" ? rows.data?.find((i) => i.id === selected) : undefined;
  const label = (list: { value: string; label: string }[] | undefined, value: string) =>
    list?.find((x) => x.value === value)?.label ?? value;

  return (
    <main className="page">
      <h1>{t("items.title")}</h1>
      <p className="muted">{t("items.help")}</p>
      <div className="toolbar">
        <label className="inline-form">
          {t("table.search")}
          <input type="search" value={search} placeholder={t("items.searchHint")} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label>
          {t("items.category")}
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t("items.allCategories")}</option>
            {o?.categories.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
          {t("items.showInactive")}
        </label>
        {o?.can_enter && (
          <button type="button" onClick={() => setSelected("new")}>
            {t("items.add")}
          </button>
        )}
        <a className="button-link secondary" href={itemsExportUrl(inactive)}>
          {t("customers.export")}
        </a>
        {o?.can_enter && (
          <button type="button" className="secondary" onClick={() => setSelected("import")}>
            {t("customers.import")}
          </button>
        )}
      </div>

      {selected === "import" && <ImportPanel onClose={() => setSelected(null)} />}
      {o && selected === "new" && <ItemForm options={o} onDone={(id) => setSelected(id)} />}
      {o && current && <ItemForm key={current.id} options={o} item={current} onDone={() => setSelected(null)} />}

      {rows.data && (
        <DataTable
          label={t("items.title")}
          rows={rows.data}
          rowKey={(i) => i.id}
          searchable={false}
          emptyText={t("items.none")}
          columns={[
            { id: "code", header: t("items.code"), value: (i) => i.code, cell: (i) => <span className="mono">{i.code}</span> },
            {
              id: "name",
              header: t("items.name"),
              value: (i) => i.name,
              cell: (i) => (
                <button type="button" className="link-button" onClick={() => setSelected(i.id)}>
                  {i.name}
                </button>
              ),
            },
            { id: "category", header: t("items.category"), value: (i) => label(o?.categories, i.category) },
            { id: "unit", header: t("items.unit"), value: (i) => i.unit },
            {
              id: "stock",
              header: t("items.kind"),
              value: (i) => (i.is_stock ? t("items.stock") : t("items.nonStock")),
            },
            { id: "qc", header: t("items.qc"), value: (i) => (i.inspection_required ? t("items.yes") : "") },
            {
              id: "account",
              header: t("items.account"),
              value: (i) => (i.inventory_account ?? i.expense_account)?.number ?? "",
            },
            {
              id: "status",
              header: t("users.status"),
              value: (i) => (i.is_active ? t("users.active") : t("users.inactive")),
            },
          ]}
        />
      )}
      <ErrorLine error={rows.error} />
    </main>
  );
}

function ItemForm(props: { options: ItemOptions; item?: Item; onDone: (id: number | null) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { item, options } = props;
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const [values, setValues] = useState({
    code: item?.code ?? "",
    name: item?.name ?? "",
    description: item?.description ?? "",
    category: item?.category ?? "raw_material",
    unit: item?.unit ?? "pcs",
    is_stock: item?.is_stock ?? true,
    package_type: item?.package_type ?? "none",
    inspection_required: item?.inspection_required ?? true,
    inventory_account: item?.inventory_account?.number ?? "",
    expense_account: item?.expense_account?.number ?? "",
    material: item?.material ?? "",
    division: item?.division ?? "",
    notes: item?.notes ?? "",
  });
  const [reason, setReason] = useState("");
  const set = <K extends keyof typeof values>(field: K, value: (typeof values)[K]) => setValues((now) => ({ ...now, [field]: value }));
  const done = () => void queryClient.invalidateQueries({ queryKey: [...itemsKey, "list"] });

  const save = useMutation({
    mutationFn: () => {
      const change: ItemChange = {
        name: values.name,
        description: values.description,
        category: values.category,
        unit: values.unit,
        is_stock: values.is_stock,
        package_type: values.package_type,
        inspection_required: values.inspection_required,
        material: values.material || null,
        division: values.division || null,
        notes: values.notes,
      };
      if (!item || !item.used) change.code = values.code;
      if (options.can_set_accounts) {
        change.inventory_account = values.inventory_account || null;
        change.expense_account = values.expense_account || null;
      }
      return item ? updateItem(item.id, change) : createItem(change);
    },
    onSuccess: (saved) => {
      done();
      props.onDone(saved.id);
    },
  });
  const active = useMutation({
    mutationFn: () => setItemActive(item!.id, !item!.is_active, reason),
    onSuccess: () => {
      done();
      props.onDone(null);
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteItem(item!.id),
    onSuccess: () => {
      done();
      props.onDone(null);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const title = item ? `${item.code} ${item.name}` : t("items.add");
  const editable = options.can_enter;
  return (
    <form className="panel form-grid" aria-label={t("items.form")} onSubmit={submit}>
      <h2 className="wide">{title}</h2>
      <label>
        {t("items.code")}
        <input value={values.code} maxLength={20} required disabled={!editable || item?.used} onChange={(e) => set("code", e.target.value.toUpperCase())} />
      </label>
      <label className="wide">
        {t("items.name")}
        <input value={values.name} maxLength={150} required disabled={!editable} onChange={(e) => set("name", e.target.value)} />
      </label>
      <label>
        {t("items.category")}
        <select value={values.category} disabled={!editable} onChange={(e) => set("category", e.target.value)}>
          {options.categories.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("items.unit")}
        <select value={values.unit} disabled={!editable} onChange={(e) => set("unit", e.target.value)}>
          {options.units.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      </label>
      <label className="check">
        <input type="checkbox" checked={values.is_stock} disabled={!editable} onChange={(e) => set("is_stock", e.target.checked)} />
        {t("items.isStock")}
      </label>
      {values.is_stock && (
        <>
          <label>
            {t("items.arrivesAs")}
            <select value={values.package_type} disabled={!editable} onChange={(e) => set("package_type", e.target.value)}>
              {options.package_types.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={values.inspection_required}
              disabled={!editable}
              onChange={(e) => set("inspection_required", e.target.checked)}
            />
            {t("items.inspectionRequired")}
          </label>
        </>
      )}
      <label>
        {t("vouchers.division")}
        <select value={values.division} disabled={!editable} onChange={(e) => set("division", e.target.value)}>
          <option value="">{t("items.allDivisions")}</option>
          {(divisions.data ?? [])
            .filter((d) => d.division_type !== "shared")
            .map((d) => (
              <option key={d.code} value={d.code}>
                {d.code} {d.name}
              </option>
            ))}
        </select>
      </label>
      <label>
        {t("items.material")}
        <select value={values.material} disabled={!editable} onChange={(e) => set("material", e.target.value)}>
          <option value="">—</option>
          {options.materials.map((m) => (
            <option key={m.code} value={m.code}>
              {m.code} {m.name}
            </option>
          ))}
        </select>
      </label>
      {values.is_stock ? (
        <label>
          {t("items.inventoryAccount")}
          <select value={values.inventory_account} disabled={!options.can_set_accounts} onChange={(e) => set("inventory_account", e.target.value)}>
            <option value="">{t("items.byCategory")}</option>
            {options.inventory_accounts.map((a) => (
              <option key={a.number} value={a.number}>
                {a.number} {a.name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <label>
          {t("items.expenseAccount")}
          <select value={values.expense_account} disabled={!options.can_set_accounts} onChange={(e) => set("expense_account", e.target.value)}>
            <option value="">—</option>
            {options.expense_accounts.map((a) => (
              <option key={a.number} value={a.number}>
                {a.number} {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="wide">
        {t("items.description")}
        <textarea rows={2} value={values.description} disabled={!editable} onChange={(e) => set("description", e.target.value)} />
      </label>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} disabled={!editable} onChange={(e) => set("notes", e.target.value)} />
      </label>
      {!options.can_set_accounts && <p className="wide muted">{t("items.accountsHelp")}</p>}
      {item?.used && <p className="wide muted">{t("items.usedHelp")}</p>}
      {editable && (
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {t("divisions.save")}
          </button>
          <button type="button" className="secondary" onClick={() => props.onDone(null)}>
            {t("access.cancel")}
          </button>
        </div>
      )}
      {editable && item && (
        <div className="wide inline-form">
          <label>
            {t("access.reason")}
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className="secondary" onClick={() => active.mutate()}>
            {item.is_active ? t("items.deactivate") : t("items.reactivate")}
          </button>
          {!item.used && (
            <button type="button" className="secondary" onClick={() => remove.mutate()}>
              {t("items.remove")}
            </button>
          )}
        </div>
      )}
      <div className="wide">
        <ErrorLine error={save.error ?? active.error ?? remove.error} />
      </div>
    </form>
  );
}

function ImportPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<{ dry_run: boolean; created: number; updated: number } | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importItems(file!, reason, dryRun),
    onSuccess: (data) => {
      setResult(data);
      if (!data.dry_run) void queryClient.invalidateQueries({ queryKey: [...itemsKey, "list"] });
    },
    onError: () => setResult(null),
  });
  return (
    <section className="panel" aria-label={t("items.import")}>
      <h2>{t("items.import")}</h2>
      <p className="muted">{t("items.importHelp")}</p>
      <div className="form-grid">
        <label>
          {t("factory.file")}
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
        </label>
        <label>
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="wide row-actions">
          <button type="button" className="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
            {t("factory.check")}
          </button>
          <button type="button" disabled={!file || run.isPending} onClick={() => run.mutate(false)}>
            {t("factory.doImport")}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t("access.cancel")}
          </button>
        </div>
      </div>
      {result && (
        <p className="notice" role="status">
          {t(result.dry_run ? "items.checked" : "items.imported", { created: String(result.created), updated: String(result.updated) })}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}
