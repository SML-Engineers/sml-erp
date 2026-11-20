import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../api/client";
import {
  getTemplate,
  listTemplates,
  previewTemplate,
  resetTemplate,
  restoreTemplate,
  saveTemplate,
  templateKey,
  templatesKey,
  type Align,
  type Layout,
  type LayoutBlock,
  type TemplatePage,
} from "../../api/printTemplates";
import { formatDateTime } from "../../lib/time";

const MAX_TEXT_BLOCKS = 10; // the server's limit (print_templates.MAX_TEXT_BLOCKS)
const ALIGNS: Align[] = ["left", "center", "right"];

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), Math.max(low, high));

/** Keep a block inside the page and at least 5 × 4 mm, as the server requires. */
export function fit(block: LayoutBlock, page: { width: number; height: number }): LayoutBlock {
  const w = clamp(Math.round(block.w), 5, page.width);
  const h = clamp(Math.round(block.h), 4, page.height);
  return { ...block, w, h, x: clamp(Math.round(block.x), 0, page.width - w), y: clamp(Math.round(block.y), 0, page.height - h) };
}

/** Settings → Printed documents: the template designer (owner, 13 Nov 2026). The Admin and the
 * Director move and resize the parts of a document, hide the optional ones and add their own
 * text, check the result on the latest real document, and save it as a new version. */
export default function PrintTemplatesPage() {
  const { t } = useTranslation();
  const list = useQuery({ queryKey: templatesKey, queryFn: listTemplates });
  const [document, setDocument] = useState("delivery_note");
  const page = useQuery({ queryKey: templateKey(document), queryFn: () => getTemplate(document) });

  return (
    <main className="page">
      <h1>{t("printTemplates.title")}</h1>
      <p className="muted">{t("printTemplates.help")}</p>
      {list.data && list.data.documents.length > 1 && (
        <label>
          {t("printTemplates.document")}
          <select value={document} onChange={(e) => setDocument(e.target.value)}>
            {list.data.documents.map((d) => (
              <option key={d.document} value={d.document}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {page.data && <Designer key={`${document}-${page.data.version ?? 0}`} data={page.data} />}
      <ErrorLine error={list.error ?? page.error} />
    </main>
  );
}

function Designer({ data }: { data: TemplatePage }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [blocks, setBlocks] = useState<LayoutBlock[]>(data.layout.blocks);
  const [selected, setSelected] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [changed, setChanged] = useState(false);
  const canvas = useRef<HTMLDivElement>(null);
  const drag = useRef<{ key: string; mode: "move" | "size"; x: number; y: number; start: LayoutBlock } | null>(null);
  const edit = data.can_edit;
  const size = data.page;
  const labels = Object.fromEntries(data.blocks.map((b) => [b.key, b]));
  const layout: Layout = { blocks };
  const label = (block: LayoutBlock) =>
    block.key.startsWith("text-")
      ? t("printTemplates.ownText")
      : t(`printTemplates.blocks.${block.key}`, { defaultValue: labels[block.key]?.label ?? block.key });

  const update = (key: string, change: Partial<LayoutBlock>) => {
    setBlocks((now) => now.map((b) => (b.key === key ? fit({ ...b, ...change }, size) : b)));
    setChanged(true);
  };
  const done = (fresh: TemplatePage) => {
    queryClient.setQueryData(templateKey(data.document), fresh);
    void queryClient.invalidateQueries({ queryKey: templatesKey });
  };
  const save = useMutation({ mutationFn: () => saveTemplate(data.document, layout, note), onSuccess: done });
  const reset = useMutation({ mutationFn: () => resetTemplate(data.document), onSuccess: done });
  const restore = useMutation({ mutationFn: (version: number) => restoreTemplate(data.document, version), onSuccess: done });
  const preview = useMutation({
    mutationFn: () => previewTemplate(data.document, layout),
    onSuccess: (pdf) => {
      const url = URL.createObjectURL(pdf);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    },
  });

  const texts = blocks.filter((b) => b.key.startsWith("text-"));
  const addText = () => {
    let n = 1;
    while (blocks.some((b) => b.key === `text-${n}`)) n += 1;
    const block: LayoutBlock = { key: `text-${n}`, x: 0, y: 0, w: 60, h: 10, size: 9, align: "left", text: t("printTemplates.newText") };
    setBlocks((now) => [...now, block]);
    setSelected(block.key);
    setChanged(true);
  };
  const remove = (key: string) => {
    setBlocks((now) => now.filter((b) => b.key !== key));
    setSelected(null);
    setChanged(true);
  };

  // Moving and resizing with a mouse or a finger (pointer events; no library).
  const start = (event: PointerEvent, block: LayoutBlock, mode: "move" | "size") => {
    if (!edit) return;
    event.preventDefault();
    event.stopPropagation();
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
    drag.current = { key: block.key, mode, x: event.clientX, y: event.clientY, start: block };
    setSelected(block.key);
  };
  const move = (event: PointerEvent) => {
    const now = drag.current;
    const box = canvas.current?.getBoundingClientRect();
    if (!now || !box || !box.width) return;
    const perMm = box.width / size.width;
    const dx = (event.clientX - now.x) / perMm;
    const dy = (event.clientY - now.y) / perMm;
    if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
    const s = now.start;
    update(now.key, now.mode === "move" ? { x: s.x + dx, y: s.y + dy } : { w: s.w + dx, h: s.h + dy });
  };
  const stop = () => {
    drag.current = null;
  };
  // The arrow keys move the chosen block by 1 mm; with Shift they change its size.
  const keys = (event: KeyboardEvent, block: LayoutBlock) => {
    const step: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const d = step[event.key];
    if (!edit || !d) return;
    event.preventDefault();
    update(block.key, event.shiftKey ? { w: block.w + d[0], h: block.h + d[1] } : { x: block.x + d[0], y: block.y + d[1] });
  };

  const chosen = blocks.find((b) => b.key === selected);
  const pct = (mm: number, of: number) => `${(mm / of) * 100}%`;

  return (
    <>
      <section className="panel" aria-label={t("printTemplates.layout")}>
        <h2>
          {data.label} · {data.version ? t("printTemplates.version", { version: data.version }) : t("printTemplates.standard")}
        </h2>
        {edit ? <p className="muted">{t("printTemplates.howTo")}</p> : <p className="muted">{t("printTemplates.viewOnly")}</p>}
        <div className="designer">
          <div
            ref={canvas}
            className="designer-page"
            style={{ aspectRatio: `${size.width} / ${size.height}` }}
            onPointerMove={move}
            onPointerUp={stop}
            onPointerCancel={stop}
            onPointerDown={() => setSelected(null)}
          >
            {blocks.map((block) => (
              <div
                key={block.key}
                role="button"
                tabIndex={0}
                aria-label={label(block)}
                aria-pressed={selected === block.key}
                className={`designer-block${block.hidden ? " is-hidden" : ""}${selected === block.key ? " is-selected" : ""}${block.key === data.table ? " is-table" : ""}`}
                style={{
                  left: pct(block.x, size.width),
                  top: pct(block.y, size.height),
                  width: pct(block.w, size.width),
                  height: pct(block.h, size.height),
                }}
                onPointerDown={(e) => start(e, block, "move")}
                onKeyDown={(e) => keys(e, block)}
                onFocus={() => setSelected(block.key)}
              >
                <span>{block.key.startsWith("text-") ? block.text : label(block)}</span>
                {edit && <span className="designer-handle" aria-hidden="true" onPointerDown={(e) => start(e, block, "size")} />}
              </div>
            ))}
          </div>
          <div className="designer-side">
            {chosen ? (
              <BlockForm
                block={chosen}
                label={label(chosen)}
                mayHide={chosen.key.startsWith("text-") || !!labels[chosen.key]?.may_hide}
                edit={edit}
                onChange={(c) => update(chosen.key, c)}
                onRemove={() => remove(chosen.key)}
              />
            ) : (
              <p className="muted">{t("printTemplates.pick")}</p>
            )}
            {edit && (
              <button type="button" className="secondary" onClick={addText} disabled={texts.length >= MAX_TEXT_BLOCKS}>
                {t("printTemplates.addText")}
              </button>
            )}
            {data.table && <p className="muted">{t("printTemplates.tableNote")}</p>}
          </div>
        </div>
        {edit && (
          <div className="row-actions">
            <label>
              {t("printTemplates.note")}
              <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
            </label>
            <button type="button" className="secondary" onClick={() => preview.mutate()} disabled={preview.isPending}>
              {t("printTemplates.preview")}
            </button>
            <button type="button" onClick={() => save.mutate()} disabled={!changed || save.isPending}>
              {t("printTemplates.save")}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!changed}
              onClick={() => {
                setBlocks(data.layout.blocks);
                setChanged(false);
              }}
            >
              {t("printTemplates.undo")}
            </button>
            {data.version !== null && (
              <button
                type="button"
                className="secondary"
                onClick={() => window.confirm(t("printTemplates.resetConfirm")) && reset.mutate()}
                disabled={reset.isPending}
              >
                {t("printTemplates.reset")}
              </button>
            )}
          </div>
        )}
        <ErrorLine error={save.error ?? preview.error ?? reset.error ?? restore.error} />
      </section>
      <History data={data} onRestore={(v) => restore.mutate(v)} busy={restore.isPending} />
    </>
  );
}

function BlockForm(props: {
  block: LayoutBlock;
  label: string;
  mayHide: boolean;
  edit: boolean;
  onChange: (change: Partial<LayoutBlock>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const { block, edit, onChange } = props;
  const own = block.key.startsWith("text-");
  const number = (key: "x" | "y" | "w" | "h" | "size", min: number, max: number) => (
    <label>
      {t(`printTemplates.field.${key}`)}
      <input
        type="number"
        min={min}
        max={max}
        value={block[key]}
        disabled={!edit}
        onChange={(e) => e.target.value !== "" && onChange({ [key]: Number(e.target.value) })}
      />
    </label>
  );
  return (
    <form className="form-grid" aria-label={props.label} onSubmit={(e) => e.preventDefault()}>
      <h3 className="wide">{props.label}</h3>
      {number("x", 0, 182)}
      {number("y", 0, 269)}
      {number("w", 5, 182)}
      {number("h", 4, 269)}
      {number("size", 6, 24)}
      <label>
        {t("printTemplates.field.align")}
        <select value={block.align} disabled={!edit} onChange={(e) => onChange({ align: e.target.value as Align })}>
          {ALIGNS.map((a) => (
            <option key={a} value={a}>
              {t(`printTemplates.align.${a}`)}
            </option>
          ))}
        </select>
      </label>
      {own && (
        <label className="wide">
          {t("printTemplates.field.text")}
          <textarea value={block.text ?? ""} maxLength={500} disabled={!edit} onChange={(e) => onChange({ text: e.target.value })} />
        </label>
      )}
      {props.mayHide && !own && (
        <label className="wide">
          <input
            type="checkbox"
            checked={!!block.hidden}
            disabled={!edit}
            onChange={(e) => onChange({ hidden: e.target.checked || undefined })}
          />{" "}
          {t("printTemplates.hide")}
        </label>
      )}
      {own && edit && (
        <div className="wide">
          <button type="button" className="danger small" onClick={props.onRemove}>
            {t("printTemplates.removeText")}
          </button>
        </div>
      )}
    </form>
  );
}

function History({ data, onRestore, busy }: { data: TemplatePage; onRestore: (version: number) => void; busy: boolean }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("printTemplates.history")}>
      <h2>{t("printTemplates.history")}</h2>
      {data.history.length === 0 ? (
        <p className="muted">{t("printTemplates.noHistory")}</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("printTemplates.col.version")}</th>
                <th>{t("printTemplates.col.note")}</th>
                <th>{t("printTemplates.col.by")}</th>
                <th>{t("printTemplates.col.at")}</th>
                {data.can_edit && <th />}
              </tr>
            </thead>
            <tbody>
              {data.history.map((h) => (
                <tr key={h.version}>
                  <td>{h.version}</td>
                  <td>{h.note || "—"}</td>
                  <td>{h.by}</td>
                  <td>{formatDateTime(h.at)}</td>
                  {data.can_edit && (
                    <td>
                      {h.version !== data.version && (
                        <button type="button" className="secondary small" disabled={busy} onClick={() => onRestore(h.version)}>
                          {t("printTemplates.restore")}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
