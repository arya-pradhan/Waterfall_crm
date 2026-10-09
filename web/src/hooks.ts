import { useCallback, useEffect, useRef, useState } from "react";

/** Load data from the API; re-fetch every `pollMs` when given (pauses while the tab is hidden). */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = [], pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    try {
      setData(await loadRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    if (!pollMs) return;
    const t = setInterval(() => document.visibilityState === "visible" && refresh(), pollMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs, refresh]);

  return { data, error, refresh, setData };
}

export const usd = (n: number | null | undefined, digits = 2) =>
  n == null ? "—" : `$${n.toFixed(n !== 0 && Math.abs(n) < 0.01 ? 4 : digits)}`;

export function relativeDays(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days < 0 ? `${-days} days overdue` : `in ${days} days`;
}
