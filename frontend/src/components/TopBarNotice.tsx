import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { getNotice, noticeKey } from "../api/notice";

/** The notice in the top bar (owner, 21 Nov 2026): English on top and Sinhala below, whatever
 * language the person chose. On a phone it sits just under the bar ("place"). */
export default function TopBarNotice({ place }: { place: "bar" | "page" }) {
  const { t } = useTranslation();
  const notice = useQuery({ queryKey: noticeKey, queryFn: getNotice, staleTime: 5 * 60 * 1000, retry: false });
  if (!notice.data?.show) return null;
  return (
    <div className={`top-notice top-notice-${place}`} role="note" aria-label={t("notice.label")}>
      <p lang="en">{notice.data.text_en}</p>
      <p lang="si">{notice.data.text_si}</p>
    </div>
  );
}
