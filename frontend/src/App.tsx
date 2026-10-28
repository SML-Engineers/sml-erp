import { Route, Routes } from "react-router";

import AuthGate from "./components/AuthGate";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import TwoFactorSetupPage from "./pages/TwoFactorSetupPage";
import AccessReviewPage from "./pages/admin/AccessReviewPage";
import UserAccessPage from "./pages/admin/UserAccessPage";
import UsersPage from "./pages/admin/UsersPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/account/password"
        element={
          <AuthGate allowPending>
            {(user) => (
              <ChangePasswordPage
                firstTime={user.requirements.includes("password_change_required")}
              />
            )}
          </AuthGate>
        }
      />
      <Route
        path="/account/two-factor"
        element={<AuthGate allowPending>{() => <TwoFactorSetupPage />}</AuthGate>}
      />
      <Route path="/" element={<AuthGate>{(user) => <HomePage user={user} />}</AuthGate>} />
      <Route path="/admin/users" element={<AuthGate>{(me) => <UsersPage me={me} />}</AuthGate>} />
      <Route
        path="/admin/users/:id"
        element={<AuthGate>{(me) => <UserAccessPage me={me} />}</AuthGate>}
      />
      <Route
        path="/admin/access-review"
        element={<AuthGate>{(me) => <AccessReviewPage me={me} />}</AuthGate>}
      />
    </Routes>
  );
}
