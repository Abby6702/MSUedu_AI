# Deployment guide

I have **not** run these steps on a server. Treat them as a checked outline and verify each one.

## 1. What a host must provide
Linux with Python 3.10+, MySQL 8 (own or managed), HTTPS, one long-running process (not "serverless"),
a persistent disk for `UPLOAD_FOLDER`. The AI needs either an online provider (`AI_PROVIDER=openai`) or a
private machine running Ollama (`OLLAMA_BASE_URL`). Most small hosts cannot run Ollama. Plans and prices change,
so check current terms before choosing.

## 2. Run exactly one worker
Rooms and whiteboards live in process memory, so use **one worker** with threads (Flask-SocketIO docs: the
threaded gunicorn worker needs `simple-websocket`, and scaling means more single-worker instances behind a load
balancer with sticky sessions):
```
gunicorn -w 1 --threads 100 --timeout 180 --bind 127.0.0.1:8000 wsgi:app
```
Set `START_SCHEDULER=true` on that one instance so reminders run.

## 3. Steps on an Ubuntu server
```bash
sudo apt install python3-venv nginx certbot python3-certbot-nginx mysql-server
sudo adduser --system --group msuedu && sudo mkdir -p /opt/msuedu-ai /var/lib/msuedu/uploads
# copy the project to /opt/msuedu-ai (without venv, .env, uploads), then:
cd /opt/msuedu-ai && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt gunicorn simple-websocket
cp .env.production.example .env && chmod 600 .env     # edit it with real values
```
Create the database and a limited user (adapt `database/setup_phase1.sql`), then:
```bash
./venv/bin/flask --app run init-db
./venv/bin/flask --app run create-admin
APP_DEBUG=false ./venv/bin/flask --app run check-config     # must show 0 errors
sudo chown -R msuedu:msuedu /opt/msuedu-ai /var/lib/msuedu
```
`/etc/systemd/system/msuedu.service`:
```ini
[Unit]
Description=MSUEdu AI
After=network.target mysql.service

[Service]
User=msuedu
WorkingDirectory=/opt/msuedu-ai
ExecStart=/opt/msuedu-ai/venv/bin/gunicorn -w 1 --threads 100 --timeout 180 --bind 127.0.0.1:8000 wsgi:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now msuedu`. nginx (`/etc/nginx/sites-available/msuedu`, then enable it):
```nginx
server {
    listen 80;
    server_name your-domain.example;
    client_max_body_size 6m;                 # the largest upload is 5 MB
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;             # AI answers can be slow
    }
}
```
Then `sudo certbot --nginx -d your-domain.example` to add HTTPS.
Set `TRUST_PROXY=true` (one proxy: nginx) and `SOCKETIO_ORIGINS=https://your-domain.example`.

## 4. TURN (live video across networks)
STUN alone fails between some networks. Get TURN URLs, a username and a credential from a TURN provider or run
coturn yourself, then set `TURN_URLS`, `TURN_USERNAME`, `TURN_CREDENTIAL`. These values reach the browsers in the
room, so use a dedicated account.

## 5. Backups
Database: `mysqldump --single-transaction --no-tablespaces -u USER -p msuedu_ai | gzip > backup.sql.gz`
(cron daily). Files: copy `UPLOAD_FOLDER`. Keep copies off the server. **Test a restore** into a scratch database.
On Windows use `backup-db.ps1`.

## 6. Updating
Back up, copy the new code, `pip install -r requirements.txt`, `flask --app run init-db`, `flask --app run
check-config`, `sudo systemctl restart msuedu`, open `/healthz`. To roll back, restore the code and the backup.

## 7. Check it works
`https://your-domain/healthz` shows `{"status":"ok"}`. Log in, ask the AI tutor, upload a file, and open a live
room from two devices on different networks. Camera and microphone prompts only appear on HTTPS.