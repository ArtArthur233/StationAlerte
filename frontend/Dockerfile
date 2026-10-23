# Étape 1 : compiler le site (Node.js ne sert qu'à ça, il n'est pas dans l'image finale).
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Étape 2 : servir les fichiers compilés avec nginx, avec les en-têtes de sécurité.
FROM nginx:1.28-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
