import { screen } from "@testing-library/react";

import { mockApi, renderAt } from "../test-utils";
import TopBarNotice from "./TopBarNotice";

const EN = "Entering false information into the system is a punishable offence.";
const SI = "පද්ධතියට අසත්‍ය තොරතුරු ඇතුළත් කිරීම දඬුවම් ලැබිය හැකි වරදකි.";

test("shows English with Sinhala below it while the notice is on (owner, 21 Nov 2026)", async () => {
  mockApi({ "GET /api/v1/notice/": { body: { show: true, text_en: EN, text_si: SI } } });
  renderAt("/x", <TopBarNotice place="bar" />);
  const note = await screen.findByRole("note", { name: "Notice" });
  const lines = note.querySelectorAll("p");
  expect(lines[0]).toHaveTextContent(EN);
  expect(lines[0]).toHaveAttribute("lang", "en");
  expect(lines[1]).toHaveTextContent(SI);
  expect(lines[1]).toHaveAttribute("lang", "si");
});

test("shows nothing while the notice is off", async () => {
  const calls = mockApi({ "GET /api/v1/notice/": { body: { show: false, text_en: "", text_si: "" } } });
  renderAt("/x", <TopBarNotice place="page" />);
  await vi.waitFor(() => expect(calls).toHaveBeenCalled());
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
});
