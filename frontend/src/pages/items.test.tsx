import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { Item, ItemOptions, Store } from "../api/items";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import ItemsPage from "./ItemsPage";
import StoresPage from "./settings/StoresPage";

const options: ItemOptions = {
  can_enter: true,
  can_set_accounts: false,
  categories: [
    { value: "raw_material", label: "Raw material" },
    { value: "consumable", label: "Consumable" },
  ],
  units: ["pcs", "kg"],
  package_types: [
    { value: "none", label: "Not by package" },
    { value: "bag", label: "Bags (resin, masterbatch)" },
  ],
  inventory_accounts: [{ number: "1210", name: "Raw materials" }],
  expense_accounts: [],
  materials: [],
};

const resin: Item = {
  id: 5, code: "PP-H-WHITE", name: "PP homopolymer, white", description: "", category: "raw_material", unit: "kg",
  is_stock: true, package_type: "bag", inspection_required: true, package_tare: "0.100", weight_tolerance_pct: "0.50", standard_kg_per_m: null, density: null, inventory_account: { number: "1210", name: "Raw materials" },
  expense_account: null, material: null, division: null, notes: "", is_active: true, used: true,
};

const divisions = {
  "GET /api/v1/divisions/": {
    body: [
      { id: 1, code: "HO", name: "Head Office", division_type: "shared" },
      { id: 2, code: "IM", name: "Moulding", division_type: "production" },
    ],
  },
};

test("the buyer adds an item; accounts are left to the Accountant", async () => {
  const calls = mockApi({
    "GET /api/v1/items/options/": { body: options },
    "GET /api/v1/items/": { body: [resin] },
    "POST /api/v1/items/": { status: 201, body: { ...resin, id: 6, code: "INS-M6", used: false } },
    ...divisions,
  });
  renderAt("/items", <ItemsPage />);
  const table = await screen.findByRole("table", { name: "Items" });
  expect(within(table).getByText("PP-H-WHITE")).toBeInTheDocument();
  expect(within(table).getByText("Raw material")).toBeInTheDocument();
  expect(within(table).getByText("1210")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Add item" }));
  const form = screen.getByRole("form", { name: "Item details" });
  fireEvent.change(within(form).getByLabelText("Code"), { target: { value: "ins-m6" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Brass insert M6" } });
  fireEvent.change(within(form).getByLabelText("Unit"), { target: { value: "pcs" } });
  expect(within(form).getByLabelText("Inventory account")).toBeDisabled();
  expect(screen.getByText(/The Accountant chooses an item's accounts/)).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/items/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/items/" && i?.method === "POST")!;
  const sent = JSON.parse(String(init!.body));
  expect(sent).toMatchObject({ code: "INS-M6", name: "Brass insert M6", unit: "pcs", is_stock: true });
  expect(sent).not.toHaveProperty("inventory_account");
});

test("a used item keeps its code and is deactivated with a reason", async () => {
  const calls = mockApi({
    "GET /api/v1/items/options/": { body: options },
    "GET /api/v1/items/": { body: [resin] },
    "POST /api/v1/items/5/active/": { body: { ...resin, is_active: false } },
    ...divisions,
  });
  renderAt("/items", <ItemsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "PP homopolymer, white" }));
  const form = screen.getByRole("form", { name: "Item details" });
  expect(within(form).getByLabelText("Code")).toBeDisabled();
  expect(within(form).queryByRole("button", { name: "Remove (never used)" })).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Grade discontinued" } });
  fireEvent.click(within(form).getByRole("button", { name: "Deactivate" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/items/5/active/",
      expect.objectContaining({ body: JSON.stringify({ active: false, reason: "Grade discontinued" }) }),
    ),
  );
});

test("the Admin sees each division's stores and adds one", async () => {
  const admin: CurrentUser = { ...sampleUser, access: { areas: { settings: ["manage", "view"] }, actions: [], divisions: "all" } };
  const stores: Store[] = [
    { id: 1, code: "IM-MAIN", name: "Moulding: Main store", division: "IM", kind: "main", is_active: true, used: false },
    { id: 2, code: "IM-QUAR", name: "Moulding: Quarantine", division: "IM", kind: "quarantine", is_active: true, used: false },
  ];
  const calls = mockApi({
    "GET /api/v1/stores/": { body: stores },
    "POST /api/v1/stores/": { status: 201, body: { ...stores[0], id: 3, code: "IM-RESIN" } },
    ...divisions,
  });
  renderAt("/settings/stores", <StoresPage me={admin} />);
  const table = await screen.findByRole("table", { name: "Stores" });
  expect(within(table).getByText("Quarantine (waiting for QC)")).toBeInTheDocument();
  expect(within(table).getAllByRole("button", { name: "Deactivate" })).toHaveLength(1); // main stores only
  const form = screen.getByRole("form", { name: "Add a store" });
  fireEvent.change(within(form).getByLabelText("Code"), { target: { value: "im-resin" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Resin store" } });
  await waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(2));
  fireEvent.change(within(form).getByLabelText("Division"), { target: { value: "IM" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add a store" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/stores/",
      expect.objectContaining({ body: JSON.stringify({ code: "IM-RESIN", name: "Resin store", division: "IM", kind: "main" }) }),
    ),
  );
});
