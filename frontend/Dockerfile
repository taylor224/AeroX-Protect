# ── build ────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

ARG VITE_APP_API_URL=/api/v1
ARG VITE_APP_NAME=axp
ARG VITE_APP_VERSION=1
ENV VITE_APP_API_URL=$VITE_APP_API_URL \
    VITE_APP_NAME=$VITE_APP_NAME \
    VITE_APP_VERSION=$VITE_APP_VERSION

RUN npm run build

# ── serve ────────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine
RUN apk add --no-cache wget
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
