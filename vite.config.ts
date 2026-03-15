import { defineConfig } from "vite";
import basicSsl from "@vitejs/plugin-basic-ssl";

export default defineConfig({
  plugins: [basicSsl()],
  server: {
    port: 5173,
    host: true, // listen on 0.0.0.0 so you can open from other devices (e.g. mobile) via LAN IP
    https: true, // required for camera (getUserMedia) on iOS Safari — use the https:// URL on your phone
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
