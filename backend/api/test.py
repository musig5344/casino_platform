from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
import uuid
from datetime import datetime, timedelta
from pydantic import BaseModel
from decimal import Decimal
import random

from backend.database import get_db
from backend.models.wallet import Transaction as TransactionModel, Wallet as WalletModel
from backend.models.user import Player as PlayerModel
from backend.utils.auth import get_admin_user

router = APIRouter(prefix="/test", tags=["Test"])

class MockTransactionRequest(BaseModel):
    transaction_id: str
    player_id: str
    amount: float
    transaction_type: str = "deposit"
    source: str = "test"
    metadata: Optional[Dict[str, Any]] = None

class BulkTransactionRequest(BaseModel):
    player_id: str
    transaction_count: int = 5
    min_amount: float = 1000000.0  # 기본 1백만
    max_amount: float = 1000000000.0  # 기본 10억
    transaction_type: str = "deposit"
    source: str = "bulk_test"
    days_ago: int = 0  # 과거 날짜 지정 (0=오늘)

@router.post("/mock-transaction", status_code=status.HTTP_201_CREATED)
async def create_mock_transaction(
    transaction_data: MockTransactionRequest,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    테스트용 모의 트랜잭션을 생성합니다 (관리자 전용).
    """
    try:
        player_id = transaction_data.player_id
        
        # 1. 플레이어 존재 확인 및 생성
        player = db.query(PlayerModel).filter(PlayerModel.id == player_id).first()
        
        # 플레이어가 없으면 생성
        if not player:
            # Player 모델에 맞게 필드 조정
            player = PlayerModel(
                id=player_id,
                first_name=transaction_data.metadata.get("first_name", "Test"),
                last_name=transaction_data.metadata.get("last_name", "User"),
                country=transaction_data.metadata.get("country", "KR"),
                currency=transaction_data.metadata.get("currency", "KRW")
            )
            db.add(player)
            db.commit()
            db.refresh(player)
            
        # 2. 지갑 존재 확인 및 생성
        wallet = db.query(WalletModel).filter(WalletModel.player_id == player_id).first()
        
        # 지갑이 없으면 생성
        if not wallet:
            wallet = WalletModel(
                player_id=player_id,
                balance=Decimal('10000'),  # 기본 테스트 잔액
                currency=player.currency  # 플레이어의 통화 사용
            )
            db.add(wallet)
            db.commit()
            db.refresh(wallet)
        
        # 3. 금액을 Decimal로 변환
        amount = Decimal(str(transaction_data.amount))
        
        # 4. 트랜잭션 객체 생성
        transaction = TransactionModel(
            transaction_id=transaction_data.transaction_id,
            player_id=player_id,
            amount=amount,  # Decimal 타입으로 변환된 금액 사용
            transaction_type=transaction_data.transaction_type,
            created_at=datetime.now(),
            transaction_metadata={
                "source": transaction_data.source,
                "is_test": True,
                **(transaction_data.metadata or {})  # 사용자가 제공한 메타데이터 병합
            }
        )
        
        # 5. 지갑 잔액 업데이트
        if transaction.transaction_type == "deposit":
            wallet.balance += amount
        elif transaction.transaction_type == "withdrawal":
            if wallet.balance < amount:
                wallet.balance = Decimal('0')
            else:
                wallet.balance -= amount
        
        db.add(transaction)
        db.commit()
        
        return {
            "status": "success",
            "message": f"Mock transaction {transaction.transaction_id} created successfully",
            "transaction": {
                "id": transaction.id,
                "transaction_id": transaction.transaction_id,
                "player_id": transaction.player_id,
                "amount": float(transaction.amount),  # JSON 직렬화를 위해 float로 변환
                "transaction_type": transaction.transaction_type,
                "created_at": transaction.created_at.isoformat(),
                "wallet_balance": float(wallet.balance)  # JSON 직렬화를 위해 float로 변환
            }
        }
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create mock transaction: {str(e)}"
        )

@router.post("/bulk-transactions", status_code=status.HTTP_201_CREATED)
async def create_bulk_transactions(
    request: BulkTransactionRequest,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    대량의 테스트 트랜잭션을 생성합니다 (관리자 전용).
    이 함수는 특정 플레이어에 대해 다수의 고액 트랜잭션을 생성하여 알림 생성과 위험 프로필 업데이트를 테스트합니다.
    """
    try:
        player_id = request.player_id
        
        # 1. 플레이어 존재 확인 및 생성
        player = db.query(PlayerModel).filter(PlayerModel.id == player_id).first()
        
        # 플레이어가 없으면 생성
        if not player:
            # Player 모델에 맞게 필드 조정
            player = PlayerModel(
                id=player_id,
                first_name="Bulk",
                last_name="User",
                country="KR",
                currency="KRW"
            )
            db.add(player)
            db.commit()
            db.refresh(player)
            
        # 2. 지갑 존재 확인 및 생성
        wallet = db.query(WalletModel).filter(WalletModel.player_id == player_id).first()
        
        # 지갑이 없으면 생성
        if not wallet:
            wallet = WalletModel(
                player_id=player_id,
                balance=Decimal('1000000000'),  # 10억 기본 잔액
                currency=player.currency  # 플레이어의 통화 사용
            )
            db.add(wallet)
            db.commit()
            db.refresh(wallet)
        
        created_transactions = []
        
        # 트랜잭션 생성 기준 시간 (과거 날짜 지정 가능)
        base_time = datetime.now() - timedelta(days=request.days_ago)
        
        # 요청된 수의 트랜잭션 생성
        for i in range(request.transaction_count):
            # 랜덤 금액 생성
            amount = Decimal(str(random.uniform(request.min_amount, request.max_amount)))
            
            # 트랜잭션 시간 - 기준 시간에서 랜덤하게 조금씩 변경
            tx_time = base_time - timedelta(
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
                seconds=random.randint(0, 59)
            )
            
            # 트랜잭션 ID 생성
            transaction_id = str(uuid.uuid4())
            
            # 트랜잭션 객체 생성
            transaction = TransactionModel(
                transaction_id=transaction_id,
                player_id=player_id,
                amount=amount,
                transaction_type=request.transaction_type,
                created_at=tx_time,
                transaction_metadata={
                    "source": request.source,
                    "is_test": True,
                    "bulk_index": i + 1
                }
            )
            
            # 지갑 잔액 업데이트 (필요한 경우)
            if request.transaction_type == "deposit":
                wallet.balance += amount
            elif request.transaction_type == "withdrawal":
                if wallet.balance < amount:
                    wallet.balance = Decimal('0')
                else:
                    wallet.balance -= amount
            
            db.add(transaction)
            db.flush()  # flush로 ID 할당 확인
            
            created_transactions.append({
                "id": transaction.id,
                "transaction_id": transaction.transaction_id,
                "player_id": transaction.player_id,
                "amount": float(transaction.amount),
                "transaction_type": transaction.transaction_type,
                "created_at": transaction.created_at.isoformat()
            })
        
        db.commit()
        
        return {
            "status": "success",
            "message": f"Successfully created {request.transaction_count} bulk transactions",
            "wallet_balance": float(wallet.balance),
            "transactions": created_transactions
        }
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create bulk transactions: {str(e)}"
        ) 