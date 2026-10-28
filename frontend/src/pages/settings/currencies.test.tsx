import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import type { Currency, ExchangeRate } from "../../api/currencies";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import CurrenciesPage from "./CurrenciesPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const accountant: CurrentUser = {
  ...sampleUser,
  access: {
    areas: { settings: ["view"], accounting: ["enter", "manage", "view"] },
    actions: [],
    divisions: "all",
  },
};

const currency = (code: string, name: string, extra: Partial<Currency> = {}): Currency => ({
  id: code.charCodeAt(0),
  code,
  name,
  symbol: "",
  decimal_places: 2,
  is_base: false,
  is_active: true,
  latest_rate: null,
  ...extra,
});

const list = [
  currency("LKR", "Sri Lankan rupee", { is_base: true }),
  currency("USD", "US dollar", { latest_rate: { date: "2026-10-27", rate: "299.875000" } }),
];

const rate: ExchangeRate = {
  id: 1,
  currency: "USD",
  date: "2026-10-27",
  rate: "299.875000",
  buying: "296.500000",
  selling: "303.250000",
  source: "manual",
  created_by: "accountant@sml.lk",
  created_at: "2026-10-27T03:00:00Z",
  used: true,
};

const api = (extra = {}) => ({
  "GET /api/v1/settings/currencies/": { body: list },
  "GET /api/v1/settings/exchange-rates/": { body: [rate] },
  ...extra,
});

test("the currency list shows LKR as base and each currency's latest rate", async () => {
  const calls = mockApi(
    api({
      "PATCH /api/v1/settings/currencies/USD/": {
        body: { ...list[1], is_active: false },
      },
    }),
  );
  renderAt("/settings/currencies", <CurrenciesPage me={admin} />);

  const lkr = (await screen.findByText("Sri Lankan rupee")).closest("tr")!;
  expect(within(lkr).getByText("base")).toBeInTheDocument();
  expect(within(lkr).queryByRole("button")).not.toBeInTheDocument();
  const usd = screen.getByText("US dollar").closest("tr")!;
  expect(within(usd).getByText("299.875000 (2026-10-27)")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "no US customers" } });
  fireEvent.click(within(usd).getByRole("button", { name: "Switch off USD" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/currencies/USD/",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ is_active: false, reason: "no US customers" }),
      }),
    ),
  );
});

test("the accountant enters a rate with buying and selling", async () => {
  const calls = mockApi(
    api({ "POST /api/v1/settings/exchange-rates/": { status: 201, body: rate } }),
  );
  renderAt("/settings/currencies", <CurrenciesPage me={accountant} />);

  // The accountant cannot change the currency list.
  await screen.findByText("Sri Lankan rupee");
  expect(screen.queryByRole("region", { name: "Add currency" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "Exchange rates" }));
  const form = await screen.findByRole("region", { name: "Enter a rate" });
  fireEvent.change(within(form).getByLabelText("Buying"), { target: { value: "296.50" } });
  fireEvent.change(within(form).getByLabelText("Selling"), { target: { value: "303.25" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save rate" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/exchange-rates/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    currency: "USD",
    rate: "",
    buying: "296.50",
    selling: "303.25",
  });
  // A rate used on documents is marked.
  expect(await screen.findByText("Used on documents")).toBeInTheDocument();
});

test("a CSV import is checked first and refused lines are listed", async () => {
  let calls = 0;
  mockApi(
    api({
      "POST /api/v1/settings/exchange-rates/import/": () => {
        calls += 1;
        return calls === 1
          ? { body: { dry_run: true, added: 20, corrected: 1, unchanged: 0 } }
          : {
              status: 400,
              body: { detail: "Nothing was imported.", errors: ["Line 4: Unknown currency XYZ."] },
            };
      },
    }),
  );
  renderAt("/settings/currencies", <CurrenciesPage me={accountant} />);

  fireEvent.click(await screen.findByRole("tab", { name: "Exchange rates" }));
  const panel = await screen.findByRole("region", { name: "Import rates from CSV" });
  fireEvent.change(within(panel).getByLabelText("CSV file"), {
    target: { files: [new File(["x"], "rates.csv")] },
  });
  fireEvent.click(within(panel).getByRole("button", { name: "Check file" }));
  expect(await within(panel).findByRole("status")).toHaveTextContent("add 20 rates, correct 1");
  fireEvent.click(within(panel).getByRole("button", { name: "Import" }));
  expect(await within(panel).findByRole("alert")).toHaveTextContent("Line 4: Unknown currency XYZ.");
});
