/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  // 设置基础路径，用于子路径部署
  basePath: '/stock',
  // 确保 assetPrefix 也正确配置
  assetPrefix: '/stock',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: '/stock-api/:path*',
      },
    ]
  },
}

module.exports = nextConfig
