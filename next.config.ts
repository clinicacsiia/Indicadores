import type { NextConfig } from "next";

const cabecalhos = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },   // o portal usa iframes do próprio site
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const config: NextConfig = {
  poweredByHeader: false,
  serverExternalPackages: ["@sparticuz/chromium", "puppeteer-core"],
  reactStrictMode: true,
  async headers() {
    return [
      { source: "/:path*", headers: cabecalhos },
      { source: "/((?!_next/static|_next/image|favicon).*)", headers: [{ key: "Cache-Control", value: "no-store" }] },
    ];
  },
};

export default config;
