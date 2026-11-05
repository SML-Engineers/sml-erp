import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { Employee, EmployeeList } from "../api/employees";
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
  results: [
    {
      id: 7, number: "E001", full_name: "Kamal Perera", designation: "Machinist", division: "WS", section: "",
      employment_type: "permanent", employment_type_label: "Permanent", join_date: "2024-01-15", is_active: true,
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
