# Image de production de l'interface web CoifLink (Next.js standalone) — issue #4.
#
# Build multi-stage → runtime minimal (sortie `output: 'standalone'` de
# next.config.ts). Principes : AUCUN secret dans l'image (config par variables
# d'environnement à l'exécution, #5) ; utilisateur NON-root ; Node 20 (ADR-0007).
# Push vers un registre différé (#5) : image construite en CI (build-seul).

# --- Étape 1 : dépendances -------------------------------------------------- #
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- Étape 2 : build -------------------------------------------------------- #
FROM node:20-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# --- Étape 3 : runtime ------------------------------------------------------ #
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Utilisateur non-root dédié.
RUN groupadd --system --gid 1001 nodejs \
 && useradd --system --uid 1001 --gid nodejs nextjs

# Sortie standalone : serveur autonome + assets statiques uniquement.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
