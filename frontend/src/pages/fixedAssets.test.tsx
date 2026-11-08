import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { DepreciationRunRow } from "../api/assets";
import { mockApi, renderAt } from "../test-utils";
import FixedAssetsPage from "./FixedAssetsPage";

const draft: DepreciationRunRow = {
  id: 5,
  month_end: "2026-10-31",
  status: "draft",
  total: "12000.00",
  journal_entry: null,
  prepared_by: "Accountant",
  posted_by: null,
  lines: [
    {
      asset: { id: 1, code: "FA0001", name: "CNC lathe" },
      division: "WS",
      method: "straight_line",
      rate: "12",
      book_value_before: "1200000.00",
      amount: "12000.00",
    },
  ],
};

test("the Accountant checks the month and posts it", async () => {
  const calls = mockApi({
    "GET /api/v1/depreciation/": { body: { next_month: "2026-10-31", runs: [draft] } },
    "POST /api/v1/depreciation/5/post/": { body: { ...draft, status: "posted", journal_entry: "JE-9" } },
  });
  renderAt("/fixed-assets?tab=depreciation", <FixedAssetsPage />, "/fixed-assets");
  const month = await screen.findByRole("region", { name: "2026-10-31" });
  expect(within(month).getByText("CNC lathe", { exact: false })).toBeInTheDocument();
  fireEvent.click(within(month).getByRole("button", { name: "Checked: post it" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/depreciation/5/post/", expect.objectContaining({ method: "POST" })));
});

test("the Director approves an asset's terms and the earlier assets go with their class's defaults", async () => {
  const calls = mockApi({
    "GET /api/v1/fixed-assets/waiting/": {
      body: {
        rates: [],
        terms: [
          {
            id: 7,
            asset: "FA0002",
            asset_name: "Injection press",
            asset_class: "PLANT",
            cost: "5000000.00",
            effective_from: "2026-11-01",
            method: "straight_line",
            rate: "10.0000",
            life_years: 10,
            status: "awaiting",
            reason: "",
            by: "Accountant",
            can_decide: true,
          },
        ],
        without_terms: 3,
        can_send_all: true,
      },
    },
    "POST /api/v1/fixed-assets/terms/7/decide/": { body: { status: "approved" } },
    "POST /api/v1/fixed-assets/send-all/": { body: { sent: 3 } },
  });
  renderAt("/fixed-assets?tab=approvals", <FixedAssetsPage />, "/fixed-assets");
  const waiting = await screen.findByRole("table", { name: "Asset terms waiting" });
  expect(within(waiting).getByText("10.0000% straight line · 10 years")).toBeInTheDocument();
  fireEvent.click(within(waiting).getByRole("button", { name: "Approve FA0002" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/fixed-assets/terms/7/decide/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "approve", reason: "" }) }),
    ),
  );
  const earlier = screen.getByRole("region", { name: "Assets without terms" });
  expect(within(earlier).getByText("3 assets registered earlier have no depreciation terms yet.")).toBeInTheDocument();
  fireEvent.click(within(earlier).getByRole("button", { name: "Send them with their class's defaults" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/fixed-assets/send-all/", expect.objectContaining({ method: "POST" })));
});

test("the Accountant sends new class defaults with a useful life", async () => {
  const calls = mockApi({
    "GET /api/v1/asset-classes/": {
      body: [
        {
          id: 2,
          code: "PLANT",
          name: "Plant and machinery",
          cost_account: null,
          accumulated_account: null,
          expense_account: null,
          current: { method: "straight_line", rate: "10.0000", life_years: 10, from: "2000-01-01" },
          rates: [
            {
              id: 3,
              effective_from: "2000-01-01",
              method: "straight_line",
              rate: "10.0000",
              life_years: 10,
              status: "approved",
              reason: "",
            },
          ],
        },
      ],
    },
    "GET /api/v1/accounts/": { body: [] },
    "POST /api/v1/asset-classes/2/rates/": { body: {} },
  });
  renderAt("/fixed-assets?tab=classes", <FixedAssetsPage />, "/fixed-assets");
  expect(await screen.findByText("10.0000% straight line · 10 years", { exact: false })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Useful life (years)"), { target: { value: "8" } });
  fireEvent.click(screen.getByRole("button", { name: "Send new defaults to the Director" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/asset-classes/2/rates/",
      expect.objectContaining({ body: expect.stringContaining('"life_years":"8"') }),
    ),
  );
});
