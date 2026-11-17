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

# Push secrets from .env.local (or from your shell env, which wins) into Google Secret Manager.
for KEY in GEMINI_API_KEY ANTHROPIC_API_KEY SMTP_PASSWORD; do
  VALUE=$(venv/bin/python -c "from dotenv import dotenv_values; import os; print(os.environ.get('$KEY') or dotenv_values('.env.local').get('$KEY') or 'unset', end='')")
  [ "$VALUE" = "unset" ] && echo "⚠️  $KEY is empty in .env.local (storing placeholder)"
  printf '%s' "$VALUE" | firebase functions:secrets:set "$KEY" --data-file - --project "$PROJECT" --force >/dev/null
  echo "✓ secret $KEY"
done

cd ..
firebase deploy --only functions,firestore:rules --project "$PROJECT"

echo
echo "API:  https://us-central1-$PROJECT.cloudfunctions.net/api/api/health"
