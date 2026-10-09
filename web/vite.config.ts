import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, Vite serves the UI and forwards /api to the Python server (`uv run outreach serve`).
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
