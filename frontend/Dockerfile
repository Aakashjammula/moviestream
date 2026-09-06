FROM node:20-alpine
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json next.config.ts ./
RUN npm install

COPY app ./app

RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
