# Could La Transcriptora make money?

Notes from 2026-09-19. Short answer: yes, but the money is in a different
place than the code. The product today is a tool that lets one person
proofread a courtroom hearing several times faster than by hand. Who pays
for that, and how, is the question below.

## Three routes

### 1. Sell the service, not the software (recommended first)

Attorneys in Puerto Rico already pay per page for a *transcripción de la
prueba oral* when they appeal, and they pay a person who certifies it. With
this tool, that person can produce it in a fraction of the hours a competitor
spends.

- No billing code, no terms of service, no support burden.
- The tool is the unfair advantage, not the product. Nobody else needs to
  see it.
- Marketing is word of mouth among attorneys; the first customer is whoever
  already asks Mom for transcripts.
- **Check first:** whether the appellate rules require the transcriber to
  hold a specific certification, and what the going per-page rate is. Price
  at or slightly below market and win on turnaround time.

### 2. Software for other transcribers and small firms

Charge per hearing or per audio hour.

- GPU cost is roughly $0.20 per three-hour hearing, so the margin on a
  $15–30 price is enormous.
- Competition: Otter, Rev, Sonix, Happy Scribe, Descript all do Spanish.
- The moat is narrow but real in a small market: Puerto Rican legal
  vocabulary, courtroom roles, a Spanish-only interface built for a
  non-technical user, doubtful-word highlighting, and (once built) a
  court-format Word export. Being the one who shows up in San Juan matters
  more than any of these.

### 3. Both

Run the service for a year, learn what attorneys actually ask for, then sell
the tool to the people you would otherwise be competing with. The service
teaches you the pricing; the software scales it.

## What must exist before charging anyone else for the software

These become mandatory rather than nice-to-have (see PLAN.md §11 for the
backlog entries):

- Private per-user workspaces (today every account sees every hearing).
- Billing: Stripe or similar, per hearing or subscription.
- Terms of service and a privacy policy that address court recordings,
  sealed cases and minors; a stated retention and deletion promise.
- Backups you have actually restored once; uptime monitoring with alerts.
- The formatted court transcript export (case caption, numbered lines,
  certification page).
- A support channel in Spanish and a one-page guide.
- Security review of the login, uploads and downloads; consider Cloudflare
  Access as a second wall.
- Model licences: WhisperX, faster-whisper and Whisper large-v3 are
  permissive; verify the pyannote `speaker-diarization-community-1` terms
  before selling access.

Estimate: a few days of work, not months.

## Recommendation

Route 1. Build billing only when someone who is not Mom asks to use the
tool, and let that person tell you what it is worth.
