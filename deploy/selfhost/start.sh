#!/bin/bash
# Entry point of Dockerfile.selfhost: nginx on $PORT in front of uvicorn.
set -e

# Reuse frontend/nginx.conf: listen on Heroku's $PORT, accept any host name,
# and proxy to uvicorn in this container instead of the compose service.
sed -e "s/listen 80;/listen ${PORT:-8080};/" \
    -e "s/server_name [^;]*;/server_name _;/" \
    -e "s#http://backend:8000#http://127.0.0.1:8000#g" \
    /etc/papermanager/nginx.conf > /etc/nginx/conf.d/default.conf

cd /app
uvicorn main:app --host 127.0.0.1 --port 8000 &
nginx -g 'daemon off;' &

# Exit (and let Heroku restart the dyno) as soon as either process dies.
wait -n
exit 1
