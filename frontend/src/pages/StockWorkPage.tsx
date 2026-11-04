import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { itemsKey, listItems, listStores, storesKey } from "../api/items";
import {
  adjustmentAction,
  countAction,
  enterCounts,
  listAdjustments,
  listCounts,
  listIssues,
  makeAdjustment,
  makeIssue,
  returnIssue,
  startCount,
  stockOpsKey,
  type StockAdjustmentDoc,
  type StockCountDoc,
  type StockIssueDoc,
} from "../api/stockOps";
import SearchSelect from "../components/SearchSelect";
import { formatDecimal, formatQuantity } from "../lib/decimal";

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function useMainStores() {
  const stores = useQuery({ queryKey: storesKey, queryFn: listStores });
  return (stores.data ?? []).filter((s) => s.kind === "main" && s.is_active);
}

function useItemOptions() {
  const items = useQuery({ queryKey: [...itemsKey, "list", "", "", false], queryFn: () => listItems("", "", false) });
  return (items.data ?? []).filter((i) => i.is_stock).map((i) => ({ value: String(i.id), label: `${i.code} ${i.name} (${i.unit})` }));
}

const TABS = ["issues", "adjustments", "counts"] as const;

/** Stores work (P2-18): material issued and returned, adjustments and write-offs for the
 * Director, and stock counts. */
export default function StockWorkPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? params.get("tab")! : "issues";
  return (
    <main className="page">
      <h1>{t("sw.title")}</h1>
      <p className="muted">{t("sw.help")}</p>
      <div className="toolbar" role="tablist">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? undefined : "secondary"}
            onClick={() => setParams({ tab: name }, { replace: true })}
          >
            {t(`sw.tabs.${name}`)}
          </button>
        ))}
      </div>
      {tab === "issues" && <Issues />}
      {tab === "adjustments" && <Adjustments />}
      {tab === "counts" && <Counts />}
    </main>
  );
}

// --- Issues ----------------------------------------------------------------------------------

function Issues() {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: [...stockOpsKey, "issues"], queryFn: listIssues });
  return (
    <>
      <IssueForm />
      {rows.data?.map((d) => <IssueCard key={d.id} doc={d} />)}
      <ErrorLine error={rows.error} />
      {rows.data?.length === 0 && <p className="muted">{t("sw.noIssues")}</p>}
    </>
  );
}

function IssueForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const stores = useMainStores();
  const options = useItemOptions();
  const [store, setStore] = useState("");
  const [purpose, setPurpose] = useState("");
  const [item, setItem] = useState("");
  const [quantity, setQuantity] = useState("");
  const [lot, setLot] = useState("");
  const save = useMutation({
    mutationFn: () =>
      makeIssue({ store: Number(store), issue_date: today(), section: null, purpose, lines: [{ item: Number(item), quantity, lot_no: lot }] }),
    onSuccess: () => {
      setQuantity("");
      setLot("");
      void queryClient.invalidateQueries({ queryKey: stockOpsKey });
    },
  });
  return (
    <section className="panel form-grid" aria-label={t("sw.issue")}>
      <h2 className="wide">{t("sw.issue")}</h2>
      <label>
        {t("sw.store")}
        <select value={store} onChange={(e) => setStore(e.target.value)}>
          <option value="">—</option>
          {stores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("sw.purpose")}
        <input value={purpose} maxLength={300} onChange={(e) => setPurpose(e.target.value)} />
      </label>
      <SearchSelect label={t("sw.item")} options={options} value={item} onChange={setItem} />
      <label>
        {t("sw.quantity")}
        <input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
      </label>
      <label>
        {t("sw.lotOptional")}
        <input value={lot} maxLength={40} onChange={(e) => setLot(e.target.value)} />
      </label>
      <div className="wide row-actions">
        <button type="button" disabled={save.isPending || !store || !item || !quantity} onClick={() => save.mutate()}>
          {t("sw.issueButton")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

function IssueCard({ doc }: { doc: StockIssueDoc }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [back, setBack] = useState<Record<number, string>>({});
  const give = useMutation({
    mutationFn: () =>
      returnIssue(doc.id, {
        return_date: today(),
        lines: Object.entries(back)
          .filter(([, q]) => q)
          .map(([line, quantity]) => ({ line: Number(line), quantity })),
      }),
    onSuccess: () => {
      setBack({});
      void queryClient.invalidateQueries({ queryKey: stockOpsKey });
    },
  });
  return (
    <section className="panel" aria-label={doc.number}>
      <h2>
        <span className="mono">{doc.number}</span> · {t(`sw.kinds.${doc.kind}`)} · {doc.store} → {doc.section ?? doc.division}
      </h2>
      <p className="muted">
        {doc.issue_date} · {doc.purpose} · LKR {formatDecimal(doc.total_value)} · {doc.created_by}
        {doc.returns && ` · ${t("sw.against", { number: doc.returns.number })}`}
      </p>
      <ul className="plain-list">
        {doc.lines.map((x) => (
          <li key={x.id}>
            {x.item.code} · {t("sw.lot")} {x.lot_no} · {formatQuantity(x.quantity)} {x.item.unit} · {formatDecimal(x.value)}
            {doc.kind === "issue" && x.returned !== null && Number(x.returned) < Number(x.quantity) && (
              <input
                aria-label={t("sw.backOf", { item: x.item.code, lot: x.lot_no })}
                placeholder={t("sw.back")}
                inputMode="decimal"
                value={back[x.id] ?? ""}
                onChange={(e) => setBack((now) => ({ ...now, [x.id]: e.target.value }))}
              />
            )}
          </li>
        ))}
      </ul>
      {doc.kind === "issue" && Object.values(back).some(Boolean) && (
        <button type="button" className="small" disabled={give.isPending} onClick={() => give.mutate()}>
          {t("sw.returnButton")}
        </button>
      )}
      <ErrorLine error={give.error} />
    </section>
  );
}

// --- Adjustments -----------------------------------------------------------------------------

function Adjustments() {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: [...stockOpsKey, "adjustments"], queryFn: listAdjustments });
  return (
    <>
      <AdjustmentForm />
      {rows.data?.map((a) => <AdjustmentCard key={a.id} doc={a} />)}
      {rows.data?.length === 0 && <p className="muted">{t("sw.noAdjustments")}</p>}
      <ErrorLine error={rows.error} />
    </>
  );
}

function AdjustmentForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const stores = useMainStores();
  const options = useItemOptions();
  const [store, setStore] = useState("");
  const [kind, setKind] = useState("write_off");
  const [reason, setReason] = useState("");
  const [item, setItem] = useState("");
  const [quantity, setQuantity] = useState("");
  const [lot, setLot] = useState("");
  const [cost, setCost] = useState("");
  const save = useMutation({
    mutationFn: () =>
      makeAdjustment({ store: Number(store), kind, reason, lines: [{ item: Number(item), quantity, lot_no: lot, unit_cost: cost }] }),
    onSuccess: () => {
      setReason("");
      setQuantity("");
      void queryClient.invalidateQueries({ queryKey: stockOpsKey });
    },
  });
  return (
    <section className="panel form-grid" aria-label={t("sw.adjust")}>
      <h2 className="wide">{t("sw.adjust")}</h2>
      <label>
        {t("sw.store")}
        <select value={store} onChange={(e) => setStore(e.target.value)}>
          <option value="">—</option>
          {stores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("sw.kind")}
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="write_off">{t("sw.adjustmentKinds.write_off")}</option>
          <option value="adjustment">{t("sw.adjustmentKinds.adjustment")}</option>
        </select>
      </label>
      <label className="wide">
        {t("sw.reason")}
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <SearchSelect label={t("sw.item")} options={options} value={item} onChange={setItem} />
      <label>
        {t("sw.lot")}
        <input value={lot} maxLength={40} onChange={(e) => setLot(e.target.value)} />
      </label>
      <label>
        {t("sw.signedQuantity")}
        <input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
      </label>
      <label>
        {t("sw.costIfNew")}
        <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
      </label>
      <div className="wide row-actions">
        <button type="button" disabled={save.isPending || !store || !item} onClick={() => save.mutate()}>
          {t("sw.saveDraft")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

function AdjustmentCard({ doc }: { doc: StockAdjustmentDoc }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const act = useMutation({
    mutationFn: (action: "submit" | "approve" | "return" | "reject") => adjustmentAction(doc.id, action, text),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: stockOpsKey }),
  });
  return (
    <section className="panel" aria-label={doc.number}>
      <h2>
        <span className="mono">{doc.number}</span> · {t(`sw.adjustmentKinds.${doc.kind}`)} · {doc.store.code} ·{" "}
        {t(`sw.statuses.${doc.status}`)}
      </h2>
      <p className="muted">
        {doc.reason} · {doc.created_by}
        {doc.status === "posted" && ` · LKR ${formatDecimal(doc.total_value)} · ${doc.journal_entry}`}
      </p>
      <ul className="plain-list">
        {doc.lines.map((x, i) => (
          <li key={i}>
            {x.item.code} · {t("sw.lot")} {x.lot_no} · {formatQuantity(x.quantity)} {x.item.unit}
            {x.notes && <span className="muted"> · {x.notes}</span>}
          </li>
        ))}
      </ul>
      {(doc.can_submit || doc.can_approve) && (
        <div className="inline-form">
          <input aria-label={t("sw.commentOrReason")} placeholder={t("sw.commentOrReason")} value={text} onChange={(e) => setText(e.target.value)} />
          {doc.can_submit && (
            <button type="button" disabled={act.isPending} onClick={() => act.mutate("submit")}>
              {t("sw.submit")}
            </button>
          )}
          {doc.can_approve && (
            <>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate("approve")}>
                {t("sw.approve")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("return")}>
                {t("sw.return")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("reject")}>
                {t("sw.reject")}
              </button>
            </>
          )}
        </div>
      )}
      <ErrorLine error={act.error} />
    </section>
  );
}

// --- Counts -----------------------------------------------------------------------------------

function Counts() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const stores = useMainStores();
  const rows = useQuery({ queryKey: [...stockOpsKey, "counts"], queryFn: listCounts });
  const [store, setStore] = useState("");
  const start = useMutation({
    mutationFn: () => startCount(Number(store), today()),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: stockOpsKey }),
  });
  return (
    <>
      <section className="panel" aria-label={t("sw.startCount")}>
        <h2>{t("sw.startCount")}</h2>
        <p className="muted">{t("sw.countHelp")}</p>
        <div className="inline-form">
          <label>
            {t("sw.store")}
            <select value={store} onChange={(e) => setStore(e.target.value)}>
              <option value="">—</option>
              {stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} {s.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={start.isPending || !store} onClick={() => start.mutate()}>
            {t("sw.startButton")}
          </button>
        </div>
        <ErrorLine error={start.error} />
      </section>
      {rows.data?.map((c) => <CountCard key={c.id} doc={c} />)}
      <ErrorLine error={rows.error} />
    </>
  );
}

function CountCard({ doc }: { doc: StockCountDoc }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [counted, setCounted] = useState<Record<string, string>>(
    Object.fromEntries(doc.lines.map((x) => [`${x.item.id}|${x.lot_no}`, x.counted_quantity ?? ""])),
  );
  const refresh = () => void queryClient.invalidateQueries({ queryKey: stockOpsKey });
  const save = useMutation({
    mutationFn: () =>
      enterCounts(
        doc.id,
        doc.lines.map((x) => ({ item: x.item.id, lot_no: x.lot_no, counted_quantity: counted[`${x.item.id}|${x.lot_no}`] || null })),
      ),
    onSuccess: refresh,
  });
  const act = useMutation({ mutationFn: (action: "submit" | "cancel") => countAction(doc.id, action), onSuccess: refresh });
  const open = doc.status === "counting";
  return (
    <section className="panel" aria-label={doc.number}>
      <h2>
        <span className="mono">{doc.number}</span> · {doc.store.code} · {doc.count_date} · {t(`sw.countStatuses.${doc.status}`)}
      </h2>
      {doc.adjustment && (
        <p>
          {t("sw.differencesOn", { number: doc.adjustment.number })} · {t(`sw.statuses.${doc.adjustment.status}`)}
        </p>
      )}
      <div className="table-wrap">
        <table aria-label={t("sw.countSheet", { number: doc.number })}>
          <thead>
            <tr>
              <th>{t("sw.item")}</th>
              <th>{t("sw.lot")}</th>
              <th className="num">{t("sw.books")}</th>
              <th className="num">{t("sw.counted")}</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((x) => {
              const key = `${x.item.id}|${x.lot_no}`;
              return (
                <tr key={key}>
                  <td>
                    {x.item.code} {x.item.name}
                  </td>
                  <td>{x.lot_no}</td>
                  <td className="num">{formatQuantity(x.system_quantity)}</td>
                  <td className="num">
                    {open ? (
                      <input
                        aria-label={t("sw.countedOf", { item: x.item.code, lot: x.lot_no })}
                        inputMode="decimal"
                        className="num"
                        value={counted[key] ?? ""}
                        onChange={(e) => setCounted((now) => ({ ...now, [key]: e.target.value }))}
                      />
                    ) : (
                      formatQuantity(x.counted_quantity ?? "")
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {open && (
        <div className="row-actions">
          <button type="button" className="secondary" disabled={save.isPending} onClick={() => save.mutate()}>
            {t("sw.saveCounts")}
          </button>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate("submit")}>
            {t("sw.submitCount")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("cancel")}>
            {t("sw.cancelCount")}
          </button>
        </div>
      )}
      <ErrorLine error={save.error ?? act.error} />
    </section>
  );
}
