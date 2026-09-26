import type { NextConfig } from 'next';

// The dev-only "N" badge sat where the map controls go and read as a compass; errors still surface without it.
const nextConfig: NextConfig = { devIndicators: false };

export default nextConfig;
