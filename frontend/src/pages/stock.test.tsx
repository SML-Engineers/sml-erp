import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { mockApi, renderAt } from "../test-utils";
import StockPage from "./StockPage";

const row = (store: string, kind: "main" | "rejected", quantity: string, value: string, cost: string | null) => ({
  item: { id: 5, code: "PP-H-WHITE", name: "PP homopolymer", unit: "kg" },
  store: { id: store === "IM-MAIN" ? 1 : 2, code: store, kind, division: "IM" },
  lot_no: null,
  quantity,
  value,
  average_cost: cost,
});

test("stock on hand shows quantity and value per store, and an item's movements", async () => {
  const calls = mockApi({
    "GET /api/v1/stock/": {
      body: {
        total_value: "31500.00",
        rows: [row("IM-MAIN", "main", "75.000", "31500.00", "420.0000"), row("IM-REJ", "rejected", "25.000", "0.00", null)],
      },
    },
    "GET /api/v1/stock/movements/?item=5": {
      body: [
        {
          id: 1,
          date: "2026-11-01",
          kind: "accepted",
          item: { id: 5, code: "PP-H-WHITE", unit: "kg" },
          store: "IM-MAIN",
          lot_no: "GRN26110101-1-001",
          quantity: "25.000",
          value: "10500.00",
          grn: { id: 4, number: "GRN26110101" },
          journal: "JE26110001",
          by: "QC",
        },
      ],
    },
  });
  renderAt("/stock", <StockPage />);
  const table = await screen.findByRole("table", { name: "Stock on hand" });
  expect(within(table).getAllByText("75 kg").length).toBeGreaterThan(0);
  expect(within(table).getAllByText("31,500.00").length).toBeGreaterThan(0);
  expect(within(table).getAllByText("IM-REJ · rejected").length).toBeGreaterThan(0);
  expect(screen.getByText("Total value: LKR 31,500.00")).toBeInTheDocument();
  fireEvent.click(within(table).getAllByRole("button", { name: /PP-H-WHITE/ })[0]);
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/stock/movements/?item=5", expect.anything()));
  const moves = await screen.findByRole("table", { name: "Movements" });
  expect(within(moves).getByText("Accepted by QC")).toBeInTheDocument();
  expect(within(moves).getByRole("link", { name: "GRN26110101" })).toHaveAttribute("href", "/goods-receipts/4");
});
