import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const SERVER_PORT = process.env.SMART_FACTORY_SERVER_PORT ?? '4100';
const WEB_PORT = Number(process.env.SMART_FACTORY_WEB_PORT ?? 4110);

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 前端没有 mock 了：智能体与模型都已收进本仓 server
  // （server/src/modules/agent/、server/src/modules/model/），
  // 请求经下面那条 `/api` 代理转发。
  server: {
    port: WEB_PORT,
    // 绑全部地址：vite 默认只绑 localhost（本机会落到 ::1），经 127.0.0.1 转发访问会 ERR_CONNECTION_REFUSED
    host: true,
    // 开发态把 /api 代理到后端，前端代码里只写相对路径，避免 CORS 与环境变量分叉
    proxy: {
      '/api': {
        // 显式 127.0.0.1：localhost 在部分机器上先解析到 ::1
        target: `http://127.0.0.1:${SERVER_PORT}`,
        changeOrigin: true,
        // 实时通道与 REST 同端口同前缀（server 侧 /api/smart-factory/v1/ws）。
        // 不加这一行，浏览器的 WS 握手会被当普通 HTTP 转发，连接直接失败 —— 且报错形态很难猜。
        // 记在 4.07-待前端对齐.md §4。
        ws: true,
      },
    },
  },
});
