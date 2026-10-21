/**
 * Stands in for src/api/client.ts in the demo widget. The components it serves only build URLs
 * (figures, structure coordinates); the widget registers its static coordinates here before a
 * structure card renders, so nothing reaches a backend.
 */
const registered = new Map<string, string>();

/** `pdb=6VXX` / `afdb=P68431` → a blob: URL holding the coordinates JSON. */
export function registerStructure(query: string, url: string) {
  registered.set(query, url);
}

export function apiUrl(path: string): string {
  const q = /^\/knowledge-chat\/structures\?(.+)$/.exec(path);
  if (q) return registered.get(decodeURIComponent(q[1])) ?? 'about:blank';
  return path;
}

export async function apiFetch<T>(): Promise<T> {
  throw new Error('This demo has no backend.');
}
