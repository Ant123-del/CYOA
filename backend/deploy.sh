#!/usr/bin/env bash
# Deploy the CYOA backend to Cloud Functions for Firebase (+ Firestore rules).
#
#   Prereqs (once):  firebase login:add cyoa740@gmail.com   (and: firebase login:use cyoa740@gmail.com)
#                    Project on the Blaze plan (Firebase console -> Upgrade)
#   Run:             ./backend/deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
PROJECT=cyoa-f15a9

[ -f .env.local ] || { echo "backend/.env.local not found (copy .env.example and fill it in)"; exit 1; }
[ -x venv/bin/python ] || { python3 -m venv venv && venv/bin/pip install -q -r requirements.txt; }

# Reuse the local Google OAuth client ID in production if the prod file leaves it blank.
venv/bin/python - <<'EOF'
from dotenv import dotenv_values
import re
local = dotenv_values(".env.local")
p = ".env.cyoa-f15a9"
text = open(p).read()
cid = (local.get("GOOGLE_CLIENT_ID") or "").strip()
if cid and re.search(r"^GOOGLE_CLIENT_ID=\s*$", text, re.M):
    text = re.sub(r"^GOOGLE_CLIENT_ID=\s*$", f"GOOGLE_CLIENT_ID={cid}", text, flags=re.M)
    open(p, "w").write(text)
    print("Filled GOOGLE_CLIENT_ID in .env.cyoa-f15a9 from .env.local")
EOF

# Push secrets from .env.local into Google Secret Manager.
for KEY in ANTHROPIC_API_KEY GOOGLE_CLIENT_SECRET SMTP_PASSWORD; do
  VALUE=$(venv/bin/python -c "from dotenv import dotenv_values; print(dotenv_values('.env.local').get('$KEY') or 'unset', end='')")
  [ "$VALUE" = "unset" ] && echo "⚠️  $KEY is empty in .env.local (storing placeholder)"
  printf '%s' "$VALUE" | firebase functions:secrets:set "$KEY" --data-file - --project "$PROJECT" --force >/dev/null
  echo "✓ secret $KEY"
done

cd ..
firebase deploy --only functions,firestore:rules --project "$PROJECT"

echo
echo "API:  https://us-central1-$PROJECT.cloudfunctions.net/api/api/health"
