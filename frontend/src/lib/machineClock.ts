import { useEffect, useState } from "react";

import type { MachineJob } from "../api/machineJobs";

/** The time now, moving on every 30 seconds while the page is open, so running jobs count up. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** Whole minutes a job has run: the server's figure, or from its start to now if later. */
export function runningMinutes(job: MachineJob, now: number): number {
  return Math.max(job.minutes, Math.floor((now - new Date(job.started_at).getTime()) / 60_000));
}
