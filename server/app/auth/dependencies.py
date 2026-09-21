import logging
import os
import uuid
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database.crud.subscription_crud import subscription_crud
from app.database.crud.user_crud import user as user_crud
from app.database.database import get_db
from app.database.models import User as UserModel
from app.schemas.user import CurrentUser

logger = logging.getLogger(__name__)

# Session cookie name
SESSION_COOKIE_NAME = "session_token"

# Setup header auth
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


DEV_USER_EMAIL = os.getenv("DEV_USER_EMAIL", "dev@localhost.com")


def _get_dev_user(db: Session) -> Optional[CurrentUser]:
    """Return a local dev user when DEBUG=True and no real auth is provided."""
    if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
        return None

    db_user = user_crud.get_by_email(db, email=DEV_USER_EMAIL)
    if not db_user:
        db_user = UserModel(
            email=DEV_USER_EMAIL,
            name="Local Dev",
            auth_provider="email",
            provider_user_id=DEV_USER_EMAIL,
            is_active=True,
            is_admin=True,
            is_email_verified=True,
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        logger.info(f"Created local dev user: {DEV_USER_EMAIL}")

    return CurrentUser(
        id=uuid.UUID(str(db_user.id)),
        email=str(db_user.email),
        name=db_user.name or "Local Dev",
        is_admin=bool(db_user.is_admin),
        picture=db_user.picture,
        is_email_verified=bool(db_user.is_email_verified),
        is_active=True,
        is_blocked=False,
    )


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str = Depends(api_key_header),
) -> Optional[CurrentUser]:
    """
    Get the current user from session token in cookie or Authorization header.

    When DEBUG=True and no valid session is found, returns a local dev user.
    This allows running the app without Google OAuth setup for local development.

    This is a FastAPI dependency that can be used in route functions.
    """
    token = None

    # First try from Authorization header
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")

    # Then try from cookie
    if not token:
        token = request.cookies.get(SESSION_COOKIE_NAME)

    if token:
        # Get session from database
        db_session = user_crud.get_by_token(db=db, token=token)
        if db_session:
            # Get user from session
            db_user = user_crud.get(db=db, id=db_session.user_id)
            if db_user and db_user.is_active and db_user.id:
                is_user_active = subscription_crud.is_user_active(db, db_user)
                return CurrentUser(
                    id=uuid.UUID(str(db_user.id)),
                    email=str(db_user.email),
                    name=db_user.name,
                    is_admin=bool(db_user.is_admin),
                    picture=db_user.picture,
                    is_email_verified=bool(db_user.is_email_verified),
                    is_active=is_user_active,
                    is_blocked=bool(db_user.is_blocked),
                )

    # Dev mode fallback: auto-login as local user
    return _get_dev_user(db)


async def get_required_user(
    current_user: Annotated[Optional[CurrentUser], Depends(get_current_user)],
) -> CurrentUser:
    """
    Require a logged-in user for protected routes.
    Raises 401 Unauthorized if no user is found.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_admin_user(
    current_user: Annotated[CurrentUser, Depends(get_required_user)],
) -> CurrentUser:
    """
    Require an admin user for admin-only routes.
    Raises 403 Forbidden if user is not admin.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user
