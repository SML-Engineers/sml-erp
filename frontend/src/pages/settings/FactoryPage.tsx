import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { can } from "../../api/access";
import { listUsers } from "../../api/admin";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  MOULDING_FIELDS,
  addRate,
  createMachine,
  createSection,
  deleteMachine,
  deleteSection,
  exportUrl,
  importFactory,
  listMachines,
  listRates,
  listSections,
  machinesKey,
  photoUrl,
  removeRate,
  sectionsKey,
  updateMachine,
  updateSection,
  uploadPhoto,
  type Category,
  type ImportResult,
  type Machine,
  type MachineChange,
  type MachineStatus,
  type Section,
  type SectionType,
} from "../../api/factory";
import { divisionsAdminKey, listDivisionsAdmin } from "../../api/organisation";
import { formatDecimal } from "../../lib/decimal";

type Selection =
  | { kind: "section"; id: number }
  | { kind: "machine"; id: number }
  | { kind: "new-section"; division: string }
  | { kind: "new-machine"; section: string }
  | { kind: "import" }
  | null;

const STATUSES: MachineStatus[] = ["active", "maintenance", "retired"];
const TYPES: SectionType[] = ["machining", "moulding", "support"];

function errorText(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    const errors = (error.body as { errors?: string[] } | null)?.errors;
    if (errors?.length) return [error.detail, ...errors].filter(Boolean).join("\n");
    if (error.detail) return error.detail;
  }
  return fallback;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error pre-line" role="alert">
      {errorText(error, t("common.error"))}
    </p>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: sectionsKey });
    void queryClient.invalidateQueries({ queryKey: machinesKey });
    void queryClient.invalidateQueries({ queryKey: divisionsAdminKey });
  };
}

export default function FactoryPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const canManage = can(me.access, "settings", "manage");
  const divisions = useQuery({ queryKey: divisionsAdminKey, queryFn: listDivisionsAdmin });
  const sections = useQuery({ queryKey: sectionsKey, queryFn: listSections });
  const machines = useQuery({ queryKey: machinesKey, queryFn: listMachines });
  const [selected, setSelected] = useState<Selection>(null);
  const [search, setSearch] = useState("");

  const loading = divisions.isPending || sections.isPending || machines.isPending;
  const failed = divisions.isError || sections.isError || machines.isError;
  const section = selected?.kind === "section" ? sections.data?.find((s) => s.id === selected.id) : undefined;
  const machine = selected?.kind === "machine" ? machines.data?.find((m) => m.id === selected.id) : undefined;
  const firstDivision = divisions.data?.find((d) => d.is_active)?.code ?? "";
  const firstSection =
    section?.code ?? sections.data?.find((s) => s.code === machine?.section)?.code ?? sections.data?.[0]?.code ?? "";

  return (
    <main className="page">
      <h1>{t("factory.title")}</h1>
      <p className="muted">{t("factory.help")}</p>

      <div className="toolbar">
        <Link className="button-link secondary" to="/settings/divisions">
          {t("factory.addDivision")}
        </Link>
        {canManage && (
          <>
            <button
              type="button"
              onClick={() => setSelected({ kind: "new-section", division: section?.division ?? firstDivision })}
            >
              {t("factory.addSection")}
            </button>
            <button
              type="button"
              disabled={!sections.data?.length}
              onClick={() => setSelected({ kind: "new-machine", section: firstSection })}
            >
              {t("factory.addMachine")}
            </button>
            <button type="button" className="secondary" onClick={() => setSelected({ kind: "import" })}>
              {t("factory.import")}
            </button>
          </>
        )}
        <a className="button-link secondary" href={exportUrl}>
          {t("factory.export")}
        </a>
      </div>

      {loading && <p className="muted">{t("common.loading")}</p>}
      {failed && <p className="form-error">{t("common.error")}</p>}
      {divisions.data && sections.data && machines.data && (
        <div className="tree-layout">
          <nav className="panel tree" aria-label={t("factory.tree")}>
            <input
              type="search"
              placeholder={t("table.search")}
              aria-label={t("table.search")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Tree
              divisions={divisions.data.map((d) => ({ code: d.code, name: d.name, active: d.is_active }))}
              sections={sections.data}
              machines={machines.data}
              search={search}
              selected={selected}
              onSelect={setSelected}
            />
          </nav>
          <div className="tree-detail">
            {selected === null && <p className="panel muted">{t("factory.pick")}</p>}
            {section && (
              <SectionForm
                key={`s${section.id}`}
                section={section}
                divisions={divisions.data.map((d) => d.code)}
                canManage={canManage}
                onDone={setSelected}
              />
            )}
            {selected?.kind === "new-section" && (
              <SectionForm
                key={`new-s-${selected.division}`}
                division={selected.division}
                divisions={divisions.data.filter((d) => d.is_active).map((d) => d.code)}
                canManage={canManage}
                onDone={setSelected}
              />
            )}
            {machine && (
              <MachineForm
                key={`m${machine.id}`}
                machine={machine}
                sections={sections.data}
                canManage={canManage}
                onDone={setSelected}
              />
            )}
            {selected?.kind === "new-machine" && (
              <MachineForm
                key={`new-m-${selected.section}`}
                sectionCode={selected.section}
                sections={sections.data.filter((s) => s.is_active)}
                canManage={canManage}
                onDone={setSelected}
              />
            )}
            {selected?.kind === "import" && canManage && <ImportPanel />}
          </div>
        </div>
      )}
    </main>
  );
}

// --- Tree --------------------------------------------------------------------------------

function matches(search: string, ...texts: string[]) {
  const needle = search.trim().toLowerCase();
  return !needle || texts.some((text) => text.toLowerCase().includes(needle));
}

function Tree(props: {
  divisions: { code: string; name: string; active: boolean }[];
  sections: Section[];
  machines: Machine[];
  search: string;
  selected: Selection;
  onSelect: (selection: Selection) => void;
}) {
  const { t } = useTranslation();
  const { search, selected, onSelect } = props;
  const isSelected = (kind: string, id: number) =>
    selected !== null && selected.kind === kind && "id" in selected && selected.id === id;

  return (
    <ul className="tree-list">
      {props.divisions.map((division) => {
        const sections = props.sections
          .filter((s) => s.division === division.code)
          .map((s) => ({
            section: s,
            machines: props.machines.filter(
              (m) => m.section === s.code && matches(search, m.code, m.name, s.code, s.name),
            ),
          }))
          .filter(({ section: s, machines }) => machines.length > 0 || matches(search, s.code, s.name));
        if (sections.length === 0 && !matches(search, division.code, division.name)) return null;
        return (
          <li key={division.code}>
            <span className="tree-division">
              {division.code} {division.name}
              {!division.active && <span className="tag">{t("users.inactive")}</span>}
            </span>
            <ul>
              {sections.map(({ section: s, machines }) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`tree-item${isSelected("section", s.id) ? " selected" : ""}`}
                    aria-current={isSelected("section", s.id) || undefined}
                    onClick={() => onSelect({ kind: "section", id: s.id })}
                  >
                    {s.code} {s.name}
                    {!s.is_active && <span className="tag">{t("users.inactive")}</span>}
                  </button>
                  {machines.length > 0 && (
                    <ul>
                      {machines.map((m) => (
                        <li key={m.id}>
                          <button
                            type="button"
                            className={`tree-item machine${isSelected("machine", m.id) ? " selected" : ""}`}
                            aria-current={isSelected("machine", m.id) || undefined}
                            onClick={() => onSelect({ kind: "machine", id: m.id })}
                          >
                            {m.code} {m.name}
                            {m.status !== "active" && (
                              <span className="tag">{t(`factory.status.${m.status}`)}</span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}

// --- Section form ------------------------------------------------------------------------

function SectionForm(props: {
  section?: Section;
  division?: string;
  divisions: string[];
  canManage: boolean;
  onDone: (selection: Selection) => void;
}) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const existing = props.section;
  const users = useQuery({ queryKey: ["users"], queryFn: listUsers, enabled: props.canManage });
  const [code, setCode] = useState(existing?.code ?? "");
  const [name, setName] = useState(existing?.name ?? "");
  const [division, setDivision] = useState(existing?.division ?? props.division ?? "");
  const [type, setType] = useState<SectionType>(existing?.section_type ?? "machining");
  const [category, setCategory] = useState<Category>(existing?.category ?? "manual");
  const [supervisors, setSupervisors] = useState<number[]>(
    existing?.supervisors.map((s) => s.id) ?? [],
  );
  const [reason, setReason] = useState("");
  const editable = props.canManage;

  const payload = () => ({
    ...(existing?.in_use ? {} : { code }),
    name,
    division,
    section_type: type,
    category: type === "machining" ? category : ("" as Category),
    supervisors,
    reason,
  });
  const save = useMutation({
    mutationFn: () => (existing ? updateSection(existing.id, payload()) : createSection(payload())),
    onSuccess: (saved) => {
      refresh();
      props.onDone({ kind: "section", id: saved.id });
    },
  });
  const toggle = useMutation({
    mutationFn: () => updateSection(existing!.id, { is_active: !existing!.is_active, reason }),
    onSuccess: () => refresh(),
  });
  const remove = useMutation({
    mutationFn: () => deleteSection(existing!.id, reason),
    onSuccess: () => {
      refresh();
      props.onDone(null);
    },
  });
  const busy = save.isPending || toggle.isPending || remove.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const title = existing ? t("factory.sectionTitle", { code: existing.code }) : t("factory.addSection");
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>
          {t("divisions.code")}
          <input
            className="code-input wide-code"
            value={code}
            required
            maxLength={20}
            disabled={!editable || existing?.in_use}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
          />
        </label>
        <label>
          {t("divisions.name")}
          <input value={name} required disabled={!editable} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          {t("factory.division")}
          <select value={division} disabled={!editable} onChange={(e) => setDivision(e.target.value)}>
            {props.divisions.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("divisions.type")}
          <select
            value={type}
            disabled={!editable}
            onChange={(e) => setType(e.target.value as SectionType)}
          >
            {TYPES.map((value) => (
              <option key={value} value={value}>
                {t(`factory.types.${value}`)}
              </option>
            ))}
          </select>
        </label>
        {type === "machining" && (
          <label>
            {t("factory.category")}
            <select
              value={category || "manual"}
              disabled={!editable}
              onChange={(e) => setCategory(e.target.value as Category)}
            >
              <option value="manual">{t("factory.categories.manual")}</option>
              <option value="cnc">{t("factory.categories.cnc")}</option>
            </select>
          </label>
        )}
        <fieldset className="wide checks">
          <legend>{t("factory.supervisors")}</legend>
          {existing?.supervisors
            .filter((s) => !users.data?.some((u) => u.id === s.id))
            .map((s) => (
              <span key={s.id}>{s.name}</span>
            ))}
          {users.data
            ?.filter((u) => u.is_active)
            .map((u) => (
              <label key={u.id} className="check">
                <input
                  type="checkbox"
                  checked={supervisors.includes(u.id)}
                  disabled={!editable}
                  onChange={() =>
                    setSupervisors((now) =>
                      now.includes(u.id) ? now.filter((id) => id !== u.id) : [...now, u.id],
                    )
                  }
                />
                {u.full_name}
              </label>
            ))}
        </fieldset>
        {editable && (
          <>
            <label className="wide">
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <div className="wide row-actions">
              <button type="submit" disabled={busy}>
                {t("divisions.save")}
              </button>
              {existing && (
                <button
                  type="button"
                  className={existing.is_active ? "danger" : "secondary"}
                  disabled={busy}
                  onClick={() => toggle.mutate()}
                >
                  {existing.is_active ? t("factory.makeInactive") : t("divisions.reactivate")}
                </button>
              )}
              {existing && !existing.in_use && existing.machine_count === 0 && (
                <button type="button" className="danger" disabled={busy} onClick={() => remove.mutate()}>
                  {t("divisions.delete")}
                </button>
              )}
            </div>
          </>
        )}
      </form>
      {existing?.in_use && <p className="muted">{t("factory.codeFixed")}</p>}
      {editable && existing && <p className="muted">{t("factory.reasonNeeded")}</p>}
      <ErrorLine error={save.error ?? toggle.error ?? remove.error} />
    </section>
  );
}

// --- Machine form ------------------------------------------------------------------------

type MachineDraft = Record<string, string>;

function draftOf(machine: Machine | undefined, sectionCode: string): MachineDraft {
  const draft: MachineDraft = {
    code: machine?.code ?? "",
    name: machine?.name ?? "",
    section: machine?.section ?? sectionCode,
    make: machine?.make ?? "",
    model: machine?.model ?? "",
    serial_no: machine?.serial_no ?? "",
    year: machine?.year?.toString() ?? "",
    status: machine?.status ?? "active",
    notes: machine?.notes ?? "",
  };
  for (const field of MOULDING_FIELDS) draft[field] = machine?.[field] ?? "";
  return draft;
}

function MachineForm(props: {
  machine?: Machine;
  sectionCode?: string;
  sections: Section[];
  canManage: boolean;
  onDone: (selection: Selection) => void;
}) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const existing = props.machine;
  const [draft, setDraft] = useState(() => draftOf(existing, props.sectionCode ?? ""));
  const [reason, setReason] = useState("");
  const editable = props.canManage;
  const sectionType = props.sections.find((s) => s.code === draft.section)?.section_type;
  const showMoulding =
    sectionType === "moulding" || MOULDING_FIELDS.some((field) => draft[field] !== "");
  const set = (field: string) => (value: string) => setDraft((now) => ({ ...now, [field]: value }));

  const payload = (): MachineChange => {
    const change: Record<string, unknown> = { ...draft, reason };
    if (existing?.in_use) delete change.code;
    change.year = draft.year === "" ? null : Number(draft.year);
    for (const field of MOULDING_FIELDS) change[field] = draft[field] === "" ? null : draft[field];
    return change as MachineChange;
  };
  const save = useMutation({
    mutationFn: () => (existing ? updateMachine(existing.id, payload()) : createMachine(payload())),
    onSuccess: (saved) => {
      refresh();
      props.onDone({ kind: "machine", id: saved.id });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteMachine(existing!.id, reason),
    onSuccess: () => {
      refresh();
      props.onDone(null);
    },
  });
  const busy = save.isPending || remove.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const text = (field: string, label: string, type = "text") => (
    <label key={field}>
      {label}
      <input
        type={type}
        inputMode={type === "number" ? "decimal" : undefined}
        step={type === "number" ? "0.1" : undefined}
        value={draft[field]}
        disabled={!editable || (field === "code" && existing?.in_use)}
        required={field === "code" || field === "name"}
        className={field === "code" ? "code-input wide-code" : undefined}
        onChange={(e) => set(field)(field === "code" ? e.target.value.toUpperCase() : e.target.value)}
      />
    </label>
  );

  const title = existing ? t("factory.machineTitle", { code: existing.code }) : t("factory.addMachine");
  return (
    <>
      <section className="panel" aria-label={title}>
        <h2>{title}</h2>
        <form className="form-grid" onSubmit={submit}>
          {text("code", t("divisions.code"))}
          {text("name", t("divisions.name"))}
          <label>
            {t("factory.section")}
            <select value={draft.section} disabled={!editable} onChange={(e) => set("section")(e.target.value)}>
              {props.sections.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} {s.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("users.status")}
            <select value={draft.status} disabled={!editable} onChange={(e) => set("status")(e.target.value)}>
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {t(`factory.status.${status}`)}
                </option>
              ))}
            </select>
          </label>
          {text("make", t("factory.make"))}
          {text("model", t("factory.model"))}
          {text("serial_no", t("factory.serialNo"))}
          {text("year", t("factory.year"), "number")}
          {showMoulding && (
            <fieldset className="wide form-grid">
              <legend>{t("factory.mouldingSize")}</legend>
              {MOULDING_FIELDS.map((field) => text(field, t(`factory.field.${field}`), "number"))}
            </fieldset>
          )}
          <label className="wide">
            {t("factory.notes")}
            <textarea rows={2} value={draft.notes} disabled={!editable} onChange={(e) => set("notes")(e.target.value)} />
          </label>
          {editable && (
            <>
              <label className="wide">
                {t("access.reason")}
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <div className="wide row-actions">
                <button type="submit" disabled={busy}>
                  {t("divisions.save")}
                </button>
                {existing && !existing.in_use && (
                  <button type="button" className="danger" disabled={busy} onClick={() => remove.mutate()}>
                    {t("divisions.delete")}
                  </button>
                )}
              </div>
            </>
          )}
        </form>
        {existing?.in_use && <p className="muted">{t("factory.codeFixed")}</p>}
        {editable && <p className="muted">{t("factory.retireHelp")}</p>}
        <ErrorLine error={save.error ?? remove.error} />
      </section>
      {existing && <RatesPanel machine={existing} canManage={editable} />}
      {existing && <PhotoPanel machine={existing} canManage={editable} />}
    </>
  );
}

// --- Rates and photo ---------------------------------------------------------------------

function RatesPanel({ machine, canManage }: { machine: Machine; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["settings", "machines", machine.id, "rates"];
  const rates = useQuery({ queryKey: key, queryFn: () => listRates(machine.id) });
  const [from, setFrom] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const done = () => {
    setAmount("");
    setReason("");
    void queryClient.invalidateQueries({ queryKey: key });
    void queryClient.invalidateQueries({ queryKey: machinesKey });
  };
  const add = useMutation({
    mutationFn: () => addRate(machine.id, { effective_from: from, rate: amount, reason }),
    onSuccess: done,
  });
  const remove = useMutation({
    mutationFn: (rateId: number) => removeRate(machine.id, rateId, reason),
    onSuccess: done,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <section className="panel">
      <h2>{t("factory.rates")}</h2>
      <p className="muted">{t("factory.ratesHelp")}</p>
      {rates.data && rates.data.length === 0 && <p className="muted">{t("factory.noRates")}</p>}
      {rates.data && rates.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("factory.from")}</th>
                <th className="num">{t("factory.rate")}</th>
                <th>{t("access.reason")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rates.data.map((rate) => (
                <tr key={rate.id}>
                  <td>{rate.effective_from}</td>
                  <td className="num">{formatDecimal(rate.rate)}</td>
                  <td>{rate.reason}</td>
                  <td>
                    {canManage && !rate.in_force && (
                      <button
                        type="button"
                        className="small secondary"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(rate.id)}
                      >
                        {t("divisions.delete")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canManage && (
        <form className="inline-form" onSubmit={submit}>
          <label>
            {t("factory.from")}
            <input type="date" value={from} required onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label>
            {t("factory.rate")}
            <input
              inputMode="decimal"
              value={amount}
              required
              pattern="\d+(\.\d{1,2})?"
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          <label>
            {t("access.reason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="submit" disabled={add.isPending}>
            {t("factory.addRate")}
          </button>
        </form>
      )}
      <ErrorLine error={add.error ?? remove.error} />
    </section>
  );
}

function PhotoPanel({ machine, canManage }: { machine: Machine; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [version, setVersion] = useState(0);
  const upload = useMutation({
    mutationFn: (file: File) => uploadPhoto(machine.id, file),
    onSuccess: () => {
      setVersion((v) => v + 1);
      void queryClient.invalidateQueries({ queryKey: machinesKey });
    },
  });
  return (
    <section className="panel">
      <h2>{t("factory.photo")}</h2>
      {machine.has_photo ? (
        <img className="machine-photo" src={`${photoUrl(machine)}?v=${version}`} alt={machine.name} />
      ) : (
        <p className="muted">{t("factory.noPhoto")}</p>
      )}
      {canManage && (
        <label>
          {t("factory.uploadPhoto")}
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
      )}
      <ErrorLine error={upload.error} />
    </section>
  );
}

// --- Import ------------------------------------------------------------------------------

function ImportPanel() {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importFactory(file!, reason, dryRun),
    onSuccess: (data) => {
      setResult(data);
      if (!data.dry_run) refresh();
    },
    onError: () => setResult(null),
  });
  const summary = useMemo(
    () => (result ? t(result.dry_run ? "factory.checked" : "factory.imported", { ...result }) : ""),
    [result, t],
  );

  return (
    <section className="panel" aria-label={t("factory.import")}>
      <h2>{t("factory.import")}</h2>
      <p className="muted">{t("factory.importHelp")}</p>
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
          <button
            type="button"
            className="secondary"
            disabled={!file || run.isPending}
            onClick={() => run.mutate(true)}
          >
            {t("factory.check")}
          </button>
          <button type="button" disabled={!file || run.isPending} onClick={() => run.mutate(false)}>
            {t("factory.doImport")}
          </button>
        </div>
      </div>
      {result && (
        <p className="notice" role="status">
          {summary}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}
