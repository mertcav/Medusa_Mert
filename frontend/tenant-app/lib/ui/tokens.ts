// WBS 13.1.3 — design token erişimi. design-tokens.json (canonical kopya; probe hash ile eşitler) →
// tipli token nesnesi + CSS değişken haritası. CSS değişkenleri app/globals.css'te :root altında da
// yayımlanır (komponentler var(--rmc-*) ile stillenir). Sır/PII YOK.
import tokensJson from "./design-tokens.json";

export const tokens = tokensJson;
export type Tokens = typeof tokensJson;

// Düz CSS değişken haritası: --rmc-<anahtar-tire>. (color/typography/space/radius/shadow/zindex/breakpoint)
export function tokenCssVars(): Record<string, string> {
  const out: Record<string, string> = {};
  const groups = ["color", "typography", "space", "radius", "shadow", "zindex", "breakpoint"] as const;
  for (const g of groups) {
    const grp = (tokensJson as Record<string, unknown>)[g] as Record<string, string> | undefined;
    if (!grp) continue;
    for (const [k, v] of Object.entries(grp)) {
      if (k.startsWith("$")) continue;
      out[`--rmc-${k.replace(/_/g, "-")}`] = v;
    }
  }
  return out;
}

export const SUPPORTED_LOCALES = tokensJson.locales.supported;
export const RTL_READY = tokensJson.locales.rtl_ready;
