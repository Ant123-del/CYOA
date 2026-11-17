# CYOA — Choose Your Own Adventure

A productivity app for days that don't go to plan. You keep a Trello-style board of goals. The day before (or a week before), CYOA's AI turns your priorities and Google Calendar into a **branching day**: a few parallel *storylines* and a series of *chapters*. Each chapter offers several options of the same priority:

- **Calendar events** get four paths: **Yes**, **Yes, and…**, **No**, **No, and…**
- **Other blocks** get one route per storyline (e.g. Main Quest, Steady Path, Pivot)

When a chapter is about to start, you get an email. You pick a path, and it goes on your Google Calendar.

```
CYOA/
├── frontend/   React + TypeScript (Vite), Firebase Auth (Google sign-in)  → deployed on Vercel
├── backend/    FastAPI, Firestore, Google Calendar API, Claude, reminder emails → Cloud Functions for Firebase
├── firebase.json / .firebaserc
└── firestore.rules
```

**Production architecture:**
- **Vercel** serves the React app.
- **Cloud Functions for Firebase** runs the backend as two functions, both in `us-central1`:
  - `api`: the whole FastAPI app, at `https://us-central1-cyoa-f15a9.cloudfunctions.net/api`.
  - `send_reminders`: runs every minute via Cloud Scheduler and sends the "time to choose" emails.
- **Firestore** and **Firebase Auth** store the data and handle sign-in.

Nothing depends on your laptop being on.

## One-time setup

### 1. Firebase (project `cyoa-f15a9`, owned by cyoa740@gmail.com)
These are already done: Google sign-in is enabled, the Web app config is in `frontend/.env.local` and `frontend/.env.production`, and Firestore exists. `deploy.sh` deploys [firestore.rules](firestore.rules), which block direct browser access because the backend does all reads and writes.

The service account key is at `backend/serviceAccountKey.json`. It's git-ignored and never deployed, because Cloud Functions uses its own built-in credentials.

### 2. Google Calendar OAuth client
In [Google Cloud Console](https://console.cloud.google.com/) with project **cyoa-f15a9** selected:
1. **APIs & Services → Library → enable "Google Calendar API".**
2. **OAuth consent screen:** set it to External and add your Google account as a **test user**.
3. **Credentials → Create credentials → OAuth client ID → Web application.**
   - Authorized JavaScript origins: `http://localhost:5173` and your Vercel URL
   - Authorized redirect URIs (both):
     - `http://localhost:8000/api/google/callback`
     - `https://us-central1-cyoa-f15a9.cloudfunctions.net/api/api/google/callback`
4. Put the client ID and secret in `backend/.env.local` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`).

### 3. Claude API key
Create a key at https://console.anthropic.com and set `ANTHROPIC_API_KEY` in `backend/.env.local`. The planner uses `claude-opus-5-5`, which you can change with `ANTHROPIC_MODEL`.

### 4. Email (optional)
Fill in the `SMTP_*` values in `backend/.env.local`. For production, also copy the non-secret ones (`SMTP_HOST`, `SMTP_USER`, `SMTP_FROM`) into `backend/.env.cyoa-f15a9`. For Gmail: host `smtp.gmail.com`, port `587`, your address as the user, and a Google **App password** as the password. If `SMTP_HOST` is empty, reminder emails are printed in the backend console instead.

## Run it locally (two terminals)

```bash
# Terminal 1 — backend
cd backend
source venv/bin/activate           # first time: python3 -m venv venv && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
# Terminal 2 — frontend
cd frontend
npm install                         # first time only
npm run dev                         # http://localhost:5173
```

API docs: http://localhost:8000/docs

## Deploy

### Backend → Cloud Functions for Firebase
1. In the Firebase console (signed in as cyoa740@gmail.com), go to **Upgrade → Blaze plan**. Cloud Functions and Cloud Scheduler require it. Usage this small usually fits in the free tier, but setting a budget alert is a good idea.
2. Log the CLI into that account once:
   ```bash
   firebase login:add cyoa740@gmail.com
   firebase login:use cyoa740@gmail.com
   ```
3. Deploy:
   ```bash
   ./backend/deploy.sh
   ```
   The script copies `ANTHROPIC_API_KEY`, `GOOGLE_CLIENT_SECRET` and `SMTP_PASSWORD` from `backend/.env.local` into **Secret Manager**. It then deploys both functions and the Firestore rules. Non-secret production settings live in [backend/.env.cyoa-f15a9](backend/.env.cyoa-f15a9).
4. Check it: https://us-central1-cyoa-f15a9.cloudfunctions.net/api/api/health should return `{"ok":true}`.

Run `./backend/deploy.sh` again after any backend change.

### Frontend → Vercel
1. Log in and deploy from `frontend/`:
   ```bash
   cd frontend
   vercel login
   vercel --prod        # first run: create a new project and accept the detected Vite settings
   ```
   Or push the repo to GitHub, import it at vercel.com/new, and set **Root Directory = `frontend`**.
   No environment variables are needed: the build reads [frontend/.env.production](frontend/.env.production), which holds the public Firebase web config and the API URL.
2. Allow Google sign-in on your Vercel domain:
   ```bash
   backend/venv/bin/python backend/tools/authorize_domain.py <your-app>.vercel.app
   ```
3. Put that URL in `FRONTEND_URL` in `backend/.env.cyoa-f15a9` (it defaults to `https://cyoa.vercel.app`) and run `./backend/deploy.sh` again. The backend uses it for CORS, email links and the redirect after connecting Calendar.
4. Add the Vercel URL to the OAuth client's **Authorized JavaScript origins** (setup step 2).

## How it works

| Page | What it does |
|---|---|
| **Board** | Four drag-and-drop columns (Backlog / To do / Doing / Done). Each card has a priority, an estimate, a due date and tags. |
| **Plan** | Pick a day from the week strip. Write priorities, or use **Pull priorities from Board** to fill them from your open cards. Choose 2–4 storylines and click **Generate my adventure**. You can edit anything afterwards, import calendar events, add chapters, or **Reroll** one chapter's options with a hint like "I'll be tired". |
| **Today** | A timeline of the day. The current chapter opens up with its paths. Pick one and it's added to Google Calendar. **Change course** undoes a choice and removes the event CYOA created. |
| **Settings** | Connect or disconnect Google Calendar, pick a calendar, set the reminder email address and lead time, send a test email, and set your timezone. |

**Calendar behavior when you choose:**
- **Yes** on a calendar chapter: nothing new is created, because the event already exists.
- **Yes, and…**: the "and" part is scheduled right after the event.
- **No**, **No, and…**, and **routes**: an event is created at the chapter's start time, or now if the chapter has already started.

Events created by CYOA are tagged, so they are never re-imported as new chapters.

**Reminders:** saving a day schedules one reminder per unchosen chapter (chapter start minus your lead time). Choosing a path cancels that chapter's reminder. In production, the `send_reminders` Cloud Function checks every minute and sends due emails. Locally, an in-process scheduler does the same job while `uvicorn` is running.

### Firestore layout
```
users/{uid}                       settings (timezone, reminder prefs, calendarId, googleConnected)
users/{uid}/private/google        Google refresh token (server-only)
users/{uid}/goals/{goalId}        board cards
users/{uid}/days/{YYYY-MM-DD}     day plan: storylines + chapters + options + choices
reminders/{uid_date_chapter}      pending reminder emails (sendAt in UTC)
oauth_states/{state}              short-lived OAuth state + PKCE verifier
```
