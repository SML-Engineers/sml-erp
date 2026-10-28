import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { TaxOverview } from "../api/taxes";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import TaxesPage from "./TaxesPage";

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["view"] }, actions: [], divisions: "all" },
};

const overview: TaxOverview = {
  components: [
    {
      id: 1,
      code: "VAT",
      name: "Value added tax",
      kind: "charged",
      sales_account: { id: 30, number: "2100", name: "VAT payable" },
      purchase_account: { id: 13, number: "1340", name: "VAT receivable" },
      is_active: true,
      in_use: false,
      current_rate: null,
      rates: [],
    },
    {
      id: 2,
      code: "SSCL",
      name: "Social security contribution levy",
      kind: "charged",
      sales_account: null,
      purchase_account: null,
      is_active: true,
      in_use: false,
      current_rate: "2.125",
      rates: [{ id: 7, effective_from: "2024-01-01", rate: "2.125", in_force: true }],
    },
  ],
  codes: [
    {
      id: 1,
      code: "VAT-SSCL",
      name: "SSCL, then VAT on the amount plus SSCL",
      description: "",
      use: "both",
      is_active: true,
      in_use: false,
      components: [
        { component: 2, code: "SSCL", base: "net" },
        { component: 1, code: "VAT", base: "net_and_tax" },
      ],
    },
  ],
};

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/taxes/": { body: overview },
  "GET /api/v1/chart-of-accounts/": { body: [] },
  ...extra,
});

test("the accountant enters the VAT rate in force", async () => {
  const calls = mockApi(api({ "POST /api/v1/taxes/components/1/rates/": { status: 201, body: overview } }));
  renderAt("/taxes", <TaxesPage me={accountant} />);

  const taxes = await screen.findByRole("table", { name: "Taxes" });
  expect(within(taxes).getByText("No rate yet")).toBeInTheDocument();
  expect(within(taxes).getByText("2.125%")).toBeInTheDocument();
  fireEvent.click(within(taxes).getByRole("button", { name: "VAT" }));
  const panel = await screen.findByRole("region", { name: "VAT – Value added tax" });
  expect(within(panel).getByText("Enter the rate in force before this tax is used.")).toBeInTheDocument();
  const form = within(panel).getByRole("form", { name: "Add rate" });
  fireEvent.change(within(form).getByLabelText("From"), { target: { value: "2024-01-01" } });
  fireEvent.change(within(form).getByLabelText("Rate (%)"), { target: { value: "18" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add rate" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/taxes/components/1/rates/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ effective_from: "2024-01-01", rate: "18", reason: "" }),
      }),
    ),
  );
});

test("a tax code shows its taxes in order and the calculator gives the total", async () => {
  mockApi(
    api({
      "GET /api/v1/taxes/calculate/?code=VAT-SSCL&amount=115750": {
        body: {
          code: "VAT-SSCL",
          net: "115750.00",
          lines: [
            { code: "SSCL", name: "SSCL", rate: "2.125", base: "115750.00", amount: "2459.69" },
            { code: "VAT", name: "VAT", rate: "18", base: "118209.69", amount: "21277.74" },
          ],
          tax: "23737.43",
          gross: "139487.43",
        },
      },
    }),
  );
  renderAt("/taxes", <TaxesPage me={director} />);

  const codes = await screen.findByRole("table", { name: "Tax codes" });
  expect(within(codes).getByText("SSCL → VAT (on the amount plus the taxes above)")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add tax code" })).not.toBeInTheDocument();
  const calculator = screen.getByRole("form", { name: "Tax calculator" });
  fireEvent.change(within(calculator).getByLabelText("Net amount"), { target: { value: "115750" } });
  fireEvent.click(within(calculator).getByRole("button", { name: "Calculate" }));
  const result = await screen.findByRole("table", { name: "Tax calculation" });
  expect(within(result).getByText("2,459.69")).toBeInTheDocument();
  expect(within(result).getByText("21,277.74")).toBeInTheDocument();
  expect(within(result).getByText("139,487.43")).toBeInTheDocument();
});
