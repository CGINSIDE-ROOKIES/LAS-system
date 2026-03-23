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
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: `frame-ancestors ${frameAncestors}`,
          },
        ],
      },
    ];
  },
};

export default nextConfig;
