import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { AttendanceMonth } from "../api/attendance";
import { mockApi, renderAt } from "../test-utils";
import AttendancePage from "./AttendancePage";

const month: AttendanceMonth = {
  month: "2026-10", division: "WS", divisions: ["HO", "IM", "WS"], confirmed: false, confirmed_by: null,
  confirmed_at: null, can_edit: true, month_ended: true,
  rows: [
    {
      employee: { id: 7, number: "E001", name: "Kamal Perera" }, working_days: 26, days_worked: 24, hours_worked: "208:00",
      late_days: 2, late: "0:25", early: "0:10", leave_days: "1.0", absent_days: 1,
    },
  ],
};

test("HR opens an employee's days and confirms the month", async () => {
  const calls = mockApi({
    "GET /api/v1/attendance/": { body: month },
    "GET /api/v1/employees/7/attendance/?month=2026-10": {
      body: { month: "2026-10", days: [{ date: "2026-10-01", shift: "D", time_in: "08:10", time_out: "17:00", leave: "", worked: "8:50", late: 10, early: 0, remarks: "" }] },
    },
    "POST /api/v1/attendance/confirm/": { body: { ok: true } },
  });
  renderAt("/attendance", <AttendancePage />);
  fireEvent.click(await screen.findByRole("button", { name: "E001 Kamal Perera" }));
  expect(await screen.findByText("8:50")).toBeInTheDocument();
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
