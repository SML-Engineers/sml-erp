import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { CurrentUser } from "../../api/auth";
import type { EmailTemplate, MailAccount } from "../../api/documentEmail";
import SendEmailForm from "../../components/SendEmailForm";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import DocumentEmailPage from "./DocumentEmailPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const account: MailAccount = {
  from_name: "SML Engineers Finance",
  from_address: "finance@smlengineers.lk",
  reply_to: "",
  copy_to: "finance@smlengineers.lk",
  host: "smtp.hostinger.com",
  port: 465,
  security: "ssl",
  username: "finance@smlengineers.lk",
  has_password: true,
  is_ready: true,
  last_test_at: null,
  last_test_ok: null,
  last_test_error: "",
};

const template: EmailTemplate = {
  kind: "tax_invoice",
  label: "Tax invoice",
  subject: "Tax invoice {document_number} from {company_name}",
  body: "Dear {recipient_name},\n\nPlease find attached tax invoice {document_number}.",
  placeholders: [
    { name: "recipient_name", label: "The customer's or supplier's name" },
    { name: "document_number", label: "Invoice number" },
  ],
  updated_at: null,
};

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/settings/document-email/": { body: account },
  "GET /api/v1/settings/document-email/templates/": { body: [template] },
  ...extra,
});

test("the Admin changes the mailbox; an empty password keeps the saved one", async () => {
  const calls = mockApi(api({ "PUT /api/v1/settings/document-email/": { body: account } }));
  renderAt("/settings/document-email", <DocumentEmailPage me={admin} />);

  const form = await screen.findByRole("form", { name: "Sending mailbox" });
  expect(within(form).getByLabelText("New password (leave empty to keep the saved one)")).toHaveValue("");
  fireEvent.change(within(form).getByLabelText("Replies go to (optional)"), {
    target: { value: "accounts@smlengineers.lk" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "Save mailbox" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/settings/document-email/", expect.objectContaining({ method: "PUT" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "PUT")!;
  const sent = JSON.parse(String(init!.body));
  expect(sent).toMatchObject({ reply_to: "accounts@smlengineers.lk", port: 465, security: "ssl" });
  expect(sent).not.toHaveProperty("password");
  expect(screen.getByRole("status")).toHaveTextContent("Send a test email to check these settings.");
});

test("the Admin edits the default message, with its placeholders listed", async () => {
  const calls = mockApi(
    api({ "PUT /api/v1/settings/document-email/templates/tax_invoice/": { body: template } }),
  );
  renderAt("/settings/document-email", <DocumentEmailPage me={admin} />);

  const form = await screen.findByRole("form", { name: "Default message: Tax invoice" });
  expect(within(form).getByText("{document_number}")).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Subject"), { target: { value: "Invoice {document_number}" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save message" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/document-email/templates/tax_invoice/",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ subject: "Invoice {document_number}", body: template.body, reason: "" }),
      }),
    ),
  );
});

test("the person sending edits the message before it goes", async () => {
  const onSend = vi.fn().mockResolvedValue({});
  render(
    <SendEmailForm
      draft={{
        from: '"SML Engineers Finance" <finance@smlengineers.lk>',
        ready: true,
        to: ["accounts@lankaplastics.lk"],
        cc: [],
        subject: "Tax invoice 26SEP_W1_35 from SML Engineers",
        body: "Dear Lanka Plastics,\n\nPlease find attached tax invoice 26SEP_W1_35.",
      }}
      attachmentName="26SEP_W1_35.pdf"
      onSend={onSend}
    />,
  );

  expect(screen.getByText("📎 26SEP_W1_35.pdf")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Cc"), { target: { value: "owner@sml.lk; md@sml.lk" } });
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Dear Sir,\n\nCorrected invoice attached." } });
  fireEvent.click(screen.getByRole("button", { name: "Send email" }));
  await waitFor(() =>
    expect(onSend).toHaveBeenCalledWith({
      to: ["accounts@lankaplastics.lk"],
      cc: ["owner@sml.lk", "md@sml.lk"],
      subject: "Tax invoice 26SEP_W1_35 from SML Engineers",
      body: "Dear Sir,\n\nCorrected invoice attached.",
    }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("Sent to accounts@lankaplastics.lk.");
});

test("without a sending mailbox the form says so", () => {
  render(
    <SendEmailForm
      draft={{ from: "", ready: false, to: [], cc: [], subject: "", body: "" }}
      onSend={vi.fn()}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Document email is not set up yet");
});
