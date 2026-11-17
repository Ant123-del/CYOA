from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..firebase import user_ref
from ..models import Goal, GoalIn, GoalPatch
from ..timeutil import now_iso

router = APIRouter(prefix="/api/goals", tags=["goals"])


def _col(uid: str):
    return user_ref(uid).collection("goals")


def list_goal_dicts(uid: str) -> list[dict]:
    return [{**d.to_dict(), "id": d.id} for d in _col(uid).stream()]


@router.get("", response_model=list[Goal])
def list_goals(user: CurrentUser = Depends(current_user)):
    goals = list_goal_dicts(user.uid)
    return sorted(goals, key=lambda g: (g.get("order", 0), g.get("createdAt") or ""))


@router.post("", response_model=Goal)
def create_goal(goal: GoalIn, user: CurrentUser = Depends(current_user)):
    ts = now_iso()
    data = {**goal.model_dump(), "createdAt": ts, "updatedAt": ts}
    ref = _col(user.uid).document()
    ref.set(data)
    return {**data, "id": ref.id}


@router.patch("/{goal_id}", response_model=Goal)
def update_goal(goal_id: str, patch: GoalPatch, user: CurrentUser = Depends(current_user)):
    ref = _col(user.uid).document(goal_id)
    if not ref.get().exists:
        raise HTTPException(404, "Goal not found")
    # exclude_unset so the client can explicitly clear fields (e.g. dueDate: null)
    ref.update({**patch.model_dump(exclude_unset=True), "updatedAt": now_iso()})
    return {**ref.get().to_dict(), "id": goal_id}


@router.delete("/{goal_id}")
def delete_goal(goal_id: str, user: CurrentUser = Depends(current_user)):
    _col(user.uid).document(goal_id).delete()
    return {"ok": True}
