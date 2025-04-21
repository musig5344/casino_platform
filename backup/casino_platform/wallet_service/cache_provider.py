import logging
import json
from typing import Any, Dict, Optional, Union, List
from datetime import datetime
from decimal import Decimal
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

class DecimalEncoder(json.JSONEncoder):
    """Decimal 타입을 JSON으로 인코딩하기 위한 클래스"""
    
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)

class CacheProvider:
    """
    Redis 기반 캐시 프로바이더 클래스
    """
    
    # 캐시 키 접두사 및 만료 시간 설정
    WALLET_PREFIX = "wallet:"
    TRANSACTION_PREFIX = "transaction:"
    USER_PREFIX = "user:"
    DEFAULT_TTL = 3600  # 1시간
    BALANCE_TTL = 60    # 잔액 캐시 TTL (초)
    
    # 채널 이름
    WALLET_UPDATE_CHANNEL = "wallet_updates"
    
    def __init__(self, redis_client: aioredis.Redis, prefix: str = "casino:"):
        """
        캐시 프로바이더 초기화
        
        Args:
            redis_client: Redis 비동기 클라이언트
            prefix: 캐시 키 접두사
        """
        self.redis = redis_client
        self.prefix = prefix
    
    def get_player_balance_key(self, player_id: str) -> str:
        """
        플레이어 잔액 캐시 키 생성
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            str: 캐시 키
        """
        return f"{self.prefix}{self.WALLET_PREFIX}{player_id}:balance"
    
    def get_transaction_key(self, transaction_id: str) -> str:
        """
        트랜잭션 캐시 키 생성
        
        Args:
            transaction_id: 트랜잭션 ID
            
        Returns:
            str: 캐시 키
        """
        return f"{self.prefix}{self.TRANSACTION_PREFIX}{transaction_id}"
    
    def get_user_preferences_key(self, user_id: str) -> str:
        """
        사용자 환경설정 캐시 키 생성
        
        Args:
            user_id: 사용자 ID
            
        Returns:
            str: 캐시 키
        """
        return f"{self.prefix}{self.USER_PREFIX}{user_id}:preferences"
    
    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        캐시에서 데이터 조회
        
        Args:
            key: 캐시 키
            
        Returns:
            Optional[Dict[str, Any]]: 캐시된 데이터 또는 None (캐시 미스)
        """
        try:
            cached_data = await self.redis.get(key)
            
            if cached_data:
                # JSON 문자열을 파이썬 객체로 변환
                data = json.loads(cached_data)
                
                # Decimal 문자열을 Decimal 객체로 변환
                if "balance" in data and isinstance(data["balance"], str):
                    data["balance"] = Decimal(data["balance"])
                
                logger.debug(f"캐시 히트: {key}")
                return data
            
            logger.debug(f"캐시 미스: {key}")
            return None
            
        except Exception as e:
            logger.error(f"캐시 조회 중 오류: {str(e)}")
            # 캐시 오류 시 None 반환 (실패 시에도 앱 동작 가능)
            return None
    
    async def set(self, key: str, value: Dict[str, Any], ttl: int = None) -> bool:
        """
        캐시에 데이터 저장
        
        Args:
            key: 캐시 키
            value: 저장할 데이터
            ttl: TTL (초 단위, 기본값 사용 시 None)
            
        Returns:
            bool: 성공 여부
        """
        try:
            # 만료 시간 설정
            expiration = ttl if ttl is not None else self.DEFAULT_TTL
            
            # Decimal 객체를 문자열로 변환하여 JSON 직렬화
            json_data = json.dumps(value, cls=DecimalEncoder)
            
            # 캐시에 저장
            await self.redis.set(key, json_data, ex=expiration)
            logger.debug(f"캐시 저장 성공: {key}, TTL={expiration}초")
            return True
            
        except Exception as e:
            logger.error(f"캐시 저장 중 오류: {str(e)}")
            return False
    
    async def delete(self, key: str) -> bool:
        """
        캐시에서 데이터 삭제
        
        Args:
            key: 캐시 키
            
        Returns:
            bool: 성공 여부
        """
        try:
            await self.redis.delete(key)
            logger.debug(f"캐시 삭제 성공: {key}")
            return True
            
        except Exception as e:
            logger.error(f"캐시 삭제 중 오류: {str(e)}")
            return False
    
    async def publish_wallet_update(self, wallet_id: str, player_id: str) -> bool:
        """
        지갑 업데이트 이벤트 발행
        
        Args:
            wallet_id: 지갑 ID
            player_id: 플레이어 ID
            
        Returns:
            bool: 성공 여부
        """
        try:
            message = json.dumps({
                "event": "wallet_updated",
                "wallet_id": wallet_id,
                "player_id": player_id,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Redis Pub/Sub 채널에 메시지 발행
            await self.redis.publish(self.WALLET_UPDATE_CHANNEL, message)
            logger.debug(f"지갑 업데이트 이벤트 발행: player_id={player_id}")
            return True
            
        except Exception as e:
            logger.error(f"이벤트 발행 중 오류: {str(e)}")
            return False
    
    async def subscribe_to_wallet_updates(self, callback):
        """
        지갑 업데이트 이벤트 구독
        
        Args:
            callback: 메시지 수신 시 호출할 콜백 함수
            
        Returns:
            None
        """
        try:
            # Redis Pub/Sub 채널 구독 설정
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(self.WALLET_UPDATE_CHANNEL)
            
            # 비동기 메시지 처리 시작
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    await callback(data)
            
        except Exception as e:
            logger.error(f"이벤트 구독 중 오류: {str(e)}")
    
    def _prepare_for_serialization(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        직렬화를 위해 데이터 변환
        
        Args:
            data: 변환할 데이터
            
        Returns:
            Dict[str, Any]: 직렬화 가능한 데이터
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if hasattr(value, 'isoformat') and callable(getattr(value, 'isoformat')):
                    # datetime 객체 변환
                    result[key] = value.isoformat()
                elif hasattr(value, '__str__'):
                    # Decimal 등 다른 특수 객체 변환
                    result[key] = str(value)
                elif isinstance(value, dict):
                    # 중첩된 딕셔너리 처리
                    result[key] = self._prepare_for_serialization(value)
                elif isinstance(value, list):
                    # 리스트 내부 항목 처리
                    result[key] = [
                        self._prepare_for_serialization(item) if isinstance(item, dict)
                        else str(item) if hasattr(item, '__str__')
                        else item
                        for item in value
                    ]
                else:
                    result[key] = value
            return result
        return data
    
    async def set_with_hash_field(self, hash_key: str, field: str, value: Dict[str, Any], ttl: int = None) -> bool:
        """
        Redis Hash 구조에 데이터 저장
        
        Args:
            hash_key: Hash 키
            field: Hash 필드
            value: 저장할 데이터
            ttl: TTL (초 단위, 기본값 사용 시 None)
            
        Returns:
            bool: 성공 여부
        """
        try:
            # Decimal 객체를 문자열로 변환하여 JSON 직렬화
            json_data = json.dumps(value, cls=DecimalEncoder)
            
            # Hash에 저장
            await self.redis.hset(hash_key, field, json_data)
            
            # 만료 시간 설정
            if ttl is not None:
                await self.redis.expire(hash_key, ttl)
                
            logger.debug(f"Hash 저장 성공: {hash_key}:{field}")
            return True
            
        except Exception as e:
            logger.error(f"Hash 저장 중 오류: {str(e)}")
            return False
    
    async def get_from_hash(self, hash_key: str, field: str) -> Optional[Dict[str, Any]]:
        """
        Redis Hash에서 데이터 조회
        
        Args:
            hash_key: Hash 키
            field: Hash 필드
            
        Returns:
            Optional[Dict[str, Any]]: 조회된 데이터 또는 None
        """
        try:
            data = await self.redis.hget(hash_key, field)
            
            if data:
                return json.loads(data)
                
            return None
            
        except Exception as e:
            logger.error(f"Hash 조회 중 오류: {str(e)}")
            return None
    
    async def get_all_from_hash(self, hash_key: str) -> Dict[str, Any]:
        """
        Redis Hash의 모든 필드 조회
        
        Args:
            hash_key: Hash 키
            
        Returns:
            Dict[str, Any]: 모든 필드와 값
        """
        try:
            result = {}
            data = await self.redis.hgetall(hash_key)
            
            for field, value in data.items():
                try:
                    result[field.decode('utf-8')] = json.loads(value)
                except Exception:
                    result[field.decode('utf-8')] = value
                    
            return result
            
        except Exception as e:
            logger.error(f"Hash 전체 조회 중 오류: {str(e)}")
            return {}
    
    async def invalidate_player_cache(self, player_id: str) -> bool:
        """
        플레이어 관련 모든 캐시 무효화
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            bool: 성공 여부
        """
        try:
            # 플레이어 패턴과 일치하는 모든 키 검색 후 삭제
            pattern = f"{self.prefix}{self.WALLET_PREFIX}{player_id}:*"
            cursor = 0
            deleted_count = 0
            
            while True:
                cursor, keys = await self.redis.scan(cursor=cursor, match=pattern)
                
                if keys:
                    await self.redis.delete(*keys)
                    deleted_count += len(keys)
                
                if cursor == 0:
                    break
            
            # 이벤트 발행
            await self.publish_wallet_update(str(player_id), str(player_id))
            
            logger.debug(f"플레이어 {player_id} 캐시 무효화 완료, {deleted_count}개 키 삭제")
            return True
            
        except Exception as e:
            logger.error(f"캐시 무효화 중 오류: {str(e)}")
            return False
            
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Redis 캐시 통계 정보를 조회합니다.
        
        Returns:
            Dict[str, Any]: 캐시 통계 정보
        """
        try:
            info = await self.redis.info()
            
            stats = {
                "hits": int(info.get("keyspace_hits", 0)),
                "misses": int(info.get("keyspace_misses", 0)),
                "keys": await self.redis.dbsize(),
                "memory_used": info.get("used_memory_human", "unknown"),
                "uptime_seconds": int(info.get("uptime_in_seconds", 0)),
                "connected_clients": int(info.get("connected_clients", 0)),
                "last_updated": datetime.utcnow().isoformat()
            }
            
            # 히트율 계산 (0으로 나누기 방지)
            total = stats["hits"] + stats["misses"]
            stats["hit_rate"] = round(stats["hits"] / total * 100, 2) if total > 0 else 0
            
            return stats
            
        except Exception as e:
            logger.error(f"캐시 통계 조회 중 오류: {str(e)}")
            return {
                "error": str(e),
                "status": "error"
            } 