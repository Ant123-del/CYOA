"""Hope: logs of negative and positive manifestations.

Writing a thought down is the acceptance step. Each negative one can carry a
"corrected manifestation" - words to repeat to yourself. The only AI here is the
suggestion endpoint, which offers 5 corrected versions based on the description.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import ai
from ..auth import CurrentUser, current_user
from ..firebase import user_ref
from ..models import (
    CorrectedSuggestIn,
    CorrectedSuggestions,
    Manifestation,
    ManifestationIn,
    ManifestationPatch,
)
from ..timeutil import now_iso

router = APIRouter(prefix="/api/manifestations", tags=["hope"])


def _col(uid: str):
    return user_ref(uid).collection("manifestations")


@router.get("", response_model=list[Manifestation])
def list_manifestations(user: CurrentUser = Depends(current_user)):
    items = [{**d.to_dict(), "id": d.id} for d in _col(user.uid).stream()]
    return sorted(items, key=lambda m: m.get("createdAt") or "", reverse=True)


@router.post("", response_model=Manifestation)
def create_manifestation(body: ManifestationIn, user: CurrentUser = Depends(current_user)):
    ts = now_iso()
    data = {**body.model_dump(), "createdAt": ts, "updatedAt": ts}
    if body.kind == "positive":
        data["corrected"] = ""
    ref = _col(user.uid).document()
    ref.set(data)
    return {**data, "id": ref.id}


@router.patch("/{item_id}", response_model=Manifestation)
def update_manifestation(item_id: str, patch: ManifestationPatch, user: CurrentUser = Depends(current_user)):
    ref = _col(user.uid).document(item_id)
    if not ref.get().exists:
        raise HTTPException(404, "Manifestation not found")
    ref.update({**patch.model_dump(exclude_unset=True), "updatedAt": now_iso()})
    return {**ref.get().to_dict(), "id": item_id}


@router.delete("/{item_id}")
def delete_manifestation(item_id: str, user: CurrentUser = Depends(current_user)):
    _col(user.uid).document(item_id).delete()
    return {"ok": True}


# ---------- the one bit of AI ----------

SUGGEST_SYSTEM = """You help someone reframe a negative thought they have written down in a
personal journal. They have already done the hard part - naming it and accepting it.
Your job is to offer CORRECTED MANIFESTATIONS: short statements they can repeat to
themselves when this thought shows up.

Write exactly 5, each a different angle (e.g. self-compassion, a grounded fact,
a next small step, a broader perspective, a statement of who they are becoming).
Rules:
- First person, present tense ("I am...", "I can...", "I choose...").
- One or two sentences, under 30 words. Easy to say out loud.
- Speak directly to the specifics of what they wrote - not generic poster quotes.
- Believable, not toxic positivity: acknowledge the feeling rather than deny it.
- No advice, no questions, no therapy-speak, no emojis, no quotation marks.
- If the description mentions self-harm or being unsafe, one of the 5 should affirm
  that reaching out to someone they trust or a crisis line is a strong choice."""


class _AISuggestions(BaseModel):
    suggestions: list[str]


@router.post("/suggest", response_model=CorrectedSuggestions)
def suggest_corrected(body: CorrectedSuggestIn, user: CurrentUser = Depends(current_user)):
    """5 corrected manifestations for a negative one, based on its description."""
    content = json.dumps({"title": body.title, "description": body.description}, indent=1)
    try:
        result: _AISuggestions = ai._call(_AISuggestions, content, max_tokens=2000, system=SUGGEST_SYSTEM)
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
    clean = [s.strip().strip('"“”').strip() for s in result.suggestions if s and s.strip()]
    if not clean:
        raise HTTPException(502, "The AI didn't come up with anything - try adding more to the description.")
    return {"suggestions": clean[:5]}
