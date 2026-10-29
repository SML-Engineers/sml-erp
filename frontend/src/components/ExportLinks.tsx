import { useTranslation } from "react-i18next";

import { exportUrl } from "../api/vouchers";

/** "Excel" and "PDF" download links for a list or report, with its current filters. */
export default function ExportLinks({ path, params = {}, label }: { path: string; params?: Record<string, string>; label: string }) {
  const { t } = useTranslation();
  return (
    <span className="export-links" role="group" aria-label={t("exports.of", { what: label })}>
      <a className="button-link small secondary" href={exportUrl(path, params, "xlsx")}>
        {t("exports.excel")}
      </a>{" "}
      <a className="button-link small secondary" href={exportUrl(path, params, "pdf")}>
        {t("exports.pdf")}
      </a>
    </span>
  );
}
