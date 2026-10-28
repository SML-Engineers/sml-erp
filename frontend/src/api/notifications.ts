import { apiGet, apiSend } from "./client";

export interface NotificationItem {
  id: number;
  event: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read: boolean;
}

export interface Bell {
  unread: number;
  items: NotificationItem[];
}

export interface Preference {
  event: string;
  label: string;
  in_app: boolean;
  email: boolean;
}

export const bellKey = ["notifications"];
export const preferencesKey = ["notifications", "preferences"];

export const getBell = () => apiGet<Bell>("/notifications/");
export const markRead = (ids?: number[]) =>
  apiSend<{ unread: number }>("POST", "/notifications/read/", ids ? { ids } : {});
export const getPreferences = () => apiGet<Preference[]>("/notifications/preferences/");
export const setPreference = (event: string, change: { in_app?: boolean; email?: boolean }) =>
  apiSend<Preference[]>("PUT", "/notifications/preferences/", { event, ...change });
