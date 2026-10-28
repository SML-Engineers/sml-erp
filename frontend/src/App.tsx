import { Route, Routes } from "react-router";

import AuthGate from "./components/AuthGate";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import TwoFactorSetupPage from "./pages/TwoFactorSetupPage";

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
    </Routes>
  );
}
