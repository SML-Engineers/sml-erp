import { apiGet, apiSend } from "./client";

export type Security = "starttls" | "ssl" | "none";

export interface MailAccount {
  from_name: string;
  from_address: string;
  reply_to: string;
  copy_to: string;
  host: string;
  port: number;
  security: Security;
  username: string;
  has_password: boolean;
  is_ready: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string;
}

export type MailAccountChange = Partial<Omit<MailAccount, "has_password" | "is_ready" | "last_test_at" | "last_test_ok" | "last_test_error">> & {
  password?: string;
  clear_password?: boolean;
  reason?: string;
};

export interface EmailTemplate {
  kind: string;
  label: string;
  subject: string;
  body: string;
  placeholders: { name: string; label: string }[];
  updated_at: string | null;
}

/** The filled-in message a document module offers before sending (document_email.draft). */
export interface EmailDraft {
  from: string;
  ready: boolean;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
}

/** What the person finally sends, after editing. */
export interface EmailToSend {
  to: string[];
  cc: string[];
  subject: string;
  body: string;
}

export interface SentEmail {
  id: number;
  document_type: string;
  document_id: number | null;
  document_label: string;
  from: string;
  to: string;
  cc: string;
  subject: string;
  body: string;
  attachment_name: string;
  attachment_sha256: string;
  status: "sent" | "failed";
  error: string;
  sent_by: string;
  sent_at: string;
}

const BASE = "/settings/document-email/";
export const mailAccountKey = ["settings", "document-email"];
export const templatesKey = ["settings", "document-email", "templates"];

export const getMailAccount = () => apiGet<MailAccount>(BASE);
export const updateMailAccount = (change: MailAccountChange) => apiSend<MailAccount>("PUT", BASE, change);
export const sendTestEmail = (to: string) =>
  apiSend<MailAccount & { test_ok: boolean; test_error: string }>("POST", `${BASE}test/`, { to });
export const listTemplates = () => apiGet<EmailTemplate[]>(`${BASE}templates/`);
export const saveTemplate = (kind: string, subject: string, body: string, reason = "") =>
  apiSend<EmailTemplate>("PUT", `${BASE}templates/${kind}/`, { subject, body, reason });
export const previewTemplate = (kind: string, subject: string, body: string) =>
  apiSend<{ subject: string; body: string }>("POST", `${BASE}templates/${kind}/preview/`, { subject, body });
export const listSentEmails = () => apiGet<SentEmail[]>("/sent-emails/");

/** "a@b.lk; c@d.lk" -> ["a@b.lk", "c@d.lk"] */
export function splitAddresses(text: string): string[] {
  return text
    .split(/[;,\n]/)
    .map((part) => part.trim())
    .filter(Boolean);
}
