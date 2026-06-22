import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const apiUrl = (process.env.NEXT_PUBLIC_API_URL?.trim() || "https://goldie-api-production.up.railway.app").replace(
	/\/+$/,
	"",
);

const nextConfig: NextConfig = {
	allowedDevOrigins: ["172.25.176.1:3000"],
	async rewrites() {
		if (isDev) {
			return [
				{
					source: "/api/:path*",
					destination: `${apiUrl}/api/:path*`,
				},
			];
		}
		return [];
	},
};

export default nextConfig;
