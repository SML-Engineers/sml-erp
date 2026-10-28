import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import type { NumberSeries } from "../../api/organisation";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import NumberSeriesPage from "./NumberSeriesPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["view"] }, actions: [], divisions: "all" },
};

const voucher: NumberSeries = {
  id: 1,
  document_type: "voucher",
  name: "Payment vouchers",
  format: "{PP}{YY}{MM}{DD}{XXX}",
  reset_period: "daily",
  next_numbers: [
    { division: "HO", next: "HO261028001" },
    { division: "IM", next: "IM261028003" },
    { division: "WS", next: "WS261028001" },
  ],
};

test("the list shows each document's format and its next numbers", async () => {
  mockApi({ "GET /api/v1/settings/number-series/": { body: [voucher] } });
  renderAt("/settings/number-series", <NumberSeriesPage me={director} />);

  const row = (await screen.findByText("Payment vouchers")).closest("tr")!;
  expect(within(row).getByText("{PP}{YY}{MM}{DD}{XXX}")).toBeInTheDocument();
  expect(within(row).getByText("Every day")).toBeInTheDocument();
  expect(within(row).getByText("IM261028003")).toBeInTheDocument();
  // View only: no edit button.
  expect(within(row).queryByRole("button")).not.toBeInTheDocument();
});

test("the admin checks a wider format, then saves it with a reason", async () => {
  const api = mockApi({
    "GET /api/v1/settings/number-series/": { body: [voucher] },
    "POST /api/v1/settings/number-series/1/preview/": {
      body: { next_numbers: [{ division: "IM", next: "IM2610280003" }] },
    },
    "PATCH /api/v1/settings/number-series/1/": (sent) => ({
      body: { ...voucher, ...(sent as object) },
    }),
  });
  renderAt("/settings/number-series", <NumberSeriesPage me={admin} />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Edit numbering: Payment vouchers" }),
  );
  const panel = screen.getByRole("region", { name: "Edit numbering: Payment vouchers" });
  fireEvent.change(within(panel).getByLabelText("Format"), {
    target: { value: "{PP}{YY}{MM}{DD}{XXXX}" },
  });
  fireEvent.click(within(panel).getByRole("button", { name: "Check" }));
  expect(await within(panel).findByText("IM2610280003")).toBeInTheDocument();

  fireEvent.change(within(panel).getByLabelText("Reason"), { target: { value: "busy days" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(screen.queryByRole("region", { name: /Edit numbering/ })).not.toBeInTheDocument(),
  );
  expect(api).toHaveBeenCalledWith(
    "/api/v1/settings/number-series/1/",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        format: "{PP}{YY}{MM}{DD}{XXXX}",
        reset_period: "daily",
        reason: "busy days",
      }),
    }),
  );
});

test("token buttons add to the format, and a refused format shows why", async () => {
  mockApi({
    "GET /api/v1/settings/number-series/": { body: [voucher] },
    "POST /api/v1/settings/number-series/1/preview/": {
      status: 400,
      body: { detail: "The format can have only one running number." },
    },
  });
  renderAt("/settings/number-series", <NumberSeriesPage me={admin} />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Edit numbering: Payment vouchers" }),
  );
  const panel = screen.getByRole("region", { name: "Edit numbering: Payment vouchers" });
  fireEvent.click(within(panel).getByRole("button", { name: "{XXXX}" }));
  expect(within(panel).getByLabelText("Format")).toHaveValue("{PP}{YY}{MM}{DD}{XXX}{XXXX}");

  fireEvent.click(within(panel).getByRole("button", { name: "Check" }));
  expect(await within(panel).findByRole("alert")).toHaveTextContent(
    "The format can have only one running number.",
  );
});
