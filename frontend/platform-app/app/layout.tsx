// @chanteur/platform-app — kök layout (L0 Platform Control Plane).
// 13.1.3: tasarım sistemi (globals.css token'ları) + i18n (TR/EN) bağlanır. <html lang/dir> sunucu-tarafı
// müzakereyle (çerez + Accept-Language); SkipLink (a11y) eklenir. Locale-duyarlı başlık.
import type { ReactNode } from "react";
import "./globals.css";
import { getServerLocale } from "@/lib/i18n/server";
import { dir, getCatalog, t } from "@/lib/i18n";
import { SkipLink } from "@/lib/ui/components";

export const metadata = {
  title: "RMC Platform Console (L0)",
  description: "Platform Admin Console — internal-only (ADR-011). Cross-tenant yönetim.",
  robots: { index: false, follow: false }, // internal-only: indekslenmez
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  return (
    <html lang={locale} dir={dir(locale)}>
      <body>
        <SkipLink targetId="main" label={t(cat, "app.skip_to_content")} />
        {children}
      </body>
    </html>
  );
}
