# Deploy runbook (phase 3): VPS + Cloudflare Tunnel

Accounts and one-time setup (Modal, Hugging Face, Cloudflare, VPS) are in
`SETUP.md` §2–4. This file is the order of operations on the server and the
things to check afterwards. Budget about an hour.

## 0. What you need in hand

- VPS with Docker installed, SSH key login, firewall allowing only port 22
  (`SETUP.md` §4).
- Domain on Cloudflare, a tunnel named `transcripciones` and its token, and a
  public hostname `transcripciones.<domain>` → `http://web:8000`
  (`SETUP.md` §3).
- Modal workspace token (`ak-…` / `as-…`) and the app deployed once from your
  laptop: `uv run modal deploy modal_app.py`.

## 1. Put the code on the server

```bash
ssh root@<server-ip>
git clone https://github.com/rrivera1849/transcripciones.git /opt/transcripciones
cd /opt/transcripciones
git checkout <deploy branch>        # main once merged; claude/vibrant-lovelace-vse1kx until then
```

## 2. Configure

```bash
cp .env.example .env
nano .env
```

Set `SECRET_KEY` (`openssl rand -hex 32`), `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`,
`TUNNEL_TOKEN`. Leave `TRANSCRIBER=modal`, `RETENTION_DAYS=30`. Then:

```bash
chmod 600 .env
mkdir -p data && chmod 700 data
```

## 3. Start

```bash
docker compose up -d --build        # first build ≈ 2–3 min
docker compose ps                   # web (healthy), worker, cloudflared: all "Up"
docker compose logs cloudflared | tail -5   # look for "Registered tunnel connection"
```

## 4. Create the accounts

```bash
docker compose exec web python scripts/add_user.py mama        # asks for a password (Enter = generate one)
docker compose exec web python scripts/add_user.py <other person>
```

Passwords can be changed in the app (click the username → Cambiar
contraseña). Admin reset: `docker compose exec web python scripts/set_password.py mama`.

## 5. Verify end to end

1. Open `https://transcripciones.<domain>` — the login page, over HTTPS.
2. Log in, upload a short recording, wait for **Listo**, open it, play the
   audio, download the Word file.
3. `docker compose logs worker | tail` shows the job going to Modal and back.

## 6. Backups and updates

```bash
crontab -e
15 3 * * *  /opt/transcripciones/scripts/backup.sh >> /var/log/transcripciones-backup.log 2>&1
```

Backups are gzip'd SQLite copies under `backups/` (transcripts, users, search
index; no audio), kept 60 days. For an off-site copy, configure `rclone`
with a Backblaze B2 or Cloudflare R2 bucket and uncomment the last line of
`scripts/backup.sh`. Test a restore once: `gunzip -k backups/app-….sqlite3.gz`,
stop the stack, replace `data/app.sqlite3`, start it.

Updating the app after a new commit:

```bash
/opt/transcripciones/scripts/deploy.sh
```

It updates the branch the VPS already has checked out. To switch branches,
set `DEPLOY_BRANCH=<branch>` for that one run.

Changes to `modal_app.py` or `transcribe/` also need `uv run modal deploy
modal_app.py` from your laptop.

## Email notifications (optional)

The worker emails the uploader when a hearing finishes or fails, if `.env`
has an SMTP server and the account has an address (set under Mi cuenta).
With a Gmail account: create an app password (Google Account → Security →
2-Step Verification → App passwords), then:

```
APP_URL=https://latranscriptora.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<app password>
SMTP_FROM=you@gmail.com
```

Restart the stack (`docker compose up -d`) after editing `.env`. Port 465
uses implicit TLS; any other port uses STARTTLS. Leave `SMTP_HOST` empty
to disable; the browser notification ("Avisarme al terminar" on the home
page) works regardless.

OS updates: `unattended-upgrades` was enabled in `SETUP.md` §4; reboot when
`/var/run/reboot-required` appears. `restart: unless-stopped` brings the
stack back after a reboot.

## 7. Monitoring

Point a free uptime monitor (UptimeRobot, Better Stack) at
`https://transcripciones.<domain>/healthz` every 5 minutes, alerting your
email. Disk: `df -h /` occasionally; steady state is a few GB.

## 8. Security posture (what is and isn't true)

- HTTPS everywhere; the origin is never exposed (no inbound ports besides SSH).
- Cloudflare terminates TLS at its edge and re-encrypts to the tunnel, so
  Cloudflare can see traffic in transit. It does not store uploads. If that
  is unacceptable for court audio, the alternative is a plain VPS with its
  own certificate (Caddy + Let's Encrypt, ports 80/443 open); say so and it
  is a one-file change.
- Login: bcrypt, 5 failures → 15-minute lockout per user+IP, 90-day cookie
  marked `Secure` and `HttpOnly`, CSRF token on every write.
- Audio: kept at most `RETENTION_DAYS` on the host; on Modal only for the
  duration of the job. Transcripts live in `data/app.sqlite3` and in backups.
- Optional extra: Cloudflare Access (email one-time code) in front of the
  hostname. Free for this size; adds a second login step for her.

## Troubleshooting

| Symptom | Check |
|---|---|
| Site unreachable, tunnel logs say unauthorized | `TUNNEL_TOKEN` in `.env`; recreate the token in Zero Trust |
| Login works but cookie not kept | `docker compose logs web` must show `X-Forwarded-Proto`-aware https URLs; the Dockerfile passes `--proxy-headers` |
| Job stuck "Enviando al servidor GPU" | Modal token in `.env`; `docker compose logs worker` |
| "no está desplegado en Modal" | `uv run modal deploy modal_app.py` from the laptop, then Reintentar |
| Upload fails around 100 MB | Chunks are 5 MB, so this should not happen; check `MAX_UPLOAD_MB` |
