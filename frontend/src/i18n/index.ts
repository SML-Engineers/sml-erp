import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import si from "./si.json";

/** P3-21: English, and Sinhala for the shop-floor pages (machine translation, to be checked
 * by a Sinhala reader before go-live). Wording without a Sinhala version shows in English.
 * The choice is kept on the device, so a supervisor's phone stays in Sinhala. */
export const LANGUAGES = [
  { code: "en", name: "English" },
  { code: "si", name: "සිංහල" },
] as const;

const KEY = "sml-language";

function stored(): string {
  try {
    const found = window.localStorage.getItem(KEY);
    return LANGUAGES.some((l) => l.code === found) ? (found as string) : "en";
  } catch {
    return "en";
  }
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, si: { translation: si } },
  lng: stored(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

function keep(code: string) {
  document.documentElement.lang = code;
  try {
    window.localStorage.setItem(KEY, code);
  } catch {
    // Private browsing: the choice lasts until the page is closed.
  }
}

document.documentElement.lang = i18n.language;
i18n.on("languageChanged", keep);

export default i18n;
