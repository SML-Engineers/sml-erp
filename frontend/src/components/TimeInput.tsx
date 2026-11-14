import type { InputHTMLAttributes } from "react";

import { normaliseTime } from "../lib/time";

/** A time box on the 24-hour clock (owner, 12 Nov 2026): the browser's own time picker follows
 * the PC's AM/PM setting, so this is a plain box for "HH:MM" that tidies "830" into "08:30". */
export default function TimeInput({
  value,
  onChange,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value" | "type"> & {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <input
      {...rest}
      type="text"
      inputMode="numeric"
      placeholder="HH:MM"
      maxLength={5}
      pattern="([01][0-9]|2[0-3]):[0-5][0-9]"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={(e) => {
        const tidy = normaliseTime(e.target.value);
        if (tidy !== e.target.value) onChange(tidy);
      }}
    />
  );
}
