import { apiGet, apiPost } from "./client";

/** The top-bar notice (owner, 21 Nov 2026): English with Sinhala below it, for everyone. */
export interface Notice {
  show: boolean;
  text_en: string;
  text_si: string;
}

export interface NoticeChange extends Notice {
  id: number;
  reason: string;
  requested_by: string;
  requested_at: string;
  status: "waiting" | "approved" | "refused" | "withdrawn";
  status_label: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_reason: string;
  can_decide: boolean;
  mine?: boolean;
}

export interface NoticeAdmin {
  current: Notice;
  defaults: { text_en: string; text_si: string };
  in_force: { text_en: string; text_si: string } | null;
  waiting: NoticeChange | null;
  history: NoticeChange[];
}

export const noticeKey = ["notice"] as const;
export const noticeAdminKey = ["notice-admin"] as const;

export const getNotice = () => apiGet<Notice>("/notice/");
export const getNoticeAdmin = () => apiGet<NoticeAdmin>("/access/notice/");
export const askNoticeChange = (change: Notice & { reason: string }) => apiPost<NoticeChange>("/access/notice/", change);
export const approveNotice = (id: number) => apiPost<NoticeChange>(`/access/notice/${id}/approve/`);
export const refuseNotice = (id: number, reason: string) => apiPost<NoticeChange>(`/access/notice/${id}/refuse/`, { reason });
export const withdrawNotice = (id: number) => apiPost<NoticeChange>(`/access/notice/${id}/withdraw/`);
