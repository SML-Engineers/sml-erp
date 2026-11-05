import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Employee master (P2B-01): kept by HR, seen by HR and the Director. */

export type EmploymentType = "permanent" | "probation" | "contract" | "casual" | "trainee";

export interface EmployeeRow {
  id: number;
  number: string;
  full_name: string;
  designation: string;
  division: string;
  section: string;
  employment_type: EmploymentType;
  employment_type_label: string;
  join_date: string;
  is_active: boolean;
  bank_check_pending: boolean;
}

export interface Employee extends EmployeeRow {
  name_with_initials: string;
  nic: string;
  date_of_birth: string | null;
  address: string;
  phone: string;
  email: string;
  epf_no: string;
  etf_no: string;
  grade: string;
  confirmation_date: string | null;
  leaving_date: string | null;
  leaving_reason: string;
  user: { id: number; name: string } | null;
  bank_name: string;
  bank_branch: string;
  account_name: string;
  account_number: string;
  bank_changed_at: string | null;
  bank_changed_by: string | null;
  bank_checked_at: string | null;
  bank_checked_by: string | null;
  created_by: string | null;
  created_at: string;
  can_edit: boolean;
  can_check_bank: boolean;
}

export interface EmployeeList {
  results: EmployeeRow[];
  can_add: boolean;
  types: { value: EmploymentType; label: string }[];
}

export interface EmployeeImportResult {
  errors: string[];
  added: number;
  updated: number;
  saved: boolean;
}

/** The fields HR types in; the server checks them all. */
export const EMPLOYEE_FIELDS = [
  "number",
  "full_name",
  "name_with_initials",
  "nic",
  "date_of_birth",
  "division",
  "section",
  "designation",
  "grade",
  "employment_type",
  "join_date",
  "confirmation_date",
  "epf_no",
  "etf_no",
  "phone",
  "email",
  "address",
] as const;
export const BANK_FIELDS = ["bank_name", "bank_branch", "account_name", "account_number"] as const;
export type EmployeeValues = Partial<Record<(typeof EMPLOYEE_FIELDS)[number] | (typeof BANK_FIELDS)[number], string>>;

export const employeesKey = ["employees"] as const;

export const listEmployees = (query: string) => apiGet<EmployeeList>(`/employees/${query ? `?${query}` : ""}`);
export const getEmployee = (id: number) => apiGet<Employee>(`/employees/${id}/`);
export const addEmployee = (values: EmployeeValues) => apiSend<Employee>("POST", "/employees/", values);
export const changeEmployee = (id: number, values: EmployeeValues, reason: string) =>
  apiSend<Employee>("PATCH", `/employees/${id}/`, { ...values, reason });
export const checkEmployeeBank = (id: number) => apiSend<Employee>("POST", `/employees/${id}/check-bank/`);
export const recordLeaving = (id: number, leaving_date: string, reason: string) =>
  apiSend<Employee>("POST", `/employees/${id}/leave/`, { leaving_date, reason });

export const employeeTemplateUrl = `${API_BASE}/employees/excel/?template=1`;
export const employeeExportUrl = `${API_BASE}/employees/excel/`;
export function importEmployees(file: File, dryRun: boolean, reason = "") {
  const form = new FormData();
  form.append("file", file);
  form.append("dry_run", dryRun ? "true" : "false");
  form.append("reason", reason);
  return apiUpload<EmployeeImportResult>("/employees/excel/", form, "POST");
}
