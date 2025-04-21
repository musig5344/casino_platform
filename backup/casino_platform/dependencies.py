import logging
import os
from typing import Optional

import asyncpg
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from casino_platform.wallet_service import WalletService, CacheProvider, WalletRepository
from casino_platform.security import decode_jwt

# 보안 의존성
security = HTTPBearer()
logger = logging.getLogger(__name__)

async def validate_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    JWT 토큰 검증
    
    Args:
        credentials: HTTP Authorization 토큰
        
    Returns:
        dict: 토큰 내용
        
    Raises:
        HTTPException: 토큰이 유효하지 않은 경우
    """
    try:
        token = credentials.credentials
        payload = decode_jwt(token)
        return payload
    except Exception as e:
        logger.error(f"토큰 검증 실패: {str(e)}")
        raise HTTPException(status_code=401, detail="인증 실패")

async def get_db_pool(request: Request):
    """
    데이터베이스 연결 풀 가져오기
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        asyncpg.Pool: 데이터베이스 풀
    """
    return request.app.state.db_pool

async def get_cache_provider(request: Request) -> CacheProvider:
    """
    캐시 프로바이더 인스턴스 가져오기
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        CacheProvider: 캐시 프로바이더 인스턴스
    """
    return request.app.state.cache_provider

async def get_wallet_repository(request: Request) -> WalletRepository:
    """
    지갑 리포지토리 인스턴스 가져오기
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        WalletRepository: 지갑 리포지토리 인스턴스
    """
    if not hasattr(request.app.state, "wallet_repository"):
        db_pool = await get_db_pool(request)
        request.app.state.wallet_repository = WalletRepository(db_pool)
    
    return request.app.state.wallet_repository

async def get_wallet_service(request: Request) -> WalletService:
    """
    지갑 서비스 인스턴스 가져오기
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        WalletService: 지갑 서비스 인스턴스
    """
    if not hasattr(request.app.state, "wallet_service"):
        wallet_repository = await get_wallet_repository(request)
        cache_provider = await get_cache_provider(request)
        request.app.state.wallet_service = WalletService(wallet_repository, cache_provider)
    
    return request.app.state.wallet_service 