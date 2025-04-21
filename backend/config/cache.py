from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from dotenv import load_dotenv
import os

load_dotenv()

class CacheSettings(BaseSettings):
    """
    Memurai 캐시 설정을 관리하는 클래스
    
    Memurai는 Windows 환경에서 Redis와 호환되는 인메모리 데이터 스토어입니다.
    Redis와 동일한 프로토콜, 명령어, 구성을 사용하여 연결할 수 있습니다.
    
    Attributes:
        redis_url: Memurai 서버 연결 URL (Redis와 호환)
        redis_ttl: 기본 캐시 TTL (초 단위)
    """
    # Windows 환경에서는 "redis://localhost:6379/0" 또는 "redis://127.0.0.1:6379/0" 사용
    redis_url: str = Field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        description="Memurai 서버 연결 URL (Redis 프로토콜 호환)"
    )
    redis_ttl: int = Field(
        default_factory=lambda: int(os.getenv("REDIS_TTL", "60")),
        description="기본 캐시 TTL (초 단위)"
    )

    # Pydantic v2에서는 Config 클래스 대신 model_config 사용
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        case_sensitive=False,
        extra="ignore"  # 추가 필드 무시 설정
    )

# 전역 설정 객체 생성
settings = CacheSettings() 