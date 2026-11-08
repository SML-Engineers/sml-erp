import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { AttendanceMonth } from "../api/attendance";
import { mockApi, renderAt } from "../test-utils";
import AttendancePage from "./AttendancePage";

const month: AttendanceMonth = {
  month: "2026-10",
  period: { month: "2026-10", start: "2026-09-21", end: "2026-10-20" },
  division: "WS",
  divisions: ["HO", "IM", "WS"],
  confirmed: false,
  confirmed_by: null,
  confirmed_at: null,
  can_edit: true,
  month_ended: true,
  rows: [
    {
      employee: { id: 7, number: "E001", name: "Kamal Perera" },
      working_days: 26,
      days_worked: 24,
      hours_worked: "208:00",
      late_days: 2,
      late: "0:25",
      early: "0:10",
      leave_days: "1.0",
      absent_days: 1,
    },
  ],
};

const sites = {
  results: [{ id: 1, name: "Colombo office", latitude: "6.927079", longitude: "79.861244", radius_m: 200, is_active: true }],
  can_edit: true,
};

test("HR opens an employee's days and confirms the month", async () => {
  const calls = mockApi({
    "GET /api/v1/attendance/": { body: month },
    "GET /api/v1/punch-sites/": { body: sites },
    "GET /api/v1/employees/7/attendance/?month=2026-10": {
      body: {
        month: "2026-10",
        period: { month: "2026-10", start: "2026-09-21", end: "2026-10-20" },
        days: [
          {
            date: "2026-10-01",
            shift: "D",
            time_in: "08:10",
            time_out: "17:00",
            leave: "",
            worked: "8:50",
            late: 10,
            early: 0,
            remarks: "Phone punches",
            from_punches: true,
          },
        ],
        punches: [
          { at: "2026-10-01 08:10", kind: "in", site: "Colombo office", distance_m: 47 },
          { at: "2026-10-01 17:00", kind: "out", site: "Colombo office", distance_m: 30 },
        ],
      },
    },
    "POST /api/v1/attendance/confirm/": { body: { ok: true } },
  });
  renderAt("/attendance", <AttendancePage />);
  fireEvent.click(await screen.findByRole("button", { name: "E001 Kamal Perera" }));
  expect(await screen.findByText("8:50")).toBeInTheDocument();
  expect(screen.getByText("Phone punches (2)")).toBeInTheDocument();
  expect(screen.getByText(/2026-10-01 08:10 in — Colombo office \(47 m\)/)).toBeInTheDocument();
  expect(screen.getByText("Pay month Oct 2026: 21 Sep – 20 Oct")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm the month" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/attendance/confirm/",
      expect.objectContaining({ body: JSON.stringify({ division: "WS", month: "2026-10" }) }),
    ),
  );
});

test("a confirmed month is reopened with a reason", async () => {
  const calls = mockApi({
    "GET /api/v1/punch-sites/": { body: sites },
    "GET /api/v1/attendance/": { body: { ...month, confirmed: true, confirmed_by: "HR", confirmed_at: "2026-11-03T09:00:00Z" } },
    "POST /api/v1/attendance/reopen/": { body: { ok: true } },
  });
  renderAt("/attendance", <AttendancePage />);
  fireEvent.change(await screen.findByLabelText("Reason for reopening"), { target: { value: "Wrong sheet" } });
  fireEvent.click(screen.getByRole("button", { name: "Reopen the month" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/attendance/reopen/",
      expect.objectContaining({ body: JSON.stringify({ division: "WS", month: "2026-10", reason: "Wrong sheet" }) }),
    ),
  );
});

test("HR previews a pay month's phone punches, then brings them in", async () => {
  const preview = {
    month: "2026-10",
    period: month.period,
    punches: 7,
    days: 2,
    employees: 1,
    saved: false,
    notes: ["E001 2026-10-05: clocked in at 08:00 but never out; enter the day in the attendance sheet."],
    rows: [{ number: "E001", name: "Kamal Perera", date: "2026-10-01", time_in: "08:10", time_out: "17:00", shift: "G" }],
  };
  const calls = mockApi({
    "GET /api/v1/attendance/": { body: month },
    "GET /api/v1/punch-sites/": { body: sites },
    "POST /api/v1/attendance/punches/": (sent) => ({ body: { ...preview, saved: (sent as { dry_run: string }).dry_run === "false" } }),
  });
  renderAt("/attendance", <AttendancePage />);
  fireEvent.click(await screen.findByRole("button", { name: "Preview 2026-10" }));
  expect(await screen.findByText(/7 punches make 2 days for 1 employees/)).toBeInTheDocument();
  expect(screen.getByText(/never out/)).toBeInTheDocument();
  expect(screen.getByText("08:10–17:00")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Bring in" }));
  expect(await screen.findByText(/2 days for 1 employees brought into attendance/)).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith(
    "/api/v1/attendance/punches/",
    expect.objectContaining({ body: JSON.stringify({ month: "2026-10", dry_run: "false" }) }),
  );
});

test("HR adds a punch site and deactivates one", async () => {
  const calls = mockApi({
    "GET /api/v1/attendance/": { body: month },
    "GET /api/v1/punch-sites/": { body: sites },
    "POST /api/v1/punch-sites/": { body: sites.results[0], status: 201 },
    "PATCH /api/v1/punch-sites/1/": { body: { ...sites.results[0], is_active: false } },
  });
  renderAt("/attendance", <AttendancePage />);
  expect(await screen.findByRole("link", { name: "6.927079, 79.861244" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Site"), { target: { value: "Kandy customer" } });
  fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "7.2906" } });
  fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "80.6337" } });
  fireEvent.click(screen.getByRole("button", { name: "Add site" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/punch-sites/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "Kandy customer", latitude: "7.2906", longitude: "80.6337", radius_m: "200" }),
      }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/punch-sites/1/", expect.objectContaining({ method: "PATCH" })));
});

test("the fingerprint machine's file is checked like the template, with the days not brought in", async () => {
  mockApi({
    "GET /api/v1/attendance/": { body: month },
    "GET /api/v1/punch-sites/": { body: sites },
    "POST /api/v1/attendance/import/": {
      body: {
        rows: 3,
        employees: 1,
        months: ["2026-11"],
        leave_days: 0,
        errors: [],
        saved: false,
        source: "device",
        notes: ["E001 2026-10-22: only one punch (08:30); enter the day in the sheet."],
      },
    },
  });
  renderAt("/attendance", <AttendancePage />);
  const file = new File(["<Workbook/>"], "01Schedule-26-10.XLS");
  fireEvent.change(await screen.findByLabelText("Excel file"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Check the file" }));
  expect(await screen.findByText(/Fingerprint machine file:/)).toBeInTheDocument();
  expect(screen.getByText(/only one punch \(08:30\)/)).toBeInTheDocument();
});
