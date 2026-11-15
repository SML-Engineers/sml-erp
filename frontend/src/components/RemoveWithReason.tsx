import { useState } from "react";
import { useTranslation } from "react-i18next";

/** A "Remove" button that first asks for the reason right there (owner, 15 Nov 2026: the
 * reason box used to be the one of the add form below, which nobody could guess). */
export default function RemoveWithReason({
  label,
  pending,
  onRemove,
}: {
  label: string;
  pending: boolean;
  onRemove: (reason: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open) {
    return (
      <button type="button" className="small secondary" onClick={() => setOpen(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="remove-with-reason">
      <label>
        {t("removeWithReason.reason")}
        <input value={reason} autoFocus onChange={(e) => setReason(e.target.value)} />
      </label>
      <button type="button" className="small danger" disabled={pending || !reason.trim()} onClick={() => onRemove(reason.trim())}>
        {label}
      </button>
      <button
        type="button"
        className="small secondary"
        onClick={() => {
          setOpen(false);
          setReason("");
        }}
      >
        {t("access.cancel")}
      </button>
    </span>
  );
}
