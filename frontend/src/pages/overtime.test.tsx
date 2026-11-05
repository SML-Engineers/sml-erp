import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { OvertimeMonth, WorkRuleList } from "../api/overtime";
import { mockApi, renderAt } from "../test-utils";
import OvertimePage from "./OvertimePage";
import WorkRulesPage from "./WorkRulesPage";

const rule = {
  id: 1, division: "WS", effective_from: "2024-01", normal_day_minutes: 480, grace_minutes: 10, short_leaves_per_month: 2,
  short_leave_minutes: 90, ot_min_minutes: 30, ot_step_minutes: 15, hourly_divisor: 240, rate_working_day: "1.50",
  rate_sunday: "2.00", rate_holiday: "2.00", reason: "Default", created_by: null, can_withdraw: false,
};

const month: OvertimeMonth = {
  month: "2026-10", division: "WS", divisions: ["WS"], confirmed: true, rule,
  rows: [
    {
      employee: { id: 7, number: "E001", name: "Kamal Perera", section: "" }, ot_working: "3:00", ot_sunday: "4:00",
      ot_holiday: "2:15", short: "3:05", short_leaves: 2, nopay_time: "2:15", nopay_days: "19.0", checked_by: null,
      checked_at: null, can_check: true,
    },
  ],
};

test("the Director chooses employees and checks their overtime", async () => {
  const calls = mockApi({
    "GET /api/v1/overtime/": { body: month },
    "POST /api/v1/overtime/check/": { body: { checked: 1 } },
  });
  renderAt("/overtime", <OvertimePage />);
  fireEvent.click(await screen.findByLabelText("Choose E001"));
  fireEvent.click(screen.getByRole("button", { name: "Check 1 employee" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/overtime/check/",
      expect.objectContaining({ body: JSON.stringify({ division: "WS", month: "2026-10", employees: [7] }) }),
    ),
  );
});

test("HR enters a new rule from a month, keeping the other values", async () => {
  const list: WorkRuleList = { results: [rule], divisions: ["WS"], can_manage: true };
  const calls = mockApi({
    "GET /api/v1/work-rules/": { body: list },
    "POST /api/v1/work-rules/": { body: rule },
  });
  renderAt("/work-rules", <WorkRulesPage />);
  fireEvent.change(await screen.findByLabelText("Division"), { target: { value: "WS" } });
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2027-01" } });
  fireEvent.change(screen.getByLabelText("OT rate, Sunday"), { target: { value: "2.5" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Wages Board decision" } });
  fireEvent.click(screen.getByRole("button", { name: "Save rule" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/work-rules/",
      expect.objectContaining({
        body: JSON.stringify({ division: "WS", effective_from: "2027-01", rate_sunday: "2.5", reason: "Wages Board decision" }),
      }),
    ),
  );
});
