import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI backend (uvicorn on :8000).
// In production the backend serves the built frontend itself, same origin.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          // CommonJS helpers are also used by React. Letting Rollup place
          // them in Plotly would make the entry point import the whole chart
          // library even when only the upload/zone editor is displayed.
          if (id.includes("commonjsHelpers")) return "commonjs";
          if (id.includes("plotly.js-basic-dist-min")) return "plotly";
          if (id.includes("/node_modules/cytoscape") || id.includes("/node_modules/@dagrejs/")) return "cytoscape";
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/THIRD_PARTY_NOTICES.txt": { target: "http://127.0.0.1:8000" },
    },
  },
});
