import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  publicDir: "public",
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["fflate", "standardized-audio-context"],
        },
      },
    },
  },
  server: {
    port: 5173,
    open: true,
    fs: {
      allow: ["..", "../data"],
    },
  },
});
