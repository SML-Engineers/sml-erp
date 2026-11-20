import { apiGet, apiPost, apiPostFile } from "./client";

/** Settings → Printed documents: where each part of a printed document goes (owner, 13 Nov 2026). */

export type Align = "left" | "center" | "right";

/** One block on the page, in millimetres from the top-left corner inside the margins. */
export interface LayoutBlock {
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
  size: number;
  align: Align;
  hidden?: boolean;
  /** Only for the owner's own text blocks (key "text-…"). */
  text?: string;
}

export interface Layout {
  blocks: LayoutBlock[];
}

export interface TemplateSummary {
  document: string;
  label: string;
  version: number | null;
}

export interface TemplatePage {
  document: string;
  label: string;
  page: { width: number; height: number };
  blocks: { key: string; label: string; may_hide: boolean }[];
  table: string;
  standard: Layout;
  layout: Layout;
  version: number | null;
  history: { version: number; note: string; by: string; at: string }[];
  can_edit: boolean;
}

export const templatesKey = ["print-templates"] as const;
export const templateKey = (document: string) => ["print-templates", document] as const;

export function listTemplates() {
  return apiGet<{ documents: TemplateSummary[]; can_edit: boolean }>("/print-templates/");
}

export function getTemplate(document: string) {
  return apiGet<TemplatePage>(`/print-templates/${document}/`);
}

export function saveTemplate(document: string, layout: Layout, note: string) {
  return apiPost<TemplatePage>(`/print-templates/${document}/`, { layout, note });
}

export function resetTemplate(document: string) {
  return apiPost<TemplatePage>(`/print-templates/${document}/`, { reset: true });
}

export function restoreTemplate(document: string, version: number) {
  return apiPost<TemplatePage>(`/print-templates/${document}/`, { restore: version });
}

/** The latest document printed with this (unsaved) layout. */
export function previewTemplate(document: string, layout: Layout) {
  return apiPostFile(`/print-templates/${document}/preview/`, { layout });
}
