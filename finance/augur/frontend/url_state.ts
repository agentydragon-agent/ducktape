type SearchParamValue = string | number | null | undefined;
type BrowserUrlState = Pick<Window, "location" | "history">;

export function replaceSearchParams(
  updates: Readonly<Record<string, SearchParamValue>>,
  browser: BrowserUrlState = window
) {
  const { pathname, search: currentSearch, hash } = browser.location;
  const params = new URLSearchParams(currentSearch);
  for (const [key, value] of Object.entries(updates)) {
    if (value == null) params.delete(key);
    else params.set(key, String(value));
  }
  const search = params.toString();
  const nextUrl = `${pathname}${search ? `?${search}` : ""}${hash}`;
  if (nextUrl === pathname + currentSearch + hash) return false;
  browser.history.replaceState(null, "", nextUrl);
  return true;
}
