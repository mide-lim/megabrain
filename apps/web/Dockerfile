ARG NODE_BASE_IMAGE=node:26.7.0-alpine
FROM ${NODE_BASE_IMAGE} AS dependencies

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

FROM ${NODE_BASE_IMAGE} AS builder

WORKDIR /app

COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM ${NODE_BASE_IMAGE} AS runtime

ARG SOURCE_REVISION
ARG IMAGE_VERSION
LABEL org.opencontainers.image.revision=${SOURCE_REVISION} \
      org.opencontainers.image.source=https://github.com/mide-lim/megabrain \
      org.opencontainers.image.version=${IMAGE_VERSION}

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

WORKDIR /app

RUN addgroup --system --gid 10001 nodejs \
    && adduser --system --uid 10001 --ingroup nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
