import path from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

/** @type {import('next').NextConfig} */
const allowedFrameOrigins = process.env.ALLOWED_FRAME_ORIGINS
  ? process.env.ALLOWED_FRAME_ORIGINS.split(",").map((o) => o.trim())
  : [];

const frameAncestors =
  allowedFrameOrigins.length > 0
    ? `'self' ${allowedFrameOrigins.join(" ")}`
    : "'self'";

const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../../"),
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
};

export default nextConfig;
