import type { TFunction } from "i18next";

/** Who a document waits for and who last acted on it, from the server's approval engine
 * (owner, 16 Nov 2026: clear statuses such as "Waiting for Ruwan (Director)"). */
export interface StatusPeople {
  /** `people`: everyone who can act, when two or three can (testing T41: two Directors). */
  waiting: { person: string | null; people?: string[]; role: string } | null;
  last: { action: string; by: string } | null;
}

/** "Ruwan" from "Ruwan Jayasinghe": short enough for a list, clear in a small company. */
export function firstName(full: string): string {
  return full.trim().split(/\s+/)[0] ?? full;
}

/** The clear status of a document that goes through approval, or null when its own label
 * says it best (paid, cancelled…). `approvedStatus` is the status that means fully approved. */
export function approvalStatus(
  t: TFunction,
  doc: { status: string; created_by: string; people?: StatusPeople | null },
  approvedStatus: string,
): string | null {
  const { people } = doc;
  const last = people?.last;
  // Sent back to the maker: some documents go back to draft, vouchers to "returned".
  if ((doc.status === "returned" || doc.status === "draft") && last?.action === "return")
    return t("docStatus.returnedBy", { person: firstName(last.by) });
  if (doc.status === "draft") return t("docStatus.draftOf", { person: firstName(doc.created_by) });
  if (people?.waiting) {
    const { person, role } = people.waiting;
    const several = people.waiting.people ?? [];
    if (person) return t("docStatus.waitingFor", { person: firstName(person), role });
    if (several.length > 1) return t("docStatus.waitingForEither", { people: several.map(firstName).join(t("docStatus.or")), role });
    return t("docStatus.waitingForRole", { role });
  }
  if (!last) return null;
  if (doc.status === "rejected") return t("docStatus.rejectedBy", { person: firstName(last.by) });
  if (doc.status === approvedStatus && last.action === "approve") return t("docStatus.approvedBy", { person: firstName(last.by) });
  return null;
}
