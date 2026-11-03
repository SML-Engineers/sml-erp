import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { StatementTemplate } from "../api/bankStatements";
import { mockApi, renderAt } from "../test-utils";
import BankStatementsPage from "./BankStatementsPage";

const combank: StatementTemplate = {
  id: 1, code: "COMBANK-PDF", bank_name: "Commercial Bank of Ceylon", file_kind: "pdf", date_format: "%d/%m/%Y",
  date_column: "Date", description_column: "Description", reference_column: "", out_column: "Debit",
  in_column: "Credit", amount_column: "", negative_is_out: true, balance_column: "Balance", checked: false,
  notes: "", is_active: true,
};

const line = { date: "2026-10-01", description: "CHQ DEP 004512", reference: "", money_out: "0.00", money_in: "20000.00", balance: "120000.00" };

test("the accountant reads a statement, checks it, then imports it", async () => {
  const calls = mockApi({
    "GET /api/v1/bank-statements/": { body: [] },
    "GET /api/v1/statement-templates/": { body: [combank] },
    "GET /api/v1/payments/accounts/": {
      body: [{ id: 2, code: "COM-CUR", name: "Commercial Bank current", kind: "current", currency: "LKR", has_ledger: true, next_cheque: null }],
    },
    "POST /api/v1/bank-statements/import/": (sent) =>
      (sent as FormData).get("preview")
        ? { body: { opening: "100000.00", lines: [{ ...line, already: false }], problems: [] } }
        : { status: 201, body: { id: 9 } },
  });
  renderAt("/bank-statements", <BankStatementsPage />);
  const form = await screen.findByRole("form", { name: "Import a statement" });
  await within(form).findByRole("option", { name: "COM-CUR Commercial Bank current" });
  fireEvent.change(within(form).getByLabelText("Bank account"), { target: { value: "2" } });
  await within(form).findByRole("option", { name: /Commercial Bank of Ceylon/ });
  fireEvent.change(within(form).getByLabelText("Bank and file"), { target: { value: "1" } });
  const file = new File(["%PDF-1.4"], "statement.pdf", { type: "application/pdf" });
  fireEvent.change(within(form).getByLabelText("Statement file"), { target: { files: [file] } });
  fireEvent.click(within(form).getByRole("button", { name: "Read and check" }));
  expect(await within(form).findByText("CHQ DEP 004512")).toBeInTheDocument();
  expect(within(form).getByText("Opening balance 100,000.00")).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Import these lines" }));
  await waitFor(() =>
    expect(calls.mock.calls.filter(([url]) => url === "/api/v1/bank-statements/import/")).toHaveLength(2),
  );
});
