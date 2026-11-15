import { apiGet, apiPost } from "./client";

/** Machine time (P3-24): jobs started and finished live at the machine. */
export interface MachineJob {
  id: number;
  machine: string;
  section: string;
  kind: "job" | "moulding";
  job: string | null;
  operation: number | null;
  operation_name: string | null;
  order: string | null;
  item: string | null;
  mould: string | null;
  operator: string | null;
  drawing_no: string;
  description: string;
  notes: string;
  started_at: string;
  started_by: string;
  ended_at: string | null;
  ended_by: string | null;
  minutes: number;
  hours: string;
  completed: string | null;
  rejected: string | null;
  start_counter: number | null;
  end_counter: number | null;
  second_allowed_by: string | null;
  second_reason: string;
}

export interface BoardMachine {
  code: string;
  name: string;
  section: string;
  section_type: "moulding" | "machining";
  status: "running" | "idle" | "maintenance";
  jobs: MachineJob[];
}

export interface MachineBoard {
  now: string;
  machines: BoardMachine[];
  can_enter: boolean;
  can_allow_second: boolean;
}

export interface JobChoice {
  number: string;
  item: string;
  description: string;
  drawing_no: string;
  operations: { seq: number; name: string; card: string; here: boolean }[];
}

export interface StartOptions {
  kind: "job" | "moulding";
  jobs: JobChoice[];
  orders: { number: string; item: string; mould: string }[];
}

export const machineJobsKey = ["machine-jobs"];

export const getBoard = () => apiGet<MachineBoard>("/machine-jobs/board/");
export const getRecent = () => apiGet<{ results: MachineJob[] }>("/machine-jobs/");
export const getStartOptions = (machine: string) => apiGet<StartOptions>(`/machine-jobs/options/?machine=${encodeURIComponent(machine)}`);
export const startJob = (values: Record<string, string>) => apiPost<MachineJob>("/machine-jobs/", values);
export const finishJob = (id: number, values: Record<string, string>) => apiPost<MachineJob>(`/machine-jobs/${id}/finish/`, values);

/** "2 h 05 min" (or "45 min") from whole minutes. */
export function duration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`;
}
