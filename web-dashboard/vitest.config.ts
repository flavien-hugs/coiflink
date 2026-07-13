import { fileURLToPath } from "url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    // Aligné sur tsconfig.json : "@/*" → "./*" (racine du paquet).
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    include: ["test/**/*.test.ts"],
  },
});
