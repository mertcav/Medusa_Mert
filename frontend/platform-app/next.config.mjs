// @chanteur/platform-app — L0 Platform Control Plane (ADR-011: ayrı, internal-only deploy)
// Vendor-neutral (ADR-002): hosting/CDN sağlayıcısı bağlamaz. Sır/credential YOK — yalnız ${ENV} referansı.
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // L0 ayrı origin/auth realm: değerler deploy ortamından (${ENV}); kaynakta sabit değer YOK.
  env: {
    APP_PLANE: "platform_control_plane",
    APP_TIER: "L0",
    NETWORK_EXPOSURE: "internal_only",
    AUTH_REALM: "platform",
  },
  // ADR-011: internal-only — güvenlik başlıkları sıkı; dış indeksleme/çerçeveleme kapalı.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
