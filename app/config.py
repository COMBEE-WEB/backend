import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_key: str
    cors_origins: tuple[str, ...] = ('http://localhost:3000',)
    password_reset_url: str = 'http://localhost:3000/auth/reset-password'
    openai_api_key: str = ''
    openai_model: str = 'gpt-4.1-mini'

    @classmethod
    def from_env(cls):
        url = os.getenv('SUPABASE_URL', '').strip().rstrip('/')
        key = (os.getenv('SUPABASE_PUBLISHABLE_KEY') or os.getenv('SUPABASE_ANON_KEY', '')).strip()
        if url and (urlsplit(url).scheme != 'https' or not urlsplit(url).hostname):
            raise ValueError('SUPABASE_URL must be an HTTPS URL')
        return cls(url, key, tuple(
            origin.strip() for origin in os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',')
            if origin.strip()
        ), os.getenv('PASSWORD_RESET_URL', 'http://localhost:3000/auth/reset-password').strip(),
           os.getenv('OPENAI_API_KEY', '').strip(), os.getenv('OPENAI_MODEL', 'gpt-4.1-mini').strip())
