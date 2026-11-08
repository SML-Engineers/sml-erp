import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Bom, BomLine, BomList } from "../api/boms";
import { mockApi, renderAt } from "../test-utils";
import BomsPage from "./BomsPage";

const line = (over: Partial<BomLine>): BomLine => ({
  seq: 10,
  line_type: "raw",
  line_type_label: "Raw material",
  component: "",
  component_name: "",
  description: "",
  supplier: "",
  quantity: "",
  unit: "",
  scrap_pct: "0",
  pct_of_resin: "",
  operation_seq: null,
  issue_method: "manual",
  customer_supplied: false,
  unit_cost: "",
  stock_size: "",
  bar_length_mm: "",
  cut_length_mm: "",
  facing_mm: "",
  saw_mm: "",
  notes: "",
  standard_value: "",
  ...over,
});

const bom: Bom = {
  id: 7,
  item: "CAP-28",
  item_name: "28 mm cap",
  item_unit: "nos",
  revision: 1,
  kind: "moulding",
  kind_label: "Moulding",
  division: "IM",
  drawing_revision: "",
  effective_from: "2026-11-08",
  base_quantity: "1000",
  mould: "MLD-001",
  reject_pct: "5",
  max_regrind_pct: "20",
  status: "awaiting",
  status_label: "Waiting for approval",
  notes: "",
  created_by: "Planner",
  outputs: [{ item: "CAP-28", name: "28 mm cap", cavities: 8, part_weight_g: "4.5" }],
  resin: { shot_g: "37.80", per_piece_g: "4.725", pieces_per_shot: 8, family: false },
  lines: [
    line({
      component: "PP-H110",
      component_name: "PP homopolymer",
      quantity: "4.725",
      unit: "kg",
      issue_method: "backflush",
      standard_value: "2126.25",
    }),
    line({
      seq: 20,
      line_type: "masterbatch",
      line_type_label: "Masterbatch",
      component: "MB-BLUE",
      component_name: "Blue masterbatch",
      quantity: "0.0945",
      unit: "kg",
      pct_of_resin: "2",
      issue_method: "backflush",
    }),
  ],
  cost: {
    material: "2126.25",
    machine: "0.00",
    labour: "0.40",
    overhead: "0.10",
    mould: "0.25",
    per_unit: "2.88",
    missing: ["MB-BLUE: no cost yet"],
  },
  returned_reason: null,
  can_edit: false,
  can_decide: true,
};
const list: BomList = {
  results: [bom],
  can_prepare: true,
  statuses: [{ value: "approved", label: "Approved" }],
  line_types: [
    { value: "raw", label: "Raw material" },
    { value: "masterbatch", label: "Masterbatch" },
    { value: "subcontract", label: "Subcontract service" },
  ],
};

test("the Production Manager sees the resin worked out and approves the BOM", async () => {
  const calls = mockApi({
    "GET /api/v1/boms/?q=&status=": { body: list },
    "POST /api/v1/boms/7/approve/": { body: { ...bom, status: "approved", status_label: "Approved", can_decide: false } },
  });
  renderAt("/boms", <BomsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "CAP-28" }));
  const panel = screen.getByRole("region", { name: "BOM CAP-28 rev 1" });
  expect(within(panel).getByText(/37.80 g of resin a shot, 4.725 g a piece \(8 a shot, 5% reject allowance\)/)).toBeInTheDocument();
  expect(within(panel).getByText("MB-BLUE: no cost yet")).toBeInTheDocument();
  expect(within(panel).getByText(/a unit: machine time LKR 0.00, labour LKR 0.40, overhead LKR 0.10, mould LKR 0.25/)).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/boms/7/approve/", expect.objectContaining({ method: "POST" })));
});

test("the planner drafts a machined part with a cut length and a plating service", async () => {
  const calls = mockApi({
    "GET /api/v1/boms/?q=&status=": { body: { ...list, results: [] } },
    "POST /api/v1/boms/": { body: { ...bom, kind: "machining", status: "draft", can_edit: true, can_decide: false }, status: 201 },
  });
  renderAt("/boms", <BomsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "New BOM" }));
  const form = screen.getByRole("region", { name: "New BOM" });
  fireEvent.change(within(form).getByLabelText("Part"), { target: { value: "SH-100" } });
  fireEvent.change(within(form).getByLabelText("Component of line 1"), { target: { value: "EN8-50" } });
  fireEvent.change(within(form).getByLabelText("Cut length of line 1"), { target: { value: "120" } });
  fireEvent.change(within(form).getByLabelText("Bar length of line 1"), { target: { value: "3000" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add line" }));
  fireEvent.change(within(form).getByLabelText("Type of line 2"), { target: { value: "subcontract" } });
  fireEvent.change(within(form).getByLabelText("Service of line 2"), { target: { value: "Hard chrome" } });
  fireEvent.change(within(form).getByLabelText("Supplier of line 2"), { target: { value: "S0100" } });
  fireEvent.change(within(form).getByLabelText("Quantity of line 2"), { target: { value: "1" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/boms/", expect.objectContaining({ method: "POST" })));
  const sent = JSON.parse((calls.mock.calls.find((c) => c[0] === "/api/v1/boms/")![1] as RequestInit).body as string);
  expect(sent.item).toBe("SH-100");
  expect(sent.kind).toBe("machining");
  expect(sent.outputs).toBeUndefined();
  expect(sent.lines.map((x: BomLine) => [x.seq, x.line_type, x.cut_length_mm || x.description])).toEqual([
    ["10", "raw", "120"],
    ["20", "subcontract", "Hard chrome"],
  ]);
});

test("where used lists the parts a material goes into", async () => {
  mockApi({
    "GET /api/v1/boms/?q=&status=": { body: list },
    "GET /api/v1/boms/where-used/?item=PP-H110": {
      body: {
        item: "PP-H110",
        name: "PP homopolymer",
        boms: [{ id: 7, item: "CAP-28", item_name: "28 mm cap", revision: 1, status: "approved", quantity: "4.725", unit: "kg" }],
      },
    },
  });
  renderAt("/boms", <BomsPage />);
  const panel = await screen.findByRole("region", { name: "Where used" });
  fireEvent.change(within(panel).getByLabelText("Material or part code"), { target: { value: "PP-H110" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Find" }));
  expect(await within(panel).findByText("CAP-28 28 mm cap rev 1 (approved): 4.725 kg")).toBeInTheDocument();
});
