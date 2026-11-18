import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Dev mode only (ENV-12): Vite runs inside the ui container, never on the host.
  server: {
    proxy: { "/api": { target: "http://controller:8000", ws: true } },
    // Polling, because file events from a Colima host do not reach the container.
    watch: { usePolling: true, interval: 500 },
  },
});
