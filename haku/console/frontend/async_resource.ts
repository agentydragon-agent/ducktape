import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncResourceLoader<T> = (emit: (value: T) => void, previous: T | null) => Promise<T>;
export type AsyncResource<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
  update: (updater: T | null | ((current: T | null) => T | null)) => void;
};
type Options = { enabled?: boolean; pollMs?: number; formatError?: (error: unknown) => string | null };
const fallbackError = (error: unknown): string => (error instanceof Error ? error.message : String(error));
export function useAsyncResource<T>(
  load: AsyncResourceLoader<T>,
  { enabled = true, pollMs, formatError = fallbackError }: Options = {}
): AsyncResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const dataRef = useRef<T | null>(null);
  const configRef = useRef({ load, formatError });
  configRef.current = { load, formatError };
  const publish = useCallback((request: number, value: T) => {
    if (request !== generation.current) return;
    dataRef.current = value;
    setData(value);
    setError(null);
  }, []);
  const refresh = useCallback(() => {
    const request = ++generation.current;
    setLoading(true);
    void Promise.resolve()
      .then(() => configRef.current.load((value) => publish(request, value), dataRef.current))
      .then(
        (value) => {
          if (request !== generation.current) return;
          publish(request, value);
          setError(null);
          setLoading(false);
        },
        (cause: unknown) => {
          if (request !== generation.current) return;
          setError(configRef.current.formatError(cause));
          setLoading(false);
        }
      );
  }, [publish]);
  const update = useCallback((updater: T | null | ((current: T | null) => T | null)) => {
    generation.current += 1;
    const next =
      typeof updater === "function" ? (updater as (current: T | null) => T | null)(dataRef.current) : updater;
    dataRef.current = next;
    setData(next);
    setError(null);
    setLoading(false);
  }, []);
  useEffect(() => {
    if (!enabled) return;
    refresh();
    const interval = pollMs === undefined ? undefined : window.setInterval(refresh, pollMs);
    return () => {
      if (interval !== undefined) window.clearInterval(interval);
      generation.current += 1;
    };
  }, [enabled, pollMs, refresh]);
  useEffect(
    () => () => {
      generation.current += 1;
    },
    []
  );
  return { data, error, loading, refresh, update };
}
