import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  ...(process.env.MEGABRAIN_VISUAL_QA === "1" ? { experimental: { cpus: 1 } } : {}),
};

export default nextConfig;
