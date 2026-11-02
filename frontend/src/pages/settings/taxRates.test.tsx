import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { RateRow, TaxRatesPage as Page } from "../../api/taxRates";
import { mockApi, renderAt } from "../../test-utils";
import TaxRatesPage from "./TaxRatesPage";

const rate = (extra: Partial<RateRow>): RateRow => ({
  id: 1, effective_from: "2024-01-01", rate: "2.125", status: "confirmed", reason: "", created_by: "Admin",
  created_by_me: false, decided_by: "", decided_at: null, decision_note: "", ...extra,
});

const tax = (id: number, code: string, name: string, current: string) => ({
  id, code, name, printed_as: code.startsWith("SSCL") ? "SSCL" : code, is_active: true,
  current: rate({ id: id * 10, rate: current }), coming: [], pending: [], history: [],
});

const page = (extra: Partial<Page> = {}): Page => ({
  taxes: [tax(1, "SSCL", "SSCL on services", "2.5"), tax(2, "SSCL-M", "SSCL on manufactured goods", "2.125"), tax(3, "VAT", "Value added tax", "18")],
  can_propose: true,
  can_confirm: false,
  ...extra,
});

test("the Admin sees the rates and enters a change for the Director", async () => {
  const calls = mockApi({
    "GET /api/v1/settings/tax-rates/": { body: page() },
    "POST /api/v1/settings/tax-rates/": { status: 201, body: page() },
  });
  renderAt("/settings/tax-rates", <TaxRatesPage />);
  const table = await screen.findByRole("table", { name: "Rates in force today" });
  const row = within(table).getByText("SSCL on manufactured goods").closest("tr")!;
  expect(within(row).getByText("2.125%")).toBeInTheDocument();
  expect(within(row).getByText("SSCL")).toBeInTheDocument();
  const form = screen.getByRole("region", { name: "Enter a new rate" });
  fireEvent.change(within(form).getByLabelText("Tax"), { target: { value: "2" } });
  fireEvent.change(within(form).getByLabelText("New rate (%)"), { target: { value: "2.5" } });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Gazette 2499/01" } });
  fireEvent.click(within(form).getByRole("button", { name: "Send to the Director" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/settings/tax-rates/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({ component: 2, rate: "2.5", reason: "Gazette 2499/01" });
});

test("the Director confirms a waiting change", async () => {
  const waiting = page({ can_propose: false, can_confirm: true });
  waiting.taxes[1].pending = [rate({ id: 77, rate: "2.5", status: "pending", effective_from: "2026-12-01", reason: "Gazette" })];
  const calls = mockApi({
    "GET /api/v1/settings/tax-rates/": { body: waiting },
    "POST /api/v1/settings/tax-rates/77/confirm/": { body: page({ can_propose: false, can_confirm: true }) },
  });
  renderAt("/settings/tax-rates", <TaxRatesPage />);
  const change = await screen.findByRole("group", { name: "Change to SSCL-M:" });
  expect(change).toHaveTextContent("2.5% from 2026-12-01");
  expect(screen.queryByRole("region", { name: "Enter a new rate" })).not.toBeInTheDocument();
  fireEvent.click(within(change).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/settings/tax-rates/77/confirm/", expect.objectContaining({ method: "POST" })));
});
