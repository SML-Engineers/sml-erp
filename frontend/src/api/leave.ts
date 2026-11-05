import { apiGet, apiSend } from "./client";

/** Holidays and leave (P2B-03). */

export interface Holiday {
  id: number;
  date: string;
  name: string;
  kind: string;
  kind_label: string;
  can_remove: boolean;
}

export interface HolidayList {
  year: number;
  results: Holiday[];
  kinds: { value: string; label: string }[];
  can_manage: boolean;
}

export type LeaveRule = "annual_soe" | "casual_soe" | "fixed" | "unlimited";

export interface LeaveType {
  id: number;
  code: string;
  name: string;
  rule: LeaveRule;
  rule_label: string;
  days: string;
  paid: boolean;
  carry_forward_max: string;
  is_active: boolean;
}

export interface LeaveTypeList {
  results: LeaveType[];
  rules: { value: LeaveRule; label: string }[];
  can_manage: boolean;
}

export type LeaveStatus = "applied" | "approved" | "rejected" | "cancelled";

export interface LeaveRecord {
  id: number;
  employee: { id: number; number: string; name: string };
  leave_type: string;
  leave_type_name: string;
  start: string;
  end: string;
  half_day: boolean;
  days: string;
  reason: string;
  status: LeaveStatus;
  source: "hr" | "applied" | "attendance";
  created_by: string | null;
  decided_by: string | null;
  decision_note: string;
  can_decide: boolean;
  can_cancel: boolean;
}

export interface LeaveList {
  year: number;
  results: LeaveRecord[];
  types: LeaveType[];
  can_record: boolean;
}

export interface EmployeeLeave {
  year: number;
  balances: { leave_type: string; name: string; granted: string; taken: string; pending: string; available: string }[];
  grants: { id: number; leave_type: string; kind: string; days: string; reason: string; created_by: string | null; created_at: string }[];
  leave: LeaveRecord[];
  can_adjust: boolean;
}

export interface LeaveEntry {
  employee: number;
  leave_type: string;
  start: string;
  end: string;
  half_day: boolean;
  reason: string;
}

export const holidaysKey = ["holidays"] as const;
export const leaveTypesKey = ["leave-types"] as const;
export const leaveKey = ["leave"] as const;

export const listHolidays = (year: number) => apiGet<HolidayList>(`/holidays/?year=${year}`);
export const addHoliday = (values: { date: string; name: string; kind: string }) =>
  apiSend<Holiday>("POST", "/holidays/", values);
export const removeHoliday = (id: number, reason: string) => apiSend<null>("DELETE", `/holidays/${id}/`, { reason });

export const listLeaveTypes = () => apiGet<LeaveTypeList>("/leave-types/");
export const addLeaveType = (values: Partial<LeaveType>) => apiSend<LeaveType>("POST", "/leave-types/", values);
export const changeLeaveType = (id: number, values: Partial<LeaveType>, reason: string) =>
  apiSend<LeaveType>("PATCH", `/leave-types/${id}/`, { ...values, reason });

export const listLeave = (query: string) => apiGet<LeaveList>(`/leave/?${query}`);
export const recordLeave = (entry: LeaveEntry) => apiSend<LeaveRecord>("POST", "/leave/", entry);
export const leaveAction = (id: number, action: "approve" | "reject" | "cancel", note: string) =>
  apiSend<LeaveRecord>("POST", `/leave/${id}/${action}/`, { note });
export const grantLeaveYear = (year: number) =>
  apiSend<{ employees: number; grants: number }>("POST", "/leave/grant/", { year });

export const getEmployeeLeave = (id: number, year: number) =>
  apiGet<EmployeeLeave>(`/employees/${id}/leave/balances/?year=${year}`);
export const adjustLeave = (id: number, entry: { leave_type: string; year: number; days: string; reason: string }) =>
  apiSend<EmployeeLeave>("POST", `/employees/${id}/leave/balances/`, entry);
