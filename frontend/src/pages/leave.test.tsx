import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { EmployeeList } from "../api/employees";
import type { HolidayList, LeaveList, LeaveTypeList } from "../api/leave";
import { mockApi, renderAt } from "../test-utils";
import HolidaysPage from "./HolidaysPage";
import LeavePage from "./LeavePage";

const year = new Date().getFullYear();
const types: LeaveTypeList = {
  can_manage: true,
  rules: [
    { value: "annual_soe", label: "Annual leave rule (by quarter of joining)" },
    { value: "fixed", label: "Same days every year" },
    { value: "unlimited", label: "No balance kept" },
  ],
  results: [
    {
      id: 1,
      code: "ANNUAL",
      name: "Annual leave",
      rule: "annual_soe",
      rule_label: "Annual leave rule (by quarter of joining)",
      days: "14.0",
      paid: true,
      wb_rule: "",
      wb_days: null,
      max_days: null,
      carry_forward_max: "0.0",
      is_active: true,
    },
  ],
};
const holidays: HolidayList = {
  year,
  can_manage: true,
  kinds: [
    { value: "public", label: "Public holiday" },
    { value: "poya", label: "Full moon Poya day" },
  ],
  results: [{ id: 3, date: `${year}-12-25`, name: "Christmas Day", kind: "public", kind_label: "Public holiday", can_remove: true }],
};
const people: EmployeeList = {
  can_add: true,
  types: [],
  categories: [],
  results: [
    {
      id: 7,
      number: "E001",
      full_name: "Kamal Perera",
      designation: "",
      division: "WS",
      section: "",
      employment_type: "permanent",
      employment_type_label: "Permanent",
      category: "shop_office",
      category_label: "Shop and Office",
      join_date: "2024-01-15",
      is_active: true,
      bank_check_pending: false,
    },
  ],
};
const leave: LeaveList = {
  year,
  can_record: true,
  types: types.results,
  results: [
    {
      id: 9,
      employee: { id: 7, number: "E001", name: "Kamal Perera" },
      leave_type: "ANNUAL",
      leave_type_name: "Annual leave",
      start: `${year}-07-07`,
      end: `${year}-07-09`,
      half_day: false,
      days: "3.0",
      reason: "Family trip",
      status: "applied",
      source: "applied",
      created_by: "Kamal",
      decided_by: null,
      decision_note: "",
      can_decide: true,
      can_cancel: true,
    },
  ],
};

test("HR adds a Poya day and removes a future holiday with a reason", async () => {
  const calls = mockApi({
    [`GET /api/v1/holidays/?year=${year}`]: { body: holidays },
    "GET /api/v1/leave-types/": { body: types },
    "POST /api/v1/holidays/": { body: holidays.results[0] },
    "DELETE /api/v1/holidays/3/": { body: null },
  });
  renderAt("/holidays", <HolidaysPage />);
  expect(await screen.findByText("Christmas Day")).toBeInTheDocument();
  fireEvent.change(screen.getAllByLabelText("Date")[0], { target: { value: `${year}-12-04` } });
  fireEvent.change(screen.getAllByLabelText("Name")[0], { target: { value: "Unduvap Poya" } });
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "poya" } });
  fireEvent.click(screen.getByRole("button", { name: "Add holiday" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/holidays/",
      expect.objectContaining({ body: JSON.stringify({ date: `${year}-12-04`, name: "Unduvap Poya", kind: "poya" }) }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.change(screen.getByLabelText("Reason for removing"), { target: { value: "Not a holiday" } });
  fireEvent.click(screen.getByRole("button", { name: "Remove the holiday" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/holidays/3/",
      expect.objectContaining({ method: "DELETE", body: JSON.stringify({ reason: "Not a holiday" }) }),
    ),
  );
});

test("HR records half a day of leave and approves leave applied for", async () => {
  const calls = mockApi({
    [`GET /api/v1/leave/?year=${year}`]: { body: leave },
    "GET /api/v1/employees/?status=active": { body: people },
    "POST /api/v1/leave/": { body: leave.results[0] },
    "POST /api/v1/leave/9/approve/": { body: { ...leave.results[0], status: "approved", can_decide: false } },
  });
  renderAt("/leave", <LeavePage />);
  expect(await screen.findByText("Family trip")).toBeInTheDocument();
  await screen.findByRole("option", { name: "E001 Kamal Perera" });
  fireEvent.change(screen.getByLabelText("Employee"), { target: { value: "7" } });
  fireEvent.change(screen.getAllByLabelText("Leave")[0], { target: { value: "ANNUAL" } });
  fireEvent.change(screen.getByLabelText("From"), { target: { value: `${year}-08-04` } });
  fireEvent.click(screen.getByLabelText("Half a day"));
  fireEvent.click(screen.getByRole("button", { name: "Record" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/leave/",
      expect.objectContaining({
        body: JSON.stringify({ employee: 7, leave_type: "ANNUAL", start: `${year}-08-04`, end: "", half_day: true, reason: "" }),
      }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve the leave" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/leave/9/approve/", expect.objectContaining({ method: "POST" })));
});
