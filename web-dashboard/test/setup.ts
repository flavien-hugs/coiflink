// Setup global vitest — matchers `@testing-library/jest-dom` (`toBeInTheDocument`
// etc.) pour les tests d'interaction React (`*.test.tsx`). `cleanup()` explicite
// après chaque test : sans `test.globals: true` dans `vitest.config.ts`,
// `@testing-library/react` ne détecte pas automatiquement le hook `afterEach` de
// vitest et laisse les rendus précédents (y compris les portails `createPortal`)
// dans `document.body` d'un test à l'autre.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
