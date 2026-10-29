import { useId, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

export interface SearchOption {
  value: string;
  label: string;
}

const SHOWN = 12;

/** Every word typed must appear somewhere in the label ("elec" finds "6100 Electricity",
 * "6100" too), in any order, ignoring case. */
export function matches(label: string, text: string): boolean {
  const haystack = label.toLowerCase();
  return text
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

/** A drop-down that can be searched by typing any part of an entry (a long list such as the
 * chart of accounts). Arrow keys and Enter work as in a normal list; Escape closes it. */
export default function SearchSelect(props: {
  label: string;
  options: SearchOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const { t } = useTranslation();
  const listId = useId();
  const chosen = props.options.find((o) => o.value === props.value);
  const [text, setText] = useState<string | null>(null); // null: not typing, show the chosen entry
  const [active, setActive] = useState(0);
  const open = text !== null;
  const found = text !== null ? props.options.filter((o) => matches(o.label, text)) : [];
  const shown = found.slice(0, SHOWN);

  function pick(option: SearchOption | undefined) {
    if (option) props.onChange(option.value);
    setText(null);
  }

  function key(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) setText("");
      setActive((i) => Math.min(i + 1, Math.max(shown.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter" && open) {
      event.preventDefault(); // choosing an entry must not submit the form
      pick(shown[active]);
    } else if (event.key === "Escape") {
      setText(null);
    }
  }

  return (
    <div className="search-select">
      <input
        role="combobox"
        aria-label={props.label}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        placeholder={props.placeholder ?? t("common.typeToSearch")}
        value={text ?? chosen?.label ?? ""}
        onFocus={(e) => e.target.select()}
        onChange={(e) => {
          setText(e.target.value);
          setActive(0);
        }}
        onKeyDown={key}
        onBlur={() => setText(null)} // leaving without choosing keeps the entry chosen before
      />
      {open && (
        <ul id={listId} role="listbox" aria-label={props.label} className="search-select-list">
          {shown.map((o, i) => (
            <li
              key={o.value}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              // mousedown, not click: it runs before the box loses focus and closes the list
              onMouseDown={(e) => {
                e.preventDefault();
                pick(o);
              }}
            >
              {o.label}
            </li>
          ))}
          {found.length === 0 && <li className="muted">{t("common.noMatches")}</li>}
          {found.length > SHOWN && (
            <li className="muted">{t("common.moreMatches", { count: String(found.length - SHOWN) })}</li>
          )}
        </ul>
      )}
    </div>
  );
}
