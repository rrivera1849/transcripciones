# Setup checklist (your side)

We build local-first: the app runs on your laptop and only the GPU work goes
to Modal. **To start phase 1 you need sections 1, 2, 5 and 6 only**, about
30 minutes. Sections 3 and 4 (Cloudflare, VPS) are for phase 3 and can wait.

**Never paste tokens or passwords into chat.** Where Claude needs a secret to
test something, add it as an environment variable in the Claude Code
environment settings (claude.ai/code → Environments → your environment →
Environment variables). Everything else lives in the VPS `.env`.

---

## 1. Hugging Face (pyannote diarization models) — 10 min

1. Create an account at https://huggingface.co/join.
2. Accept the gated-model conditions (a short form each, approval is
   immediate):
   - https://huggingface.co/pyannote/speaker-diarization-community-1
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Create a token: Settings → Access Tokens → **Create new token** →
   type **Read** → name it `transcripciones`. Copy it once; it starts with
   `hf_`.

- [ ] Account created
- [ ] All three model licenses accepted
- [ ] Read token created → goes to Modal (step 2.4) and to the Claude Code
      environment as `HF_TOKEN`

## 2. Modal (GPU transcription) — 15 min

1. Sign up at https://modal.com with GitHub or email. The Starter plan is
   free and includes a monthly compute credit that should cover normal use.
2. On your laptop, install the CLI and log in:

   ```bash
   pip install modal
   modal setup
   ```

   This opens a browser and stores a personal token on your laptop.
3. Create a **workspace token** for servers (the VPS worker and Claude's
   environment): dashboard → Settings → API Tokens → **New token**.
   You get a `MODAL_TOKEN_ID` (`ak-…`) and `MODAL_TOKEN_SECRET` (`as-…`).
4. Store the Hugging Face token as a Modal secret named `huggingface`:

   ```bash
   modal secret create huggingface HF_TOKEN=hf_xxxxxxxxxxxxxxxx
   ```

   (or dashboard → Secrets → Create → custom → key `HF_TOKEN`).
5. Add a billing method even if you expect to stay inside the free credit;
   Modal pauses functions without one once the credit runs out.

- [ ] Account created, CLI logged in on laptop
- [ ] Workspace token created → VPS `.env` and Claude Code environment as
      `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`
- [ ] Secret `huggingface` with key `HF_TOKEN` exists
- [ ] Billing method on file

## 3. Domain + Cloudflare — 20 min — *phase 3, needed now*

Cloudflare gives us the public address, HTTPS and the tunnel, all free.

**3.1 Account**

1. Go to https://dash.cloudflare.com/sign-up, create the account, confirm the
   email.

**3.2 Domain** — pick one of the two:

- *Buy a new one (simplest).* Left menu → **Domain Registration** →
  **Register Domains** → search a name → add to cart → pay. Cloudflare sells
  at cost (≈ $10/yr for .com). It is active immediately; skip to 3.3.
- *Use a domain you already own.* Left menu → **Add a domain** → type it →
  **Continue** → choose the **Free** plan → Cloudflare scans existing DNS,
  click **Continue** → it shows **two nameservers** (like
  `ada.ns.cloudflare.com`). Log in at the registrar where you bought the
  domain, find "Nameservers", replace them with those two, save. Back in
  Cloudflare click **Check nameservers**. Status changes to **Active** within
  minutes to a day; you get an email.

**3.3 Zero Trust (where tunnels live)**

1. Left menu → **Zero Trust**. The first time it asks for a *team name*
   (anything, e.g. `riverasoto`) and a plan: choose **Free**. It may ask for
   a payment method even for the free plan; nothing is charged.

**3.4 Create the tunnel**

1. Zero Trust → **Networks** → **Tunnels** → **Create a tunnel**.
2. Connector type: **Cloudflared** → **Next**.
3. Tunnel name: `transcripciones` → **Save tunnel**.
4. The next page ("Install and run a connector") shows install commands.
   Click the **Docker** tab. The command ends in
   `--token eyJhbGci...` (a very long string). **Copy only the token**, the
   part after `--token`. That is `TUNNEL_TOKEN` for the server's `.env`.
   Do not run the command here. → **Next**.

**3.5 Route the hostname to the app**

On the "Route tunnel" page (also reachable later: click the tunnel → **Edit**
→ **Public Hostname** → **Add a public hostname**):

| Field | Value |
|---|---|
| Subdomain | `transcripciones` (or whatever you like) |
| Domain | your domain (dropdown) |
| Path | leave empty |
| Type | **HTTP** |
| URL | `web:8000` |

**Save**. Cloudflare creates the DNS record for you. `web:8000` is the name
of the app container inside Docker Compose; the `cloudflared` container
resolves it on the same private network.

The tunnel shows **Inactive/Down** until the server side runs; that is
expected.

**3.6 Optional hardening (skip for now)**

- Zero Trust → **Access** → Applications: put an email one-time-code login in
  front of the hostname. Adds a step for Mom; the app's own login is enough
  to start.

- [ ] Cloudflare account
- [ ] Domain shows **Active**
- [ ] Tunnel `transcripciones` created; `TUNNEL_TOKEN` saved somewhere safe
- [ ] Public hostname `transcripciones.<domain>` → HTTP `web:8000`

## 4. VPS (Hetzner) — 25 min — *phase 3, needed now*

**4.1 SSH key on your laptop** (skip if `~/.ssh/id_ed25519.pub` exists)

```bash
ssh-keygen -t ed25519 -C "laptop"        # accept defaults; a passphrase is fine
cat ~/.ssh/id_ed25519.pub                # copy this whole line
```

**4.2 Account**

1. https://console.hetzner.cloud → **Sign up**. New accounts go through a
   verification step (payment method; sometimes an ID check). This can take
   from minutes to a day.

**4.3 Create the server**

1. **New project** → name `transcripciones` → open it → **Add Server**.
2. **Location**: **Ashburn, VA** (`ash`). Closest to Puerto Rico.
3. **Image**: **Ubuntu 24.04**.
4. **Type**: **Shared vCPU** → **x86 (Intel/AMD)** → **CPX21**
   (3 vCPU, 4 GB RAM, 80 GB disk, ≈ €8/mo). US locations only offer the
   CPX line, which is why not the cheaper CX plans.
5. **Networking**: keep **Public IPv4** and **IPv6** both ticked. IPv4 costs
   about €0.50/mo; you need it to SSH in from most home networks.
6. **SSH keys**: **Add SSH key** → paste the line from 4.1 → name it
   `laptop`. Make sure it is ticked. (With a key, Hetzner disables password
   login on the server.)
7. **Firewalls**: **Create firewall** → name `ssh-only` → inbound rules: keep
   only **SSH (TCP 22)** from `Any IPv4 / Any IPv6`; delete any ICMP or
   other rows if present. Outbound: default (allow all). Apply to this
   server. Nothing else needs to be open: the tunnel dials out.
8. **Backups**: leave off (we do our own; this would add 20 %).
9. **Name**: `transcripciones`. → **Create & Buy now**.

The server is ready in about a minute; note its **IPv4 address**.

**4.4 First login and base setup**

```bash
ssh root@<server-ip>          # answer "yes" to the fingerprint prompt

apt update && apt upgrade -y
apt install -y git unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades     # choose <Yes>
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version     # both print versions
timedatectl set-timezone America/Puerto_Rico
```

If `apt upgrade` says a reboot is required: `reboot`, wait a minute,
`ssh` back in.

**4.5 Hand over to the runbook**

Continue with `docs/DEPLOY.md` from step 1 (clone, `.env`, `docker compose
up`, accounts, verification, backups).

- [ ] Server running, `ssh root@<ip>` works with the key
- [ ] Firewall `ssh-only` attached
- [ ] Docker + Compose installed, git installed
- [ ] Unattended security updates enabled

## 4b. Your laptop (for running the app locally) — 10 min

1. Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) (`pip install uv` or
   the one-line installer on that page).
2. `ffmpeg` on the PATH: macOS `brew install ffmpeg`; Windows
   `winget install ffmpeg`; Ubuntu `sudo apt install ffmpeg`.
3. Git, and a clone of this repo.

- [ ] `uv --version`, `ffmpeg -version`, and `modal --version` all print
      something.

## 5. Stand-in audio (until real hearings arrive) — 10 min

We need 2–3 long, multi-speaker Puerto Rican recordings in a formal register.
Good sources, all public:

- **Senado de Puerto Rico** and **Cámara de Representantes** session
  recordings on YouTube (search "Sesión Senado de Puerto Rico").
- **Tribunal Supremo de Puerto Rico** oral arguments ("argumentación oral
  Tribunal Supremo Puerto Rico"), when available.
- Any PR news interview with several people talking over room mics.

What to do: pick 2–3 videos of 20–60 minutes and **send Claude the links**.
Claude will extract the audio and keep it out of git. If a link can't be
fetched from the remote environment, fall back to:

```bash
pip install yt-dlp
yt-dlp -x --audio-format m4a -o "samples/%(title)s.%(ext)s" "<url>"
```

and upload the files somewhere Claude can download them (a temporary Google
Drive or Dropbox link), or commit them with Git LFS.

- [ ] 2–3 links sent

## 6. Give Claude what it needs for phase 1

Two things, both in claude.ai/code → Environments → your environment:

**a. Environment variables**

| Name | Value |
|---|---|
| `MODAL_TOKEN_ID` | the `ak-…` from step 2.3 |
| `MODAL_TOKEN_SECRET` | the `as-…` from step 2.3 |
| `HF_TOKEN` | the `hf_…` from step 1.3 |

**b. Network access.** Set the environment's network access to **Full** (or
allow `huggingface.co`, `cdn-lfs.huggingface.co`, `hf.co`). This lets Claude
download models and validate the pipeline on CPU inside a session.

**Known limit:** the Claude Code remote environment routes traffic through
an HTTPS proxy that does not support gRPC, and the Modal client is gRPC-only.
So `modal deploy` / `modal run` cannot be executed from a Claude session
regardless of the network policy. Modal commands run from **your laptop**;
Claude writes and validates the code, you run the two commands below and
paste the output back.

Both changes apply to **new** sessions only.
Docs: https://code.claude.com/docs/en/claude-code-on-the-web

**Running Modal from your laptop** (the normal path):

```bash
uv sync --group dev
uv run modal deploy modal_app.py                # builds the image once (~10 min)
uv run modal run modal_app.py --file samples/x.m4a --out out/ --min-speakers 3 \
    --vocabulary "Morovis, Ciales, Lcda. Torres"   # optional: names, places, key terms
```

and paste the printed timing line plus a few lines of `out/x.txt` back to
Claude.

- [ ] Env vars set and network opened, new session started
- [ ] Modal CLI logged in on the laptop (`modal setup`)

## 7. Later, not now

- **Backups** (phase 3): a Backblaze B2 account and a bucket, or a Cloudflare
  R2 bucket. Free tiers cover this.
- **Uptime monitor** (phase 3): a free UptimeRobot or Better Stack account
  pointing at `https://transcripciones.<domain>/healthz`.
- **Second account** for the other person (phase 4): just their preferred
  username; `scripts/add_user.py` asks for the password (or generates one).
  Anyone can change their own password from the app (click the username in
  the header); `scripts/set_password.py` is the admin reset if it is forgotten.

---

## What you will end up holding

| Secret | Where it lives |
|---|---|
| `HF_TOKEN` | Modal secret `huggingface`; Claude Code env var |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | VPS `.env`; Claude Code env var |
| `TUNNEL_TOKEN` | VPS `.env` only |
| `SECRET_KEY` (session signing) | generated during phase 3 with `openssl rand -hex 32`; VPS `.env` only |
| Account passwords | typed or generated in `scripts/add_user.py` in phase 3; give to each person directly |
