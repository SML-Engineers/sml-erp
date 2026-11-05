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
  reason: string;
  created_by: string | null;
  created_at: string;
  can_withdraw: boolean;
}

export interface EmployeePay {
  on: string;
  current: {
    component: string;
    component_name: string;
    kind: ComponentKind;
    epf_liable: boolean;
    apit_taxable: boolean;
    amount: string;
    since: string;
  }[];
  totals: { earnings: string; deductions: string; net: string; epf_earnings: string; apit_earnings: string };
  upcoming: PayRate[];
  history: PayRate[];
  components: PayComponent[];
  can_edit: boolean;
}

export type ComponentValues = Partial<Omit<PayComponent, "id">>;

export const payComponentsKey = ["pay-components"] as const;
export const employeePayKey = (id: number) => ["employees", id, "pay"] as const;

export const listPayComponents = () => apiGet<PayComponentList>("/pay-components/");
export const addPayComponent = (values: ComponentValues) => apiSend<PayComponent>("POST", "/pay-components/", values);
export const changePayComponent = (id: number, values: ComponentValues, reason: string) =>
  apiSend<PayComponent>("PATCH", `/pay-components/${id}/`, { ...values, reason });

export const getEmployeePay = (id: number) => apiGet<EmployeePay>(`/employees/${id}/pay/`);
export const addPayAmount = (id: number, entry: { component: string; month: string; amount: string; reason: string }) =>
  apiSend<EmployeePay>("POST", `/employees/${id}/pay/`, entry);
export const withdrawPayAmount = (id: number, rateId: number, reason: string) =>
  apiSend<EmployeePay>("DELETE", `/employees/${id}/pay/${rateId}/`, { reason });
