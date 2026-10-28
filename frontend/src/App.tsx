import type { ReactNode } from "react";
import { Route, Routes } from "react-router";

import type { CurrentUser } from "./api/auth";
import AuthGate from "./components/AuthGate";
import AppLayout, { useMe } from "./layout/AppLayout";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import TwoFactorSetupPage from "./pages/TwoFactorSetupPage";
import AccessReviewPage from "./pages/admin/AccessReviewPage";
import AuditLogPage from "./pages/admin/AuditLogPage";
import UserAccessPage from "./pages/admin/UserAccessPage";
import UsersPage from "./pages/admin/UsersPage";
import CompanyPage from "./pages/settings/CompanyPage";
import DivisionsPage from "./pages/settings/DivisionsPage";
import FactoryPage from "./pages/settings/FactoryPage";
import NumberSeriesPage from "./pages/settings/NumberSeriesPage";
import ShiftsPage from "./pages/settings/ShiftsPage";

/** Hands the signed-in user (from the layout) to a page. */
function WithMe({ page }: { page: (me: CurrentUser) => ReactNode }) {
  return <>{page(useMe())}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/account/two-factor"
        element={<AuthGate allowPending>{() => <TwoFactorSetupPage />}</AuthGate>}
      />
      <Route
        path="/account/password"
        element={
          <AuthGate allowPending>
            {(user) =>
              user.requirements.includes("password_change_required") ? (
                <ChangePasswordPage firstTime />
              ) : (
                <AppLayout user={user} />
              )
            }
          </AuthGate>
        }
      >
        <Route index element={<ChangePasswordPage />} />
      </Route>

      {/* Every signed-in page sits inside the layout: side menu, top bar, user menu. */}
      <Route element={<AuthGate>{(user) => <AppLayout user={user} />}</AuthGate>}>
        <Route index element={<WithMe page={(me) => <HomePage user={me} />} />} />
        <Route path="admin/users" element={<WithMe page={(me) => <UsersPage me={me} />} />} />
        <Route
          path="admin/users/:id"
          element={<WithMe page={(me) => <UserAccessPage me={me} />} />}
        />
        <Route
          path="admin/access-review"
          element={<WithMe page={(me) => <AccessReviewPage me={me} />} />}
        />
        <Route path="admin/audit" element={<AuditLogPage />} />
        <Route
          path="settings/company"
          element={<WithMe page={(me) => <CompanyPage me={me} />} />}
        />
        <Route
          path="settings/divisions"
          element={<WithMe page={(me) => <DivisionsPage me={me} />} />}
        />
        <Route
          path="settings/factory"
          element={<WithMe page={(me) => <FactoryPage me={me} />} />}
        />
        <Route
          path="settings/shifts"
          element={<WithMe page={(me) => <ShiftsPage me={me} />} />}
        />
        <Route
          path="settings/number-series"
          element={<WithMe page={(me) => <NumberSeriesPage me={me} />} />}
        />
      </Route>
    </Routes>
  );
}
