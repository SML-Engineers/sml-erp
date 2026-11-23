import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** "Are you sure?" before critical actions (owner, testing T49, 22 Nov 2026): delete, submit,
 * approve, reject, send back, cancel, accept, post, issue, mark sent and pay. The question
 * names the document and, where there is one, the amount. Cancel has the focus, so pressing
 * Enter by mistake does nothing; Esc also cancels. */
export interface ConfirmRequest {
  /** The question, e.g. "Pay LKR 315,000.00 to Polymer Resins Lanka (Pvt) Ltd on voucher IM261121001?" */
  question: string;
  /** The button that goes ahead, e.g. "Pay". */
  yes: string;
  /** A line under the question, e.g. "This cannot be undone." */
  detail?: string;
  /** Red Yes button, for deleting, rejecting and cancelling. */
  danger?: boolean;
}

type Ask = (request: ConfirmRequest) => Promise<boolean>;

const ConfirmContext = createContext<Ask | null>(null);

/** Ask "Are you sure?"; resolves true only when the person clicks the Yes button. */
export function useConfirm(): Ask {
  const ask = useContext(ConfirmContext);
  if (!ask) throw new Error("useConfirm needs a ConfirmProvider");
  return ask;
}

/** Wraps the app once. `autoYes` is only for tests of other behaviour: it answers yes
 * without showing anything. The confirmation tests use the real dialog. */
export function ConfirmProvider({ children, autoYes = false }: { children: ReactNode; autoYes?: boolean }) {
  const [open, setOpen] = useState<(ConfirmRequest & { resolve: (yes: boolean) => void }) | null>(null);
  const ask = useCallback<Ask>(
    (request) => (autoYes ? Promise.resolve(true) : new Promise<boolean>((resolve) => setOpen({ ...request, resolve }))),
    [autoYes],
  );
  const answer = (yes: boolean) => {
    open?.resolve(yes);
    setOpen(null);
  };
  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {open && <Dialog request={open} answer={answer} />}
    </ConfirmContext.Provider>
  );
}

function Dialog({ request, answer }: { request: ConfirmRequest; answer: (yes: boolean) => void }) {
  const { t } = useTranslation();
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") answer(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [answer]);
  return (
    <div className="confirm-backdrop" onClick={() => answer(false)}>
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-question"
        aria-describedby={request.detail ? "confirm-detail" : undefined}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-question">{request.question}</h2>
        {request.detail && <p id="confirm-detail">{request.detail}</p>}
        <div className="row-actions">
          <button type="button" className="secondary" ref={cancel} onClick={() => answer(false)}>
            {t("confirm.no")}
          </button>
          <button type="button" className={request.danger ? "danger" : undefined} onClick={() => answer(true)}>
            {request.yes}
          </button>
        </div>
      </div>
    </div>
  );
}
