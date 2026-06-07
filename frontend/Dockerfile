FROM nginx:1.27-alpine

RUN apk add --no-cache openssl && \
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
      -keyout /etc/ssl/private/nginx-selfsigned.key \
      -out /etc/ssl/certs/nginx-selfsigned.crt \
      -subj "/C=TR/ST=Local/L=Local/O=YuzTanima/CN=yuz-tanima" && \
    chmod 600 /etc/ssl/private/nginx-selfsigned.key

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY static/ /usr/share/nginx/html/

EXPOSE 80 443
