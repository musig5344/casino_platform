import redis
import json
from typing import Any, Dict, Optional, Union, List, Tuple
from backend.config.cache import settings
import logging
import platform
import os
import hashlib
from datetime import datetime, timedelta
import time
import threading
import functools

logger = logging.getLogger(__name__)

# 캐시 TTL(Time To Live) 상수 정의 - 리소스 유형별 최적 TTL
CACHE_TTL = {
    'player': 600,        # 10분 (사용자 정보)
    'wallet': 60,         # 1분 (지갑 잔액, 자주 변경됨)
    'game_history': 300,  # 5분 (게임 기록)
    'game_list': 1800,    # 30분 (게임 목록)
    'game_state': 30,     # 30초 (실시간 게임 상태)
    'session': 3600,      # 1시간 (세션 정보)
    'default': 300        # 기본 5분
}

class CacheTier:
    """캐시 계층을 정의합니다."""
    L1 = 'l1'  # 메모리 캐시 (가장 빠름, 짧은 TTL) 
    L2 = 'l2'  # Redis 캐시 (중간, 보통 TTL)
    L3 = 'l3'  # 영구 저장소 (데이터베이스, 가장 느림)

class MemoryCache:
    """간단한 인메모리 캐시 구현 (L1 캐시)"""
    def __init__(self, max_size=1000):
        self.cache = {}
        self.max_size = max_size
        self.lock = threading.RLock()
    
    def get(self, key):
        with self.lock:
            item = self.cache.get(key)
            if not item:
                return None
            
            # TTL 만료 확인
            expiry, value = item
            if expiry and expiry < time.time():
                del self.cache[key]
                return None
                
            return value
    
    def set(self, key, value, ttl=None):
        with self.lock:
            # 캐시가 최대 크기에 도달하면 가장 오래된 항목 제거
            if len(self.cache) >= self.max_size and key not in self.cache:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
            
            # TTL 설정
            expiry = None
            if ttl:
                expiry = time.time() + ttl
                
            self.cache[key] = (expiry, value)
            return True
    
    def delete(self, key):
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False
    
    def clear(self):
        with self.lock:
            self.cache.clear()
            return True

def default_json_serializer(obj):
    """
    기본 JSON 직렬화 함수로, SQLAlchemy 모델 객체 등을 처리합니다.
    
    Args:
        obj: 직렬화할 객체
        
    Returns:
        직렬화된 값
    """
    # SQLAlchemy 모델 객체 처리
    if hasattr(obj, 'to_dict') and callable(getattr(obj, 'to_dict')):
        return obj.to_dict()
    
    # datetime 객체 처리
    if hasattr(obj, 'isoformat') and callable(getattr(obj, 'isoformat')):
        return obj.isoformat()
    
    # 기본 처리
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

class RedisClient:
    """
    Memurai/Redis 클라이언트 클래스로 캐싱 기능을 제공합니다.
    
    Windows 환경에서는 Memurai를 사용하고, 다른 환경에서는 Redis를 사용합니다.
    Memurai는 Redis와 완전히 호환되므로 동일한 API로 접근할 수 있습니다.
    
    Attributes:
        client: Memurai/Redis 연결 클라이언트
        memory_cache: 인메모리 캐시 (L1)
        default_ttl: 기본 TTL (초 단위)
        is_windows: Windows 환경 여부
        prefix: 캐시 키 접두사 (기본값: 'casino')
    """
    def __init__(self, prefix: str = "casino"):
        """Memurai/Redis 클라이언트 초기화 및 연결"""
        self.is_windows = platform.system() == "Windows"
        cache_type = "Memurai" if self.is_windows else "Redis"
        self.prefix = prefix
        
        # L1 메모리 캐시 초기화
        self.memory_cache = MemoryCache(max_size=5000)
        
        # 기본값 설정
        self.default_ttl = getattr(settings, 'redis_ttl', 60)
        self.host = "localhost"
        self.port = 6379
        self.db = 0
        
        try:
            # 테스트용: Redis가 없어도 진행되도록 timeout 설정
            self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
            
            # 연결 정보 저장
            self.host = getattr(self.client.connection_pool, 'connection_kwargs', {}).get('host', 'unknown')
            self.port = getattr(self.client.connection_pool, 'connection_kwargs', {}).get('port', 0)
            self.db = getattr(self.client.connection_pool, 'connection_kwargs', {}).get('db', 0)
            
            logger.info(f"{cache_type} 클라이언트가 초기화되었습니다. URL: {settings.redis_url}")
            # 연결 테스트
            self.client.ping()
            logger.info(f"{cache_type} 서버에 성공적으로 연결되었습니다.")
        except redis.ConnectionError as e:
            logger.warning(f"{cache_type} 연결 오류: {e}")
            if self.is_windows:
                logger.warning("Windows에서 Memurai가 실행 중인지 확인하세요.")
            else:
                logger.warning("Redis 서비스가 실행 중인지 확인하세요.")
            # 테스트용: Redis가 없어도 진행되도록 수정
            logger.warning("Redis 없이 진행합니다. 일부 기능이 제한될 수 있습니다.")
            self.client = None
        except Exception as e:
            logger.warning(f"{cache_type} 초기화 오류: {e}")
            logger.warning("Redis 없이 진행합니다. 일부 기능이 제한될 수 있습니다.")
            self.client = None

    def is_connected(self) -> bool:
        """Memurai/Redis 서버 연결 상태 확인"""
        if not self.client:
            return False
        try:
            return self.client.ping()
        except:
            return False
            
    # CacheProvider의 is_available 메서드와 동일 기능으로 별칭 제공
    def is_available(self) -> bool:
        """Redis 연결 가능 여부 확인 (is_connected의 별칭)"""
        return self.is_connected()

    def get(self, key: str, tier: str = CacheTier.L2) -> Optional[str]:
        """
        지정된 캐시 계층에서 키에 해당하는 값을 반환합니다.
        
        Args:
            key: 조회할 키
            tier: 캐시 계층 (L1: 메모리, L2: Redis)
        
        Returns:
            키에 해당하는 값 또는 None (키가 없는 경우)
        """
        # L1 캐시 먼저 확인
        if tier == CacheTier.L1 or tier == CacheTier.L2:
            memory_value = self.memory_cache.get(key)
            if memory_value is not None:
                logger.debug(f"L1 캐시 적중: {key}")
                return memory_value
        
        # L1에 없으면 L2(Redis) 확인
        if tier == CacheTier.L2 and self.is_connected():
            try:
                redis_value = self.client.get(key)
                if redis_value is not None:
                    logger.debug(f"L2 캐시 적중: {key}")
                    # L1 캐시에도 저장 (더 빠른 액세스를 위해)
                    # L1은 더 짧은 TTL 사용
                    l1_ttl = min(self.get_ttl(key) or self.default_ttl, 60)  # L1은 최대 60초
                    self.memory_cache.set(key, redis_value, ttl=l1_ttl)
                    return redis_value
            except Exception as e:
                logger.error(f"Redis GET 오류 (키: {key}): {e}")
        
        return None

    def get_json(self, key: str, tier: str = CacheTier.L2) -> Optional[dict]:
        """
        지정된 캐시 계층에서 키에 해당하는 JSON 값을 파싱하여 반환합니다.
        
        Args:
            key: 조회할 키
            tier: 캐시 계층 (L1: 메모리, L2: Redis)
        
        Returns:
            파싱된 JSON 딕셔너리 또는 None (키가 없거나 파싱 오류)
        """
        value = self.get(key, tier=tier)
        if not value:
            return None
        
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 오류 (키: {key}): {e}")
            # 손상된 데이터 삭제
            self.delete(key)
            return None

    def set(self, key: str, value: Union[str, dict], ttl: Optional[int] = None, tier: str = CacheTier.L2) -> bool:
        """
        지정된 캐시 계층에 값을 저장합니다.
        
        Args:
            key: 저장할 키
            value: 저장할 값 (문자열 또는 딕셔너리)
            ttl: TTL (초) - 미지정 시 리소스 유형에 따른 기본값 사용
            tier: 캐시 계층 (L1: 메모리, L2: Redis 또는 Both)
            
        Returns:
            성공 여부 (True/False)
        """
        # 리소스 유형에 따른 TTL 결정
        if ttl is None:
            resource_type = key.split(':')[0] if ':' in key else 'default'
            ttl = CACHE_TTL.get(resource_type, self.default_ttl)
        
        # 딕셔너리인 경우 JSON으로 변환
        string_value = value
        if not isinstance(value, str):
            # 저장 시간 기록
            if isinstance(value, dict) and not value.get("_cached_at"):
                value["_cached_at"] = datetime.now().isoformat()
            try:
                string_value = json.dumps(value, default=default_json_serializer)
            except TypeError as e:
                logger.error(f"JSON 직렬화 오류 (키: {key}): {e}")
                return False
        
        success = True
        
        # L1 캐시에 저장 (더 짧은 TTL 사용)
        if tier == CacheTier.L1 or tier == CacheTier.L2:
            l1_ttl = min(ttl, 60)  # 최대 60초
            self.memory_cache.set(key, string_value, ttl=l1_ttl)
            
        # L2(Redis) 캐시에 저장
        if tier == CacheTier.L2 and self.is_connected():
            try:
                success = bool(self.client.set(key, string_value, ex=ttl))
            except Exception as e:
                logger.error(f"Redis SET 오류 (키: {key}): {e}")
                success = False
        
        return success

    def delete(self, key: str, tier: str = CacheTier.L2) -> bool:
        """
        지정된 캐시 계층에서 키를 삭제합니다.
        
        Args:
            key: 삭제할 키
            tier: 캐시 계층 (L1: 메모리, L2: Redis)
            
        Returns:
            성공 여부 (True/False)
        """
        success = True
        
        # L1 캐시에서 삭제
        if tier == CacheTier.L1 or tier == CacheTier.L2:
            self.memory_cache.delete(key)
        
        # L2(Redis) 캐시에서 삭제
        if tier == CacheTier.L2 and self.is_connected():
            try:
                success = bool(self.client.delete(key))
            except Exception as e:
                logger.error(f"Redis DELETE 오류 (키: {key}): {e}")
                success = False
        
        return success

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
        # 캐시 키 형식 통일 (wallet:{player_id})
        cache_key = f"wallet:{player_id}"
        cache_data = {"balance": float(balance), "currency": currency, "_cached_at": time.time()}
        
        # 캐시 잠금을 통한 원자적 업데이트 시도
        lock_key = f"lock:{cache_key}"
        try:
            # 잠금 획득 시도 (10ms 타임아웃)
            if self.client and self.client.set(lock_key, 1, ex=5, nx=True):
                # 지갑에 대해서는 짧은 TTL 적용 (자주 변경됨)
                result = self.set(cache_key, cache_data, ttl=CACHE_TTL['wallet'])
                logger.info(f"지갑 캐시 업데이트 성공: {player_id}, 새 잔액: {balance}")
                return result
            else:
                # 잠금 획득 실패 - 다른 프로세스가 업데이트 중
                logger.warning(f"지갑 캐시 업데이트 잠금 획득 실패: {player_id}")
                # 캐시 무효화 (다음 요청에서 DB에서 최신 데이터 조회하도록)
                self.delete(cache_key)
                return False
        except Exception as e:
            logger.error(f"지갑 캐시 업데이트 오류: {e}")
            return False
        finally:
            # 잠금 해제 시도
            if self.client:
                try:
                    self.client.delete(lock_key)
                except:
                    pass

    def get_client_info(self) -> dict:
        """
        Redis 클라이언트 연결 정보 및 상태를 반환합니다.
        
        Returns:
            Redis 클라이언트 정보 딕셔너리
        """
        info = {
            "type": "Memurai" if self.is_windows else "Redis",
            "connected": self.is_connected(),
            "host": getattr(self, 'host', 'unknown'),
            "port": getattr(self, 'port', 0),
            "db": getattr(self, 'db', 0),
            "default_ttl": self.default_ttl,
            "prefix": self.prefix,
            "memory_cache_size": len(getattr(self.memory_cache, 'cache', {})),
        }
        
        # 서버 정보 추가 (연결된 경우)
        if self.is_connected():
            try:
                redis_info = self.client.info()
                info.update({
                    "version": redis_info.get('redis_version', 'unknown'),
                    "used_memory": redis_info.get('used_memory_human', 'unknown'),
                    "clients_connected": redis_info.get('connected_clients', 0),
                    "uptime_days": redis_info.get('uptime_in_days', 0),
                })
            except:
                pass
                
        return info

    def get_player_balance_key(self, player_id: str) -> str:
        """
        플레이어 지갑 잔액 캐시 키를 생성합니다.
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            캐시 키
        """
        return f"wallet:{player_id}"

    def get_game_state_key(self, game_id: str) -> str:
        """
        게임 상태 캐시 키를 생성합니다.
        
        Args:
            game_id: 게임 ID
            
        Returns:
            캐시 키
        """
        return f"game_state:{game_id}"

    def get_player_session_key(self, player_id: str) -> str:
        """
        플레이어 세션 캐시 키를 생성합니다.
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            캐시 키
        """
        return f"session:{player_id}"

    def get_ttl(self, key: str) -> int:
        """
        Redis에 저장된 키의 남은 TTL을 반환합니다.
        
        Args:
            key: 조회할 키
            
        Returns:
            남은 TTL (초) 또는 -1 (만료 시간 없음) 또는 -2 (키 없음)
        """
        if not self.is_connected():
            return -2
            
        try:
            return self.client.ttl(key)
        except Exception as e:
            logger.error(f"TTL 조회 오류 (키: {key}): {e}")
            return -2

    def publish(self, channel: str, message: Union[str, dict]) -> bool:
        """
        Redis 채널에 메시지를 발행합니다 (실시간 업데이트용).
        
        Args:
            channel: 채널 이름
            message: 발행할 메시지 (문자열 또는 딕셔너리)
            
        Returns:
            성공 여부 (True/False)
        """
        if not self.is_connected():
            return False
            
        try:
            if isinstance(message, dict):
                message = json.dumps(message)
                
            return bool(self.client.publish(channel, message))
        except Exception as e:
            logger.error(f"메시지 발행 오류 (채널: {channel}): {e}")
            return False

    def flush_all(self) -> bool:
        """
        모든 캐시를 삭제합니다 (주의: 개발/테스트 환경에서만 사용).
        
        Returns:
            성공 여부 (True/False)
        """
        # 안전 검사: 환경 변수로 허용된 경우에만 실행
        if os.environ.get('ENVIRONMENT', 'development').lower() == 'production':
            logger.error("프로덕션 환경에서 모든 캐시 삭제 시도가 차단되었습니다.")
            return False
            
        # L1 캐시 삭제
        self.memory_cache.clear()
            
        # Redis 캐시 삭제
        if not self.is_connected():
            return False
            
        try:
            # 참고: 실무에서는 FLUSHALL 대신 데이터베이스별 FLUSHDB 또는 UNLINK/DEL 사용 권장
            if self.prefix:
                # 접두사가 있으면 해당 패턴의 키만 삭제
                cursor = '0'
                pattern = f"{self.prefix}:*"
                deleted = 0
                
                while cursor != 0:
                    cursor, keys = self.client.scan(cursor=cursor, match=pattern, count=1000)
                    if keys:
                        deleted += self.client.delete(*keys)
                        
                logger.info(f"패턴 '{pattern}'에 해당하는 {deleted}개 키 삭제됨")
                return True
            else:
                # 접두사가 없으면 전체 삭제 (주의!)
                self.client.flushdb()
                logger.info("모든 캐시가 삭제되었습니다.")
                return True
        except Exception as e:
            logger.error(f"캐시 삭제 오류: {e}")
            return False

# 캐시 데코레이터
def cached(key_prefix: str, ttl: Optional[int] = None, tier: str = CacheTier.L2):
    """
    함수 결과를 캐시하는 데코레이터입니다.
    
    Args:
        key_prefix: 캐시 키 접두사
        ttl: TTL (초) - 미지정 시 리소스 타입별 기본값 사용
        tier: 캐시 계층 (L1, L2)
        
    Returns:
        캐시된 결과를 반환하는 데코레이터된 함수
    """
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 캐시 키 생성 (접두사 + 인자 해시)
            args_str = str(args) + str(sorted(kwargs.items()))
            args_hash = hashlib.md5(args_str.encode()).hexdigest()
            cache_key = f"{key_prefix}:{args_hash}"
            
            # 캐시에서 결과 조회
            redis_client = get_redis_client()
            cached_result = redis_client.get_json(cache_key, tier=tier)
            
            if cached_result:
                return cached_result
            
            # 캐시 미스: 원본 함수 실행
            result = await func(*args, **kwargs)
            
            # 결과 캐싱
            if result:
                redis_client.set(cache_key, result, ttl=ttl, tier=tier)
                
            return result
            
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 캐시 키 생성 (접두사 + 인자 해시)
            args_str = str(args) + str(sorted(kwargs.items()))
            args_hash = hashlib.md5(args_str.encode()).hexdigest()
            cache_key = f"{key_prefix}:{args_hash}"
            
            # 캐시에서 결과 조회
            redis_client = get_redis_client()
            cached_result = redis_client.get_json(cache_key, tier=tier)
            
            if cached_result:
                return cached_result
            
            # 캐시 미스: 원본 함수 실행
            result = func(*args, **kwargs)
            
            # 결과 캐싱
            if result:
                redis_client.set(cache_key, result, ttl=ttl, tier=tier)
                
            return result
            
        # 원본 함수가 비동기인지 확인
        if asyncio_helper_is_coroutine(func):
            return async_wrapper
        return sync_wrapper
        
    return decorator

# asyncio 헬퍼 함수 (Python 3.8+ 지원)
def asyncio_helper_is_coroutine(obj):
    """객체가 코루틴 함수인지 확인합니다."""
    import inspect
    return inspect.iscoroutinefunction(obj)

# 싱글톤 Redis 클라이언트 인스턴스
_redis_client = None

def get_redis_client() -> RedisClient:
    """
    싱글톤 Redis 클라이언트 인스턴스를 반환합니다.
    
    Returns:
        RedisClient 인스턴스
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient(prefix="casino")
    return _redis_client

# 기본 인스턴스 생성 (import 시 초기화)
redis_client = get_redis_client() 