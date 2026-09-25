FROM nginx:1.29-alpine

COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf

RUN chown -R nginx:nginx /var/cache/nginx /var/run

USER nginx

EXPOSE 8080
