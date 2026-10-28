import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import type { QuotationLimit } from "../../api/limits";
import type { DivisionAdmin } from "../../api/organisation";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import QuotationLimitsPage from "./QuotationLimitsPage";

const admin: CurrentUser = {
  ...sampleUser,
  email: "admin@sml.lk",
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  email: "director@sml.lk",
  access: { areas: { settings: ["view"] }, actions: ["confirm_limits"], divisions: "all" },
};

const division = (id: number, code: string, name: string): DivisionAdmin => ({
  id,
  code,
  name,
  division_type: "production",
  tax_invoice_code: "",
  tax_invoice_code_in_use: false,
  is_active: true,
  in_use: false,
  first_used_at: null,
  users: 0,
  created_at: "2026-10-01T00:00:00Z",
});

const limit = (extra: Partial<QuotationLimit>): QuotationLimit => ({
  id: 1,
  division: "WS",
  effective_from: "2026-10-01",
  min_margin_pct: "20.00",
  director_above_lkr: "1000000.00",
  status: "confirmed",
  reason: "owner's policy",
  created_by: "admin@sml.lk",
  created_at: "2026-10-01T00:00:00Z",
  decided_by: "director@sml.lk",
  decided_at: "2026-10-01T02:00:00Z",
  decision_note: "",
  in_force: true,
  ...extra,
});

const rows = [
  limit({}),
  limit({
    id: 2,
    effective_from: "2026-11-01",
    min_margin_pct: "22.50",
    status: "pending",
    decided_by: null,
    decided_at: null,
    in_force: false,
    reason: "steel prices up",
  }),
];

const api = (extra = {}) => ({
  "GET /api/v1/settings/quotation-limits/": { body: rows },
  "GET /api/v1/settings/divisions/": {
    body: [division(1, "WS", "Workshop"), division(2, "IM", "Plastic Injection Moulding")],
  },
  ...extra,
});

test("the page shows the limits in force, and divisions not set yet", async () => {
  mockApi(api());
  renderAt("/settings/quotation-limits", <QuotationLimitsPage me={director} />);

  const ws = (await screen.findByText("WS Workshop")).closest("tr")!;
  expect(within(ws).getByText("20.00%")).toBeInTheDocument();
  expect(within(ws).getByText("1,000,000.00")).toBeInTheDocument();
  const im = screen.getByText("IM Plastic Injection Moulding").closest("tr")!;
  expect(within(im).getByText("Not set")).toBeInTheDocument();
});

test("the Director confirms a change the Admin entered; the Director cannot propose", async () => {
  const calls = mockApi(
    api({
      "POST /api/v1/settings/quotation-limits/2/confirm/": {
        body: { ...rows[1], status: "confirmed" },
      },
    }),
  );
  renderAt("/settings/quotation-limits", <QuotationLimitsPage me={director} />);

  const change = await screen.findByRole("group", { name: "Change for WS:" });
  expect(change).toHaveTextContent("minimum margin 22.50%");
  expect(change).toHaveTextContent("steel prices up");
  expect(within(change).queryByRole("button", { name: "Withdraw" })).not.toBeInTheDocument();
  fireEvent.click(within(change).getByRole("button", { name: "Confirm" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/quotation-limits/2/confirm/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(screen.queryByRole("region", { name: "Propose new limits" })).not.toBeInTheDocument();
});

test("the Admin proposes limits and can only withdraw their own pending change", async () => {
  const calls = mockApi(
    api({ "POST /api/v1/settings/quotation-limits/": { status: 201, body: rows[1] } }),
  );
  renderAt("/settings/quotation-limits", <QuotationLimitsPage me={admin} />);

  const change = await screen.findByRole("group", { name: "Change for WS:" });
  expect(within(change).queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  expect(within(change).getByRole("button", { name: "Withdraw" })).toBeInTheDocument();

  const form = screen.getByRole("region", { name: "Propose new limits" });
  fireEvent.change(within(form).getByLabelText("Division"), { target: { value: "IM" } });
  fireEvent.change(within(form).getByLabelText("Minimum margin %"), { target: { value: "15" } });
  fireEvent.change(within(form).getByLabelText("Director approves above (LKR)"), {
    target: { value: "1000000" },
  });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "board decision" } });
  fireEvent.click(within(form).getByRole("button", { name: "Send to the Director" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/quotation-limits/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    division: "IM",
    min_margin_pct: "15",
    director_above_lkr: "1000000",
    reason: "board decision",
  });
});
