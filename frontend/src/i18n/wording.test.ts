import en from "./en.json";
import si from "./si.json";

/** Every text shown on screen, with its key. */
function texts(node: unknown, path = ""): [string, string][] {
  if (typeof node === "string") return [[path, node]];
  if (node && typeof node === "object") return Object.entries(node).flatMap(([k, v]) => texts(v, path ? `${path}.${k}` : k));
  return [];
}

// Testing T21 (20 Nov 2026): "from Phase 2, invoices set them off" — the project's phases are
// developer words, not something staff should read.
test("no text on screen talks about the project's phases", () => {
  const found = [...texts(en), ...texts(si)].filter(([, text]) => /\bPhase \d/i.test(text));
  expect(found).toEqual([]);
});
