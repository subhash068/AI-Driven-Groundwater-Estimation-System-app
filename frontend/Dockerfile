FROM node:20-alpine AS build

WORKDIR /repo

ARG VITE_API_BASE=/api
ARG VITE_ENABLE_LIVE_API=true
ARG VITE_LOCAL_DATA_ONLY=false

ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_ENABLE_LIVE_API=${VITE_ENABLE_LIVE_API}
ENV VITE_LOCAL_DATA_ONLY=${VITE_LOCAL_DATA_ONLY}

RUN apk add --no-cache python3

COPY frontend/package*.json /repo/frontend/
WORKDIR /repo/frontend
RUN npm ci

WORKDIR /repo
COPY frontend /repo/frontend
COPY scripts /repo/scripts
COPY output /repo/output
COPY model /repo/model

WORKDIR /repo/frontend
RUN npm run build

FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/frontend/dist /usr/share/nginx/html

EXPOSE 80
