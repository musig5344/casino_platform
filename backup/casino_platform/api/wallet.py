import logging
import uuid
from decimal import Decimal
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession

from casino_platform.wallet_service import WalletService
from casino_platform.dependencies import get_wallet_service
from casino_platform.auth.jwt import get_current_user
from casino_platform.database import get_session
from casino_platform.models.user import User
from casino_platform.api.deps import get_db
from casino_platform.crud import wallet as wallet_crud
from casino_platform.schemas.wallet import (
    TransactionCreate,
    TransactionResponse,
    WalletResponse,
    WalletBalance,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/wallet",
    tags=["지갑"]
)

class BalanceResponse(BaseModel):
    wallet_id: str
    player_id: str
    balance: Decimal
    currency: str
    created_at: str
    updated_at: str

class CreateWalletRequest(BaseModel):
    currency: str = "KRW"

class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    transaction_id: Optional[str] = None
    description: Optional[str] = None
    reference_id: Optional[str] = None

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('금액은 0보다 커야 합니다')
        return v

class WithdrawRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    transaction_id: Optional[str] = None
    description: Optional[str] = None
    reference_id: Optional[str] = None

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('금액은 0보다 커야 합니다')
        return v

class TransferRequest(BaseModel):
    to_player_id: str
    amount: Decimal = Field(..., gt=0)
    description: Optional[str] = None

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('금액은 0보다 커야 합니다')
        return v

class BetRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    game_id: str
    transaction_id: Optional[str] = None
    reference_id: Optional[str] = None

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('금액은 0보다 커야 합니다')
        return v

class WinRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    game_id: str
    transaction_id: Optional[str] = None
    reference_id: Optional[str] = None

    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('금액은 0보다 커야 합니다')
        return v

class Transaction(BaseModel):
    id: str
    transaction_id: str
    type: str
    amount: Decimal
    balance_after: Decimal
    description: Optional[str] = None
    reference_id: Optional[str] = None
    game_id: Optional[str] = None
    created_at: str

class TransactionHistoryResponse(BaseModel):
    player_id: str
    transactions: List[Transaction]
    pagination: dict

@router.get("/balance", response_model=WalletBalance)
async def get_wallet_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    현재 사용자의 지갑 잔액을 조회합니다.
    """
    wallet = await wallet_crud.get_user_wallet(db, user_id=current_user.id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="지갑을 찾을 수 없습니다",
        )
    return {"balance": wallet.balance}

@router.get("/", response_model=WalletResponse)
async def get_wallet(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    현재 사용자의 지갑 정보와 최근 거래 내역을 조회합니다.
    """
    wallet = await wallet_crud.get_user_wallet(db, user_id=current_user.id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="지갑을 찾을 수 없습니다",
        )
    
    transactions = await wallet_crud.get_recent_transactions(db, wallet_id=wallet.id, limit=10)
    return {
        "wallet_id": wallet.id,
        "user_id": wallet.user_id,
        "balance": wallet.balance,
        "recent_transactions": transactions,
    }

@router.get("/transactions", response_model=List[TransactionResponse])
async def get_transactions(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    현재 사용자의 거래 내역을 조회합니다.
    """
    wallet = await wallet_crud.get_user_wallet(db, user_id=current_user.id)
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="지갑을 찾을 수 없습니다",
        )
    
    transactions = await wallet_crud.get_transactions(
        db, wallet_id=wallet.id, skip=skip, limit=limit
    )
    return transactions

@router.post("/deposit", response_model=TransactionResponse)
async def deposit_funds(
    transaction: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자 지갑에 자금을 입금합니다.
    """
    if transaction.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="입금 금액은 0보다 커야 합니다",
        )
    
    result = await wallet_crud.create_deposit(
        db, user_id=current_user.id, amount=transaction.amount, description=transaction.description
    )
    return result

@router.post("/withdraw", response_model=TransactionResponse)
async def withdraw_funds(
    transaction: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자 지갑에서 자금을 출금합니다.
    """
    if transaction.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="출금 금액은 0보다 커야 합니다",
        )
    
    try:
        result = await wallet_crud.create_withdrawal(
            db, user_id=current_user.id, amount=transaction.amount, description=transaction.description
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

@router.post("/create", response_model=BalanceResponse)
async def create_wallet(
    request: CreateWalletRequest,
    current_user: User = Depends(get_current_user), 
    session = Depends(get_session)
):
    """
    현재 사용자를 위한 새 지갑 생성
    """
    try:
        wallet_service = WalletService(session)
        return await wallet_service.create_wallet(current_user.id, request.currency)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"지갑 생성 실패: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="지갑 생성 중 오류가 발생했습니다")

@router.post("/transfer", response_model=dict)
async def transfer(
    request: TransferRequest,
    current_user: User = Depends(get_current_user), 
    session = Depends(get_session)
):
    """
    다른 플레이어에게 자금 이체
    """
    try:
        # 자신에게 이체하는지 확인
        if current_user.id == request.to_player_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="자신에게 이체할 수 없습니다")
            
        wallet_service = WalletService(session)
        return await wallet_service.transfer(
            from_player_id=current_user.id,
            to_player_id=request.to_player_id,
            amount=request.amount,
            description=request.description
        )
    except ValueError as e:
        if "잔액 부족" in str(e):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="잔액이 부족합니다")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"이체 실패: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="이체 처리 중 오류가 발생했습니다")

@router.post("/bet", response_model=BalanceResponse)
async def place_bet(
    request: BetRequest,
    current_user: User = Depends(get_current_user), 
    session = Depends(get_session)
):
    """
    게임에 베팅
    """
    try:
        wallet_service = WalletService(session)
        return await wallet_service.place_bet(
            player_id=current_user.id,
            amount=request.amount,
            game_id=request.game_id,
            transaction_id=request.transaction_id,
            reference_id=request.reference_id
        )
    except ValueError as e:
        if "잔액 부족" in str(e):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="잔액이 부족합니다")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"베팅 실패: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="베팅 처리 중 오류가 발생했습니다")

@router.post("/win", response_model=BalanceResponse)
async def win_payout(
    request: WinRequest,
    current_user: User = Depends(get_current_user), 
    session = Depends(get_session)
):
    """
    게임 승리 정산
    """
    try:
        wallet_service = WalletService(session)
        return await wallet_service.win_payout(
            player_id=current_user.id,
            amount=request.amount,
            game_id=request.game_id,
            transaction_id=request.transaction_id,
            reference_id=request.reference_id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"정산 실패: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="정산 처리 중 오류가 발생했습니다")

@router.get("/transactions", response_model=TransactionHistoryResponse)
async def get_transaction_history(
    limit: int = 10,
    offset: int = 0,
    current_user: User = Depends(get_current_user), 
    session = Depends(get_session)
):
    """
    사용자의 트랜잭션 내역 조회
    """
    try:
        wallet_service = WalletService(session)
        return await wallet_service.get_transaction_history(
            player_id=current_user.id,
            limit=limit,
            offset=offset
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"트랜잭션 내역 조회 실패: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="트랜잭션 내역 조회 중 오류가 발생했습니다") 