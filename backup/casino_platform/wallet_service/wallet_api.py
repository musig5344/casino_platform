import logging
from decimal import Decimal
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession

from casino_platform.auth.jwt_handler import JWTBearer, get_current_user
from casino_platform.db.database import get_db_session
from casino_platform.wallet_service.wallet_service import WalletService
from casino_platform.wallet_service.wallet_repository import WalletRepository
from casino_platform.wallet_service.cache_provider import CacheProvider
from casino_platform.dependencies.redis import get_redis_client

logger = logging.getLogger(__name__)

# API 라우터 생성
router = APIRouter(
    prefix="/wallet",
    tags=["지갑"],
    dependencies=[Depends(JWTBearer())],
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "권한 부족"},
        500: {"description": "서버 오류"}
    }
)

# 요청/응답 모델 정의
class BalanceResponse(BaseModel):
    """잔액 조회 응답 모델"""
    player_id: str
    balance: Decimal
    currency: str
    updated_at: str

class CreditRequest(BaseModel):
    """입금 요청 모델"""
    amount: Decimal = Field(..., gt=0)
    description: Optional[str] = None
    reference_id: Optional[str] = None
    
    @validator("amount")
    def validate_amount(cls, v):
        """금액 검증"""
        if v <= 0:
            raise ValueError("입금액은 0보다 커야 합니다")
        return v

class DebitRequest(BaseModel):
    """출금 요청 모델"""
    amount: Decimal = Field(..., gt=0)
    description: Optional[str] = None
    game_id: Optional[str] = None
    reference_id: Optional[str] = None
    
    @validator("amount")
    def validate_amount(cls, v):
        """금액 검증"""
        if v <= 0:
            raise ValueError("출금액은 0보다 커야 합니다")
        return v

class TransactionResponse(BaseModel):
    """트랜잭션 응답 모델"""
    transaction_id: str
    amount: Decimal
    transaction_type: str
    balance_after: Decimal
    currency: str
    description: Optional[str]
    created_at: str

class PaginationInfo(BaseModel):
    """페이지네이션 정보"""
    page: int
    page_size: int
    total_items: int
    total_pages: int

class TransactionHistoryResponse(BaseModel):
    """트랜잭션 내역 응답 모델"""
    transactions: list[TransactionResponse]
    pagination: PaginationInfo

# 의존성 주입
async def get_wallet_service(
    db: AsyncSession = Depends(get_db_session),
    redis = Depends(get_redis_client)
) -> WalletService:
    """지갑 서비스 의존성"""
    wallet_repo = WalletRepository(db)
    cache_provider = CacheProvider(redis)
    return WalletService(wallet_repo, cache_provider)

# API 엔드포인트
@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    wallet_service: WalletService = Depends(get_wallet_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    현재 사용자의 지갑 잔액 조회
    """
    try:
        player_id = user["id"]
        balance = await wallet_service.get_player_balance(player_id)
        return balance
    except ValueError as e:
        logger.warning(f"잔액 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"잔액 조회 중 서버 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 오류가 발생했습니다"
        )

@router.post("/credit", response_model=BalanceResponse)
async def credit_wallet(
    request: CreditRequest,
    wallet_service: WalletService = Depends(get_wallet_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    현재 사용자 지갑에 입금
    """
    try:
        player_id = user["id"]
        result = await wallet_service.credit(
            player_id, 
            request.amount, 
            description=request.description, 
            reference_id=request.reference_id
        )
        return result
    except ValueError as e:
        logger.warning(f"입금 실패: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"입금 중 서버 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 오류가 발생했습니다"
        )

@router.post("/debit", response_model=BalanceResponse)
async def debit_wallet(
    request: DebitRequest,
    wallet_service: WalletService = Depends(get_wallet_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    현재 사용자 지갑에서 출금
    """
    try:
        player_id = user["id"]
        result = await wallet_service.debit(
            player_id, 
            request.amount, 
            description=request.description, 
            game_id=request.game_id, 
            reference_id=request.reference_id
        )
        return result
    except ValueError as e:
        # 잔액 부족 등의 검증 오류
        logger.warning(f"출금 실패: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"출금 중 서버 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 오류가 발생했습니다"
        )

@router.get("/transactions", response_model=TransactionHistoryResponse)
async def get_transactions(
    page: int = 1,
    page_size: int = 20,
    wallet_service: WalletService = Depends(get_wallet_service),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    현재 사용자의 트랜잭션 내역 조회
    """
    try:
        player_id = user["id"]
        history = await wallet_service.get_transaction_history(
            player_id, 
            page=page, 
            page_size=page_size
        )
        return history
    except Exception as e:
        logger.error(f"트랜잭션 내역 조회 중 서버 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 오류가 발생했습니다"
        ) 