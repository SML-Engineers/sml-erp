import { can, canDo, worksIn, type Access } from "./access";

const clerk: Access = {
  areas: { dashboard: ["view"], vouchers: ["enter", "view"] },
  actions: [],
  divisions: ["IM"],
};

test("checks area levels as sent by the server", () => {
  expect(can(clerk, "vouchers", "enter")).toBe(true);
  expect(can(clerk, "vouchers")).toBe(true);
  expect(can(clerk, "vouchers", "approve")).toBe(false);
  expect(can(clerk, "payments")).toBe(false);
});

test("checks special actions", () => {
  expect(canDo(clerk, "record_payment")).toBe(false);
  expect(canDo({ ...clerk, actions: ["record_payment"] }, "record_payment")).toBe(true);
});

test("checks divisions", () => {
  expect(worksIn(clerk, "IM")).toBe(true);
  expect(worksIn(clerk, "WS")).toBe(false);
  expect(worksIn({ ...clerk, divisions: "all" }, "WS")).toBe(true);
});

test("no access when nothing is known", () => {
  expect(can(undefined, "dashboard")).toBe(false);
  expect(worksIn(undefined, "IM")).toBe(false);
});
