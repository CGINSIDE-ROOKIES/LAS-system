import path from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

/** @type {import('next').NextConfig} */
const allowedFrameOrigins = process.env.ALLOWED_FRAME_ORIGINS
  ? process.env.ALLOWED_FRAME_ORIGINS.split(",").map((o) => o.trim())
  : [];
const backendInternalUrl = process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "");

const frameAncestors =
  allowedFrameOrigins.length > 0
    ? `'self' ${allowedFrameOrigins.join(" ")}`
    : "'self'";

const nextConfig = {
  output: "standalone",
  experimental: {
    outputFileTracingRoot: path.join(__dirname, "../../"),
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: `frame-ancestors ${frameAncestors}`,
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
        ],
      },
    ];
  },
  async rewrites() {
    if (!backendInternalUrl) {
      return [];
    }

    return [
      {
        source: "/api/:path*",
        destination: `${backendInternalUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
