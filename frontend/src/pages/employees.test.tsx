import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { Employee, EmployeeList } from "../api/employees";
import type { EmployeePay, PayChange } from "../api/pay";
import { visibleMenu } from "../layout/menu";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import EmployeePage from "./EmployeePage";
import EmployeesPage from "./EmployeesPage";

const hr: CurrentUser = {
  ...sampleUser,
  access: { areas: { hr_payroll: ["enter", "manage", "view"] }, actions: ["export_personal_data"], divisions: "all" },
};
const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { hr_payroll: ["approve", "view"] }, actions: [], divisions: "all" },
};
const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { hr_payroll: ["view"] }, actions: [], divisions: "all" },
};

const list: EmployeeList = {
  can_add: true,
  types: [{ value: "permanent", label: "Permanent" }],
  categories: [
    { value: "shop_office", label: "Shop and Office" },
    { value: "wages_board", label: "Wages Board" },
  ],
  results: [
    {
      id: 7, number: "E001", full_name: "Kamal Perera", designation: "Machinist", division: "WS", section: "",
      employment_type: "permanent", employment_type_label: "Permanent", category: "shop_office", category_label: "Shop and Office", join_date: "2024-01-15", is_active: true,
      bank_check_pending: true,
    },
  ],
};

const employee: Employee = {
  ...list.results[0],
  name_with_initials: "K. Perera", nic: "199012345678", date_of_birth: "1990-05-01", address: "", phone: "",
  email: "", epf_no: "1234", etf_no: "", grade: "", confirmation_date: null, leaving_date: null, leaving_reason: "",
  user: null, bank_name: "Commercial Bank", bank_branch: "Kandy", account_name: "K Perera",
  account_number: "8001234567", bank_changed_at: "2026-11-05T09:00:00Z", bank_changed_by: "HR Officer",
  bank_checked_at: null, bank_checked_by: null, created_by: "HR Officer", created_at: "2026-11-05T09:00:00Z",
  can_edit: false, can_check_bank: true,
};

const thisYear = new Date().getFullYear();
const noLeave = { year: thisYear, balances: [], grants: [], leave: [], can_adjust: false };
const leaveRoute = { [`GET /api/v1/employees/7/leave/balances/?year=${thisYear}`]: { body: noLeave } };

const settings = {
  normal_day_minutes: null, grace_minutes: null, rate_working_day: null, rate_sunday: null, rate_holiday: null,
  annual_leave_days: null, casual_leave_days: null, apit: null,
};

const pay: EmployeePay = {
  on: "2026-11-05",
  current: [
    { component: "BASIC", component_name: "Basic salary", kind: "earning", epf_liable: true, apit_taxable: true, own_marks: false, amount: "60000.00", since: "2024-01" },
    { component: "WELFARE", component_name: "Welfare society", kind: "deduction", epf_liable: false, apit_taxable: false, own_marks: false, amount: "250.00", since: "2024-01" },
  ],
  totals: { earnings: "60000.00", deductions: "250.00", net: "59750.00", epf_earnings: "60000.00", apit_earnings: "60000.00" },
  upcoming: [],
  history: [
    { id: 3, component: "BASIC", component_name: "Basic salary", kind: "earning", effective_from: "2024-01", amount: "60000.00", epf_liable: null, apit_taxable: null, reason: "Joined", created_by: "HR", created_at: "2026-11-05T09:00:00Z" },
  ],
  components: [
    { id: 1, code: "BASIC", name: "Basic salary", kind: "earning", basis: "fixed", epf_liable: true, apit_taxable: true, is_allowance: false, in_day_rate: false, sort_order: 10, is_active: true },
    { id: 3, code: "ATTEND", name: "Attendance bonus", kind: "earning", basis: "variable", epf_liable: true, apit_taxable: true, is_allowance: false, in_day_rate: false, sort_order: 30, is_active: true },
  ],
  settings: null,
  settings_since: null,
  defaults: { ...settings, normal_day_minutes: "480", grace_minutes: "10", annual_leave_days: "14.0", casual_leave_days: "7.0", apit: "primary" },
  changes: [],
  next_month: "2026-12",
  can_prepare: true,
};

const waiting: PayChange = {
  id: 9, effective_from: "2026-12", is_new_employee: false, reason: "Increment", status: "awaiting",
  status_label: "Waiting for the Director", returned: false,
  lines: [{ component: "BASIC", component_name: "Basic salary", kind: "earning", amount: "66000.00", epf_liable: null, apit_taxable: null }],
  settings: null, created_by: "HR Officer", created_at: "2026-11-05T09:00:00Z", approved_at: null,
  history: [{ action: "Submitted", user: "HR Officer", reason: "", at: "2026-11-05T09:00:00Z" }],
  can_edit: false, can_submit: false, can_withdraw: false, can_approve: true,
};

test("only HR and the Director have the Employees menu", () => {
  const labels = (me: CurrentUser) => visibleMenu(me.access).flatMap((s) => s.items.map((i) => i.label));
  expect(labels(hr)).toContain("emp.title");
  expect(labels(director)).toContain("emp.title");
  expect(labels(accountant)).not.toContain("emp.title");
});

test("HR sees the list with the bank check waiting, and can export", async () => {
  mockApi({ "GET /api/v1/employees/": { body: list } });
  renderAt("/employees", <EmployeesPage me={hr} />);
  expect(await screen.findByText("Kamal Perera")).toBeInTheDocument();
  expect(screen.getByText("Waiting for the Director's check")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Category" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "Shop and Office" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download all (Excel)" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Import from Excel" })).toBeInTheDocument();
});

test("the Director confirms a new bank account", async () => {
  let current = employee;
  const checked = {
    ...employee, bank_check_pending: false, can_check_bank: false, bank_checked_by: "Director",
    bank_checked_at: "2026-11-05T10:00:00Z",
  };
  const calls = mockApi({
    "GET /api/v1/employees/7/": () => ({ body: current }),
    ...leaveRoute,
    "GET /api/v1/employees/7/pay/": { body: { ...pay, can_edit: false } },
    "POST /api/v1/employees/7/check-bank/": () => {
      current = checked;
      return { body: checked };
    },
  });
  renderAt("/employees/7", <EmployeePage />, "/employees/:id");
  fireEvent.click(await screen.findByRole("button", { name: "I have confirmed this account" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/employees/7/check-bank/", expect.objectContaining({ method: "POST" })),
  );
  expect(await screen.findByText(/Bank account checked by Director/)).toBeInTheDocument();
});

test("HR changing the bank account is asked for a reason and sends only what changed", async () => {
  const editable = { ...employee, bank_check_pending: false, can_edit: true, can_check_bank: false };
  const calls = mockApi({
    "GET /api/v1/employees/7/": { body: editable },
    ...leaveRoute,
    "GET /api/v1/employees/7/pay/": { body: pay },
    "PATCH /api/v1/employees/7/": { body: editable },
  });
  renderAt("/employees/7", <EmployeePage />, "/employees/:id");
  fireEvent.change(await screen.findByLabelText("Account number"), { target: { value: "8009999999" } });
  fireEvent.change(screen.getByLabelText("Reason for changing the bank account"), { target: { value: "New account" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/employees/7/",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ account_number: "8009999999", reason: "New account" }),
      }),
    ),
  );
});

test("HR prepares a new employee's pay; the attendance bonus starts at 1,500", async () => {
  const calls = mockApi({
    "GET /api/v1/employees/7/": { body: { ...employee, can_edit: true, bank_check_pending: false } },
    ...leaveRoute,
    "GET /api/v1/employees/7/pay/": { body: pay },
    "POST /api/v1/employees/7/pay-changes/": { body: { ...pay, can_prepare: false } },
  });
  renderAt("/employees/7", <EmployeePage />, "/employees/:id");
  expect(await screen.findByText("59,750.00")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Prepare a pay change" }));
  expect(screen.getByRole("heading", { name: "Pay for a new employee" })).toBeInTheDocument();
  expect(screen.getByLabelText("New amount Attendance bonus")).toHaveValue("1500");
  fireEvent.change(screen.getByLabelText("New amount Basic salary"), { target: { value: "60000" } });
  fireEvent.change(screen.getByLabelText("Reason (for example: annual increment)"), { target: { value: "Joined" } });
  fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/employees/7/pay-changes/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          effective_from: "2026-12",
          reason: "Joined",
          lines: [
            { component: "BASIC", amount: "60000", epf_liable: null, apit_taxable: null },
            { component: "ATTEND", amount: "1500", epf_liable: null, apit_taxable: null },
          ],
          settings: null,
        }),
      }),
    ),
  );
});

test("the Director approves a pay change waiting for him", async () => {
  const calls = mockApi({
    "GET /api/v1/employees/7/": { body: employee },
    ...leaveRoute,
    "GET /api/v1/employees/7/pay/": { body: { ...pay, can_prepare: false, changes: [waiting] } },
    "POST /api/v1/pay-changes/9/approve/": { body: pay },
  });
  renderAt("/employees/7", <EmployeePage />, "/employees/:id");
  expect(await screen.findByText("Waiting for the Director")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Prepare a pay change" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/pay-changes/9/approve/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "" }) }),
    ),
  );
});
