import type { TFunction } from "i18next";

import { firstName } from "./docStatus";
import { formatDateTime } from "./time";

/** "Cancelled by Dilini Wijesekara on 2026-11-16 14:52: wrong quantity" (owner, 16 Nov 2026);
 * documents cancelled before who was kept say only the reason. */
export function cancelledNote(t: TFunction, doc: { cancel_reason: string; cancelled_by?: string | null; cancelled_at?: string | null }) {
  if (!doc.cancelled_by) return t("cancelled.because", { reason: doc.cancel_reason });
  return t("cancelled.byOn", { person: doc.cancelled_by, at: formatDateTime(doc.cancelled_at), reason: doc.cancel_reason });
}

/** The list's status: "Cancelled by Dilini" when we know who. */
export function cancelledStatus(t: TFunction, cancelledBy: string | null | undefined, plain: string) {
  return cancelledBy ? t("cancelled.by", { person: firstName(cancelledBy) }) : plain;
}
