# ── Clinical Copilot Engine — Frontend Dockerfile ───────────────────
# Multi-stage build: Node build → Nginx serve

# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
# RUN npm ci
RUN npm install

COPY . .
RUN npm run build


# Stage 2: Serve with Nginx
FROM nginx:alpine AS runtime

LABEL maintainer="Clinical Copilot Engine"
LABEL description="React frontend for clinical autocomplete"

# Copy custom Nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
