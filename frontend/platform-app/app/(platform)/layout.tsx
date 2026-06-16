// @chanteur/platform-app — (platform) route group layout (L0 — Platform Admin Console).
// SAD §14.4.1: "platform auth realm + platform rol guard".
//
// İSKELET (13.1.1): bu layout L0 (platform) route group'unu çerçeveler. Platform auth realm +
// platform rol guard ENFORCEMENT'ı 13.1.2'de eklenir. UI yalnız görsel kapıdır; nihai yetki
// kararı backend'dedir (SAD §14.4.1 — A8). Bu group YALNIZ platform ekranlarını barındırır;
// tenant iş verisi (call/transcript/recording) route'u YOKTUR (ADR-011, FR-IAM-008 — A5).
import type { ReactNode } from "react";

const PLATFORM_NAV = [
  { href: "/overview", label: "Genel Bakış", code: "P-01" },
  { href: "/tenants", label: "Tenant'lar", code: "P-02" },
  { href: "/resources", label: "Kaynaklar / Kota", code: "P-03" },
  { href: "/providers", label: "Sağlayıcılar", code: "P-04" },
  { href: "/billing", label: "Faturalama", code: "P-05" },
  { href: "/policy", label: "Global Politika", code: "P-06" },
  { href: "/audit", label: "Denetim (metrik/log)", code: "P-07" },
  { href: "/releases", label: "Sürümler", code: "P-08" },
  { href: "/incidents", label: "Olaylar", code: "P-09" },
];

export default function PlatformLayout({ children }: { children: ReactNode }) {
  return (
    <div data-plane="platform_control_plane" data-tier="L0">
      <aside aria-label="Platform navigasyon">
        <strong>RMC Platform Console (L0)</strong>
        <nav>
          <ul>
            {PLATFORM_NAV.map((item) => (
              <li key={item.href}>
                <a href={item.href}>{item.label}</a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main>{children}</main>
    </div>
  );
}
