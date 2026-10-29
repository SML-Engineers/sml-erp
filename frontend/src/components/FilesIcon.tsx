import { useTranslation } from "react-i18next";

/** A small paperclip after a voucher number: the voucher has scanned files. Drawn, not an
 * emoji, so it looks the same on every computer. */
export default function FilesIcon() {
  const { t } = useTranslation();
  return (
    <svg className="files-icon" role="img" aria-label={t("vouchers.hasFiles")} viewBox="0 0 16 16" width="14" height="14">
      <title>{t("vouchers.hasFiles")}</title>
      <path
        d="M10.5 4.5 5.4 9.6a1.5 1.5 0 0 0 2.1 2.1l5.3-5.3a3 3 0 0 0-4.2-4.2L3.2 7.6a4.5 4.5 0 0 0 6.4 6.4l4.4-4.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
