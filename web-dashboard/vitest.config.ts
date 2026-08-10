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
    // jsdom : requis par les tests d'interaction React (`@testing-library/react`,
    // `*.test.tsx`) — voir `receipt-print-modal.test.tsx`. Les tests purs (logique
    // domaine, gateways, BFF) n'utilisent aucune API DOM et restent inchangés
    // sous jsdom.
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.ts", "test/**/*.test.tsx"],
  },
});
