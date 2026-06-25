import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.db_models import User

MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize_mobile(mobile: str) -> str:
        digits = re.sub(r"\D", "", mobile)
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        if not MOBILE_RE.match(digits):
            raise ValueError("Mobile must be a valid 10-digit Indian number")
        return digits

    @staticmethod
    def _user_out(user: User) -> dict:
        return {
            "id": user.id,
            "name": user.name,
            "mobile": user.mobile,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    async def register(self, name: str, mobile: str, email: str, password: str) -> dict:
        mobile = self._normalize_mobile(mobile)
        email = email.strip().lower()
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters")

        existing = await self.db.execute(
            select(User).where(or_(User.email == email, User.mobile == mobile))
        )
        if existing.scalar_one_or_none():
            raise ValueError("Email or mobile already registered")

        user = User(
            name=name.strip(),
            mobile=mobile,
            email=email,
            hashed_password=hash_password(password),
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        token = create_access_token(user.id)
        return {"access_token": token, "token_type": "bearer", "user": self._user_out(user)}

    async def login(self, identifier: str, password: str) -> dict:
        identifier = identifier.strip().lower()
        mobile = re.sub(r"\D", "", identifier)
        if mobile.startswith("91") and len(mobile) == 12:
            mobile = mobile[2:]

        clauses = [User.email == identifier]
        if len(mobile) == 10:
            clauses.append(User.mobile == mobile)

        result = await self.db.execute(select(User).where(or_(*clauses)))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.hashed_password):
            raise ValueError("Invalid email/mobile or password")
        if not user.is_active:
            raise ValueError("Account is disabled")

        token = create_access_token(user.id)
        return {"access_token": token, "token_type": "bearer", "user": self._user_out(user)}

    async def get_user(self, user_id: int) -> dict | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        return self._user_out(user) if user else None

    async def forgot_password(self, email: str) -> dict:
        email = email.strip().lower()
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            return {"message": "If that email is registered, password reset instructions have been sent."}

        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=settings.password_reset_expire_hours)
        await self.db.commit()

        response: dict = {
            "message": "If that email is registered, password reset instructions have been sent.",
        }
        if settings.debug:
            response["reset_token"] = token
            response["reset_url"] = f"/reset-password?token={token}"
        return response

    async def reset_password(self, token: str, new_password: str) -> dict:
        if len(new_password) < 6:
            raise ValueError("Password must be at least 6 characters")

        result = await self.db.execute(select(User).where(User.reset_token == token))
        user = result.scalar_one_or_none()
        if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
            raise ValueError("Invalid or expired reset token")

        user.hashed_password = hash_password(new_password)
        user.reset_token = None
        user.reset_token_expires = None
        await self.db.commit()

        access_token = create_access_token(user.id)
        return {
            "message": "Password reset successful",
            "access_token": access_token,
            "token_type": "bearer",
            "user": self._user_out(user),
        }
