server {
    listen 80;
    server_name atlas.agentydragon.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name atlas.agentydragon.com;

    ssl_certificate /etc/letsencrypt/live/atlas.agentydragon.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/atlas.agentydragon.com/privkey.pem;

    location / {
        proxy_pass https://10.13.13.30:8006;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Ignore self-signed certificate errors from the backend
        proxy_ssl_verify off;
        proxy_ssl_server_name on;
        
        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Increase timeout values for SPICE sessions
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        
        # Disable buffering for real-time protocols
        proxy_buffering off;
        proxy_request_buffering off;
    }
}