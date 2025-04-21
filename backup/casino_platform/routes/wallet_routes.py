import uuid
from decimal import Decimal
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from casino_platform.dependencies import get_wallet_service, validate_token
from casino_platform.security import get_current_player_id

router = APIRouter(
    prefix="/api",
    tags=["wallet"],
    dependencies=[Depends(validate_token)]
)

class BalanceResponse(BaseModel):
    player_id: str
    balance: str
    currency: str
    last_updated: Optional[str] = None
    cache_hit: bool = False

class TransactionRequest(BaseModel):
    amount: str = Field(..., description="트랜잭션 금액")
    transaction_id: Optional[str] = Field(None, description="트랜잭션 ID (없으면 자동 생성)")

class TransactionResponse(BaseModel):
    player_id: str
    balance: str
    currency: str
    last_updated: Optional[str] = None
    transaction_id: str

@router.get("/balance", response_model=BalanceResponse)
async def get_balance(request: Request, player_id: str = Depends(get_current_player_id)):
    """
    플레이어 잔액 조회 API
    
    캐시를 통한 최적화가 적용됨
    """
    wallet_service = await get_wallet_service(request)
    
    try:
        balance_data, cache_hit = await wallet_service.get_balance(player_id)
        response = BalanceResponse(
            player_id=balance_data["player_id"],
            balance=balance_data["balance"],
            currency=balance_data["currency"],
            last_updated=balance_data["last_updated"],
            cache_hit=cache_hit
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"잔액 조회 중 오류 발생: {str(e)}")

@router.post("/credit", response_model=TransactionResponse)
async def credit_wallet(
    request: Request,
    transaction: TransactionRequest,
    player_id: str = Depends(get_current_player_id)
):
    """
    플레이어 계정 입금 API
    
    캐시 자동 업데이트됨
    """
    wallet_service = await get_wallet_service(request)
    
    try:
        amount = Decimal(transaction.amount)
        tx_id = transaction.transaction_id or str(uuid.uuid4())
        
        result = await wallet_service.credit(player_id, amount, tx_id)
        
        return TransactionResponse(
            player_id=result["player_id"],
            balance=result["balance"],
            currency=result["currency"],
            last_updated=result["last_updated"],
            transaction_id=tx_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"입금 처리 중 오류 발생: {str(e)}")

@router.post("/debit", response_model=TransactionResponse)
async def debit_wallet(
    request: Request,
    transaction: TransactionRequest,
    player_id: str = Depends(get_current_player_id)
):
    """
    플레이어 계정 출금 API
    
    캐시 자동 업데이트됨
    """
    wallet_service = await get_wallet_service(request)
    
    try:
        amount = Decimal(transaction.amount)
        tx_id = transaction.transaction_id or str(uuid.uuid4())
        
        result = await wallet_service.debit(player_id, amount, tx_id)
        
        return TransactionResponse(
            player_id=result["player_id"],
            balance=result["balance"],
            currency=result["currency"],
            last_updated=result["last_updated"],
            transaction_id=tx_id
        )
    except ValueError as e:
        if "잔액 부족" in str(e):
            raise HTTPException(status_code=400, detail=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"출금 처리 중 오류 발생: {str(e)}") 