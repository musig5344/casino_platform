import os
from typing import Optional
from pydantic import BaseSettings
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # 디버그 모드
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # 캐싱 설정 (Redis/Memurai)
    CACHE_HOST: str = os.getenv("CACHE_HOST", "localhost")
    CACHE_PORT: int = int(os.getenv("CACHE_PORT", "6379"))
    CACHE_DB: int = int(os.getenv("CACHE_DB", "0"))
    CACHE_PASSWORD: Optional[str] = os.getenv("CACHE_PASSWORD")
    CACHE_TIMEOUT: int = int(os.getenv("CACHE_TIMEOUT", "5"))
    CACHE_SSL: bool = os.getenv("CACHE_SSL", "False").lower() == "true"
    CACHE_TTL: int = int(os.getenv("REDIS_TTL", "60"))  # 캐시 TTL (초 단위)
    
    # Redis URL
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings() 