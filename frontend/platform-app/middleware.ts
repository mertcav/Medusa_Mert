// @chanteur/platform-app — L0 middleware iskeleti (ADR-011, SAD §14.4.1).
//
// KAPSAM (13.1.1): yalnız iki-app ayrımının frontend iskeleti. Bu middleware bir İSKELETtir:
// internal-only erişim sınırını (VPN/allowlist/private endpoint) ve platform auth realm'ini
// İŞARETLER. Çalışma-anı oturum doğrulama + platform rol guard ENFORCEMENT'ı 13.1.2'de
// (route group + middleware) eklenir; nihai YETKİ KARARI HER ZAMAN backend'dedir (12.2.x;
// SAD §14.4.1 "UI yalnız görsel kapıdır"). Burada hardcoded authz KARARI YOKTUR (A8).
//
// ADR-011: platform-app tenant iş verisi route'u BARINDIRMAZ; bu app'te (platform) dışında
// route group yoktur (A3/A5). Ağ-seviyesi internal-only kısıt deploy/altyapı katmanında.
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export function middleware(_req: NextRequest) {
  // 13.1.2 yer tutucu: oturum (platform realm) + platform rol guard çalışma-anında burada zorlanacak.
  // İskelet aşamasında istek geçirilir; yetki backend'de (12.2.x) karar verir.
  const res = NextResponse.next();
  res.headers.set("x-app-plane", "platform_control_plane"); // gözlemlenebilirlik (düşük kardinalite)
  return res;
}

export const config = {
  // Statik varlıklar hariç tüm route'lar.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
