import { apiGet, apiSend } from "./client";

/** Pay structure (P2B-02): pay components and each employee's dated amounts. */

export type ComponentKind = "earning" | "deduction";
export type ComponentBasis = "fixed" | "variable";

export interface PayComponent {
  id: number;
  code: string;
  name: string;
  kind: ComponentKind;
  basis: ComponentBasis;
  epf_liable: boolean;
  apit_taxable: boolean;
  /** An allowance: at most four per employee (P2B-17). */
  is_allowance: boolean;
  sort_order: number;
  is_active: boolean;
}

export interface PayComponentList {
  results: PayComponent[];
  can_manage: boolean;
}

export interface PayRate {
  id: number;
  component: string;
  component_name: string;
  kind: ComponentKind;
  effective_from: string; // "YYYY-MM"
  amount: string;
  epf_liable: boolean | null;
  apit_taxable: boolean | null;
  reason: string;
  created_by: string | null;
  created_at: string;
}

/** An employee's own settings (P2B-17); null fields mean the default. */
export interface PaySettings {
  normal_day_minutes: string | null;
  grace_minutes: string | null;
  rate_working_day: string | null;
  rate_sunday: string | null;
  rate_holiday: string | null;
  annual_leave_days: string | null;
  casual_leave_days: string | null;
  apit: "primary" | "secondary" | null;
}

export const SETTING_FIELDS = [
  "normal_day_minutes",
  "grace_minutes",
  "rate_working_day",
  "rate_sunday",
  "rate_holiday",
  "annual_leave_days",
  "casual_leave_days",
] as const;

export type ChangeStatus = "draft" | "awaiting" | "approved" | "rejected" | "withdrawn";

export interface PayChangeLine {
  component: string;
  component_name: string;
  kind: ComponentKind;
  amount: string;
  epf_liable: boolean | null;
  apit_taxable: boolean | null;
}

/** A new employee's pay settings or a change, approved by the Director (P2B-17). */
export interface PayChange {
  id: number;
  effective_from: string;
  is_new_employee: boolean;
  reason: string;
  status: ChangeStatus;
  status_label: string;
  returned: boolean;
  lines: PayChangeLine[];
  settings: PaySettings | null;
  created_by: string | null;
  created_at: string;
  approved_at: string | null;
  history: { action: string; user: string | null; reason: string; at: string }[];
  can_edit: boolean;
  can_submit: boolean;
  can_withdraw: boolean;
  can_approve: boolean;
}

export interface ChangeValues {
  effective_from: string;
  reason: string;
  lines: { component: string; amount: string; epf_liable: boolean | null; apit_taxable: boolean | null }[];
  settings: Record<string, string> | null;
}

export interface EmployeePay {
  on: string;
  current: {
    component: string;
    component_name: string;
    kind: ComponentKind;
    epf_liable: boolean;
    apit_taxable: boolean;
    own_marks: boolean;
    amount: string;
    since: string;
  }[];
  totals: { earnings: string; deductions: string; net: string; epf_earnings: string; apit_earnings: string };
  upcoming: PayRate[];
  history: PayRate[];
  components: PayComponent[];
  settings: PaySettings | null;
  settings_since: string | null;
  defaults: PaySettings;
  changes: PayChange[];
  next_month: string;
  can_prepare: boolean;
}

export type ComponentValues = Partial<Omit<PayComponent, "id">>;

export const payComponentsKey = ["pay-components"] as const;
export const employeePayKey = (id: number) => ["employees", id, "pay"] as const;

export const listPayComponents = () => apiGet<PayComponentList>("/pay-components/");
export const addPayComponent = (values: ComponentValues) => apiSend<PayComponent>("POST", "/pay-components/", values);
export const changePayComponent = (id: number, values: ComponentValues, reason: string) =>
  apiSend<PayComponent>("PATCH", `/pay-components/${id}/`, { ...values, reason });

export const getEmployeePay = (id: number) => apiGet<EmployeePay>(`/employees/${id}/pay/`);
export const preparePayChange = (id: number, values: ChangeValues) =>
  apiSend<EmployeePay>("POST", `/employees/${id}/pay-changes/`, values);
export const editPayChange = (changeId: number, values: ChangeValues) =>
  apiSend<EmployeePay>("PUT", `/pay-changes/${changeId}/`, values);
export type ChangeAction = "submit" | "approve" | "return" | "reject" | "withdraw";
export const actOnPayChange = (changeId: number, action: ChangeAction, reason = "") =>
  apiSend<EmployeePay>("POST", `/pay-changes/${changeId}/${action}/`, { reason });
