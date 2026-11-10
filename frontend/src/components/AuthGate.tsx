import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation } from "react-router";

import { getMe, meQueryKey, type CurrentUser } from "../api/auth";
import { isNetworkError, keepMe, keptMe } from "../lib/offline";

/** P3-21: without a connection, the sign-in last confirmed on this device opens the screens;
 * the server still checks every request when it is reached. */
async function meOrKept() {
  try {
    const me = await getMe();
    keepMe(me);
    return me;
  } catch (error) {
    const kept = isNetworkError(error) ? keptMe() : null;
    if (!kept) throw error;
    return kept;
  }
}

interface Props {
  children: (user: CurrentUser) => ReactNode;
  /** Pages that finish sign-in (change password, two-factor setup) are reachable while those
   *  steps are still outstanding; every other page is not. */
  allowPending?: boolean;
}

export const REQUIREMENT_PAGES = {
  password_change_required: "/account/password",
  two_factor_setup_required: "/account/two-factor",
} as const;

export default function AuthGate({ children, allowPending = false }: Props) {
  const { t } = useTranslation();
  const location = useLocation();
  const me = useQuery({ queryKey: meQueryKey, queryFn: meOrKept, retry: false });

  if (me.isPending) return <p className="page-message">{t("common.loading")}</p>;
  if (me.isError) return <p className="page-message">{t("home.unreachable")}</p>;
  if (!me.data.authenticated) return <Navigate to="/login" replace state={{ from: location }} />;

  const pending = me.data.user.requirements[0];
  if (pending && !allowPending) return <Navigate to={REQUIREMENT_PAGES[pending]} replace />;
  return <>{children(me.data.user)}</>;
}
