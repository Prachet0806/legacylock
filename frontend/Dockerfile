# Production image: npm ci -> build (NEXT_PUBLIC_API_URL baked in!) -> serve.
# Build with: docker build --build-arg NEXT_PUBLIC_API_URL=<empty for same-origin> .
# Same-origin default ("") uses /api. Set the API_UPSTREAM build argument for
# the Next rewrite, or configure the edge rewrite described in DEPLOY.md.
ARG NEXT_PUBLIC_API_URL=""

FROM node:22.23.3-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22.23.3-alpine AS builder
ARG NEXT_PUBLIC_API_URL=""
ARG API_UPSTREAM="http://backend:8000"
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV API_UPSTREAM=${API_UPSTREAM}
RUN npm run build

FROM node:22.23.3-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://localhost:3000/ > /dev/null || exit 1
CMD ["node", "server.js"]
