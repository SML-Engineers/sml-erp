import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";

import SearchSelect from "./SearchSelect";

const options = [
  { value: "S0001", label: "S0001 Polymer Resins Lanka (Pvt) Ltd" },
  { value: "S0002", label: "S0002 Polychem Traders" },
  { value: "S0003", label: "S0003 Lanka Steel (Pvt) Ltd" },
];

function Box() {
  const [value, setValue] = useState("");
  return (
    <>
      <SearchSelect label="Supplier" options={options} value={value} onChange={setValue} />
      <p>Chosen: {value || "none"}</p>
    </>
  );
}

test("type, then Enter chooses the first match (testing T40)", () => {
  render(<Box />);
  const box = screen.getByRole("combobox", { name: "Supplier" });
  fireEvent.change(box, { target: { value: "poly" } });
  const list = screen.getByRole("listbox", { name: "Supplier" });
  expect(within(list).getAllByRole("option")).toHaveLength(2);
  expect(within(list).getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(box, { key: "Enter" });
  expect(screen.getByText("Chosen: S0001")).toBeInTheDocument();
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

test("↓ and ↑ move, Enter chooses, Esc closes without choosing", () => {
  render(<Box />);
  const box = screen.getByRole("combobox", { name: "Supplier" });
  // ↓ on a closed box opens it on the first entry.
  fireEvent.keyDown(box, { key: "ArrowDown" });
  const list = screen.getByRole("listbox", { name: "Supplier" });
  expect(within(list).getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(box, { key: "ArrowDown" });
  fireEvent.keyDown(box, { key: "ArrowDown" });
  fireEvent.keyDown(box, { key: "ArrowUp" });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(screen.getByText("Chosen: S0002")).toBeInTheDocument();

  fireEvent.change(box, { target: { value: "steel" } });
  fireEvent.keyDown(box, { key: "Escape" });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(screen.getByText("Chosen: S0002")).toBeInTheDocument();
});
