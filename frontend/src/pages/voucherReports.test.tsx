import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ApprovedRow, PendingReport, VoucherSummary } from "../api/vouchers";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import VoucherReportsPage from "./VoucherReportsPage";
import VouchersPage from "./VouchersPage";

const approvedRow: ApprovedRow = {
  id: 1,
  number: "WS261029001",
  voucher_date: "2026-10-29",
  type: "Cheque Payment",
  division: "WS",
  payee: "Lanka Steel",
  approved_at: "2026-10-29T11:15:00Z",
  approved_by: "Mewantha",
  status: "Partly paid",
  status_code: "partly_paid",
  total_amount: "1000.00",
  paid: "400.00",
};

const pending: PendingReport = {
  rows: [
    {
      id: 2, number: "WS261029002", type: "Online Payment", division: "WS", payee: "CEB", level: 2,
      waiting_for: "L2 Accountant", approvers: "Kumari", since: "2026-10-20T09:00:00Z", days: 9,
      band: "8–14 days", total_amount: "25000.00",
    },
  ],
  summary: [
    { waiting_for: "L2 Accountant", count: 1, bands: { "0–2 days": 0, "3–7 days": 0, "8–14 days": 1, "15 days or more": 0 } },
  ],
};

test("the approved list filters by date and exports with the same filters", async () => {
  const calls = mockApi({
    "GET /api/v1/vouchers/reports/approved/": { body: [approvedRow] },
    "GET /api/v1/vouchers/reports/approved/?from=2026-10-01": { body: [] },
  });
  renderAt("/vouchers/reports", <VoucherReportsPage />);

  const table = await screen.findByRole("table", { name: "Approved list" });
  expect(within(table).getByText("Mewantha")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/reports/approved/?from=2026-10-01", expect.anything()),
  );
  const downloads = screen.getByRole("group", { name: "Download Approved list" });
  expect(within(downloads).getByRole("link", { name: "Excel" })).toHaveAttribute(
    "href",
    "/api/v1/vouchers/reports/approved/?from=2026-10-01&export=xlsx",
  );
  expect(within(downloads).getByRole("link", { name: "PDF" })).toHaveAttribute(
    "href",
    "/api/v1/vouchers/reports/approved/?from=2026-10-01&export=pdf",
  );
});

test("pending vouchers by approver and age", async () => {
  mockApi({
    "GET /api/v1/vouchers/reports/approved/": { body: [] },
    "GET /api/v1/vouchers/reports/pending/": { body: pending },
  });
  renderAt("/vouchers/reports", <VoucherReportsPage />);

  fireEvent.click(await screen.findByRole("tab", { name: "Pending by approver and age" }));
  const summary = await screen.findByRole("table", { name: "Waiting, by approver and age" });
  const row = within(summary).getByText("L2 Accountant").closest("tr")!;
  expect(row).toHaveTextContent("L2 Accountant10010");
  const list = screen.getByRole("table", { name: "Pending by approver and age" });
  expect(within(list).getByText("Kumari")).toBeInTheDocument();
  expect(within(list).getByText("9")).toBeInTheDocument();
});

test("the approval history of a voucher found by its number", async () => {
  const found: VoucherSummary = {
    id: 5, number: "WS261029005", status: "paid", voucher_type: { code: "CHQ", name: "Cheque Payment" },
    division: "WS", payee: { id: 3, name: "Lanka Steel" }, voucher_date: "2026-10-29", total_amount: "1000.00",
    created_by: "Nimal", attachments: 1,
  };
  mockApi({
    "GET /api/v1/vouchers/reports/approved/": { body: [] },
    "GET /api/v1/vouchers/?q=WS261029005": { body: [found] },
    "GET /api/v1/vouchers/5/history/": {
      body: [
        { acted_at: "2026-10-29T08:00:00Z", round: 1, level: 1, action: "Submitted", user: "Nimal", reason: "" },
        { acted_at: "2026-10-29T09:00:00Z", round: 1, level: 2, action: "Approved", user: "Kumari", reason: "coded" },
      ],
    },
  });
  renderAt("/vouchers/reports", <VoucherReportsPage />);

  fireEvent.click(await screen.findByRole("tab", { name: "Approval history" }));
  fireEvent.change(screen.getByLabelText("Voucher number"), { target: { value: "WS261029005" } });
  fireEvent.click(screen.getByRole("button", { name: "Show history" }));
  const table = await screen.findByRole("table", { name: "Approval history" });
  expect(within(table).getByText("coded")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Download Approval history" })).getByRole("link", { name: "PDF" })).toHaveAttribute(
    "href",
    "/api/v1/vouchers/5/history/?export=pdf",
  );
});

test("the voucher list exports what is filtered", async () => {
  mockApi({
    "GET /api/v1/vouchers/": { body: [] },
    "GET /api/v1/vouchers/?status=paid": { body: [] },
    "GET /api/v1/voucher-types/": { body: [] },
  });
  renderAt("/vouchers", <VouchersPage me={sampleUser} />);
  fireEvent.change(await screen.findByLabelText("Status"), { target: { value: "paid" } });
  expect(within(screen.getByRole("group", { name: "Download Payment vouchers" })).getByRole("link", { name: "Excel" })).toHaveAttribute(
    "href",
    "/api/v1/vouchers/?status=paid&export=xlsx",
  );
});
