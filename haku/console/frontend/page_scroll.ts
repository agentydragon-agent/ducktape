import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

const STORAGE_PREFIX = "haku-page-scroll:";

function storageKey(viewKey: string): string {
  return `${STORAGE_PREFIX}${viewKey}`;
}

function readScrollTop(viewKey: string): number | null {
  try {
    const stored = sessionStorage.getItem(storageKey(viewKey));
    if (stored === null) return null;
    const value = Number(stored);
    return Number.isFinite(value) && value >= 0 ? value : null;
  } catch (error) {
    console.warn("Unable to read page scroll position from session storage", error);
    return null;
  }
}

function writeScrollTop(viewKey: string, scrollTop: number): void {
  try {
    sessionStorage.setItem(storageKey(viewKey), String(scrollTop));
  } catch (error) {
    console.warn("Unable to save page scroll position to session storage", error);
  }
}

export function usePageScroll(viewKey: string): RefObject<HTMLDivElement | null> {
  const scrollRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const element = scrollRef.current;
    const scrollTop = readScrollTop(viewKey);
    if (element && scrollTop !== null) element.scrollTop = scrollTop;
  });

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const save = () => writeScrollTop(viewKey, element.scrollTop);
    element.addEventListener("scroll", save, { passive: true });
    return () => {
      save();
      element.removeEventListener("scroll", save);
    };
  }, [viewKey]);

  return scrollRef;
}
