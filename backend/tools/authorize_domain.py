"""Add a domain (e.g. your Vercel URL) to Firebase Auth's authorized domains so Google
sign-in works there. Uses backend/serviceAccountKey.json.

    venv/bin/python tools/authorize_domain.py cyoa.vercel.app
"""

import sys
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

KEY = Path(__file__).resolve().parent.parent / "serviceAccountKey.json"
URL = "https://identitytoolkit.googleapis.com/admin/v2/projects/cyoa-f15a9/config"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    domain = sys.argv[1].removeprefix("https://").removeprefix("http://").strip("/")
    creds = service_account.Credentials.from_service_account_file(
        str(KEY), scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    s = AuthorizedSession(creds)
    domains = s.get(URL).json().get("authorizedDomains", [])
    if domain in domains:
        print(f"{domain} is already authorized")
        return
    r = s.patch(URL, params={"updateMask": "authorizedDomains"}, json={"authorizedDomains": [*domains, domain]})
    r.raise_for_status()
    print(f"Authorized {domain}. Now: {r.json().get('authorizedDomains')}")


if __name__ == "__main__":
    main()
