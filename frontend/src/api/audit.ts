import { apiGet } from "./client";

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor_email: string;
  ip_address: string | null;
  action: "create" | "update" | "delete";
  object_type: string;
  object_id: string;
  object_repr: string;
  related_user: number | null;
  related_user_email: string | null;
  event: string;
  reason: string;
  changes: Record<string, [unknown, unknown]>;
}

export interface AuditFilters {
  user?: number;
  actor?: string;
  event?: string;
  from?: string;
  to?: string;
  limit?: number;
}

export function getAuditLog(filters: AuditFilters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const query = params.toString();
  return apiGet<AuditEvent[]>(`/audit/${query ? `?${query}` : ""}`);
}
