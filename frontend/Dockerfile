# Development image: runs the Vite dev server. The production build, served by Nginx,
# is made by deploy/web/Dockerfile (P1-10).
FROM node:22-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
