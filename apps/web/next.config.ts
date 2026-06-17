import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
	async rewrites() {
		if (isDev) {
			return [
				{
					source: "/api/:path*",
					destination: "https://goldie-api-production.up.railway.app/api/:path*",
				},
			];
		}
		return [];
	},
};

export default nextConfig;
