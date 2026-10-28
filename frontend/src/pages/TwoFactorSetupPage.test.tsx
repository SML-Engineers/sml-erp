import { fireEvent, screen } from "@testing-library/react";

import { mockApi, renderAt } from "../test-utils";
import TwoFactorSetupPage from "./TwoFactorSetupPage";

test("shows the QR code, then the recovery codes once the code is confirmed", async () => {
  const api = mockApi({
    "POST /api/v1/auth/two-factor/setup/": {
      body: {
        secret: "JBSWY3DPEHPK3PXP",
        otpauth_uri: "otpauth://totp/SML%20ERP:director@sml.lk?secret=JBSWY3DPEHPK3PXP",
        qr_svg_data_uri: "data:image/svg+xml,%3Csvg%3E%3C/svg%3E",
      },
    },
    "POST /api/v1/auth/two-factor/confirm/": {
      body: { recovery_codes: ["ABCDE-FGHJK", "LMNPQ-RSTUV"] },
    },
  });
  renderAt("/account/two-factor", <TwoFactorSetupPage />);

  expect(await screen.findByAltText("QR code for your authenticator app")).toBeInTheDocument();
  expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Code"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Turn on" }));

  expect(await screen.findByText("ABCDE-FGHJK")).toBeInTheDocument();
  expect(screen.getByText("LMNPQ-RSTUV")).toBeInTheDocument();
  const setupCalls = api.mock.calls.filter(([url]) => url === "/api/v1/auth/two-factor/setup/");
  expect(setupCalls).toHaveLength(1);
});
