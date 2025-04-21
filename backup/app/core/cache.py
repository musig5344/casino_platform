import redis
import json
import logging
from typing import Any, Optional, Union, Dict
from datetime import timedelta
import platform

from app.core.config import settings

logger = logging.getLogger(__name__)

class RedisClient:
    """
    Memurai/Redis 클라이언트 클래스로 캐싱 기능을 제공합니다.
    
    Windows 환경에서는 Memurai를 사용하고, 다른 환경에서는 Redis를 사용합니다.
    Memurai는 Redis와 완전히 호환되므로 동일한 API로 접근할 수 있습니다.
    
    Attributes:
        client: Memurai/Redis 연결 클라이언트
        default_ttl: 기본 TTL (초 단위)
        is_windows: Windows 환경 여부
    """
    def __init__(self):
        """Memurai/Redis 클라이언트 초기화 및 연결"""
        self.is_windows = platform.system() == "Windows"
        cache_type = "Memurai" if self.is_windows else "Redis"
        
        try:
            # Redis URL 또는 개별 연결 파라미터 사용
            if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
                self.client = redis.Redis.from_url(
                    settings.REDIS_URL, 
                    decode_responses=True,
                    socket_timeout=settings.CACHE_TIMEOUT
                )
                logger.info(f"{cache_type} 클라이언트가 URL로 초기화되었습니다: {settings.REDIS_URL}")
            else:
                self.client = redis.Redis(
                    host=settings.CACHE_HOST,
                    port=settings.CACHE_PORT,
                    db=settings.CACHE_DB,
                    password=settings.CACHE_PASSWORD,
                    socket_timeout=settings.CACHE_TIMEOUT,
                    ssl=settings.CACHE_SSL,
                    decode_responses=True
                )
                logger.info(f"{cache_type} 클라이언트가 초기화되었습니다: {settings.CACHE_HOST}:{settings.CACHE_PORT}")
            
            self.default_ttl = settings.CACHE_TTL
            
            # 연결 테스트
            self.client.ping()
            logger.info(f"{cache_type} 서버에 성공적으로 연결되었습니다.")
        except redis.ConnectionError as e:
            logger.error(f"{cache_type} 연결 오류: {e}")
            if self.is_windows:
                logger.error("Windows에서 Memurai가 실행 중인지 확인하세요. 서비스 또는 작업 관리자에서 확인할 수 있습니다.")
                logger.error("Memurai 서비스 상태 확인: 'sc query Memurai'")
                logger.error("Memurai 재시작: 'sc stop Memurai' 후 'sc start Memurai'")
            else:
                logger.error("Redis 서비스가 실행 중인지 확인하세요.")
            # 운영 환경에서는 실패해도 애플리케이션이 계속 실행될 수 있도록 함
            self.client = None
        except Exception as e:
            logger.error(f"{cache_type} 초기화 오류: {e}")
            self.client = None

    def is_connected(self) -> bool:
        """Memurai/Redis 서버 연결 상태 확인"""
        if not self.client:
            return False
        try:
            return self.client.ping()
        except:
            return False

    def get(self, key: str) -> Optional[str]:
        """
        Memurai/Redis에서 키에 해당하는 값을 반환합니다.
        
        Args:
            key: 조회할 키
        
        Returns:
            키에 해당하는 값 또는 None (키가 없는 경우)
        """
        cache_type = "Memurai" if self.is_windows else "Redis"
        if not self.is_connected():
            logger.warning(f"{cache_type} 연결 없음: 캐시 조회 건너뜀")
            return None
        
        try:
            return self.client.get(key)
        except Exception as e:
            logger.error(f"{cache_type} GET 오류 (키: {key}): {e}")
            return None

    def get_json(self, key: str) -> Optional[dict]:
        """
        Memurai/Redis에서 키에 해당하는 JSON 값을 파싱하여 반환합니다.
        
        Args:
            key: 조회할 키
        
        Returns:
            파싱된 JSON 딕셔너리 또는 None (키가 없거나 파싱 오류)
        """
        value = self.get(key)
        if not value:
            return None
        
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 오류 (키: {key}): {e}")
            return None

    def set(self, key: str, value: Union[str, dict], ttl: Optional[int] = None) -> bool:
        """
        Memurai/Redis에 값을 저장합니다.
        
        Args:
            key: 저장할 키
            value: 저장할 값 (문자열 또는 딕셔너리)
            ttl: TTL (초) - 미지정 시 기본값 사용
            
        Returns:
            성공 여부 (True/False)
        """
        cache_type = "Memurai" if self.is_windows else "Redis"
        if not self.is_connected():
            logger.warning(f"{cache_type} 연결 없음: 캐시 저장 건너뜀")
            return False
        
        ttl = ttl or self.default_ttl
        
        try:
            # 딕셔너리인 경우 JSON으로 변환
            if isinstance(value, dict):
                value = json.dumps(value)
                
            return bool(self.client.setex(key, ttl, value))
        except Exception as e:
            logger.error(f"{cache_type} SET 오류 (키: {key}): {e}")
            return False

    def delete(self, key: str) -> bool:
        """
        Memurai/Redis에서 키를 삭제합니다.
        
        Args:
            key: 삭제할 키
            
        Returns:
            성공 여부 (True/False)
        """
        cache_type = "Memurai" if self.is_windows else "Redis"
        if not self.is_connected():
            logger.warning(f"{cache_type} 연결 없음: 캐시 삭제 건너뜀")
            return False
        
        try:
            return bool(self.client.delete(key))
        except Exception as e:
            logger.error(f"{cache_type} DELETE 오류 (키: {key}): {e}")
            return False

    def update_wallet_balance(self, player_id: str, balance: float, currency: str) -> bool:
        """
        지갑 잔액 캐시를 업데이트하는 헬퍼 메서드입니다.
        
        Args:
            player_id: 플레이어 ID
            balance: 새 잔액
            currency: 통화
            
        Returns:
            성공 여부 (True/False)
        """
        cache_key = f"wallet:{player_id}"
        cache_data = {"balance": float(balance), "currency": currency}
        return self.set(cache_key, cache_data)

    def get_client_info(self) -> dict:
        """
        Memurai/Redis 클라이언트 정보를 반환합니다.
        주로 디버깅 및 상태 확인용입니다.
        
        Returns:
            클라이언트 정보 딕셔너리
        """
        if not self.is_connected():
            return {"status": "disconnected"}
        
        try:
            info = self.client.info()
            return {
                "status": "connected",
                "type": "Memurai" if self.is_windows else "Redis",
                "version": info.get("redis_version"),
                "os": platform.system(),
                "clients_connected": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human")
            }
        except Exception as e:
            logger.error(f"클라이언트 정보 조회 오류: {e}")
            return {"status": "error", "message": str(e)}

# 전역 Redis 클라이언트 객체 생성
redis_client = RedisClient() 