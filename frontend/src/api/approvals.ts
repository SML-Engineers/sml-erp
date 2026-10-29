import { apiGet, apiSend } from "./client";

export interface ApprovalDocumentType {
  code: string;
  name: string;
  min_approvals: number;
  final_role: string;
  subtype_label: string;
}

export interface ApprovalRule {
  id: number;
  document_type: string;
  level: number;
  role: { code: string; name: string };
  min_amount: string | null;
  max_amount: string | null;
  division: string | null;
  subtype: string;
  is_active: boolean;
  created_at: string;
}

export interface ApprovalMatrix {
  document_types: ApprovalDocumentType[];
  rules: ApprovalRule[];
  roles: { code: string; name: string }[];
}

export interface RuleChange {
  document_type: string;
  level: number;
  role: string;
  min_amount?: string | null;
  max_amount?: string | null;
  division?: string | null;
  subtype?: string;
  reason?: string;
}

export interface RouteStep {
  level: number;
  role: string;
  role_name: string;
}

export const matrixKey = ["settings", "approval-matrix"];

export const getMatrix = () => apiGet<ApprovalMatrix>("/settings/approval-matrix/");
export const addRule = (change: RuleChange) =>
  apiSend<ApprovalMatrix>("POST", "/settings/approval-matrix/", change);
export const switchOffRule = (id: number, reason: string) =>
  apiSend<ApprovalMatrix>("POST", `/settings/approval-matrix/${id}/switch-off/`, { reason });
export function previewRoute(params: { document_type: string; amount?: string; division?: string; subtype?: string }) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  return apiGet<RouteStep[]>(`/settings/approval-matrix/route/?${query.toString()}`);
}

// --- Reminders (P1-09) -------------------------------------------------------------------

export interface ReminderSetting {
  document_type: string;
  name: string;
  enabled: boolean;
  after_days: number;
}

export const remindersKey = ["settings", "approval-reminders"];
export const getReminders = () => apiGet<ReminderSetting[]>("/settings/approval-reminders/");
export const setReminder = (change: { document_type: string; enabled: boolean; after_days: number; reason: string }) =>
  apiSend<ReminderSetting[]>("PUT", "/settings/approval-reminders/", change);
