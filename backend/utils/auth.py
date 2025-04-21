from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from datetime import datetime

from backend.database import get_db
from backend.config.settings import get_settings
from backend.models.user import User

# OAuth2 토큰 URL 설정
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)

# 설정 가져오기
settings = get_settings()

async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    현재 인증된 사용자 정보를 가져옵니다.
    
    Args:
        request: FastAPI 요청 객체
        token: JWT 토큰
        db: 데이터베이스 세션
        
    Returns:
        Dict[str, Any]: 사용자 정보
    
    Raises:
        HTTPException: 인증 실패 시
    """
    # 개발 환경에서는 기본 테스트 사용자 반환
    if settings.ENVIRONMENT == "development":
        # 헤더에 X-Admin: true가 있으면 관리자 권한 부여
        is_admin = request.headers.get("X-Admin", "").lower() == "true"
        return {
            "username": "test_user",
            "player_id": "test_player_123",
            "is_admin": is_admin,
            "is_active": True
        }
    
    # 토큰이 없는 경우
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증할 수 없습니다",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # JWT 토큰 디코딩
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        # 페이로드에서, 사용자 식별자 추출
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
            
        # 토큰 만료 확인
        exp = payload.get("exp")
        if exp is not None and datetime.utcnow().timestamp() > exp:
            raise credentials_exception
            
        # 사용자 정보 조회
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise credentials_exception
            
        # 유효한 사용자 정보 반환
        return {
            "username": user.username,
            "player_id": user.player_id,
            "is_admin": user.is_admin,
            "is_active": user.is_active
        }
    except JWTError:
        raise credentials_exception
    except Exception as e:
        # 개발 환경에서 디버깅을 위해 예외 로깅
        print(f"인증 중 오류: {str(e)}")
        raise credentials_exception

async def get_current_player_id(current_user: Dict[str, Any] = Depends(get_current_user)) -> str:
    """
    현재 인증된 플레이어 ID를 가져옵니다.
    
    Args:
        current_user: 현재 사용자 정보
        
    Returns:
        str: 플레이어 ID
    
    Raises:
        HTTPException: 권한 부족 시
    """
    if not current_user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다"
        )
        
    player_id = current_user.get("player_id")
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="플레이어 ID가 없습니다"
        )
        
    return player_id

async def get_admin_user(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    현재 사용자가 관리자인지 확인하고, 관리자 정보를 반환합니다.
    
    Args:
        current_user: 현재 사용자 정보
        
    Returns:
        Dict[str, Any]: 관리자 정보
    
    Raises:
        HTTPException: 권한 부족 시
    """
    if not current_user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다"
        )
    
    # 개발 환경에서는 항상 관리자 권한 허용
    if settings.ENVIRONMENT == "development":
        # is_admin이 이미 True로 설정되어 있으면 그대로 사용
        if current_user.get("is_admin"):
            return current_user
        
        # 개발 편의를 위해 관리자 권한 부여
        admin_user = dict(current_user)
        admin_user["is_admin"] = True
        return admin_user
        
    # 운영 환경에서는 관리자 권한 확인
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다"
        )
        
    return current_user

# 테스트 환경에서 사용할 수 있는 더미 인증 함수 (개발 환경에서 인증 우회용)
async def get_test_user() -> Dict[str, Any]:
    """
    테스트용 더미 사용자 정보를 반환합니다.
    
    Returns:
        Dict[str, Any]: 더미 사용자 정보
    """
    return {
        "username": "test_admin",
        "player_id": "admin_123",
        "is_admin": True,
        "is_active": True
    } 