FROM node:24-alpine AS build

WORKDIR /workspace

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci

COPY apps/web ./apps/web

ARG PUBLIC_API_BASE_URL=""
ARG PUBLIC_CLERK_PUBLISHABLE_KEY="pk_test_Zm9vLmNsZXJrLmFjY291bnRzLmRldiQ="
ENV PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}
ENV PUBLIC_CLERK_PUBLISHABLE_KEY=${PUBLIC_CLERK_PUBLISHABLE_KEY}

RUN npm run build:web && npm prune --omit=dev

FROM node:24-alpine AS runtime

ENV HOST=0.0.0.0
ENV NODE_ENV=production
ENV PORT=4321

WORKDIR /workspace

COPY --chown=node:node package.json package-lock.json ./
COPY --chown=node:node apps/web/package.json ./apps/web/package.json
COPY --chown=node:node --from=build /workspace/node_modules ./node_modules
COPY --chown=node:node --from=build /workspace/apps/web/dist ./apps/web/dist

USER node

EXPOSE 4321

CMD ["node", "./apps/web/dist/server/entry.mjs"]
