# Development image: runs the Vite dev server. A production build served by Nginx
# is added with the hosting task (P1-10).
FROM node:22-alpine

WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
