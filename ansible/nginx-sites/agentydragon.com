server {
    listen 80;
    server_name agentydragon.com www.agentydragon.com;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name agentydragon.com www.agentydragon.com;

    ssl_certificate /etc/letsencrypt/live/agentydragon.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/agentydragon.com/privkey.pem;

    # /webhook_inbox/* → proxy to webhook inbox
    location ^~ /webhook_inbox/ {
        proxy_pass         http://127.0.0.1:4473/;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_redirect / /webhook_inbox/;
    }

    root /var/www/agentydragon.com;
    index index.html index.htm;

    # TODO: what's this for?
    location / {
        try_files $uri $uri/ =404;
    }
}
