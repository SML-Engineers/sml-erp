import { useTranslation } from "react-i18next";

import { LANGUAGES } from "../i18n";

/** P3-21: choose the language of the screens on this device. */
export default function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  return (
    <label className="language-switch">
      {t("layout.language")}
      <select value={i18n.language} onChange={(e) => void i18n.changeLanguage(e.target.value)}>
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code} lang={l.code}>
            {l.name}
          </option>
        ))}
      </select>
    </label>
  );
}
