import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { DepreciationRunRow } from "../api/assets";
import { mockApi, renderAt } from "../test-utils";
import FixedAssetsPage from "./FixedAssetsPage";

const draft: DepreciationRunRow = {
  id: 5, month_end: "2026-10-31", status: "draft", total: "12000.00", journal_entry: null, prepared_by: "Accountant", posted_by: null,
  lines: [{ asset: { id: 1, code: "FA0001", name: "CNC lathe" }, division: "WS", method: "straight_line", rate: "12", book_value_before: "1200000.00", amount: "12000.00" }],
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
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/depreciation/5/post/", expect.objectContaining({ method: "POST" })),
  );
});
