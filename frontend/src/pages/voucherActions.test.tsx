import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { CurrentUser } from "../api/auth";
import type { VoucherDetail, VoucherSummary, VoucherType } from "../api/vouchers";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import DeletedVouchersPage from "./DeletedVouchersPage";
import VoucherPage from "./VoucherPage";
import VouchersPage from "./VouchersPage";

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { vouchers: ["approve", "view"] }, actions: ["delete_submitted_voucher"], divisions: "all" },
};

const row = (id: number, status: VoucherSummary["status"], actions: VoucherSummary["actions"]): VoucherSummary => ({
  id,
  number: `WS26102900${id}`,
  status,
  voucher_type: { code: "CHQ", name: "Cheque Payment" },
  division: "WS",
  payee: { id: 3, name: "Lanka Steel" },
  voucher_date: "2026-10-29",
  total_amount: "1000.00",
  created_by: "Nimal",
  attachments: 2,
  actions,
});

const listApi = (rows: VoucherSummary[], extra = {}) => ({
  "GET /api/v1/vouchers/": { body: rows },
  "GET /api/v1/voucher-types/": { body: [] },
  ...extra,
});

const cheque: VoucherType = {
  id: 1,
  code: "CHQ",
  name: "Cheque Payment",
  payment_method: "cheque",
  needs_payee: true,
  payee_category: "",
  is_advance: false,
  notes: "",
  sort_order: 10,
  is_active: true,
  in_use: true,
};

const detail: VoucherDetail = {
  ...row(5, "accountant_approved", ["resources", "print", "revise", "delete"]),
  voucher_type: cheque,
  payee: { id: 3, code: "S0003", name: "Lanka Steel", category: "supplier" },
  transfer_to: null,
  description: "Steel",
  created_by_id: 1,
  created_at: "2026-10-29T08:00:00Z",
  submitted_at: "2026-10-29T08:05:00Z",
  revision: 0,
  amendment_reason: "",
  parent: null,
  revisions: [],
  lines: [
    {
      line_no: 1,
      invoice_no: "LS-1",
      invoice_date: "2026-10-28",
      description: "",
      amount: "1000.00",
      tax_code: null,
      tax_amount: "0.00",
      total: "1000.00",
      account: null,
      division: "WS",
      job_ref: "",
      splits: [],
    },
  ],
  attachments: [
    { id: 7, file_name: "invoice.pdf", content_type: "application/pdf", size: 10, sha256: "a", uploaded_at: "" },
    { id: 8, file_name: "delivery.jpg", content_type: "image/jpeg", size: 10, sha256: "b", uploaded_at: "" },
  ],
  warnings: [],
  can_edit: false,
  payee_balance: null,
  approvals: [],
  waiting_level: 3,
  waiting_for: "Director",
  can_act: true,
  uncoded_lines: [],
};

function openMenu(number: string) {
  fireEvent.click(screen.getByRole("button", { name: `Actions for ${number}` }));
  return screen.getByRole("menu", { name: `Actions for ${number}` });
}

test("each row's menu shows only the actions the person may take", async () => {
  mockApi(
    listApi([
      row(1, "draft", ["resources", "print", "edit", "delete"]),
      row(2, "submitted", ["resources", "print", "edit_coding"]),
      row(3, "accountant_approved", ["resources", "print", "revise"]),
    ]),
  );
  renderAt("/vouchers", <VouchersPage me={director} />);

  await screen.findByRole("button", { name: "Actions for WS261029001" });
  let menu = openMenu("WS261029001");
  const items = within(menu)
    .getAllByRole("menuitem")
    .map((i) => i.textContent);
  expect(items).toEqual(["Resources", "Print", "Edit", "Delete"]);
  expect(within(menu).getByRole("menuitem", { name: "Edit" })).toHaveAttribute("href", "/vouchers/1");

  menu = openMenu("WS261029002");
  expect(
    within(menu)
      .getAllByRole("menuitem")
      .map((i) => i.textContent),
  ).toEqual(["Resources", "Print", "Edit"]);
  expect(within(menu).getByRole("menuitem", { name: "Edit" })).toHaveAttribute("href", "/vouchers/review?open=2");

  menu = openMenu("WS261029003");
  expect(within(menu).getByRole("menuitem", { name: "Edit" })).toHaveAttribute("href", "/vouchers/3?edit=1");
  expect(within(menu).queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
});

test("deleting a submitted voucher needs a reason", async () => {
  const calls = mockApi(
    listApi([row(2, "submitted", ["resources", "print", "delete"])], {
      "POST /api/v1/vouchers/2/delete/": { body: { ...detail, id: 2, status: "deleted" } },
    }),
  );
  renderAt("/vouchers", <VouchersPage me={director} />);

  await screen.findByRole("button", { name: "Actions for WS261029002" });
  fireEvent.click(within(openMenu("WS261029002")).getByRole("menuitem", { name: "Delete" }));
  const dialog = screen.getByRole("dialog", { name: "Delete voucher WS261029002" });
  const confirm = within(dialog).getByRole("button", { name: "Delete voucher" });
  expect(confirm).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText("Reason (required)"), { target: { value: "Entered twice" } });
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/2/delete/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Entered twice" }) }),
    ),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("print opens the PDF on the chosen paper", async () => {
  mockApi(listApi([row(1, "director_approved", ["resources", "print"])]));
  const open = vi.spyOn(window, "open").mockImplementation(() => null);
  renderAt("/vouchers", <VouchersPage me={director} />);

  await screen.findByRole("button", { name: "Actions for WS261029001" });
  fireEvent.click(within(openMenu("WS261029001")).getByRole("menuitem", { name: "Print" }));
  const dialog = screen.getByRole("dialog", { name: "Print voucher WS261029001" });
  fireEvent.click(within(dialog).getByLabelText("A5"));
  fireEvent.click(within(dialog).getByRole("button", { name: "Open PDF" }));
  expect(open).toHaveBeenCalledWith("/api/v1/vouchers/1/print/?paper=A5", "_blank", "noopener");
  open.mockRestore();
});

test("resources pages through the files, zooms and rotates", async () => {
  mockApi(listApi([row(5, "accountant_approved", ["resources", "print"])], { "GET /api/v1/vouchers/5/": { body: detail } }));
  renderAt("/vouchers", <VouchersPage me={director} />);

  await screen.findByRole("button", { name: "Actions for WS261029005" });
  fireEvent.click(within(openMenu("WS261029005")).getByRole("menuitem", { name: "Resources" }));
  const viewer = screen.getByRole("dialog", { name: "Files of voucher WS261029005" });
  expect(await within(viewer).findByTitle("invoice.pdf")).toHaveAttribute("src", "/api/v1/vouchers/5/attachments/7/");
  expect(within(viewer).getByText(/File 1 of 2/)).toBeInTheDocument();
  fireEvent.click(within(viewer).getByRole("button", { name: "Next" }));
  const image = within(viewer).getByAltText("delivery.jpg");
  fireEvent.click(within(viewer).getByRole("button", { name: "Rotate" }));
  fireEvent.click(within(viewer).getByRole("button", { name: "Zoom in" }));
  expect(image).toHaveStyle({ transform: "rotate(90deg) scale(1.25)" });
  expect(within(viewer).getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/v1/vouchers/5/attachments/8/?download=1");
  fireEvent.click(within(viewer).getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("the Director changes the amount; the voucher goes back to the Accountant", async () => {
  let latest: VoucherDetail = detail;
  const calls = mockApi({
    "GET /api/v1/vouchers/5/": () => ({ body: latest }),
    "GET /api/v1/voucher-types/": { body: [cheque] },
    "GET /api/v1/taxes/": { body: { components: [], codes: [] } },
    "GET /api/v1/vouchers/transfer-accounts/": { body: [] },
    "GET /api/v1/vouchers/payee-balance/3/": { body: { waiting_approval: "0.00", approved_unpaid: "0.00", outstanding: "0.00" } },
    "PATCH /api/v1/vouchers/5/revise/": () => {
      latest = {
        ...detail,
        status: "submitted",
        total_amount: "1200.00",
        actions: ["resources", "print", "delete"],
        approvals: [
          {
            level: 3,
            action: "send_down",
            user: "Mewantha",
            acted_at: "2026-10-29T10:00:00Z",
            reason: "Changed: Line 1 amount: 1,000.00 → 1,200.00; Total: 1,000.00 → 1,200.00",
          },
        ],
      };
      return { body: latest };
    },
  });
  renderAt("/vouchers/5?edit=1", <VoucherPage me={director} />, "/vouchers/:id");

  expect(await screen.findByRole("note")).toHaveTextContent("sends the voucher back to the Accountant");
  fireEvent.change(screen.getByLabelText("Amount, line 1"), { target: { value: "1200.00" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/5/revise/", expect.objectContaining({ method: "PATCH" })));
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "PATCH")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({ voucher_type: "CHQ", payee: 3, lines: [{ amount: "1200.00" }] });
  expect(await screen.findByText(/Changed by Mewantha and sent back for checking/)).toHaveTextContent("Line 1 amount: 1,000.00 → 1,200.00");
});

test("deleted vouchers are listed with who, when and why", async () => {
  mockApi({
    "GET /api/v1/vouchers/deleted/": {
      body: [
        {
          ...row(4, "deleted", ["resources", "print"]),
          deleted: { at: "2026-10-29T11:00:00Z", by: "Mewantha", reason: "Entered twice" },
        },
      ],
    },
  });
  renderAt("/vouchers/deleted", <DeletedVouchersPage />);

  const table = await screen.findByRole("table", { name: "Deleted vouchers" });
  expect(within(table).getByText("Entered twice")).toBeInTheDocument();
  expect(within(table).getByText("Mewantha")).toBeInTheDocument();
  expect(within(table).getByRole("button", { name: "Actions for WS261029004" })).toBeInTheDocument();
});
