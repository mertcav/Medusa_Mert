// @chanteur/tenant-app — (workspace) route group layout (L2 — Operasyon / Uygulama Paneli).
// SAD §14.4.1: "tenant oturumu + L2 rol guard".
//
// İSKELET (13.1.1): L2 günlük operasyon ekranlarını çerçeveler. Tenant oturumu + tenant_scope
// (tek tenant — FR-TEN-002) + panel ayrımı (/workspace → L2) ENFORCEMENT'ı 13.1.2'de middleware.ts'e
// eklendi. PII içeren görüntülemeler 13.1.4'te maskelenir. UI yalnız görsel kapı; yetki backend'de +
// RLS (SAD §14.4.1 — A8).
import type { ReactNode } from "react";

const L2_NAV = [
  { href: "/workspace/dashboard", label: "Panel", code: "A-01" },
  { href: "/workspace/live-calls", label: "Canlı Çağrılar", code: "A-02" },
  { href: "/workspace/agents", label: "Agent'lar", code: "A-03" },
  { href: "/workspace/builder", label: "Agent Builder", code: "A-04" },
  { href: "/workspace/flows", label: "Akışlar", code: "A-05" },
  { href: "/workspace/prompts", label: "Prompt'lar", code: "A-06" },
  { href: "/workspace/voice", label: "Ses Profilleri", code: "A-07" },
  { href: "/workspace/kb", label: "Bilgi Tabanı", code: "A-08" },
  { href: "/workspace/tools", label: "Araçlar", code: "A-09" },
  { href: "/workspace/campaigns", label: "Kampanyalar", code: "A-10" },
  { href: "/workspace/recordings", label: "Kayıtlar", code: "A-11" },
  { href: "/workspace/call", label: "Çağrı Detayı", code: "A-12" },
  { href: "/workspace/qa", label: "Kalite (QA)", code: "A-13" },
  { href: "/workspace/analytics", label: "Analitik", code: "A-14" },
  { href: "/workspace/cost", label: "Maliyet", code: "A-15" },
  { href: "/workspace/test", label: "Test", code: "A-16" },
  { href: "/workspace/versions", label: "Sürümler", code: "A-17" },
];

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <div data-plane="tenant_application_plane" data-tier="L2">
      <aside aria-label="Operasyon navigasyon">
        <strong>Operasyon (L2)</strong>
        <nav>
          <ul>
            {L2_NAV.map((item) => (
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
