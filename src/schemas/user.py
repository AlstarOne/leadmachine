"""Pydantic schemas for User model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Base schema for User."""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: str | None = Field(None, max_length=100)


class UserCreate(UserBase):
    """Schema for creating a User."""

    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    """Schema for updating a User."""

    username: str | None = Field(None, min_length=3, max_length=50)
    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=100)
    password: str | None = Field(None, min_length=8)
    is_active: bool | None = None


class UserRead(UserBase):
    """Schema for reading a User."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class UserList(BaseModel):
    """Schema for listing Users."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime


# Authentication schemas
class Token(BaseModel):
    """Schema for JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Schema for JWT token payload."""

    sub: int  # User ID
    exp: datetime
    type: str  # "access" or "refresh"


class LoginRequest(BaseModel):
    """Schema for login request."""

    username: str
    password: str


class PasswordChange(BaseModel):
    """Schema for changing password."""

    current_password: str
    new_password: str = Field(..., min_length=8)
