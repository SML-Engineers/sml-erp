import type { Level } from "./access";
import { apiGet, apiPost, apiSend } from "./client";

export interface RoleSummary {
  code: string;
  name: string;
  assigned_at: string;
  reason: string;
  conflict_warning: string;
}

export interface UserRecord {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  two_factor_required: boolean;
  two_factor_enabled: boolean;
  must_change_password: boolean;
  all_divisions: boolean;
  divisions: string[];
  roles: RoleSummary[];
  last_login: string | null;
  date_joined: string;
}

export interface Role {
  id: number;
  code: string;
  name: string;
  description: string;
  is_standard: boolean;
  is_active: boolean;
}

export interface Division {
  id: number;
  code: string;
  name: string;
  division_type?: "production" | "shared";
}

export interface OverrideInfo {
  id: number;
  effect: "grant" | "remove";
  status: OverrideStatus;
  ends_on: string | null;
}

export type OverrideStatus = "active" | "pending" | "revoked" | "expired";

export interface AccessGrid {
  user: UserRecord;
  areas: {
    area: string;
    label: string;
    levels: { level: Level; from_roles: boolean; override: OverrideInfo | null; effective: boolean }[];
  }[];
  actions: {
    action: string;
    label: string;
    from_roles: boolean;
    override: OverrideInfo | null;
    effective: boolean;
  }[];
}

export interface Override {
  id: number;
  area: string;
  level: string;
  action: string;
  effect: "grant" | "remove";
  reason: string;
  ends_on: string | null;
  is_sensitive: boolean;
  status: OverrideStatus;
  created_by: string;
  created_at: string;
  confirmed_by: string | null;
  revoked_by: string | null;
  revoke_reason: string;
}

export interface ReviewRow {
  user_id: number;
  email: string;
  full_name: string;
  roles: string[];
  conflicts: string[];
  overrides: { id: number; effect: string; target: string; status: string; ends_on: string | null }[];
  pending_sensitive: number;
  sensitive_access: string[];
  last_login: string | null;
  review: { outcome: string; reviewed_at: string; reviewed_by: string; note: string } | null;
}

export interface OverrideRequest {
  effect: "grant" | "remove";
  area?: string;
  level?: string;
  action?: string;
  reason: string;
  ends_on?: string | null;
}

export const listUsers = () => apiGet<UserRecord[]>("/users/");
export const createUser = (email: string, full_name: string) =>
  apiPost<UserRecord & { temporary_password: string }>("/users/", { email, full_name });
export const listRoles = () => apiGet<Role[]>("/roles/");
export const listDivisions = () => apiGet<Division[]>("/divisions/");
export const getAccessGrid = (id: number) => apiGet<AccessGrid>(`/users/${id}/access/`);
export const listOverrides = (id: number) => apiGet<Override[]>(`/users/${id}/overrides/`);
export const createOverride = (id: number, body: OverrideRequest) =>
  apiPost<Override>(`/users/${id}/overrides/`, body);
export const confirmOverride = (id: number) => apiPost<Override>(`/overrides/${id}/confirm/`);
export const revokeOverride = (id: number, reason: string) =>
  apiPost<Override>(`/overrides/${id}/revoke/`, { reason });
export const setUserRoles = (id: number, roles: string[], reason: string) =>
  apiSend<{ user: UserRecord; warnings: string[] }>("PUT", `/users/${id}/roles/`, {
    roles,
    reason,
  });
export const setUserScope = (id: number, all_divisions: boolean, divisions: string[]) =>
  apiSend<UserRecord>("PUT", `/users/${id}/scope/`, { all_divisions, divisions });
export const resetOverrides = (id: number, reason: string) =>
  apiPost<{ ended: number }>(`/users/${id}/reset-overrides/`, { reason });
export const copyAccess = (id: number, source_user: number, reason: string) =>
  apiPost<{ user: UserRecord; warnings: string[] }>(`/users/${id}/copy-access/`, {
    source_user,
    reason,
  });
export const deactivateUser = (id: number, reason: string) =>
  apiPost<UserRecord>(`/users/${id}/deactivate/`, { reason });
export const reactivateUser = (id: number) =>
  apiSend<UserRecord>("PATCH", `/users/${id}/`, { is_active: true });
export const getReview = () => apiGet<{ period: string; rows: ReviewRow[] }>("/access-review/");
export const recordReview = (user: number, outcome: "confirmed" | "changed", note = "") =>
  apiPost<{ period: string; rows: ReviewRow[] }>("/access-review/", { user, outcome, note });

// --- Password resets: the Admin asks, the Director approves, the Admin makes the password ---

export interface PasswordResetRow {
  id: number;
  status: "waiting" | "approved" | "refused" | "done" | "lapsed";
  with_authenticator: boolean;
  reason: string;
  requested_by: string;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_reason: string;
  issued_at: string | null;
  can_decide: boolean;
  can_issue: boolean;
}

export const listPasswordResets = (userId: number) =>
  apiGet<{ can_request: boolean; resets: PasswordResetRow[] }>(`/users/${userId}/password-resets/`);
export const requestPasswordReset = (userId: number, reason: string, withAuthenticator: boolean) =>
  apiPost<PasswordResetRow>(`/users/${userId}/password-resets/`, { reason, with_authenticator: withAuthenticator });
export const decidePasswordReset = (id: number, approve: boolean, reason: string) =>
  apiPost<PasswordResetRow>(`/password-resets/${id}/${approve ? "approve" : "refuse"}/`, { reason });
export const issuePasswordReset = (id: number) =>
  apiPost<PasswordResetRow & { temporary_password: string }>(`/password-resets/${id}/issue/`);
