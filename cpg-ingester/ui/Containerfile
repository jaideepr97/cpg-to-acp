FROM image-registry.openshift-image-registry.svc:5000/jrao-cpg-acp/node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM image-registry.openshift-image-registry.svc:5000/jrao-cpg-acp/nginx-unprivileged:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV BFF_HOST=cpg-ingester-bff:8080
EXPOSE 8080
