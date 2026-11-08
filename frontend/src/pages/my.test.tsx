import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { MySummary } from "../api/my";
import { mockApi, renderAt } from "../test-utils";
import MyPage from "./MyPage";

const mine: MySummary = {
  linked: true,
  employee: {
    number: "E001",
    name: "Kamal Perera",
    division: "WS",
    section: "Manual Milling",
    designation: "Machinist",
    category: "Shop and Office",
    epf_no: "101",
  },
  payslips: [
    {
      id: 11,
      month: "2026-10",
      gross: "73325.00",
      net: "67675.00",
      epf_employee: "5400.00",
      epf_employer: "8100.00",
      etf: "2025.00",
      apit: "0.00",
    },
  ],
  tax_year: 2026,
  leave_year: 2026,
  balances: [{ code: "ANNUAL", name: "Annual", granted: "14.0", taken: "2.0", pending: "1.0", left: "11.0" }],
  leave: [
    {
      id: 5,
      type: "Annual",
      start: "2026-11-10",
      end: "2026-11-10",
      days: "1.0",
      status: "applied",
      status_label: "Applied",
      note: "",
      can_withdraw: true,
    },
  ],
  leave_types: [
    { code: "ANNUAL", name: "Annual" },
    { code: "CASUAL", name: "Casual" },
  ],
  attendance: { from: "2026-09-21", days: [{ date: "2026-10-20", time_in: "07:58", time_out: "17:05", leave: "", late: 0 }] },
  to_approve: [],
};

test("an employee sees their payslips and applies for leave", async () => {
  const calls = mockApi({
    "GET /api/v1/my/": { body: mine },
    "POST /api/v1/my/leave/": { body: mine },
    "POST /api/v1/my/leave/5/withdraw/": { body: { ...mine, leave: [] } },
  });
  renderAt("/my", <MyPage />, "/my");
  const slip = await screen.findByRole("link", { name: "2026-10" });
  expect(slip).toHaveAttribute("href", "/api/v1/my/payslips/11/");
  expect(screen.getByText(/net LKR 67,675.00/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /APIT certificate 2026\/27/ })).toHaveAttribute("href", "/api/v1/my/apit-certificate/?year=2026");
  fireEvent.change(screen.getByLabelText("Kind of leave"), { target: { value: "CASUAL" } });
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-12" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Family" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/my/leave/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ leave_type: "CASUAL", start: "2026-11-12", end: "", half_day: false, reason: "Family" }),
      }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Withdraw" })).not.toBeInTheDocument());
});

test("an unlinked supervisor still approves their section's leave", async () => {
  const waiting = {
    linked: false,
    detail: "Your sign-in is not linked to an employee record yet. Ask HR to link it.",
    to_approve: [{ id: 8, employee: "E002 Nimal Silva", type: "Casual", start: "2026-11-12", end: "2026-11-12", days: "1.0", reason: "" }],
  };
  const calls = mockApi({
    "GET /api/v1/my/": { body: waiting },
    "POST /api/v1/my/team-leave/8/approve/": { body: { ...waiting, to_approve: [] } },
  });
  renderAt("/my", <MyPage />, "/my");
  expect(await screen.findByText(/Ask HR to link it/)).toBeInTheDocument();
  expect(screen.getByText("E002 Nimal Silva")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/my/team-leave/8/approve/", expect.objectContaining({ method: "POST" })));
  await waitFor(() => expect(screen.queryByText("E002 Nimal Silva")).not.toBeInTheDocument());
});

const clock = {
  mode: "sites" as const,
  mode_label: "Only at a site",
  needs_location: true,
  consent: false,
  consent_at: null,
  clocked_in: false,
  since: "",
  recent: [],
  sites: ["Colombo office"],
};

test("an employee limited to sites agrees to the location check and clocks in", async () => {
  const position = { coords: { latitude: 6.9275, longitude: 79.861244, accuracy: 12.4 } };
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: { getCurrentPosition: vi.fn((ok: (p: unknown) => void) => ok(position)) },
  });
  const agreed = { ...mine, clock: { ...clock, consent: true } };
  const calls = mockApi({
    "GET /api/v1/my/": { body: { ...mine, clock } },
    "POST /api/v1/my/location-consent/": { body: agreed },
    "POST /api/v1/my/clock/": {
      body: {
        ...agreed,
        clock: {
          ...agreed.clock,
          clocked_in: true,
          since: "08:05",
          recent: [{ kind: "in", kind_label: "In", at: "2026-11-06 08:05", site: "Colombo office" }],
        },
      },
      status: 201,
    },
  });
  renderAt("/my", <MyPage />, "/my");
  expect(await screen.findByText("Not clocked in.")).toBeInTheDocument();
  expect(screen.getByText(/only at a site: Colombo office/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Clock in" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /location is checked/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Clock in" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Clock in" }));
  expect(await screen.findByText("Clocked in since 08:05.")).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith(
    "/api/v1/my/clock/",
    expect.objectContaining({ body: JSON.stringify({ kind: "in", latitude: 6.9275, longitude: 79.861244, accuracy: 12 }) }),
  );
  expect(screen.getByRole("button", { name: "Clock out" })).toBeInTheDocument();
});

test("from anywhere, no location is asked", async () => {
  const anywhere = { ...clock, mode: "anywhere" as const, needs_location: false, sites: [] };
  const calls = mockApi({
    "GET /api/v1/my/": { body: { ...mine, clock: anywhere } },
    "POST /api/v1/my/clock/": { body: { ...mine, clock: { ...anywhere, clocked_in: true, since: "08:00" } }, status: 201 },
  });
  renderAt("/my", <MyPage />, "/my");
  expect(screen.queryByRole("checkbox", { name: /location is checked/ })).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Clock in" }));
  expect(await screen.findByText("Clocked in since 08:00.")).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith("/api/v1/my/clock/", expect.objectContaining({ body: JSON.stringify({ kind: "in" }) }));
});

test("an employee asks HR to change their phone and may withdraw it", async () => {
  const details = { phone: "0771234567", address: "", email: "", bank_name: "", bank_branch: "", account_name: "", account_number: "" };
  const waiting = {
    id: 9,
    employee: "E001 Kamal Perera",
    employee_id: 7,
    bank: false,
    note: "New SIM",
    status: "waiting" as const,
    status_label: "Waiting for HR",
    created_at: "2026-11-06T10:00:00Z",
    decision_note: "",
    changes: [{ field: "phone", before: "0771234567", after: "0719998887" }],
  };
  const calls = mockApi({
    "GET /api/v1/my/": { body: { ...mine, details, detail_requests: [] } },
    "POST /api/v1/my/details/": { body: { ...mine, details, detail_requests: [waiting] }, status: 201 },
    "POST /api/v1/my/details/9/withdraw/": {
      body: { ...mine, details, detail_requests: [{ ...waiting, status: "withdrawn", status_label: "Withdrawn" }] },
    },
  });
  renderAt("/my", <MyPage />, "/my");
  const ask = await screen.findByRole("button", { name: "Ask HR to change" });
  expect(ask).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "0719998887" } });
  fireEvent.change(screen.getByLabelText("Note for HR"), { target: { value: "New SIM" } });
  fireEvent.click(ask);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/my/details/",
      expect.objectContaining({ body: JSON.stringify({ phone: "0719998887", note: "New SIM" }) }),
    ),
  );
  expect(await screen.findByText(/Phone → 0719998887/)).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole("region", { name: "My details" })).getByRole("button", { name: "Withdraw" }));
  expect(await screen.findByText(/— Withdrawn/)).toBeInTheDocument();
});
