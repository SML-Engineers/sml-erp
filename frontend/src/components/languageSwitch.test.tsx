import { act, fireEvent, screen } from "@testing-library/react";
import { useTranslation } from "react-i18next";

import i18n from "../i18n";
import en from "../i18n/en.json";
import si from "../i18n/si.json";
import { renderAt } from "../test-utils";
import { MENU } from "../layout/menu";
import LanguageSwitch from "./LanguageSwitch";

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

function Title() {
  const { t } = useTranslation();
  return (
    <>
      <h1>{t("shiftReport.title")}</h1>
      <p>{t("profit.figures")}</p>
    </>
  );
}

test("a supervisor switches the screens to Sinhala, kept on the device", async () => {
  renderAt(
    "/",
    <>
      <LanguageSwitch />
      <Title />
    </>,
  );
  expect(screen.getByRole("heading", { name: "Work shift report" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Language"), { target: { value: "si" } });
  expect(await screen.findByRole("heading", { name: "වැඩ මුර වාර්තාව" })).toBeInTheDocument();
  expect(screen.getByText("Estimate, actual and forecast")).toBeInTheDocument(); // not translated: English
  expect(window.localStorage.getItem("sml-language")).toBe("si");
  expect(document.documentElement.lang).toBe("si");
  expect(screen.getByLabelText("භාෂාව")).toHaveValue("si");
});

type Tree = { [key: string]: string | Tree };

function flat(tree: Tree, prefix = ""): Record<string, string> {
  return Object.entries(tree).reduce<Record<string, string>>((out, [key, value]) => {
    if (typeof value === "string") out[prefix + key] = value;
    else Object.assign(out, flat(value, `${prefix}${key}.`));
    return out;
  }, {});
}

test("every Sinhala text has its English one with the same placeholders", () => {
  const english = flat(en as unknown as Tree);
  const sinhala = flat(si as unknown as Tree);
  const holes = (text: string) => (text.match(/{{\w+}}/g) ?? []).sort().join();
  for (const [key, text] of Object.entries(sinhala)) {
    expect(english[key], key).toBeDefined();
    expect(holes(text), key).toBe(holes(english[key]));
  }
  expect(Object.keys(sinhala).length).toBeGreaterThan(200);
});

test("every side-menu heading and page name has its Sinhala wording", () => {
  const sinhala = flat(si as unknown as Tree);
  for (const section of MENU) {
    expect(sinhala[section.label], section.label).toBeDefined();
    for (const item of section.items) expect(sinhala[item.label], item.label).toBeDefined();
  }
  for (const key of Object.keys(en.home)) expect(sinhala[`home.${key}`], `home.${key}`).toBeDefined();
});
