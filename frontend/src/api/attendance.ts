import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Attendance from the Excel sheet (P2B-04). */

export interface AttendanceRow {
  employee: { id: number; number: string; name: string };
  working_days: number;
  days_worked: number;
  hours_worked: string;
  late_days: number;
  late: string;
  early: string;
  leave_days: string;
  absent_days: number;
}

export interface AttendanceMonth {
  month: string;
  division: string;
  divisions: string[];
  confirmed: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  can_edit: boolean;
  month_ended: boolean;
  rows: AttendanceRow[];
}

export interface AttendanceDays {
  month: string;
  days: {
    date: string;
    shift: string;
    time_in: string;
    time_out: string;
    leave: string;
    worked: string;
    late: number;
    early: number;
    remarks: string;
  }[];
}

export interface AttendanceImportResult {
  rows: number;
  employees: number;
  months: string[];
  leave_days: number;
  errors: string[];
  saved: boolean;
}

export const attendanceKey = ["attendance"] as const;

export const getAttendance = (query: string) => apiGet<AttendanceMonth>(`/attendance/${query ? `?${query}` : ""}`);
export const getAttendanceDays = (employeeId: number, month: string) =>
  apiGet<AttendanceDays>(`/employees/${employeeId}/attendance/?month=${month}`);
export const attendanceTemplateUrl = `${API_BASE}/attendance/template/`;
export function importAttendance(file: File, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("dry_run", dryRun ? "true" : "false");
  return apiUpload<AttendanceImportResult>("/attendance/import/", form, "POST");
}
export const confirmAttendance = (division: string, month: string) =>
  apiSend<{ ok: boolean }>("POST", "/attendance/confirm/", { division, month });
export const reopenAttendance = (division: string, month: string, reason: string) =>
  apiSend<{ ok: boolean }>("POST", "/attendance/reopen/", { division, month, reason });
