FROM node:18-alpine

WORKDIR /app

# Bağımlılıkları kopyala ve kur
COPY package.json ./
RUN npm install

# Uygulama kodunu kopyala
COPY . .

# Uygulamayı derle
RUN npm run build

# Uygulama portunu aç
EXPOSE 3000

# Uygulamayı başlat
CMD ["npm", "start"]
