// @chanteur/platform-app — kök layout (L0 Platform Control Plane).
import type { ReactNode } from "react";

export const metadata = {
  title: "RMC Platform Console (L0)",
  description: "Platform Admin Console — internal-only (ADR-011). Cross-tenant yönetim.",
  robots: { index: false, follow: false }, // internal-only: indekslenmez
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
