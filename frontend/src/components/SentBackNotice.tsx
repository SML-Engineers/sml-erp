import { useTranslation } from "react-i18next";

import type { VoucherDetail } from "../api/vouchers";

/** The notice at the top of a voucher sent back to the Accountant: by the Director (to check
 * or correct), or after a later approver changed it (to check the change). */
export function SentBackNotice({ approvals }: { approvals: VoucherDetail["approvals"] }) {
  const { t } = useTranslation();
  const last = approvals.at(-1);
  if (last?.action !== "send_down" && last?.action !== "to_accountant") return null;
  return (
    <p className="notice change-notice" role="status">
      {t(last.action === "to_accountant" ? "voucherActions.toAccountant" : "voucherActions.sentBack", { name: last.user })} {last.reason}
    </p>
  );
}
