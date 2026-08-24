# Multi-stage build. The `dev` stage is used by docker-compose.dev.yml (Vite
# dev server, hot reload). The default (final) stage builds static assets
# and serves them via nginx, which also proxies /api and /ws to the backend
# so the frontend never needs to know the backend's hostname at build time.

FROM node:20-alpine AS base
WORKDIR /app
COPY package.json ./
RUN npm install

FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM base AS build
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
