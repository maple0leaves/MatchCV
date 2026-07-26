import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 后端地址：Java (Spring Boot) 网关，默认本地开发端口 8080。
// 生产环境可通过 VITE_API_BASE_URL 覆盖，此时前端直接请求该地址（需后端 CORS 放行）。
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET || "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: API_PROXY_TARGET,
        changeOrigin: true,
      },
    },
  },
});
