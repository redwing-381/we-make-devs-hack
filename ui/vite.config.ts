import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // one public URL (e.g. a Cloudflare quick tunnel) serves the UI, the API and MCP for remote agents
    allowedHosts: [".trycloudflare.com", "localhost"],
    proxy: {
      "/api": api,
      // changeOrigin: the MCP server only accepts requests addressed to its own host
      "/mcp": { target: api, changeOrigin: true },
    },
  },
});
