# Setup checklist (your side)

Everything here is done once, by you, before phase 1 starts. Estimated time:
about an hour, most of it waiting for account approvals.

**Never paste tokens or passwords into chat.** Where Claude needs a secret to
test something, add it as an environment variable in the Claude Code
environment settings (claude.ai/code → Environments → your environment →
Environment variables). Everything else lives in the VPS `.env`.

---

## 1. Hugging Face (pyannote diarization models) — 10 min

1. Create an account at https://huggingface.co/join.
2. Accept the gated-model conditions (a short form each, approval is
   immediate):
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Create a token: Settings → Access Tokens → **Create new token** →
   type **Read** → name it `transcripciones`. Copy it once; it starts with
   `hf_`.

- [ ] Account created
- [ ] Both model licenses accepted
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

## 3. Domain + Cloudflare — 15 min

1. Create a free account at https://dash.cloudflare.com/sign-up.
2. Domain: either
   - buy one through Cloudflare Registrar (Domain Registration → Register
     Domains; sold at cost, ~$10/yr), or
   - add a domain you already own (Add a site → Free plan) and change its
     nameservers at your registrar to the two Cloudflare gives you.
     Propagation can take up to a day.
3. Create the tunnel: Zero Trust → Networks → Tunnels → **Create a tunnel** →
   Cloudflared → name `transcripciones` → **Save**.
   On the next screen copy the long token from the Docker command
   (`--token eyJ…`). That is `TUNNEL_TOKEN`. Skip running the command.
4. Still in the tunnel: **Public Hostname** tab → Add a public hostname:
   - Subdomain: `transcripciones` (or whatever you want)
   - Domain: your domain
   - Service type `HTTP`, URL `web:8000`
5. Optional but recommended: Zero Trust → Settings → Authentication is
   *not* needed. We use the app's own login.

Note: Cloudflare's free plan caps a single request body at 100 MB. The app
uploads in 5 MB chunks specifically so multi-GB hearings still work.

- [ ] Cloudflare account
- [ ] Domain active on Cloudflare (status "Active" in the dashboard)
- [ ] Tunnel created, `TUNNEL_TOKEN` saved → VPS `.env`
- [ ] Public hostname `transcripciones.<domain>` → `http://web:8000`

## 4. VPS — 20 min

Hetzner is the suggested provider; any Ubuntu VPS with Docker works.

1. Sign up at https://console.hetzner.cloud (identity verification can take
   a few hours on a new account).
2. New project `transcripciones` → **Add Server**:
   - Location: **Ashburn, VA** (closest to Puerto Rico)
   - Image: **Ubuntu 24.04**
   - Type: shared vCPU, the ~€4–8 tier with **4 GB RAM**
   - Disk: hearings are big and kept 30 days. Either pick a plan with
     ≥ 80 GB or add a **Volume** of 100 GB (~€5/mo). Start with 80 GB.
   - SSH key: add your laptop's public key
     (`cat ~/.ssh/id_ed25519.pub`; create one with `ssh-keygen -t ed25519`
     if you don't have it). Do **not** use password login.
   - Firewall: create one that allows inbound **SSH (22)** only. Nothing
     else needs to be open; the tunnel makes outbound connections.
3. First login and base setup:

   ```bash
   ssh root@<server-ip>
   apt update && apt upgrade -y
   apt install -y unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades
   curl -fsSL https://get.docker.com | sh
   docker --version && docker compose version
   mkdir -p /opt/transcripciones
   ```

4. Note the server IP. Nothing is deployed yet; that is phase 3.

- [ ] Server running, SSH key login works
- [ ] Firewall allows only port 22
- [ ] Docker + Compose installed
- [ ] Unattended security updates enabled

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

In claude.ai/code → Environments → your environment → **Environment
variables**, add:

| Name | Value |
|---|---|
| `MODAL_TOKEN_ID` | the `ak-…` from step 2.3 |
| `MODAL_TOKEN_SECRET` | the `as-…` from step 2.3 |
| `HF_TOKEN` | the `hf_…` from step 1.3 |

This lets Claude deploy and run the Modal function from a session without
the secrets ever appearing in chat or in git. If you'd rather not, Claude
writes the code and you run `modal run` on your laptop and paste the output.

- [ ] Environment variables set (or decided to run Modal from the laptop)

## 7. Later, not now

- **Backups** (phase 3): a Backblaze B2 account and a bucket, or a Cloudflare
  R2 bucket. Free tiers cover this.
- **Uptime monitor** (phase 3): a free UptimeRobot or Better Stack account
  pointing at `https://transcripciones.<domain>/healthz`.
- **Second account** for the other person (phase 4): just their preferred
  username; the password is generated when you run `scripts/add_user.py`.

---

## What you will end up holding

| Secret | Where it lives |
|---|---|
| `HF_TOKEN` | Modal secret `huggingface`; Claude Code env var |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | VPS `.env`; Claude Code env var |
| `TUNNEL_TOKEN` | VPS `.env` only |
| `SECRET_KEY` (session signing) | generated during phase 3 with `openssl rand -hex 32`; VPS `.env` only |
| Account passwords | generated by `scripts/add_user.py` in phase 3; give to each person directly |
