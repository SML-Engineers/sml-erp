import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import type { Me } from "../api/auth";
import type { ReportValues, ShiftReport } from "../api/shiftReports";

/** P3-21: shift reports entered without Wi-Fi. A save that cannot reach the server is kept on
 * the phone (browser storage) with the version of the report it was made on, and sent when the
 * connection returns; the server refuses it if the report was saved elsewhere since, so the
 * supervisor chooses and nothing is overwritten silently. The last copy of each open report is
 * kept too, so the page still opens without a connection. */

export interface PendingSave {
  values: ReportValues;
  /** The report's version the values were made on. */
  base: string;
  savedAt: string;
}

const PENDING = "sml-offline-report-";
const COPY = "sml-report-copy-";

function read<T>(key: string): T | null {
  try {
    const text = window.localStorage.getItem(key);
    return text ? (JSON.parse(text) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): boolean {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function remove(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // nothing kept
  }
}

export const readPending = (id: number) => read<PendingSave>(PENDING + id);
export const writePending = (id: number, pending: PendingSave) => write(PENDING + id, pending);
export const clearPending = (id: number) => remove(PENDING + id);

export function readCopy(id: number): { report: ShiftReport; at: string } | null {
  return read<{ report: ShiftReport; at: string }>(COPY + id);
}

export function keepCopy(report: ShiftReport) {
  if (report.editable) write(COPY + report.id, { report, at: new Date().toISOString() });
  else remove(COPY + report.id);
}

/** The ids of reports with saves still on this device. */
export function pendingIds(): number[] {
  const ids: number[] = [];
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i) ?? "";
      if (key.startsWith(PENDING)) ids.push(Number(key.slice(PENDING.length)));
    }
  } catch {
    // none readable
  }
  return ids.filter((n) => n > 0);
}

/** The connection failed (as opposed to the server answering with an error). */
export function isNetworkError(error: unknown): boolean {
  return !(error instanceof ApiError);
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

export function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const ME = "sml-offline-me";

/** Who is signed in, kept so the screens open without a connection; cleared on signing out. */
export function keepMe(me: Me) {
  if (me.authenticated) write(ME, me);
  else forgetDevice();
}

export const keptMe = () => read<Me>(ME);

/** Signing out: the kept sign-in and report copies go (saves not yet sent stay). */
export function forgetDevice() {
  remove(ME);
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i) ?? "";
      if (key.startsWith(COPY)) keys.push(key);
    }
    keys.forEach(remove);
  } catch {
    // nothing kept
  }
}
