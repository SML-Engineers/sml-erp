import { apiGet, apiSend, apiUpload } from "./client";

/** Bank statement import (P2-15). */

export interface StatementTemplate {
  id: number;
  code: string;
  bank_name: string;
  file_kind: "excel" | "csv" | "pdf";
  date_format: string;
  date_column: string;
  description_column: string;
  reference_column: string;
  out_column: string;
  in_column: string;
  amount_column: string;
  negative_is_out: boolean;
  balance_column: string;
  checked: boolean;
  notes: string;
  is_active: boolean;
}

export interface StatementLine {
  line_no?: number;
  date: string;
  description: string;
  reference: string;
  money_out: string;
  money_in: string;
  balance: string | null;
  already?: boolean;
}

export interface Statement {
  id: number;
  account: { id: number; code: string; name: string };
  template: string;
  file_name: string;
  from_date: string;
  to_date: string;
  opening_balance: string | null;
  closing_balance: string | null;
  skipped: number;
  line_count: number;
  imported_by: string;
  imported_at: string;
  lines?: StatementLine[];
}

export interface Preview {
  opening: string | null;
  lines: StatementLine[];
  problems: string[];
}

export const statementsKey = ["bank-statements"];

export const listTemplates = () => apiGet<StatementTemplate[]>("/statement-templates/");
export const saveTemplate = (id: number | null, values: Partial<StatementTemplate>) =>
  id === null
    ? apiSend<StatementTemplate>("POST", "/statement-templates/", values)
    : apiSend<StatementTemplate>("PATCH", `/statement-templates/${id}/`, values);
export const listStatements = () => apiGet<Statement[]>("/bank-statements/");
export const getStatement = (id: number) => apiGet<Statement>(`/bank-statements/${id}/`);
export const deleteStatement = (id: number) => apiSend<null>("DELETE", `/bank-statements/${id}/`);

function statementForm(input: { account: string; template: string; opening: string; file: File }, preview: boolean) {
  const form = new FormData();
  form.append("account", input.account);
  form.append("template", input.template);
  if (input.opening) form.append("opening", input.opening);
  if (preview) form.append("preview", "1");
  form.append("file", input.file);
  return form;
}

type ImportInput = { account: string; template: string; opening: string; file: File };

export const previewStatement = (input: ImportInput) =>
  apiUpload<Preview>("/bank-statements/import/", statementForm(input, true), "POST");
export const importStatement = (input: ImportInput) =>
  apiUpload<Statement>("/bank-statements/import/", statementForm(input, false), "POST");
