/** What the signed-in user may do (spec 1.2), as sent by the server in /auth/me/.
 *
 * Screens use this only to decide what to show. The server checks every request itself,
 * so hiding a button is a convenience, never the protection (CLAUDE.md rule 8).
 */
export type Level = "view" | "enter" | "approve" | "manage";

export interface Access {
  areas: Record<string, Level[]>;
  actions: string[];
  divisions: "all" | string[];
}

export function can(access: Access | undefined, area: string, level: Level = "view"): boolean {
  return access?.areas[area]?.includes(level) ?? false;
}

export function canDo(access: Access | undefined, action: string): boolean {
  return access?.actions.includes(action) ?? false;
}

export function worksIn(access: Access | undefined, divisionCode: string): boolean {
  if (!access) return false;
  return access.divisions === "all" || access.divisions.includes(divisionCode);
}
