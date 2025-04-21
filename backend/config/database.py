from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    # .env 파일 로드를 활성화하고 환경 변수 이름의 대소문자를 구분하지 않도록 설정
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', case_sensitive=False)

    # 환경 변수에서 로드할 필드 정의
    DATABASE_URL: str = "sqlite:///./test.db"  # SQLite 기본값 추가
    SECRET_KEY: str = "casino_platform_secret_key_for_testing_only"  # 테스트용 기본값 추가
    # JWT 알고리즘 및 만료 시간도 설정으로 관리하는 것이 좋습니다.
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # 추가된 환경 변수 필드
    CASINO_KEY: str = "test_casino_key"  # 테스트용 기본값 추가
    API_TOKEN: str = "test_api_token"  # 테스트용 기본값 추가
    # Redis 설정 추가
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_TTL: int = 60
    
    # 보안 강화 설정 추가
    ENVIRONMENT: str = "development"  # development, production
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"  # 허용된 호스트 목록 (쉼표로 구분)
    IP_WHITELIST: str = ""  # 화이트리스트 IP 목록 (쉼표로 구분, 비어있으면 모든 IP 허용)
    ENCRYPTION_KEY: str = "vY8iWqUXbWVgBOSvSrUjWXYMNp4U4iCR"  # 테스트용 암호화 키 추가
    
    # 게임 제공업체 API 통합 설정 추가
    GAMEPROVIDER_API_KEY: str = ""
    GAMEPROVIDER_API_SECRET: str = ""
    GAMEPROVIDER_LAUNCH_URL: str = "https://uat1-games.provider.com/game/launch"
    GAMEPROVIDER_API_URL: str = "https://uat1-api.provider.com/api"
    GAMEPROVIDER_BALANCE_CALLBACK_URL: str = ""
    GAMEPROVIDER_DEBIT_CALLBACK_URL: str = ""
    GAMEPROVIDER_CREDIT_CALLBACK_URL: str = ""
    GAMEPROVIDER_CANCEL_CALLBACK_URL: str = ""

# @lru_cache 데코레이터를 사용하여 설정 객체를 캐싱 (매번 파일을 읽지 않도록)
@lru_cache()
def get_settings() -> Settings:
    return Settings()

# 앱 전체에서 사용할 설정 인스턴스
settings = get_settings() 