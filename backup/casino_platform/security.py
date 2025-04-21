import os
import logging
import datetime
from typing import Dict, Any, Optional

import jwt
from fastapi import Request, HTTPException, Depends
from passlib.context import CryptContext

# 환경 변수에서 시크릿 키 로드 (안전한 환경변수 사용)
JWT_SECRET = os.environ.get("JWT_SECRET", "casino_platform_default_secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    비밀번호 검증
    
    Args:
        plain_password: 평문 비밀번호
        hashed_password: 해시된 비밀번호
        
    Returns:
        bool: 검증 결과
    """
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    비밀번호 해시
    
    Args:
        password: 평문 비밀번호
        
    Returns:
        str: 해시된 비밀번호
    """
    return pwd_context.hash(password)

def create_jwt(data: Dict[str, Any], expires_delta: Optional[datetime.timedelta] = None) -> str:
    """
    JWT 토큰 생성
    
    Args:
        data: 토큰에 담을 데이터
        expires_delta: 만료 시간
        
    Returns:
        str: JWT 토큰
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_EXPIRATION_MINUTES)
    
    to_encode.update({"exp": expire})
    
    # Use HS256 encryption algorithm for compatibility
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    # PyJWT 2.0+ returns a string while older versions return bytes
    if isinstance(encoded_jwt, bytes):
        return encoded_jwt.decode('utf-8')
    return encoded_jwt

def decode_jwt(token: str) -> Dict[str, Any]:
    """
    JWT 토큰 디코딩
    
    Args:
        token: JWT 토큰
        
    Returns:
        Dict[str, Any]: 디코딩된 토큰 데이터
        
    Raises:
        Exception: 토큰이 유효하지 않은 경우
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("만료된 토큰")
        raise Exception("토큰이 만료되었습니다")
    except jwt.InvalidTokenError:
        logger.warning("유효하지 않은 토큰")
        raise Exception("유효하지 않은 토큰입니다")

def get_current_player_id(request: Request) -> str:
    """
    현재 인증된 플레이어 ID 가져오기
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        str: 플레이어 ID
        
    Raises:
        HTTPException: 인증 정보가 유효하지 않은 경우
    """
    try:
        auth = request.headers.get("Authorization", "")
        
        if not auth or not auth.startswith("Bearer "):
            raise ValueError("유효하지 않은 인증 헤더")
        
        token = auth.split(" ")[1]
        payload = decode_jwt(token)
        
        if not payload.get("player_id"):
            raise ValueError("토큰에 플레이어 ID가 없습니다")
        
        return payload["player_id"]
    except Exception as e:
        logger.error(f"인증 실패: {str(e)}")
        raise HTTPException(status_code=401, detail="인증 실패") 