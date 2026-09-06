import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Proxy API calls to the backend. This runs server-side inside the
  // frontend container, so it works regardless of which host/port or
  // IP the browser used to reach the frontend (localhost, LAN IP,
  // or even the container IP directly). Nginx also proxies /api/,
  // so this is a fallback for direct-frontend access.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://backend:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
