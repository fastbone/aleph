FROM node:13-slim

RUN mkdir /alephui
WORKDIR /alephui

COPY .npmrc /alephui/.npmrc
COPY tsconfig.json /alephui/tsconfig.json
COPY package.json /alephui

RUN npm install

COPY i18n /alephui/i18n
COPY public /alephui/public
COPY src /alephui/src

ENV REACT_APP_API_ENDPOINT /api/2/
# RUN npm run build
