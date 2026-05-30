FROM node:22-alpine3.22

WORKDIR /app

RUN apk upgrade --no-cache

COPY package.json package-lock.json ./
RUN npm ci

COPY . ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
