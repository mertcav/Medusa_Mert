// @chanteur/tenant-app — L1+L2 Tenant Application Plane (ADR-011: birlikte, public deploy)
// Vendor-neutral (ADR-002): hosting/CDN sağlayıcısı bağlamaz. Sır/credential YOK — yalnız ${ENV} referansı.
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // L1+L2 ayrı origin/auth realm (platform realm'inden AYRI — FR-IAM-008); değerler ${ENV}'den.
  env: {
    APP_PLANE: "tenant_application_plane",
    APP_TIER: "L1+L2",
    NETWORK_EXPOSURE: "public",
    AUTH_REALM: "tenant",
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
