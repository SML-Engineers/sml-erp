import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import type { DivisionAdmin } from "../../api/organisation";
import type { RosterPattern, RosterPreview, Shift } from "../../api/rosters";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import ShiftsPage from "./ShiftsPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["view"] }, actions: [], divisions: "all" },
};

const shift = (id: number, code: string, name: string, start: string, end: string): Shift => ({
  id,
  code,
  name,
  start_time: `${start}:00`,
  end_time: `${end}:00`,
  break_minutes: 60,
  crosses_midnight: end <= start,
  working_minutes: 0,
  is_active: true,
});

const shifts = [
  shift(1, "G", "General", "08:00", "17:00"),
  shift(2, "D", "Day 12-hour", "07:00", "19:00"),
  shift(3, "N", "Night 12-hour", "19:00", "07:00"),
];

const rotation: RosterPattern = {
  id: 1,
  name: "12-hour rotation",
  days: ["D", "D", "N", "N", null, null],
  summary: { cycle_days: 6, hours_per_cycle: 44, average_hours_per_week: 51.33 },
  is_active: true,
};

const im: DivisionAdmin = {
  id: 2,
  code: "IM",
  name: "Plastic Injection Moulding",
  division_type: "production",
  tax_invoice_code: "P1",
  tax_invoice_code_in_use: false,
  is_active: true,
  in_use: false,
  first_used_at: null,
  users: 0,
  created_at: "2026-10-01T00:00:00Z",
};

const today = new Date().toLocaleDateString("en-CA");

const preview: RosterPreview = {
  start: today,
  days: [
    {
      date: "2026-11-01",
      shifts: [
        { shift: "D", shift_name: "Day 12-hour", crew: "A", section: null },
        { shift: "N", shift_name: "Night 12-hour", crew: "B", section: null },
      ],
    },
    {
      date: "2026-11-02",
      shifts: [{ shift: "D", shift_name: "Day 12-hour", crew: "A", section: null }],
    },
  ],
  warnings: ["2026-11-02: no crew on Night 12-hour (IM)."],
};

const api = (extra = {}) => ({
  "GET /api/v1/settings/shifts/": { body: shifts },
  "GET /api/v1/settings/roster-patterns/": { body: [rotation] },
  "GET /api/v1/settings/crews/": {
    body: ["A", "B", "C"].map((code, i) => ({
      id: i + 1,
      code,
      name: "",
      division: "IM",
      is_active: true,
    })),
  },
  "GET /api/v1/settings/rosters/": { body: [] },
  "GET /api/v1/settings/divisions/": { body: [im] },
  "GET /api/v1/settings/sections/": { body: [] },
  [`GET /api/v1/settings/rosters/preview/?division=IM&start=${today}&days=28`]: { body: preview },
  ...extra,
});

test("the shifts tab lists shifts and marks the ones that run past midnight", async () => {
  mockApi(api());
  renderAt("/settings/shifts", <ShiftsPage me={director} />);

  const night = (await screen.findByText("Night 12-hour")).closest("tr")!;
  expect(within(night).getByText("overnight")).toBeInTheDocument();
  const general = screen.getByText("General").closest("tr")!;
  expect(within(general).queryByText("overnight")).not.toBeInTheDocument();
  // View only: no forms.
  expect(screen.queryByRole("region", { name: "Add shift" })).not.toBeInTheDocument();
});

test("the admin adds a shift", async () => {
  const calls = mockApi(
    api({ "POST /api/v1/settings/shifts/": { status: 201, body: shifts[0] } }),
  );
  renderAt("/settings/shifts", <ShiftsPage me={admin} />);

  const form = await screen.findByRole("region", { name: "Add shift" });
  fireEvent.change(within(form).getByLabelText("Code"), { target: { value: "s2" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Second" } });
  fireEvent.change(within(form).getByLabelText("Start"), { target: { value: "22:00" } });
  fireEvent.change(within(form).getByLabelText("End"), { target: { value: "06:00" } });
  expect(within(form).getByText(/belongs to the date it starts/)).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Add shift" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/shifts/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    code: "S2",
    start_time: "22:00",
    end_time: "06:00",
    break_minutes: 0,
  });
});

test("a roster pattern is built day by day", async () => {
  const calls = mockApi(
    api({ "POST /api/v1/settings/roster-patterns/": { status: 201, body: rotation } }),
  );
  renderAt("/settings/shifts", <ShiftsPage me={admin} />);

  fireEvent.click(await screen.findByRole("tab", { name: "Roster patterns" }));
  const form = await screen.findByRole("region", { name: "Add roster pattern" });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "12-hour rotation" } });
  for (let i = 0; i < 4; i++) {
    fireEvent.click(within(form).getByRole("button", { name: "Add a day" }));
  }
  ["D", "D", "N", "N", "", ""].forEach((code, i) => {
    fireEvent.change(within(form).getByLabelText(`Day ${i + 1}`), { target: { value: code } });
  });
  fireEvent.click(within(form).getByRole("button", { name: "Save pattern" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/roster-patterns/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body)).days).toEqual(["D", "D", "N", "N", null, null]);
  // The list shows the cycle as chips.
  expect(screen.getAllByText("Off").length).toBeGreaterThan(0);
});

test("the roster calendar previews who is on each shift and warns of gaps", async () => {
  mockApi(api());
  renderAt("/settings/shifts", <ShiftsPage me={director} />);

  fireEvent.click(await screen.findByRole("tab", { name: "Roster calendar" }));
  const panel = await screen.findByRole("region", { name: "4-week preview" });
  expect(await within(panel).findByRole("alert")).toHaveTextContent(
    "2026-11-02: no crew on Night 12-hour (IM).",
  );
  const crewB = within(panel).getByRole("rowheader", { name: "B" }).closest("tr")!;
  expect(within(crewB).getByText("N")).toBeInTheDocument();
});
