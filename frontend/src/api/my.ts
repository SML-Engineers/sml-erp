import { API_BASE, apiGet, apiSend } from "./client";

/** Self-service (P2B-11): the signed-in employee's own records. */

export interface LeaveApplication {
  id: number;
  employee: string;
  type: string;
  start: string;
  end: string;
  days: string;
  reason: string;
}

export interface MySummary {
  linked: boolean;
  detail?: string;
  employee?: { number: string; name: string; division: string; section: string; designation: string; category: string; epf_no: string };
  payslips?: {
    id: number;
    month: string;
    gross: string;
    net: string;
    epf_employee: string;
    epf_employer: string;
    etf: string;
    apit: string;
  }[];
  tax_year?: number;
  leave_year?: number;
  balances?: { code: string; name: string; granted: string; taken: string; pending: string; left: string }[];
  leave?: {
    id: number;
    type: string;
    start: string;
    end: string;
    days: string;
    status: string;
    status_label: string;
    note: string;
    can_withdraw: boolean;
  }[];
  leave_types?: { code: string; name: string }[];
  attendance?: { from: string; days: { date: string; time_in: string; time_out: string; leave: string; late: number }[] };
  to_approve: LeaveApplication[];
}

export const myKey = ["my"] as const;
export const getMy = () => apiGet<MySummary>("/my/");
export const myPayslipUrl = (id: number) => `${API_BASE}/my/payslips/${id}/`;
export const myCertificateUrl = (year: number) => `${API_BASE}/my/apit-certificate/?year=${year}`;
export const applyForLeave = (values: { leave_type: string; start: string; end: string; half_day: boolean; reason: string }) =>
  apiSend<MySummary>("POST", "/my/leave/", values);
export const withdrawLeave = (id: number) => apiSend<MySummary>("POST", `/my/leave/${id}/withdraw/`, {});
export const decideLeave = (id: number, action: "approve" | "reject", reason: string) =>
  apiSend<MySummary>("POST", `/my/team-leave/${id}/${action}/`, { reason });
