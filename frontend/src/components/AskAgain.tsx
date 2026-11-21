import { useTranslation } from "react-i18next";

/** "SO26112001 already exists for this quotation. Make another sales order?" with Yes / No
 * (testing T17, 21 Nov 2026), so a second order or proforma isn't made by mistake. */
export default function AskAgain(props: { question: string; yes: string; busy: boolean; onYes: () => void; onNo: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="notice notice-warn" role="alertdialog" aria-label={props.question}>
      <p>{props.question}</p>
      <button type="button" disabled={props.busy} onClick={props.onYes}>
        {props.yes}
      </button>{" "}
      <button type="button" className="secondary" onClick={props.onNo}>
        {t("common.no")}
      </button>
    </div>
  );
}
