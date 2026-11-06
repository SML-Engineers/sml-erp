import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Takeover } from "../api/takeover";
import { mockApi, renderAt } from "../test-utils";
import PayrollTakeoverPage from "./PayrollTakeoverPage";

const page: Takeover = {
  can_edit: true,
  is_director: false,
  batches: [],
  checks: [],
  runs: [{ id: 4, title: "WS October 2026", status_label: "Approved" }],
};
const xlsx = () => new File(["x"], "old.xlsx");

test("HR checks the year's figures, then sends them to the Director", async () => {
  const result = { errors: [], employees: 2, tax_year: "2026", totals: { gross: "876000.00", apit: "0.00" } };
  mockApi({
    "GET /api/v1/payroll-takeover/": { body: page },
    "POST /api/v1/payroll-takeover/opening/": (sent) => {
      const saved = (sent as FormData).get("dry_run") === "false";
      return { body: { ...result, saved } };
    },
  });
  renderAt("/payroll-takeover", <PayrollTakeoverPage />);
  const step = await screen.findByRole("region", { name: "3. The year's figures to date" });
  expect(within(step).getByRole("link", { name: "Download the template" })).toHaveAttribute(
    "href",
    "/api/v1/payroll-takeover/opening-template/",
  );
  fireEvent.change(within(step).getByLabelText("Excel file"), { target: { files: [xlsx()] } });
  fireEvent.click(within(step).getByRole("button", { name: "Check" }));
  expect(await within(step).findByText(/2 employees, year 2026: gross LKR 876,000.00.*Checked/)).toBeInTheDocument();
  fireEvent.click(within(step).getByRole("button", { name: "Save" }));
  expect(await within(step).findByText(/Saved and sent to the Director/)).toBeInTheDocument();
});

test("a pay month is compared and the Director signs it off", async () => {
  const people = [
    {
      number: "E002", name: "Nimal Silva", missing: "" as const, differs: true,
      figures: [{ field: "Net pay", here: "60000.00", old: "59989.50", difference: "10.50" }],
    },
    { number: "E009", name: "", missing: "here" as const, differs: true, figures: [] },
  ];
  const compared = { errors: [], saved: false, run: 4, title: "WS October 2026", employees: 3, differences: 2, people };
  mockApi({
    "GET /api/v1/payroll-takeover/": { body: page },
    "POST /api/v1/payroll-takeover/compare/4/": { body: compared },
  });
  renderAt("/payroll-takeover", <PayrollTakeoverPage />);
  const step = await screen.findByRole("region", { name: "4. One month in both" });
  fireEvent.change(within(step).getByLabelText("Excel file"), { target: { files: [xlsx()] } });
  fireEvent.click(within(step).getByRole("button", { name: "Compare" }));
  expect(await within(step).findByText("WS October 2026: 3 employees, 2 with differences.")).toBeInTheDocument();
  expect(within(step).getByRole("cell", { name: "10.50" })).toBeInTheDocument();
  expect(within(step).getByText("In the old payroll only")).toBeInTheDocument();
});

test("the Director signs off a kept comparison", async () => {
  const check = {
    id: 7, run: 4, title: "WS October 2026", file_name: "old.xlsx", employees: 2, differences: 0, people: [],
    created_by: "HR Officer", created_at: "2026-11-07T10:00:00Z", signed_off_by: "", signed_off_at: null, note: "",
    can_sign_off: true,
  };
  const director = { ...page, can_edit: false, is_director: true, checks: [check] };
  const calls = mockApi({
    "GET /api/v1/payroll-takeover/": { body: director },
    "POST /api/v1/payroll-takeover/checks/7/sign-off/": {
      body: { ...director, checks: [{ ...check, can_sign_off: false, signed_off_by: "Director", signed_off_at: "2026-11-07T11:00:00Z" }] },
    },
  });
  renderAt("/payroll-takeover", <PayrollTakeoverPage />);
  expect(await screen.findByText("Every employee's figures are the same in both.")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "2. Pay" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Sign off" }));
  expect(await screen.findByText(/Signed off by Director on 2026-11-07/)).toBeInTheDocument();
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/payroll-takeover/checks/7/sign-off/", expect.objectContaining({ method: "POST" })),
  );
});
