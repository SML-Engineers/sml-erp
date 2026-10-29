import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import {
  deleteVoucher,
  getVoucher,
  voucherFileUrl,
  voucherPrintUrl,
  vouchersKey,
  type Paper,
  type VoucherAction,
  type VoucherStatus,
} from "../api/vouchers";

interface Row {
  id: number;
  number: string;
  status: VoucherStatus;
  actions?: VoucherAction[];
}

const EDIT_LINKS: Partial<Record<VoucherAction, (id: number) => string>> = {
  edit: (id) => `/vouchers/${id}`,
  edit_coding: (id) => `/vouchers/review?open=${id}`,
  revise: (id) => `/vouchers/${id}?edit=1`,
};

/**
 * The ⋯ actions button on every voucher row (spec 4.4): Resources, Print, Edit, Delete.
 * Only the actions the server says this person may take are shown; the server refuses
 * the others even if called directly.
 */
export default function VoucherActions({ voucher, onDeleted }: { voucher: Row; onDeleted?: () => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState<"resources" | "print" | "delete" | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const allowed = voucher.actions ?? [];
  const edit = allowed.find((a) => a in EDIT_LINKS);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (allowed.length === 0) return null;
  const choose = (which: "resources" | "print" | "delete") => {
    setOpen(false);
    setDialog(which);
  };

  return (
    <div className="row-menu" ref={box}>
      <button
        type="button"
        className="icon-button small"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("voucherActions.menu", { number: voucher.number })}
        onClick={() => setOpen((v) => !v)}
      >
        ⋯
      </button>
      {open && (
        <div className="row-menu-list" role="menu" aria-label={t("voucherActions.menu", { number: voucher.number })}>
          {allowed.includes("resources") && (
            <button type="button" role="menuitem" onClick={() => choose("resources")}>
              {t("voucherActions.resources")}
            </button>
          )}
          {allowed.includes("print") && (
            <button type="button" role="menuitem" onClick={() => choose("print")}>
              {t("voucherActions.print")}
            </button>
          )}
          {edit && (
            <Link role="menuitem" to={EDIT_LINKS[edit]!(voucher.id)} onClick={() => setOpen(false)}>
              {t("voucherActions.edit")}
            </Link>
          )}
          {allowed.includes("delete") && (
            <button type="button" role="menuitem" className="danger-text" onClick={() => choose("delete")}>
              {t("voucherActions.delete")}
            </button>
          )}
        </div>
      )}
      {dialog === "resources" && <FileViewer id={voucher.id} number={voucher.number} onClose={() => setDialog(null)} />}
      {dialog === "print" && <PrintDialog voucher={voucher} onClose={() => setDialog(null)} />}
      {dialog === "delete" && (
        <DeleteDialog
          voucher={voucher}
          onClose={() => setDialog(null)}
          onDeleted={() => {
            setDialog(null);
            onDeleted?.();
          }}
        />
      )}
    </div>
  );
}

function Modal({ label, onClose, children, wide }: { label: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);
  return (
    <div className="modal-backdrop">
      <div className={`modal panel${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={label}>
        {children}
      </div>
    </div>
  );
}

/** Resources: the voucher's scans and other files, one at a time, with zoom and rotate. */
export function FileViewer({ id, number, onClose }: { id: number; number: string; onClose: () => void }) {
  const { t } = useTranslation();
  const voucher = useQuery({ queryKey: [...vouchersKey, "one", id], queryFn: () => getVoucher(id) });
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState(100);
  const [turn, setTurn] = useState(0);
  const files = voucher.data?.attachments ?? [];
  const file = files[index];
  const go = (to: number) => {
    setIndex(to);
    setZoom(100);
    setTurn(0);
  };
  const look = { transform: `rotate(${turn}deg) scale(${zoom / 100})` };

  return (
    <Modal label={t("voucherActions.filesOf", { number })} onClose={onClose} wide>
      <div className="row-actions">
        <h2>{t("voucherActions.filesOf", { number })}</h2>
        <button type="button" className="small secondary" onClick={onClose}>
          {t("voucherActions.close")}
        </button>
      </div>
      {voucher.data && files.length === 0 && <p className="muted">{t("voucherActions.noFiles")}</p>}
      {file && (
        <>
          <div className="row-actions viewer-tools">
            <button type="button" className="small secondary" disabled={index === 0} onClick={() => go(index - 1)}>
              {t("voucherActions.previous")}
            </button>
            <span>
              {t("voucherActions.fileOf", { n: String(index + 1), total: String(files.length) })}: {file.file_name}
            </span>
            <button
              type="button"
              className="small secondary"
              disabled={index === files.length - 1}
              onClick={() => go(index + 1)}
            >
              {t("voucherActions.next")}
            </button>
            <button type="button" className="small secondary" disabled={zoom <= 50} onClick={() => setZoom((z) => z - 25)}>
              {t("voucherActions.zoomOut")}
            </button>
            <span aria-label={t("voucherActions.zoom")}>{zoom}%</span>
            <button type="button" className="small secondary" disabled={zoom >= 300} onClick={() => setZoom((z) => z + 25)}>
              {t("voucherActions.zoomIn")}
            </button>
            <button type="button" className="small secondary" onClick={() => setTurn((r) => (r + 90) % 360)}>
              {t("voucherActions.rotate")}
            </button>
            <a className="button-link small" href={`${voucherFileUrl(id, file.id)}?download=1`}>
              {t("voucherActions.download")}
            </a>
          </div>
          <div className="viewer">
            {file.content_type === "application/pdf" ? (
              <iframe title={file.file_name} src={voucherFileUrl(id, file.id)} style={look} />
            ) : (
              <img alt={file.file_name} src={voucherFileUrl(id, file.id)} style={look} />
            )}
          </div>
        </>
      )}
    </Modal>
  );
}

/** Print: the payment voucher PDF, A4 or A5. Reprints come back marked "Copy". */
function PrintDialog({ voucher, onClose }: { voucher: Row; onClose: () => void }) {
  const { t } = useTranslation();
  const [paper, setPaper] = useState<Paper>("A4");
  return (
    <Modal label={t("voucherActions.printTitle", { number: voucher.number })} onClose={onClose}>
      <h2>{t("voucherActions.printTitle", { number: voucher.number })}</h2>
      <fieldset className="choice">
        <legend>{t("voucherActions.paper")}</legend>
        {(["A4", "A5"] as Paper[]).map((p) => (
          <label key={p}>
            <input type="radio" name="paper" checked={paper === p} onChange={() => setPaper(p)} /> {p}
          </label>
        ))}
      </fieldset>
      <p className="muted">{t("voucherActions.printHelp")}</p>
      <div className="row-actions">
        <button
          type="button"
          onClick={() => {
            window.open(voucherPrintUrl(voucher.id, paper), "_blank", "noopener");
            onClose();
          }}
        >
          {t("voucherActions.openPdf")}
        </button>
        <button type="button" className="secondary" onClick={onClose}>
          {t("voucherActions.cancel")}
        </button>
      </div>
    </Modal>
  );
}

/** Delete: a draft by its creator or the Admin; a submitted voucher by the Director or the
 * Admin, with a reason. The voucher keeps its number and history (Deleted Vouchers). */
function DeleteDialog({ voucher, onClose, onDeleted }: { voucher: Row; onClose: () => void; onDeleted: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const needsReason = voucher.status !== "draft";
  const remove = useMutation({
    mutationFn: () => deleteVoucher(voucher.id, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: vouchersKey });
      onDeleted();
    },
  });
  return (
    <Modal label={t("voucherActions.deleteTitle", { number: voucher.number })} onClose={onClose}>
      <h2>{t("voucherActions.deleteTitle", { number: voucher.number })}</h2>
      <p>{t("voucherActions.deleteHelp")}</p>
      <label>
        {needsReason ? t("voucherActions.reason") : t("voucherActions.reasonOptional")}
        <textarea value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </label>
      {remove.error && (
        <p className="form-error" role="alert">
          {remove.error instanceof ApiError && remove.error.detail ? remove.error.detail : t("common.error")}
        </p>
      )}
      <div className="row-actions">
        <button
          type="button"
          className="danger"
          disabled={remove.isPending || (needsReason && !reason.trim())}
          onClick={() => remove.mutate()}
        >
          {t("voucherActions.confirmDelete")}
        </button>
        <button type="button" className="secondary" onClick={onClose}>
          {t("voucherActions.cancel")}
        </button>
      </div>
    </Modal>
  );
}
