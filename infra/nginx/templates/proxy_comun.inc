proxy_http_version 1.1;
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_connect_timeout 5s;
proxy_read_timeout    30s;
# Django (config.settings.prod) también pone estos encabezados; se ocultan los suyos para que
# no salgan duplicados y la política quede en un solo lugar (los add_header del server 443).
proxy_hide_header Strict-Transport-Security;
proxy_hide_header X-Frame-Options;
proxy_hide_header X-Content-Type-Options;
proxy_hide_header Referrer-Policy;
