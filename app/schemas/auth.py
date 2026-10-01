import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('올바른 이메일을 입력해주세요.')
        return value


class LoginRequest(EmailRequest):
    password: SecretStr = Field(min_length=1, max_length=128)


class RecoveryCodeRequest(EmailRequest):
    verificationCode: SecretStr = Field(min_length=6, max_length=8)

    @field_validator('verificationCode')
    @classmethod
    def validate_code(cls, value):
        if not re.fullmatch(r'[0-9]{6,8}', value.get_secret_value()):
            raise ValueError('인증번호 6~8자리를 입력해주세요.')
        return value


class NewPasswordRequest(BaseModel):
    newPassword: SecretStr = Field(min_length=8, max_length=128)


class ChangePasswordRequest(NewPasswordRequest):
    currentPassword: SecretStr = Field(min_length=1, max_length=128)


class SignupRequest(LoginRequest):
    model_config = ConfigDict(populate_by_name=True)
    password: SecretStr = Field(min_length=8, max_length=128)
    login_id: str = Field(alias='userId', min_length=3, max_length=30, pattern=r'^[A-Za-z0-9_]+$')
    full_name: str = Field(alias='name', min_length=1, max_length=50)
    nickname: str | None = Field(default=None, min_length=1, max_length=30)
    phone: str | None = Field(default=None, max_length=20, pattern=r'^\+?[0-9 ()-]{7,20}$')
    birth_date: date | None = Field(default=None, alias='birthDate')

    @field_validator('full_name', 'nickname')
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError('공백만 입력할 수 없습니다.')
        return value.strip() if value else value

    @field_validator('birth_date', mode='before')
    @classmethod
    def normalize_date(cls, value):
        if isinstance(value, str) and re.fullmatch(r'\d{8}', value):
            return f'{value[:4]}-{value[4:6]}-{value[6:]}'
        return value

    @field_validator('birth_date')
    @classmethod
    def not_future(cls, value):
        if value and value > date.today():
            raise ValueError('생년월일은 미래일 수 없습니다.')
        return value


class RefreshRequest(BaseModel):
    refresh_token: SecretStr = Field(min_length=1, max_length=4096)
