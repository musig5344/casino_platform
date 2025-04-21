import logging
from typing import Optional, List, Dict, Any
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, validator

from casino_platform.database.db_dependency import get_db_session
from casino_platform.wallet_service.wallet_service import WalletService
from casino_platform.wallet_service.cache_provider import CacheProvider
from casino_platform.auth.auth_service import verify_token
from casino_platform.redis.redis_dependency import get_redis_client
from casino_platform.schemas.wallet_schemas import (
    BalanceResponse,
    TransactionHistoryResponse,
    DepositRequest,
    WithdrawRequest,
    WalletResponse
)

logger = logging.getLogger(__name__)
security = HTTPBearer()

router = APIRouter(
    prefix="/wallet",
    tags=["지갑"],
    responses={
        401: {"description": "인증되지 않음"},
        403: {"description": "권한 없음"},
        500: {"description": "서버 오류"}
    }
)


# 의존성 주입 함수
async def get_wallet_service(
    db: AsyncSession = Depends(get_db_session),
    redis_client = Depends(get_redis_client)
) -> WalletService:
    """
    WalletService 의존성 주입
    """
    cache_provider = CacheProvider(redis_client)
    return WalletService(db, cache_provider)


# 토큰 검증 및 플레이어 ID 추출 의존성
async def get_current_player_id(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> str:
    """
    현재 인증된 플레이어 ID 반환
    """
    token = credentials.credentials
    payload = await verify_token(token)
    
    if not payload or "player_id" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 인증 정보"
        )
    
    return payload["player_id"]


# 요청 모델
class CreateWalletRequest(BaseModel):
    """지갑 생성 요청 모델"""
    player_id: str = Field(..., description="플레이어 ID")
    initial_balance: Optional[Decimal] = Field(Decimal("0.00"), description="초기 잔액")
    currency: Optional[str] = Field("KRW", description="통화")
    
    @validator("initial_balance")
    def validate_initial_balance(cls, v):
        if v < 0:
            raise ValueError("초기 잔액은 음수가 될 수 없습니다")
        return v

class CreditRequest(BaseModel):
    """입금 요청 모델"""
    player_id: str = Field(..., description="플레이어 ID")
    amount: Decimal = Field(..., description="입금액")
    transaction_id: Optional[str] = Field(None, description="트랜잭션 ID (없을 경우 자동 생성)")
    description: Optional[str] = Field(None, description="설명")
    reference_id: Optional[str] = Field(None, description="참조 ID")
    game_id: Optional[str] = Field(None, description="게임 ID")
    
    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("입금액은 0보다 커야 합니다")
        return v

class DebitRequest(BaseModel):
    """출금 요청 모델"""
    player_id: str = Field(..., description="플레이어 ID")
    amount: Decimal = Field(..., description="출금액")
    transaction_id: Optional[str] = Field(None, description="트랜잭션 ID (없을 경우 자동 생성)")
    description: Optional[str] = Field(None, description="설명")
    reference_id: Optional[str] = Field(None, description="참조 ID")
    game_id: Optional[str] = Field(None, description="게임 ID")
    
    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("출금액은 0보다 커야 합니다")
        return v

class TransactionHistoryRequest(BaseModel):
    """트랜잭션 내역 요청 모델"""
    player_id: str = Field(..., description="플레이어 ID")
    limit: Optional[int] = Field(10, description="페이지당 항목 수", ge=1, le=100)
    offset: Optional[int] = Field(0, description="조회 시작 오프셋", ge=0)

# 응답 모델
class WalletResponse(BaseModel):
    """지갑 정보 응답 모델"""
    wallet_id: str
    player_id: str
    balance: Decimal
    currency: str
    created_at: str
    updated_at: str

class TransactionResponse(BaseModel):
    """트랜잭션 정보 응답 모델"""
    id: str
    transaction_id: str
    type: str
    amount: Decimal
    balance_after: Decimal
    description: Optional[str]
    reference_id: Optional[str]
    game_id: Optional[str]
    created_at: str

class TransactionHistoryResponse(BaseModel):
    """트랜잭션 내역 응답 모델"""
    items: List[TransactionResponse]
    pagination: Dict[str, Any]

class WalletTransactionResponse(WalletResponse):
    """지갑 정보와 트랜잭션 ID 응답 모델"""
    transaction_id: str

# 의존성 함수
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    토큰 검증 및 현재 사용자 정보 반환 의존성 함수
    
    Args:
        credentials: 인증 자격 증명
        
    Returns:
        Dict[str, Any]: 사용자 정보
        
    Raises:
        HTTPException: 인증 실패 시
    """
    token = credentials.credentials
    try:
        user_data = verify_token(token)
        return user_data
    except Exception as e:
        logger.warning(f"인증 실패: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 인증 자격 증명",
            headers={"WWW-Authenticate": "Bearer"}
        )

# API 엔드포인트
@router.get(
    "/{player_id}/balance",
    response_model=WalletResponse,
    summary="플레이어 잔액 조회",
    description="플레이어의 현재 지갑 잔액을 조회합니다."
)
async def get_player_balance(
    player_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    session = Depends(get_db_session)
):
    """
    플레이어 잔액 조회 API
    
    Args:
        player_id: 플레이어 ID
        user: 인증된 사용자 정보
        session: 데이터베이스 세션
        
    Returns:
        WalletResponse: 지갑 정보
    """
    # 간단한 권한 검사 예시
    if not user.get("is_admin", False) and user.get("player_id") != player_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="다른 플레이어의 지갑에 접근할 권한이 없습니다"
        )
    
    # 서비스 초기화 및 잔액 조회
    wallet_service = WalletService(session)
    result = await wallet_service.get_player_balance(player_id)
    
    return result

@router.post(
    "/create",
    response_model=WalletResponse,
    summary="지갑 생성",
    description="새로운 플레이어 지갑을 생성합니다. 관리자만 접근 가능합니다."
)
async def create_wallet(
    request: CreateWalletRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    session = Depends(get_db_session)
):
    """
    지갑 생성 API
    
    Args:
        request: 지갑 생성 요청 모델
        user: 인증된 사용자 정보
        session: 데이터베이스 세션
        
    Returns:
        WalletResponse: 생성된 지갑 정보
    """
    # 관리자 권한 검사
    if not user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="지갑 생성은 관리자만 가능합니다"
        )
    
    # 서비스 초기화 및 지갑 생성
    wallet_service = WalletService(session)
    result = await wallet_service.create_wallet(
        player_id=request.player_id,
        initial_balance=request.initial_balance,
        currency=request.currency
    )
    
    logger.info(f"지갑 생성 성공: 플레이어 {request.player_id}, 초기 잔액 {request.initial_balance}")
    return result

@router.post(
    "/credit",
    response_model=WalletTransactionResponse,
    summary="입금 처리",
    description="플레이어 지갑에 금액을 입금합니다."
)
async def credit(
    request: CreditRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    session = Depends(get_db_session)
):
    """
    입금 처리 API
    
    Args:
        request: 입금 요청 모델
        user: 인증된 사용자 정보
        session: 데이터베이스 세션
        
    Returns:
        WalletTransactionResponse: 업데이트된 지갑 정보와 트랜잭션 ID
    """
    # 권한 검사 - 자신의 지갑이거나 관리자만 가능
    if not user.get("is_admin", False) and user.get("player_id") != request.player_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="다른 플레이어의 지갑에 입금할 권한이 없습니다"
        )
    
    # 서비스 초기화 및 입금 처리
    wallet_service = WalletService(session)
    result = await wallet_service.credit(
        player_id=request.player_id,
        amount=request.amount,
        transaction_id=request.transaction_id,
        description=request.description,
        reference_id=request.reference_id,
        game_id=request.game_id
    )
    
    logger.info(f"입금 성공: 플레이어 {request.player_id}, 금액 {request.amount}, 트랜잭션 ID {result['transaction_id']}")
    return result

@router.post(
    "/debit",
    response_model=WalletTransactionResponse,
    summary="출금 처리",
    description="플레이어 지갑에서 금액을 출금합니다."
)
async def debit(
    request: DebitRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    session = Depends(get_db_session)
):
    """
    출금 처리 API
    
    Args:
        request: 출금 요청 모델
        user: 인증된 사용자 정보
        session: 데이터베이스 세션
        
    Returns:
        WalletTransactionResponse: 업데이트된 지갑 정보와 트랜잭션 ID
    """
    # 권한 검사 - 자신의 지갑이거나 관리자만 가능
    if not user.get("is_admin", False) and user.get("player_id") != request.player_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="다른 플레이어의 지갑에서 출금할 권한이 없습니다"
        )
    
    # 서비스 초기화 및 출금 처리
    wallet_service = WalletService(session)
    result = await wallet_service.debit(
        player_id=request.player_id,
        amount=request.amount,
        transaction_id=request.transaction_id,
        description=request.description,
        reference_id=request.reference_id,
        game_id=request.game_id
    )
    
    logger.info(f"출금 성공: 플레이어 {request.player_id}, 금액 {request.amount}, 트랜잭션 ID {result['transaction_id']}")
    return result

@router.get(
    "/{player_id}/transactions",
    response_model=TransactionHistoryResponse,
    summary="트랜잭션 내역 조회",
    description="플레이어의 트랜잭션 내역을 조회합니다."
)
async def get_transaction_history(
    player_id: str,
    limit: int = 10,
    offset: int = 0,
    user: Dict[str, Any] = Depends(get_current_user),
    session = Depends(get_db_session)
):
    """
    트랜잭션 내역 조회 API
    
    Args:
        player_id: 플레이어 ID
        limit: 페이지당 항목 수
        offset: 조회 시작 오프셋
        user: 인증된 사용자 정보
        session: 데이터베이스 세션
        
    Returns:
        TransactionHistoryResponse: 트랜잭션 내역 및 페이지네이션 정보
    """
    # 권한 검사 - 자신의 기록이거나 관리자만 가능
    if not user.get("is_admin", False) and user.get("player_id") != player_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="다른 플레이어의 트랜잭션 내역에 접근할 권한이 없습니다"
        )
    
    # 입력값 검증
    if limit < 1 or limit > 100:
        limit = 10
    if offset < 0:
        offset = 0
    
    # 서비스 초기화 및 내역 조회
    wallet_service = WalletService(session)
    result = await wallet_service.get_transaction_history(
        player_id=player_id,
        limit=limit,
        offset=offset
    )
    
    return result 