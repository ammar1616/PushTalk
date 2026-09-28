import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError("UNAUTHORIZED", "Sign in first.", 401)

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise AppError("UNAUTHORIZED", "Your session has expired. Sign in again.", 401)

    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        raise AppError("UNAUTHORIZED", "That account no longer exists.", 401)

    # The logging middleware reads this to add user_id to the request line.
    request.state.user_id = str(user.id)
    return user