import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { can } from "../api/access";
import { meQueryKey, type Me } from "../api/auth";

/** A journal entry's number as a link to it on Accounts → Journal (testing T39, 21 Nov
 * 2026: "posted as JV26110022" could not be opened). People who cannot open the journal
 * see the number only. */
export default function JournalLink({ number }: { number: string | null | undefined }) {
  const me = useQueryClient().getQueryData<Me>(meQueryKey);
  const access = me?.authenticated ? me.user.access : undefined;
  if (!number) return null;
  if (!can(access, "accounting", "view")) return <span className="mono">{number}</span>;
  return (
    <Link to={`/journal?q=${encodeURIComponent(number)}`} className="mono">
      {number}
    </Link>
  );
}

/** A sentence with a journal number in it ("posted as JV26110022"), the number a link. */
export function WithJournal({ text, number }: { text: string; number: string | null | undefined }): ReactNode {
  if (!number || !text.includes(number)) return text;
  const at = text.indexOf(number);
  return (
    <>
      {text.slice(0, at)}
      <JournalLink number={number} />
      {text.slice(at + number.length)}
    </>
  );
}
