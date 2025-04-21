import time
import logging
from typing import Dict, Tuple, Optional, Callable
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    API 요청 빈도 제한을 위한 미들웨어
    
    Redis를 사용하여 IP 또는 사용자 기반 요청 제한을 구현합니다.
    """
    
    def __init__(
        self,
        app,
        redis_client: aioredis.Redis,
        rate_limit_seconds: int = 60,
        max_requests: int = 100,
        whitelist_ips: Optional[list] = None,
        whitelist_paths: Optional[list] = None,
        block_on_exceed: bool = False,
        block_duration: int = 3600,  # 1시간
    ):
        """
        Rate Limit 미들웨어 초기화
        
        Args:
            app: FastAPI 애플리케이션
            redis_client: Redis 클라이언트
            rate_limit_seconds: 제한 기간(초)
            max_requests: 제한 기간 내 최대 요청 수
            whitelist_ips: 제한에서 제외할 IP 목록
            whitelist_paths: 제한에서 제외할 경로 목록
            block_on_exceed: 제한 초과 시 IP 차단 여부
            block_duration: IP 차단 지속 시간(초)
        """
        super().__init__(app)
        self.redis = redis_client
        self.rate_limit_seconds = rate_limit_seconds
        self.max_requests = max_requests
        self.whitelist_ips = whitelist_ips or []
        self.whitelist_paths = whitelist_paths or ["/docs", "/redoc", "/openapi.json", "/health"]
        self.block_on_exceed = block_on_exceed
        self.block_duration = block_duration
        
        logger.info(
            f"요청 비율 제한 미들웨어 초기화: "
            f"{max_requests}회/{rate_limit_seconds}초, "
            f"차단 기능: {block_on_exceed}"
        )
    
    async def _is_ip_blocked(self, client_ip: str) -> bool:
        """
        IP가 차단되었는지 확인
        
        Args:
            client_ip: 클라이언트 IP
            
        Returns:
            bool: 차단 여부
        """
        key = f"blocked:{client_ip}"
        is_blocked = await self.redis.exists(key)
        return bool(is_blocked)
    
    async def _block_ip(self, client_ip: str) -> None:
        """
        IP 차단
        
        Args:
            client_ip: 차단할 클라이언트 IP
        """
        key = f"blocked:{client_ip}"
        await self.redis.set(key, 1, ex=self.block_duration)
        logger.warning(f"IP 차단됨: {client_ip} ({self.block_duration}초 동안)")
    
    async def _get_request_count(self, key: str) -> int:
        """
        현재 요청 카운트 조회
        
        Args:
            key: Redis 키
            
        Returns:
            int: 요청 카운트
        """
        count = await self.redis.get(key)
        return int(count) if count else 0
    
    async def _increment_request_count(self, key: str) -> Tuple[int, int]:
        """
        요청 카운트 증가 및 잔여 요청 수 계산
        
        Args:
            key: Redis 키
            
        Returns:
            Tuple[int, int]: (현재 요청 수, 잔여 요청 수)
        """
        # 키가 없으면 생성하고 1로 설정
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, self.rate_limit_seconds)
            
        # TTL 확인
        ttl = await self.redis.ttl(key)
        
        # 잔여 요청 수 계산
        remaining = max(0, self.max_requests - current)
        
        return current, remaining
    
    async def _get_rate_limit_key(self, request: Request) -> str:
        """
        요청에 대한 Rate Limit 키 생성
        
        Args:
            request: FastAPI 요청 객체
            
        Returns:
            str: Redis 키
        """
        # 기본적으로 IP 기반 제한
        client_ip = request.client.host
        
        # 인증된 사용자가 있는 경우 사용자 ID 추가
        user_id = None
        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id
        
        # API 경로별 제한 적용
        path = request.url.path
        
        if user_id:
            return f"ratelimit:user:{user_id}:{path}"
        else:
            return f"ratelimit:ip:{client_ip}:{path}"
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        미들웨어 디스패치 함수
        
        Args:
            request: FastAPI 요청 객체
            call_next: 다음 처리기 호출 함수
            
        Returns:
            Response: 응답 객체
        """
        # 경로가 화이트리스트에 있는 경우 바로 처리
        if any(request.url.path.startswith(path) for path in self.whitelist_paths):
            return await call_next(request)
        
        # 클라이언트 IP 확인
        client_ip = request.client.host
        
        # IP가 화이트리스트에 있는 경우 바로 처리
        if client_ip in self.whitelist_ips:
            return await call_next(request)
        
        # IP가 차단된 경우 403 응답
        if await self._is_ip_blocked(client_ip):
            return Response(
                content='{"detail":"Rate limit exceeded. Your IP has been temporarily blocked."}',
                status_code=status.HTTP_403_FORBIDDEN,
                media_type="application/json"
            )
        
        # Rate Limit 키 생성
        rate_limit_key = await self._get_rate_limit_key(request)
        
        # 요청 카운트 증가 및 제한 확인
        current, remaining = await self._increment_request_count(rate_limit_key)
        
        # 제한 초과 시 처리
        if current > self.max_requests:
            # 차단 기능이 활성화된 경우 IP 차단
            if self.block_on_exceed:
                await self._block_ip(client_ip)
            
            # 429 Too Many Requests 응답
            return Response(
                content='{"detail":"Rate limit exceeded. Please try again later."}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(await self.redis.ttl(rate_limit_key))
                },
                media_type="application/json"
            )
        
        # 요청 처리
        response = await call_next(request)
        
        # 응답 헤더에 비율 제한 정보 추가
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        return response 