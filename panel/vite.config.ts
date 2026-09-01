import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Сборка кладётся в данные python-пакета: авторам панели не нужен Node (NFR-1).
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../ugar/data/панель",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/dashboard": "http://127.0.0.1:8765",
    },
  },
});
