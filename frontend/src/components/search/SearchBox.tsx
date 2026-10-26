import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { searchSuggest } from "../../api/client";
import type { SearchSuggestions } from "../../types";
import { SUGGESTION_SECTIONS, suggestionItems, type SuggestionItem, type SuggestionKind } from "./searchUtils";

export type PickedSuggestion = { kind: SuggestionKind; id: string; name: string };

interface Props {
  value: string;
  onChange: (value: string) => void;
  /** Called `debounceMs` after the last keystroke, and at once on Enter. */
  onCommit: (value: string) => void;
  onPick: (item: PickedSuggestion) => void;
  placeholder?: string;
  debounceMs?: number;
  suggestDelayMs?: number;
  children?: ReactNode;
}

export default function SearchBox({
  value, onChange, onCommit, onPick, placeholder, debounceMs = 250, suggestDelayMs = 80, children,
}: Props) {
  const [suggestions, setSuggestions] = useState<SearchSuggestions | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const commitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abort = useRef<AbortController | null>(null);
  const items = useMemo(() => suggestionItems(suggestions), [suggestions]);

  useEffect(() => () => {
    if (commitTimer.current) clearTimeout(commitTimer.current);
    if (suggestTimer.current) clearTimeout(suggestTimer.current);
    abort.current?.abort();
  }, []);

  const fetchSuggestions = (text: string) => {
    if (suggestTimer.current) clearTimeout(suggestTimer.current);
    abort.current?.abort();
    if (text.trim().length < 2) {
      setSuggestions(null);
      return;
    }
    suggestTimer.current = setTimeout(() => {
      const ctl = new AbortController();
      abort.current = ctl;
      searchSuggest(text.trim(), 5, ctl.signal)
        .then((s) => {
          if (ctl.signal.aborted) return;
          setSuggestions(s);
          setActive(-1);
        })
        .catch(() => { /* aborted or offline: keep the old list */ });
    }, suggestDelayMs);
  };

  const handleChange = (text: string) => {
    onChange(text);
    setOpen(true);
    if (commitTimer.current) clearTimeout(commitTimer.current);
    commitTimer.current = setTimeout(() => onCommit(text), debounceMs);
    fetchSuggestions(text);
  };

  const commitNow = () => {
    if (commitTimer.current) clearTimeout(commitTimer.current);
    onCommit(value);
    setOpen(false);
  };

  const pick = (item: SuggestionItem) => {
    if (commitTimer.current) clearTimeout(commitTimer.current);
    setOpen(false);
    setActive(-1);
    onPick({ kind: item.kind, id: item.id, name: item.name });
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => (items.length ? (a + 1) % items.length : -1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (items.length ? (a <= 0 ? items.length - 1 : a - 1) : -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && active >= 0 && items[active]) pick(items[active]);
      else commitNow();
    } else if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  const showList = open && items.length > 0 && value.trim().length >= 2;
  const groups = SUGGESTION_SECTIONS
    .map((sec) => ({ ...sec, entries: items.map((it, i) => ({ it, i })).filter(({ it }) => it.kind === sec.kind) }))
    .filter((g) => g.entries.length > 0);

  return (
    <div className="relative flex flex-1 min-w-[160px] items-center gap-1">
      <input
        type="search"
        role="combobox"
        aria-expanded={showList}
        aria-controls="search-suggestions"
        aria-autocomplete="list"
        aria-activedescendant={showList && active >= 0 ? `search-suggestion-${active}` : undefined}
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        placeholder={placeholder}
        className="flex-1 h-9 border border-line rounded-lg px-3 text-sm bg-raised text-ink focus:outline-none focus:ring-2 focus:ring-violet-300"
      />
      {children}
      {showList && (
        <ul
          id="search-suggestions"
          role="listbox"
          className="absolute left-0 right-0 top-10 z-30 bg-raised border border-line rounded-xl shadow-xl py-1 max-h-[70vh] overflow-y-auto"
        >
          {groups.map((g) => (
            <li key={g.key} role="presentation">
              <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-3">{g.label}</p>
              <ul role="presentation">
                {g.entries.map(({ it, i }) => (
                  <li
                    key={`${it.kind}-${it.id}`}
                    id={`search-suggestion-${i}`}
                    role="option"
                    aria-selected={i === active}
                    onMouseDown={(e) => { e.preventDefault(); pick(it); }}
                    onMouseEnter={() => setActive(i)}
                    className={`px-3 py-1.5 text-sm flex items-center gap-2 cursor-pointer ${
                      i === active ? "bg-accent-lo text-accent" : "text-ink-2"
                    }`}
                  >
                    <span className="flex-1 truncate">{it.name}</span>
                    {it.detail && <span className="text-[11px] text-ink-3 shrink-0">{it.detail}</span>}
                  </li>
                ))}
              </ul>
            </li>
          ))}
          <li role="presentation" className="px-3 pt-1.5 pb-1 text-[11px] text-ink-3 border-t border-line-s mt-1">
            ↑↓ to choose, Enter to open or filter, Esc to close
          </li>
        </ul>
      )}
    </div>
  );
}
