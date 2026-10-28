# Development image: runs the Vite dev server. A production build served by Nginx
# is added with the hosting task (P1-10).
FROM node:26-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
