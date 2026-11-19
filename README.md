# CYOA — Choose Your Own Adventure

A productivity app for days that don't go to plan. You keep a Trello-style board of goals. The day before (or a week before), CYOA's AI turns your priorities and Google Calendar into a **branching day**: a few parallel *storylines* and a series of *chapters*. Each chapter offers several options of the same priority:

- **Calendar events** get four paths: **Yes**, **Yes, and…**, **No**, **No, and…**
- **Other blocks** get one route per storyline (e.g. Main Quest, Steady Path, Pivot)

When a chapter is about to start, you get an email. You pick a path, and it goes on your Google Calendar.

**Sleep:** tap **🌙 Going to sleep** in the top bar before bed (you can cancel it if you don't end up sleeping), then **☀️ Woke up** in the morning, or enter the time you actually woke. CYOA tracks last night's sleep and a 7-night sleep debt against your goal (set in Settings), and suggests a wind-down time and a bedtime. The AI uses this when it plans: on short sleep you get lighter routes, the hard work goes earlier, and the day wraps up in time for bed.

**Hope:** the **Hope** tab keeps two logs: **complicated** and **positive** manifestations. Writing them down is the acceptance step. A positive one has a title and a description. A complicated one has a title, **the unbiased problem** (the stressor, put as fairly as you can), a list of **natural manifestations** (the thoughts that come along with it, added one at a time) and a **corrected manifestation**: the words you repeat to yourself. **✨ Suggest** offers 5 corrected manifestations (or none of them). Each one first accepts the problem as it is, then turns toward that problem; the natural manifestations set the tone, but the suggestions don't argue with or repeat them. That is the only AI in Hope, and manifestations are never shared with the day planner. When you open a task on Today, CYOA asks which manifestations are feeding into you (positive or complicated), lists that log's titles (plus **New +**), and shows the one you pick: the original problem and its corrected manifestation for a complicated one, the description for a positive one.

**Struggle mode** (on the Hope tab) is for the middle of a task. You check in the same way, see the original problem and your corrected manifestation, then either stay with the task or switch. Switching lists every option, across all storylines and all timelines, for the time range you're in (your current task's start to end), and picking one schedules it from now.

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

### 2. Google Calendar (calendar sharing, no OAuth client needed)
One-time: enable the **Google Calendar API** for the project:
https://console.cloud.google.com/apis/library/calendar-json.googleapis.com?project=cyoa-f15a9

Each user then links their own calendar in **Settings**:
1. In Google Calendar, go to Settings, pick their calendar, and under **Share with specific people** add `firebase-adminsdk-fbsvc@cyoa-f15a9.iam.gserviceaccount.com` with **Make changes to events**.
2. Paste the calendar's **Calendar ID** into CYOA. For a main calendar, the ID is the user's Gmail address.

Security rules, enforced in [backend/app/google_calendar.py](backend/app/google_calendar.py):
- The ID's format is validated.
- CYOA must actually have write access to the calendar.
- The user must prove ownership. Either the ID equals their verified sign-in email, or they paste a one-time code into the calendar's Description, which only someone who manages the calendar can edit.
- The linked ID is stored server-side only, and the settings API can't change it.
- CYOA only deletes events it created for that same user.
- Reminder emails only go to the user's own verified address.

### 3. AI key
Set `GEMINI_API_KEY` in `backend/.env.local`; you can get one at https://aistudio.google.com/apikey. The model is set by `GEMINI_MODEL` (default `gemini-2.5-flash`). If `GEMINI_API_KEY` is empty, the backend uses Claude instead (`ANTHROPIC_API_KEY`, model `claude-opus-5-5`). After changing a key, run `./backend/deploy.sh` again so production gets it.

### 4. Email via Gmail
Reminders are sent from cyoa740@gmail.com over Gmail SMTP. The host, user and from address are already filled in, in `backend/.env.local` and `backend/.env.cyoa-f15a9`.
1. Signed in as cyoa740@gmail.com, turn on **2-Step Verification** at https://myaccount.google.com/security.
2. Create an App Password at https://myaccount.google.com/apppasswords (name it "CYOA").
3. Put the 16 characters, without spaces, in `backend/.env.local` as `SMTP_PASSWORD=...`.
4. Run `./backend/deploy.sh`, then use **Settings → Send test email**.

Gmail allows roughly 500 recipients a day. For more, switch the `SMTP_*` values to a transactional provider; no code changes are needed.

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
   The script copies `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` and `SMTP_PASSWORD` from `backend/.env.local` into **Secret Manager**. It then deploys both functions and the Firestore rules. Non-secret production settings live in [backend/.env.cyoa-f15a9](backend/.env.cyoa-f15a9).
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
users/{uid}/private/calendar      linked Calendar ID (server-only, ownership-verified)
users/{uid}/goals/{goalId}        board cards
users/{uid}/days/{YYYY-MM-DD}     day plan: storylines + chapters + options + choices
reminders/{uid_date_chapter}      pending reminder emails (sendAt in UTC)
```
