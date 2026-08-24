import type { CSSProperties } from "react";

// Converts a plain CSS declaration string ("padding:8px;color:#fff") into a
// React style object. Memoized. Lets components carry the exact v4 visual
// styling with high fidelity. Ordinary pure function — no runtime deps.
const cache = new Map<string, CSSProperties>();

export function css(decls: string): CSSProperties {
  const hit = cache.get(decls);
  if (hit) return hit;
  const obj: Record<string, string> = {};
  for (const decl of decls.split(";")) {
    const i = decl.indexOf(":");
    if (i < 0) continue;
    const prop = decl.slice(0, i).trim();
    const val = decl.slice(i + 1).trim();
    if (!prop) continue;
    const camel = prop.replace(/-([a-z])/g, (_m, c: string) => c.toUpperCase());
    obj[camel] = val;
  }
  const out = obj as CSSProperties;
  cache.set(decls, out);
  return out;
}
