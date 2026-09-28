from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
async def signup(body: SignupRequest, session: AsyncSession = Depends(get_db)):
    user = await auth_service.create_user(session, body.username, body.password)
    if user is None:
        raise AppError("USERNAME_TAKEN", "That username is already taken.", 409)
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_db)):
    user = await auth_service.get_user_by_username(session, body.username)
    # Same message for "no such user" and "wrong password", so the response
    # cannot be used to find out which usernames exist.
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Wrong username or password.", 401)
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user