// @chanteur/platform-app — (platform) route group layout (L0 — Platform Admin Console).
// SAD §14.4.1: "platform auth realm + platform rol guard".
//
// İSKELET (13.1.1): bu layout L0 (platform) route group'unu çerçeveler. Çalışma-anı oturum +
// platform realm + panel ayrımı ENFORCEMENT'ı 13.1.2'de middleware.ts'e eklendi (platform rol
// guard'ı UX seviyesinde; nihai YETKİ backend'de — 12.2.x). UI yalnız görsel kapıdır (SAD §14.4.1
// — A8). Bu group YALNIZ platform ekranlarını barındırır;
// tenant iş verisi (call/transcript/recording) route'u YOKTUR (ADR-011, FR-IAM-008 — A5).
//
// 13.1.3: nav etiketleri i18n katalogundan (t()); chrome design token'larıyla (var(--rmc-*)) stillenir;
// dil değiştirici (LangSwitcher) + erişilebilir <main id>. Sunucu-tarafı locale müzakeresi.
import type { ReactNode } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, SUPPORTED_LOCALES } from "@/lib/i18n";
import { LangSwitcher } from "@/lib/ui/components";

// href → i18n anahtarı (etiket) + ekran kodu. Etiketler katalogdan t() ile çözülür (hardcoded YOK).
const PLATFORM_NAV = [
  { href: "/overview", key: "nav.platform.overview", code: "P-01" },
  { href: "/tenants", key: "nav.platform.tenants", code: "P-02" },
  { href: "/resources", key: "nav.platform.resources", code: "P-03" },
  { href: "/providers", key: "nav.platform.providers", code: "P-04" },
  { href: "/billing", key: "nav.platform.billing", code: "P-05" },
  { href: "/policy", key: "nav.platform.policy", code: "P-06" },
  { href: "/audit", key: "nav.platform.audit", code: "P-07" },
  { href: "/releases", key: "nav.platform.releases", code: "P-08" },
  { href: "/incidents", key: "nav.platform.incidents", code: "P-09" },
];

const LOCALE_LABEL: Record<string, string> = { tr: "TR", en: "EN" };

export default function PlatformLayout({ children }: { children: ReactNode }) {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  return (
    <div data-plane="platform_control_plane" data-tier="L0" style={{ display: "flex", minHeight: "100vh" }}>
      <aside
        aria-label={t(cat, "a11y.main_nav")}
        style={{
          background: "var(--rmc-surface)",
          borderInlineEnd: "1px solid var(--rmc-border-subtle)",
          padding: "var(--rmc-space-4)",
          minWidth: "240px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--rmc-space-2)" }}>
          <strong style={{ color: "var(--rmc-brand-primary)" }}>{t(cat, "app.title_platform")}</strong>
          <LangSwitcher
            current={locale}
            locales={SUPPORTED_LOCALES}
            hrefFor={(l) => `?lang=${l}`}
            label={t(cat, "a11y.lang_switcher")}
            localeLabel={(l) => LOCALE_LABEL[l] ?? l}
          />
        </div>
        <nav aria-label={t(cat, "a11y.main_nav")} style={{ marginTop: "var(--rmc-space-4)" }}>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--rmc-space-1)" }}>
            {PLATFORM_NAV.map((item) => (
              <li key={item.href}>
                <a href={item.href}>{t(cat, item.key)}</a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main id="main" style={{ flex: 1 }}>
        {children}
      </main>
    </div>
  );
}
