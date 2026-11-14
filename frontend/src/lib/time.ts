/**
 * Dates and times as the factory reads them (owner, 12 Nov 2026): always Sri Lanka time and
 * always the 24-hour clock, whatever the PC's own time zone or clock setting. The owner's PC
 * is in Australia, and staff abroad would otherwise see times hours ahead of the factory.
 */
export const FACTORY_TIME_ZONE = "Asia/Colombo";

function parts(when: Date): Record<string, string> {
  const out: Record<string, string> = {};
  const format = new Intl.DateTimeFormat("en-GB", {
    timeZone: FACTORY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  for (const p of format.formatToParts(when)) out[p.type] = p.value;
  return out;
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const when = value instanceof Date ? value : new Date(value);
  return Number.isNaN(when.getTime()) ? null : when;
}

/** "2026-11-12 21:00" in Sri Lanka time; "" for no value. */
export function formatDateTime(value: string | Date | null | undefined): string {
  const when = toDate(value);
  if (!when) return "";
  const p = parts(when);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

/** "2026-11-12": the Sri Lanka date of a moment. */
export function formatDate(value: string | Date | null | undefined): string {
  const when = toDate(value);
  if (!when) return "";
  const p = parts(when);
  return `${p.year}-${p.month}-${p.day}`;
}

/** "21:00": the Sri Lanka time of a moment. */
export function formatTime(value: string | Date | null | undefined): string {
  const when = toDate(value);
  if (!when) return "";
  const p = parts(when);
  return `${p.hour}:${p.minute}`;
}

/** Today's date at the factory, "YYYY-MM-DD" (a new document's default date). */
export function factoryToday(): string {
  return formatDate(new Date());
}

/** A typed time made into "HH:MM" where it can be: "830" -> "08:30", "8:5" -> "08:05". */
export function normaliseTime(text: string): string {
  const value = text.trim();
  const digits = /^(\d{1,2})(\d{2})$/.exec(value) ?? /^(\d{1,2})[:.](\d{1,2})$/.exec(value);
  if (!digits) return value;
  const [hours, minutes] = [Number(digits[1]), Number(digits[2])];
  if (hours > 23 || minutes > 59) return value;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}
