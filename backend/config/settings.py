from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from typing import Optional, Dict, Any, List

class Settings(BaseSettings):
    # 일반 설정
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "developmentsecretkey"
    
    # 데이터베이스 설정
    DATABASE_URL: str = "sqlite:///./casino.db"
    
    # API 설정
    API_TOKEN: str = "qwqw6171"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALGORITHM: str = "HS256"
    
    # 보안 설정
    ALLOWED_HOSTS: str = "*"
    IP_WHITELIST: str = ""
    ENCRYPTION_KEY: str = "aGJFeO32ljIPDO9UdmcTIRZ9Y6VPr1uaVGGDuKsX3CU="
    
    # 게임 제공자 설정
    GAMEPROVIDER_API_KEY: str = "demo_api_key"
    GAMEPROVIDER_API_SECRET: str = "demo_api_secret"
    GAMEPROVIDER_LAUNCH_URL: str = "https://demo-games.example.com/launch"
    GAMEPROVIDER_API_URL: str = "https://uat1-api.provider.com/api"
    GAMEPROVIDER_BALANCE_CALLBACK_URL: str = "https://your-casino-api.com/api/external/balance"
    GAMEPROVIDER_DEBIT_CALLBACK_URL: str = "https://your-casino-api.com/api/external/debit"
    GAMEPROVIDER_CREDIT_CALLBACK_URL: str = "https://your-casino-api.com/api/external/credit"
    GAMEPROVIDER_CANCEL_CALLBACK_URL: str = "https://your-casino-api.com/api/external/cancel"
    
    # 외부 게임 관련 설정
    EXTERNAL_API_KEY: str = "external_api_key"
    EXTERNAL_GAME_URL: str = "https://external-games.example.com"
    
    # 캐싱 설정
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_TTL: int = 60
    
    # 카지노 설정
    CASINO_KEY: str = "MY_CASINO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow"
    )

@lru_cache()
def get_settings() -> Settings:
    """
    애플리케이션 설정을 가져옵니다. lru_cache는 환경 변수가 바뀌지 않는 한
    설정을 한 번만 로드하도록 보장합니다.
    """
    return Settings()

# 환경변수 기본값 설정
settings = get_settings() 