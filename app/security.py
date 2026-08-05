from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status

try:
    from database import get_session_user
except ImportError:
    from .database import get_session_user


SESSION_COOKIE_NAME = "specguard_session"


def get_current_user(
    specguard_session: Optional[str] = Cookie(
        default=None, alias=SESSION_COOKIE_NAME
    ),
):
    user = get_session_user(specguard_session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return user


def ensure_role(user, required_role):
    if user["role"] != required_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{required_role} access required.",
        )
    return user


def require_user(current_user=Depends(get_current_user)):
    return ensure_role(current_user, "User")


def require_expert(current_user=Depends(get_current_user)):
    return ensure_role(current_user, "Expert")


def require_admin(current_user=Depends(get_current_user)):
    return ensure_role(current_user, "Admin")
