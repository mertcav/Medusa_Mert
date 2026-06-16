// @chanteur/tenant-app — (tenant-admin) route group layout (L1 — Tenant Admin Console).
// SAD §14.4.1: "tenant oturumu + L1 rol guard; tenant scope middleware'de sabitlenir".
//
// İSKELET (13.1.1): L1 tek-tenant yönetim ekranlarını çerçeveler. Tenant oturumu + tenant_scope
// (tek tenant — FR-TEN-002) + panel ayrımı (/admin → L1) ENFORCEMENT'ı 13.1.2'de middleware.ts'e
// eklendi. UI yalnız görsel kapı; nihai yetki backend'de + RLS (SAD §14.4.1 — A8).
import type { ReactNode } from "react";

const L1_NAV = [
  { href: "/admin/dashboard", label: "Panel", code: "T-01" },
  { href: "/admin/org", label: "Organizasyon", code: "T-02" },
  { href: "/admin/users", label: "Kullanıcılar / Roller", code: "T-03" },
  { href: "/admin/numbers", label: "Numaralar", code: "T-04" },
  { href: "/admin/integrations", label: "Entegrasyonlar", code: "T-05" },
  { href: "/admin/compliance", label: "Uyumluluk", code: "T-06" },
  { href: "/admin/billing", label: "Faturalama", code: "T-07" },
  { href: "/admin/audit", label: "Denetim", code: "T-08" },
  { href: "/admin/quota", label: "Kota", code: "T-09" },
];

export default function TenantAdminLayout({ children }: { children: ReactNode }) {
  return (
    <div data-plane="tenant_application_plane" data-tier="L1">
      <aside aria-label="Tenant Admin navigasyon">
        <strong>Tenant Admin (L1)</strong>
        <nav>
          <ul>
            {L1_NAV.map((item) => (
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
