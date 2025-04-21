from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import text
from typing import List, Optional, Tuple, Dict, Any
import uuid

from casino_platform.models.wallet import Wallet, Transaction
from casino_platform.models.users import User
from casino_platform.schemas.wallet import TransactionType, TransactionStatus, Currency

async def get_user_wallet(db: AsyncSession, user_id: int) -> Optional[Wallet]:
    """사용자 ID로 지갑을 조회합니다."""
    result = await db.execute(select(Wallet).where(Wallet.user_id == user_id))
    wallet = result.scalars().first()
    return wallet

async def create_wallet(db: AsyncSession, user_id: int, currency: str = "KRW") -> Wallet:
    """새 지갑을 생성합니다."""
    wallet = Wallet(user_id=user_id, balance=0.0, currency=currency)
    db.add(wallet)
    await db.commit()
    await db.refresh(wallet)
    return wallet

async def get_or_create_wallet(db: AsyncSession, user_id: int, currency: str = "KRW") -> Wallet:
    """사용자의 지갑을 조회하거나 없으면 생성합니다."""
    wallet = await get_user_wallet(db, user_id=user_id)
    if not wallet:
        wallet = await create_wallet(db, user_id=user_id, currency=currency)
    return wallet

async def get_transaction(db: AsyncSession, transaction_id: int) -> Optional[Transaction]:
    """거래 ID로 거래를 조회합니다."""
    result = await db.execute(select(Transaction).where(Transaction.id == transaction_id))
    transaction = result.scalars().first()
    return transaction

async def get_transactions(
    db: AsyncSession, wallet_id: int, skip: int = 0, limit: int = 100
) -> List[Transaction]:
    """지갑 ID로 거래 내역을 조회합니다."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.wallet_id == wallet_id)
        .order_by(Transaction.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    transactions = result.scalars().all()
    return transactions

async def get_recent_transactions(
    db: AsyncSession, wallet_id: int, limit: int = 10
) -> List[Transaction]:
    """지갑의 최근 거래 내역을 조회합니다."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.wallet_id == wallet_id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
    )
    transactions = result.scalars().all()
    return transactions

async def get_user_preferences(db: AsyncSession, user_id: int) -> Dict[str, Any]:
    """사용자의 환경 설정을 조회합니다."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == user_id)
    )
    user = result.scalars().first()
    
    if not user or not user.preferences:
        return {
            "language": "ko",
            "currency": "KRW",
            "timezone": "UTC"
        }
    
    return {
        "language": user.preferences.language.value,
        "currency": user.preferences.currency.value,
        "timezone": user.preferences.timezone.value
    }

async def create_transaction(
    db: AsyncSession,
    wallet_id: int,
    amount: float,
    transaction_type: TransactionType,
    description: Optional[str] = None,
    status: TransactionStatus = TransactionStatus.COMPLETED,
    currency: Optional[str] = None,
    reference_id: Optional[str] = None,
    game_id: Optional[str] = None,
) -> Transaction:
    """새 거래를 생성합니다."""
    async with db.begin():
        # FOR UPDATE로 지갑 잠금 (비관적 잠금)
        stmt = select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        result = await db.execute(stmt)
        wallet = result.scalars().first()
        
        if not wallet:
            raise ValueError("지갑을 찾을 수 없습니다")
        
        # 트랜잭션 통화가 지정되지 않은 경우 지갑 통화 사용
        if not currency:
            currency = wallet.currency
        
        # 통화가 지갑과 다른 경우 변환 필요 (실제 구현에서는 환율 API 사용)
        # 여기서는 간단히 1:1 비율로 가정
        converted_amount = amount
        if currency != wallet.currency:
            # TODO: 실제 환율 API를 통한 변환 로직 구현
            # converted_amount = await convert_currency(amount, currency, wallet.currency)
            pass
        
        # 지갑 잔액 업데이트
        if transaction_type in [TransactionType.DEPOSIT, TransactionType.WIN, TransactionType.BONUS, TransactionType.REFUND]:
            wallet.balance += converted_amount
        elif transaction_type in [TransactionType.WITHDRAWAL, TransactionType.BET]:
            if wallet.balance < converted_amount:
                raise ValueError("잔액이 부족합니다")
            wallet.balance -= converted_amount
        
        # 낙관적 잠금을 위한 버전 증가
        wallet.version += 1
        
        # 거래 생성
        transaction = Transaction(
            wallet_id=wallet_id,
            type=transaction_type,
            status=status,
            amount=amount,
            currency=currency,
            balance_after=wallet.balance,
            description=description,
            reference_id=reference_id or str(uuid.uuid4()),
            game_id=game_id,
        )
        db.add(transaction)
        
        # 한 번에 커밋
        await db.commit()
        await db.refresh(transaction)
        
        return transaction

async def create_deposit(
    db: AsyncSession, 
    user_id: int, 
    amount: float, 
    description: Optional[str] = None,
    currency: str = "KRW",
    reference_id: Optional[str] = None,
) -> Transaction:
    """입금 거래를 생성합니다."""
    wallet = await get_or_create_wallet(db, user_id=user_id)
    return await create_transaction(
        db=db,
        wallet_id=wallet.id,
        amount=amount,
        transaction_type=TransactionType.DEPOSIT,
        description=description,
        currency=currency,
        reference_id=reference_id,
    )

async def create_withdrawal(
    db: AsyncSession, 
    user_id: int, 
    amount: float, 
    description: Optional[str] = None,
    currency: str = "KRW",
    reference_id: Optional[str] = None,
) -> Transaction:
    """출금 거래를 생성합니다."""
    wallet = await get_user_wallet(db, user_id=user_id)
    if not wallet:
        raise ValueError("지갑을 찾을 수 없습니다")
    
    return await create_transaction(
        db=db,
        wallet_id=wallet.id,
        amount=amount,
        transaction_type=TransactionType.WITHDRAWAL,
        description=description,
        currency=currency,
        reference_id=reference_id,
    )

async def create_bet(
    db: AsyncSession, 
    user_id: int, 
    amount: float, 
    description: Optional[str] = None,
    currency: str = "KRW",
    game_id: Optional[str] = None,
    reference_id: Optional[str] = None,
) -> Transaction:
    """베팅 거래를 생성합니다."""
    wallet = await get_user_wallet(db, user_id=user_id)
    if not wallet:
        raise ValueError("지갑을 찾을 수 없습니다")
    
    return await create_transaction(
        db=db,
        wallet_id=wallet.id,
        amount=amount,
        transaction_type=TransactionType.BET,
        description=description,
        currency=currency,
        reference_id=reference_id,
        game_id=game_id,
    )

async def create_win(
    db: AsyncSession, 
    user_id: int, 
    amount: float, 
    description: Optional[str] = None,
    currency: str = "KRW",
    game_id: Optional[str] = None,
    reference_id: Optional[str] = None,
) -> Transaction:
    """승리 거래를 생성합니다."""
    wallet = await get_user_wallet(db, user_id=user_id)
    if not wallet:
        raise ValueError("지갑을 찾을 수 없습니다")
    
    return await create_transaction(
        db=db,
        wallet_id=wallet.id,
        amount=amount,
        transaction_type=TransactionType.WIN,
        description=description,
        currency=currency,
        reference_id=reference_id,
        game_id=game_id,
    ) 