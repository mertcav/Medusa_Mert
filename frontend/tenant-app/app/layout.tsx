// @chanteur/tenant-app — kök layout (L1+L2 Tenant Application Plane).
import type { ReactNode } from "react";

export const metadata = {
  title: "RMC Tenant Console",
  description: "Tenant Admin Console (L1) + Operasyon Paneli (L2) — tek tenant (ADR-011).",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
