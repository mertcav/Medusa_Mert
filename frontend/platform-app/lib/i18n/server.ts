// WBS 13.1.3 — sunucu-tarafı locale çözümü (Next App Router RSC). Çerez + Accept-Language'ten
// deterministik müzakere (saf çekirdek negotiateLocale ile). Çerez ADI sır değil. PII YOK.
import { cookies, headers } from "next/headers";
import { negotiateLocale, type Locale } from "./index";

export const LANG_COOKIE = "rmc_lang"; // sır değil — yalnız dil tercihi (tr|en)

// Not (skeleton): ?lang query'si SAYFA (page) seviyesinde okunup negotiateLocale'e geçilebilir; layout
// RSC'de query yoktur → burada çerez + Accept-Language esas. Çerez-kalıcılaştıran switch route'u 13.2+'da.
export function getServerLocale(): Locale {
  const cookie = cookies().get(LANG_COOKIE)?.value ?? null;
  const acceptLanguage = headers().get("accept-language");
  return negotiateLocale({ cookie, acceptLanguage });
}
