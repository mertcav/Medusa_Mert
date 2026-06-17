// WBS 13.1.3 — i18n çekirdeği (TR/EN). Saf/deterministik; Next/edge API'sinden BAĞIMSIZ → birim-test +
// Python aynası (design_system_probe.py). Katalog anahtarları TR↔EN BİREBİR (probe parity kapısı).
//
// ÇEKİRDEK İLKE: yerelleştirme yalnız ÇAĞRI YERİNDE t() ile; presentasyonel komponentler locale-agnostik
// (lib/ui/components.tsx i18n import ETMEZ). Sır/PII YOK. Vendor-neutral (ADR-002): Intl stdlib; i18n
// kütüphanesi/SaaS bağlanmaz. TR/EN ship; dir haritası + rtl_ready ME (AR/RTL) için genişletilebilir.
import tr from "./tr.json";
import en from "./en.json";

export const SUPPORTED_LOCALES = ["tr", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "tr";
export const FALLBACK_LOCALE: Locale = "tr";

const CATALOGS = { tr, en } as const;
export type Catalog = typeof tr;

export function isLocale(x: string | null | undefined): x is Locale {
  return x === "tr" || x === "en";
}

// TR/EN LTR; harita gelecekte AR (rtl) için genişletilebilir (design-tokens.json locales.rtl_ready).
const DIR: Record<Locale, "ltr" | "rtl"> = { tr: "ltr", en: "ltr" };
export function dir(locale: Locale): "ltr" | "rtl" {
  return DIR[locale];
}

export function getCatalog(locale: Locale): Catalog {
  return CATALOGS[locale] ?? CATALOGS[FALLBACK_LOCALE];
}

// Deterministik locale müzakeresi: ?lang query > çerez > Accept-Language > default. Date.now/rastgelelik YOK.
export function negotiateLocale(input: {
  query?: string | null;
  cookie?: string | null;
  acceptLanguage?: string | null;
}): Locale {
  if (isLocale(input.query)) return input.query;
  if (isLocale(input.cookie)) return input.cookie;
  const al = (input.acceptLanguage ?? "").toLowerCase();
  for (const part of al.split(",")) {
    const tag = part.split(";")[0].trim().slice(0, 2);
    if (isLocale(tag)) return tag;
  }
  return DEFAULT_LOCALE;
}

// dotted path çözümleme + {placeholder} interpolasyonu (deterministik).
export function t(
  catalog: Catalog,
  key: string,
  params?: Record<string, string | number>,
): string {
  const raw = resolvePath(catalog, key);
  if (raw == null) return key; // eksik anahtar → anahtarın kendisi (parity kapısı zaten FAIL eder)
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (m, name) => (name in params ? String(params[name]) : m));
}

function resolvePath(obj: unknown, key: string): string | null {
  let cur: unknown = obj;
  for (const seg of key.split(".")) {
    if (cur && typeof cur === "object" && seg in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[seg];
    } else {
      return null;
    }
  }
  return typeof cur === "string" ? cur : null;
}

// Locale-duyarlı biçimlendirme (Intl — vendor-neutral, stdlib). FR-TTS-004 panel karşılığı: tarih/sayı/para.
const INTL_LOCALE: Record<Locale, string> = { tr: "tr-TR", en: "en-GB" };
export function formatDate(locale: Locale, d: Date, opts?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(INTL_LOCALE[locale], opts).format(d);
}
export function formatNumber(locale: Locale, n: number, opts?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(INTL_LOCALE[locale], opts).format(n);
}
export function formatCurrency(locale: Locale, n: number, currency: string): string {
  return new Intl.NumberFormat(INTL_LOCALE[locale], { style: "currency", currency }).format(n);
}
