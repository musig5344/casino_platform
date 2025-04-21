import os
from typing import List, Optional
from pydantic import BaseSettings, validator, Field

class Settings(BaseSettings):
    """
    애플리케이션 설정
    
    환경 변수 또는 .env 파일을 통해 설정 가능
    """
    # 기본 정보
    APP_NAME: str = "카지노 플랫폼 API"
    API_VERSION: str = "v1"
    DEBUG: bool = Field(False, env="DEBUG")
    
    # 데이터베이스 설정
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    
    # Redis 설정
    REDIS_URL: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    REDIS_PASSWORD: Optional[str] = Field(None, env="REDIS_PASSWORD")
    
    # 보안 설정
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: List[str] = ["*"]
    
    # 캐싱 설정
    CACHE_TTL: int = 3600  # 기본 캐시 유효 시간 (초)
    BALANCE_CACHE_TTL: int = 60  # 잔액 캐시 유효 시간 (초)
    
    # 국제화 및 현지화 설정
    DEFAULT_LANGUAGE: str = "ko"
    DEFAULT_TIMEZONE: str = "Asia/Seoul"
    DEFAULT_CURRENCY: str = "KRW"
    TRANSLATIONS_DIR: str = "translations"
    
    # 비율 제한 설정
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100  # 시간당 최대 요청 수
    RATE_LIMIT_SECONDS: int = 60  # 시간 윈도우 (초)
    RATE_LIMIT_WHITELIST_IPS: List[str] = ["127.0.0.1"]
    BLOCK_ON_RATE_LIMIT_EXCEED: bool = False
    
    # 감사 및 로깅 설정
    LOG_LEVEL: str = "INFO"
    AUDIT_LOG_ENABLED: bool = True
    
    # 외부 API 설정
    CURRENCY_CONVERSION_API_URL: Optional[str] = Field(None, env="CURRENCY_API_URL")
    CURRENCY_CONVERSION_API_KEY: Optional[str] = Field(None, env="CURRENCY_API_KEY")
    
    # 알림 설정
    EMAIL_ENABLED: bool = False
    EMAIL_HOST: Optional[str] = Field(None, env="EMAIL_HOST")
    EMAIL_PORT: Optional[int] = Field(None, env="EMAIL_PORT")
    EMAIL_USERNAME: Optional[str] = Field(None, env="EMAIL_USERNAME")
    EMAIL_PASSWORD: Optional[str] = Field(None, env="EMAIL_PASSWORD")
    EMAIL_FROM: Optional[str] = Field(None, env="EMAIL_FROM")
    
    SMS_ENABLED: bool = False
    SMS_PROVIDER_URL: Optional[str] = Field(None, env="SMS_PROVIDER_URL")
    SMS_PROVIDER_KEY: Optional[str] = Field(None, env="SMS_PROVIDER_KEY")
    
    # 지역별 규제 설정
    RESTRICTED_COUNTRIES: List[str] = Field([], env="RESTRICTED_COUNTRIES")
    AGE_VERIFICATION_REQUIRED: bool = True
    MIN_GAMBLING_AGE: int = 19  # 한국 기준
    
    # 트랜잭션 제한 설정
    MAX_DEPOSIT_AMOUNT: float = 10000000.0  # 1000만원
    MAX_WITHDRAWAL_AMOUNT: float = 5000000.0  # 500만원
    MIN_DEPOSIT_AMOUNT: float = 1000.0  # 1000원
    MIN_WITHDRAWAL_AMOUNT: float = 10000.0  # 10000원
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @validator("DATABASE_URL")
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v
    
    @validator("SECRET_KEY")
    def validate_secret_key(cls, v: Optional[str]) -> str:
        if not v or len(v) < 32:
            import secrets
            generated = secrets.token_hex(32)
            if not v:
                return generated
            else:
                print("WARNING: Secret key is too short. Consider using a longer key.")
        return v
    
    @validator("CORS_ORIGINS")
    def validate_cors_origins(cls, v: List[str]) -> List[str]:
        if "*" in v:
            print("WARNING: CORS is configured to allow requests from any origin.")
        return v

# 설정 인스턴스 생성
settings = Settings() 