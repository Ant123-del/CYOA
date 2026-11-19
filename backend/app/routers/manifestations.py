"""Hope: logs of complicated and positive manifestations.

Writing a thought down is the acceptance step. A complicated one is split into the
unbiased problem (the stressor itself) and the natural manifestations that come with
it, and can carry a "corrected manifestation" - words to repeat to yourself. The only
AI here is the suggestion endpoint, which offers 5 corrected versions.
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


def _normalize(data: dict, item_id: str) -> dict:
    """Read older entries: "negative" became "complicated", and its single description
    is carried over as the problem."""
    m = {**data, "id": item_id}
    if m.get("kind") == "negative":
        m["kind"] = "complicated"
    if m.get("kind") == "complicated" and not m.get("problem") and m.get("description"):
        m["problem"] = m["description"]
        m["description"] = ""
    return m


@router.get("", response_model=list[Manifestation])
def list_manifestations(user: CurrentUser = Depends(current_user)):
    items = [_normalize(d.to_dict(), d.id) for d in _col(user.uid).stream()]
    return sorted(items, key=lambda m: m.get("createdAt") or "", reverse=True)


@router.post("", response_model=Manifestation)
def create_manifestation(body: ManifestationIn, user: CurrentUser = Depends(current_user)):
    ts = now_iso()
    data = {**body.model_dump(), "createdAt": ts, "updatedAt": ts}
    if body.kind == "positive":
        data.update(problem="", naturalManifestations=[], corrected="")
    else:
        data["description"] = ""
    ref = _col(user.uid).document()
    ref.set(data)
    return {**data, "id": ref.id}


@router.patch("/{item_id}", response_model=Manifestation)
def update_manifestation(item_id: str, patch: ManifestationPatch, user: CurrentUser = Depends(current_user)):
    ref = _col(user.uid).document(item_id)
    if not ref.get().exists:
        raise HTTPException(404, "Manifestation not found")
    changes = patch.model_dump(exclude_unset=True)
    stored = ref.get().to_dict() or {}
    if stored.get("kind") in ("negative", "complicated"):
        changes["kind"] = "complicated"  # migrate older entries on save
        if "problem" in changes:
            changes["description"] = ""  # the old description now lives in problem
    ref.update({**changes, "updatedAt": now_iso()})
    return _normalize(ref.get().to_dict(), item_id)


@router.delete("/{item_id}")
def delete_manifestation(item_id: str, user: CurrentUser = Depends(current_user)):
    _col(user.uid).document(item_id).delete()
    return {"ok": True}


# ---------- the one bit of AI ----------

SUGGEST_SYSTEM = """You help someone answer a complicated thought they have written down in a
personal journal. CYOA follows a simple blueprint: ACCEPT, then MANIFEST.

They give you:
- problem: the stressor itself, written as unbiased as they could. This is the ground truth.
- natural_manifestations: the thoughts that showed up on their own around it. These tell
  you where they are emotionally right now. They are NOT facts about the problem.

Write exactly 5 CORRECTED MANIFESTATIONS: short statements they can repeat to themselves.
Each one follows the blueprint:
1. ACCEPT - meet them where they are: plainly acknowledge the problem as it is (and,
   if it fits, that it makes sense to feel this way). No denying, no sugar-coating.
2. MANIFEST - turn toward the ORIGINAL PROBLEM: what they can do, choose or hold about
   that actual situation.

Keep the focus on the problem. Do not argue with, repeat, or build on the natural
manifestations ("I am not a failure" still centres the word failure); let them inform
your tone and how gently you start, then steer back to the real situation.

Make the 5 different angles (e.g. a next small step, what is in their control, a
grounded fact about the situation, self-compassion, who they are becoming through it).
Rules:
- First person, present tense ("I am...", "I can...", "I choose...").
- One or two sentences, under 35 words. Easy to say out loud.
- Specific to what they wrote - never generic poster quotes.
- No advice, no questions, no therapy-speak, no emojis, no quotation marks.
- If anything mentions self-harm or being unsafe, one of the 5 should affirm that
  reaching out to someone they trust or a crisis line is a strong choice."""


class _AISuggestions(BaseModel):
    suggestions: list[str]


@router.post("/suggest", response_model=CorrectedSuggestions)
def suggest_corrected(body: CorrectedSuggestIn, user: CurrentUser = Depends(current_user)):
    """5 corrected manifestations for a complicated one: accept the problem, then manifest toward it."""
    content = json.dumps(
        {"title": body.title, "problem": body.problem, "natural_manifestations": body.naturalManifestations},
        indent=1,
    )
    try:
        result: _AISuggestions = ai._call(_AISuggestions, content, max_tokens=2000, system=SUGGEST_SYSTEM)
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
    clean = [s.strip().strip('"“”').strip() for s in result.suggestions if s and s.strip()]
    if not clean:
        raise HTTPException(502, "The AI didn't come up with anything - try adding more to the problem.")
    return {"suggestions": clean[:5]}
