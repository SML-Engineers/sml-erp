import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { VoucherDetail } from "../api/vouchers";
import { mockApi, renderAt } from "../test-utils";
import DirectorPage from "./DirectorPage";

const row = (id: number, code: string, name: string, total: string, payee: string) => ({
  id,
  number: `WS26102900${id}`,
  status: "accountant_approved",
  voucher_type: { code, name },
  division: id === 3 ? "IM" : "WS",
  payee: { id: 10 + id, name: payee },
  voucher_date: "2026-10-29",
  total_amount: total,
  created_by: "Nimal",
  attachments: 1,
  submitted_at: "2026-10-29T08:00:00Z",
  waiting_level: 3,
  last_comment: "coded",
});

const waiting = [
  row(1, "CHQ", "Cheque Payment", "1000.00", "Lanka Steel"),
  row(2, "CHQ", "Cheque Payment", "2000.00", "Ceylon Oxygen"),
  row(3, "ONL", "Online Payment", "500.00", "CEB"),
];

test("tabs show the pending count of each type and filter the table", async () => {
  mockApi({ "GET /api/v1/vouchers/waiting/": { body: waiting } });
  renderAt("/vouchers/approve", <DirectorPage />);

  const tabs = await screen.findByRole("tablist", { name: "Voucher types" });
  expect(await within(tabs).findByRole("tab", { name: "All (3)" })).toHaveAttribute("aria-selected", "true");
  fireEvent.click(within(tabs).getByRole("tab", { name: "Cheque Payment (2)" }));
  const table = screen.getByRole("table", { name: "Approve vouchers" });
  expect(within(table).queryByText("CEB")).not.toBeInTheDocument();
  expect(within(table).getByText("2 shown")).toBeInTheDocument();
  expect(within(table).getByText("3,000.00")).toBeInTheDocument(); // total of the rows shown
  fireEvent.click(within(tabs).getByRole("tab", { name: "All (3)" }));
  fireEvent.click(screen.getByText("Filters"));
  fireEvent.change(screen.getByLabelText("Amount from"), { target: { value: "1,500" } });
  expect(within(table).getByText("1 shown")).toBeInTheDocument();
});

test("a reject without a reason is highlighted and nothing is sent", async () => {
  const calls = mockApi({ "GET /api/v1/vouchers/waiting/": { body: waiting } });
  renderAt("/vouchers/approve", <DirectorPage />);

  fireEvent.click(await screen.findByLabelText("Reject WS261029002"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Give a reason for every voucher you reject");
  expect(screen.getByLabelText("Reject WS261029002").closest("tr")).toHaveClass("row-error");
  expect(calls.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(0);
});

test("approve all shows the count and total, then confirms them together", async () => {
  const calls = mockApi({
    "GET /api/v1/vouchers/waiting/": { body: waiting },
    "POST /api/v1/vouchers/decisions/": { body: { confirmed: 3, approved: 2, rejected: 1, fully_approved: [] } },
  });
  renderAt("/vouchers/approve", <DirectorPage />);

  await screen.findByLabelText("Approve WS261029001");
  fireEvent.click(screen.getByRole("button", { name: "Approve all" }));
  fireEvent.click(screen.getByLabelText("Reject WS261029003"));
  fireEvent.change(screen.getByLabelText("Reason for WS261029003"), { target: { value: "duplicate bill" } });
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  const check = screen.getByRole("alertdialog", { name: "Check before confirming" });
  expect(check).toHaveTextContent("Approve 2 vouchers totalling LKR 3,000.00, and reject 1?");
  fireEvent.click(within(check).getByRole("button", { name: "Yes, confirm" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/decisions/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          decisions: [
            { id: 1, decision: "approve", reason: "" },
            { id: 2, decision: "approve", reason: "" },
            { id: 3, decision: "reject", reason: "duplicate bill" },
          ],
        }),
      }),
    ),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("Done: 2 approved, 1 rejected.");
});

test("the side panel shows the scan, the accountant's comment and the payee balance", async () => {
  const detail = {
    ...waiting[0],
    voucher_type: { ...waiting[0].voucher_type, id: 1 },
    payee: { id: 11, code: "S0011", name: "Lanka Steel", category: "supplier" },
    transfer_to: null,
    lines: [
      {
        line_no: 1,
        invoice_no: "LS-77",
        invoice_date: "2026-10-20",
        description: "",
        amount: "1000.00",
        tax_code: null,
        tax_amount: "0.00",
        total: "1000.00",
        account: { id: 5, number: "5100", name: "Raw materials" },
        division: "WS",
        job_ref: "",
        splits: [],
      },
    ],
    attachments: [{ id: 7, file_name: "invoice.pdf", content_type: "application/pdf", size: 10, sha256: "x", uploaded_at: "" }],
    warnings: [],
    payee_balance: { waiting_approval: "1000.00", approved_unpaid: "0.00", outstanding: "4500.00" },
    approvals: [{ level: 2, action: "approve", user: "Kumari", reason: "coded to raw materials", acted_at: "" }],
  } as unknown as VoucherDetail;
  mockApi({
    "GET /api/v1/vouchers/waiting/": { body: waiting },
    "GET /api/v1/vouchers/1/": { body: detail },
  });
  renderAt("/vouchers/approve", <DirectorPage />);

  fireEvent.click(await screen.findByRole("button", { name: "WS261029001" }));
  const panel = await screen.findByRole("complementary", { name: "Voucher WS261029001" });
  expect(within(panel).getByTitle("invoice.pdf")).toHaveAttribute("src", "/api/v1/vouchers/1/attachments/7/");
  expect(panel).toHaveTextContent("Checked by Kumari: coded to raw materials");
  expect(panel).toHaveTextContent("outstanding on vouchers: LKR 4,500.00");
  fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
});

test("from the side panel the Director sends a voucher back to the Accountant", async () => {
  const detail = {
    ...waiting[0],
    voucher_type: { ...waiting[0].voucher_type, id: 1 },
    payee: { id: 11, code: "S0011", name: "Lanka Steel", category: "supplier" },
    transfer_to: null,
    lines: [],
    attachments: [],
    warnings: [],
    payee_balance: null,
    approvals: [],
    can_act: true,
    can_send_to_accountant: true,
  } as unknown as VoucherDetail;
  const calls = mockApi({
    "GET /api/v1/vouchers/waiting/": { body: waiting },
    "GET /api/v1/vouchers/1/": { body: detail },
    "POST /api/v1/vouchers/1/back-to-accountant/": { body: { ...detail, status: "submitted" } },
  });
  renderAt("/vouchers/approve", <DirectorPage />);

  fireEvent.click(await screen.findByRole("button", { name: "WS261029001" }));
  const panel = await screen.findByRole("complementary", { name: "Voucher WS261029001" });
  expect(within(panel).getByRole("button", { name: "Return to Clerk" })).toBeInTheDocument();
  fireEvent.change(within(panel).getByLabelText(/Send it back instead/), { target: { value: "Code it to repairs" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Send back to the Accountant" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/1/back-to-accountant/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Code it to repairs" }) }),
    ),
  );
  expect(await screen.findByText("Voucher WS261029001 was sent back.")).toBeInTheDocument();
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
});
