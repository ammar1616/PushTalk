import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.models import Membership, User
from app.db.session import get_db
from app.services import channel_service

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


async def require_membership(
    channel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Membership:
    """Every channel-scoped route needs this: prove the caller is a member."""
    membership = await channel_service.get_membership(
        session, current_user.id, channel_id
    )
    if membership is None:
        raise AppError("NOT_A_MEMBER", "Join the channel first.", 403)
    return membership