import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { LayoutBlock, TemplatePage } from "../../api/printTemplates";
import { mockApi, renderAt } from "../../test-utils";
import PrintTemplatesPage, { fit } from "./PrintTemplatesPage";

// jsdom has no PointerEvent: a MouseEvent carries the pointer's position just the same.
if (!("PointerEvent" in window)) Object.assign(window, { PointerEvent: class extends MouseEvent {} });

const block = (key: string, x: number, y: number, w: number, h: number): LayoutBlock => ({ key, x, y, w, h, size: 9, align: "left" });

const STANDARD = {
  blocks: [
    block("letterhead", 0, 0, 182, 24),
    block("customer", 0, 27, 109, 32),
    block("lines", 0, 62, 182, 110),
    block("slogan", 0, 241, 182, 8),
  ],
};

const page = (extra: Partial<TemplatePage> = {}): TemplatePage => ({
  document: "delivery_note",
  label: "Delivery note",
  page: { width: 182, height: 269 },
  blocks: [
    { key: "letterhead", label: "Letterhead (logo, name, address)", may_hide: true },
    { key: "customer", label: "Customer and delivery address", may_hide: false },
    { key: "lines", label: "Items table", may_hide: false },
    { key: "slogan", label: "Slogan", may_hide: true },
  ],
  table: "lines",
  standard: STANDARD,
  layout: STANDARD,
  version: 2,
  history: [
    { version: 2, note: "Logo smaller", by: "Nimal Director", at: "2026-11-14T04:30:00Z" },
    { version: 1, note: "", by: "Admin", at: "2026-11-13T04:30:00Z" },
  ],
  can_edit: true,
  ...extra,
});

const LIST = {
  "GET /api/v1/print-templates/": {
    body: { documents: [{ document: "delivery_note", label: "Delivery note", version: 2 }], can_edit: true },
  },
};
const URL_ = "/api/v1/print-templates/delivery_note/";

const sentLayout = (calls: ReturnType<typeof mockApi>) => {
  const [, init] = calls.mock.calls.find(([url, i]) => url === URL_ && i?.method === "POST")!;
  return JSON.parse(String(init!.body));
};

test("a block is kept inside the page and at its smallest size", () => {
  const size = { width: 182, height: 269 };
  expect(fit(block("x", 170, -3, 30, 2), size)).toMatchObject({ x: 152, y: 0, w: 30, h: 4 });
  expect(fit(block("x", 10.4, 10.6, 300, 10), size)).toMatchObject({ x: 0, y: 11, w: 182 });
});

test("the Director moves a block with the arrow keys and saves a new version with a note", async () => {
  const calls = mockApi({ ...LIST, [`GET ${URL_}`]: { body: page() }, [`POST ${URL_}`]: { body: page({ version: 3 }) } });
  renderAt("/settings/printed-documents", <PrintTemplatesPage />);
  const customer = await screen.findByRole("button", { name: "Customer and delivery address" });
  expect(screen.getByRole("heading", { name: "Delivery note · Version 2" })).toBeInTheDocument();
  const save = screen.getByRole("button", { name: "Save as new version" });
  expect(save).toBeDisabled();
  fireEvent.focus(customer);
  fireEvent.keyDown(customer, { key: "ArrowRight" });
  fireEvent.keyDown(customer, { key: "ArrowDown" });
  fireEvent.keyDown(customer, { key: "ArrowRight", shiftKey: true });
  const form = screen.getByRole("form", { name: "Customer and delivery address" });
  expect(within(form).getByLabelText("Left (mm)")).toHaveValue(1);
  expect(within(form).getByLabelText("Top (mm)")).toHaveValue(28);
  expect(within(form).getByLabelText("Width (mm)")).toHaveValue(110);
  // The customer block must stay: it has no "leave off" box.
  expect(within(form).queryByLabelText("Leave this off the document")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("What changed (optional)"), { target: { value: "Address lower" } });
  fireEvent.click(save);
  await waitFor(() => expect(calls).toHaveBeenCalledWith(URL_, expect.objectContaining({ method: "POST" })));
  const body = sentLayout(calls);
  expect(body.note).toBe("Address lower");
  expect(body.layout.blocks.find((b: LayoutBlock) => b.key === "customer")).toMatchObject({ x: 1, y: 28, w: 110, h: 32 });
});

test("a block is dragged with the mouse or a finger, in millimetres of the page", async () => {
  const calls = mockApi({ ...LIST, [`GET ${URL_}`]: { body: page() }, [`POST ${URL_}`]: { body: page({ version: 3 }) } });
  renderAt("/settings/printed-documents", <PrintTemplatesPage />);
  const slogan = await screen.findByRole("button", { name: "Slogan" });
  const sheet = slogan.parentElement!;
  // Drawn 364 px wide: 2 px for each millimetre.
  sheet.getBoundingClientRect = () => ({
    width: 364,
    height: 538,
    left: 0,
    top: 0,
    right: 364,
    bottom: 538,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
  fireEvent.pointerDown(slogan, { clientX: 100, clientY: 500, pointerId: 1 });
  fireEvent.pointerMove(sheet, { clientX: 100, clientY: 460, pointerId: 1 });
  fireEvent.pointerUp(sheet, { pointerId: 1 });
  expect(within(screen.getByRole("form", { name: "Slogan" })).getByLabelText("Top (mm)")).toHaveValue(221);
  fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith(URL_, expect.objectContaining({ method: "POST" })));
  expect(sentLayout(calls).layout.blocks.find((b: LayoutBlock) => b.key === "slogan")).toMatchObject({ y: 221, x: 0 });
});

test("the Director leaves the slogan off and adds own text", async () => {
  const calls = mockApi({ ...LIST, [`GET ${URL_}`]: { body: page() }, [`POST ${URL_}`]: { body: page({ version: 3 }) } });
  renderAt("/settings/printed-documents", <PrintTemplatesPage />);
  fireEvent.focus(await screen.findByRole("button", { name: "Slogan" }));
  fireEvent.click(screen.getByLabelText("Leave this off the document"));
  fireEvent.click(screen.getByRole("button", { name: "Add a text block" }));
  const form = screen.getByRole("form", { name: "Your text" });
  fireEvent.change(within(form).getByLabelText("Text"), { target: { value: "Goods once sold are not returnable" } });
  fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith(URL_, expect.objectContaining({ method: "POST" })));
  const blocks = sentLayout(calls).layout.blocks as LayoutBlock[];
  expect(blocks.find((b) => b.key === "slogan")?.hidden).toBe(true);
  expect(blocks.find((b) => b.key === "text-1")).toMatchObject({ text: "Goods once sold are not returnable", w: 60, h: 10 });
});

test("an old version is brought back from the history", async () => {
  const calls = mockApi({ ...LIST, [`GET ${URL_}`]: { body: page() }, [`POST ${URL_}`]: { body: page({ version: 3 }) } });
  renderAt("/settings/printed-documents", <PrintTemplatesPage />);
  const history = await screen.findByRole("region", { name: "History" });
  const rows = within(history).getAllByRole("row");
  // The version in use has no button.
  expect(within(rows[1]).queryByRole("button")).not.toBeInTheDocument();
  fireEvent.click(within(rows[2]).getByRole("button", { name: "Bring back" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith(URL_, expect.objectContaining({ method: "POST" })));
  expect(sentLayout(calls)).toEqual({ restore: 1 });
});

test("the preview shows the server's reason when it cannot print", async () => {
  mockApi({
    ...LIST,
    [`GET ${URL_}`]: { body: page() },
    [`POST ${URL_}preview/`]: { status: 400, body: { detail: "Make a delivery note first: the preview prints the latest one." } },
  });
  renderAt("/settings/printed-documents", <PrintTemplatesPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Make a delivery note first");
});

test("other users see the layout and its history but cannot change it", async () => {
  mockApi({ ...LIST, [`GET ${URL_}`]: { body: page({ can_edit: false }) } });
  renderAt("/settings/printed-documents", <PrintTemplatesPage />);
  expect(await screen.findByText(/Only the Admin and the Director change the layout/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save as new version" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Preview" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add a text block" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Bring back" })).not.toBeInTheDocument();
  fireEvent.focus(screen.getByRole("button", { name: "Slogan" }));
  expect(within(screen.getByRole("form", { name: "Slogan" })).getByLabelText("Top (mm)")).toBeDisabled();
});
