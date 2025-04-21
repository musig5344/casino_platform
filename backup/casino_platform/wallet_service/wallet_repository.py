import logging
import uuid
from decimal import Decimal
from typing import Dict, Any, List, Tuple, Optional

from sqlalchemy import select, func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from casino_platform.models.wallet import Wallet, Transaction

logger = logging.getLogger(__name__)

class WalletRepository:
    """
    지갑 리포지토리 - 데이터베이스 액세스
    """
    
    def __init__(self, session: AsyncSession):
        """
        지갑 리포지토리 초기화
        
        Args:
            session: 데이터베이스 세션
        """
        self.session = session
    
    async def get_player_balance(self, player_id: str) -> Dict[str, Any]:
        """
        플레이어 잔액 조회
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Dict[str, Any]: 지갑 정보
            
        Raises:
            ValueError: 플레이어 지갑이 존재하지 않을 경우
        """
        # 지갑 조회 쿼리
        query = select(Wallet).where(Wallet.player_id == player_id)
        result = await self.session.execute(query)
        
        try:
            # 결과 추출
            wallet = result.scalar_one()
            
            # 지갑 정보 반환
            return {
                "wallet_id": wallet.id,
                "player_id": wallet.player_id,
                "balance": wallet.balance,
                "currency": wallet.currency,
                "created_at": wallet.created_at.isoformat(),
                "updated_at": wallet.updated_at.isoformat()
            }
            
        except NoResultFound:
            # 지갑이 존재하지 않는 경우
            raise ValueError(f"플레이어 {player_id}의 지갑이 존재하지 않습니다")
    
    async def credit(
        self, 
        player_id: str, 
        amount: Decimal,
        transaction_id: str,
        description: Optional[str] = None,
        reference_id: Optional[str] = None,
        game_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        플레이어 계정에 금액 입금
        
        Args:
            player_id: 플레이어 ID
            amount: 입금액
            transaction_id: 트랜잭션 ID
            description: 설명
            reference_id: 참조 ID
            game_id: 게임 ID
            
        Returns:
            Dict[str, Any]: 업데이트된 지갑 정보와 트랜잭션 ID
            
        Raises:
            ValueError: 플레이어 지갑이 존재하지 않을 경우
        """
        # 지갑 조회 쿼리
        query = select(Wallet).where(Wallet.player_id == player_id)
        result = await self.session.execute(query)
        
        try:
            # 결과 추출
            wallet = result.scalar_one()
            
            # 잔액 업데이트
            new_balance = wallet.balance + amount
            wallet.balance = new_balance
            
            # 트랜잭션 기록
            transaction = Transaction(
                id=str(uuid.uuid4()),
                wallet_id=wallet.id,
                transaction_id=transaction_id,
                type="credit",
                amount=amount,
                balance_after=new_balance,
                description=description,
                reference_id=reference_id,
                game_id=game_id
            )
            self.session.add(transaction)
            
            # 지갑 정보 반환
            return {
                "wallet_id": wallet.id,
                "player_id": wallet.player_id,
                "balance": wallet.balance,
                "currency": wallet.currency,
                "created_at": wallet.created_at.isoformat(),
                "updated_at": wallet.updated_at.isoformat(),
                "transaction_id": transaction_id
            }
            
        except NoResultFound:
            # 지갑이 존재하지 않는 경우
            raise ValueError(f"플레이어 {player_id}의 지갑이 존재하지 않습니다")
    
    async def debit(
        self, 
        player_id: str, 
        amount: Decimal,
        transaction_id: str,
        description: Optional[str] = None,
        reference_id: Optional[str] = None,
        game_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        플레이어 계정에서 금액 출금
        
        Args:
            player_id: 플레이어 ID
            amount: 출금액
            transaction_id: 트랜잭션 ID
            description: 설명
            reference_id: 참조 ID
            game_id: 게임 ID
            
        Returns:
            Dict[str, Any]: 업데이트된 지갑 정보와 트랜잭션 ID
            
        Raises:
            ValueError: 플레이어 지갑이 존재하지 않을 경우 또는 잔액 부족
        """
        # 지갑 조회 쿼리
        query = select(Wallet).where(Wallet.player_id == player_id)
        result = await self.session.execute(query)
        
        try:
            # 결과 추출
            wallet = result.scalar_one()
            
            # 잔액 검증
            if wallet.balance < amount:
                raise ValueError(f"잔액 부족: 현재 {wallet.balance}, 요청 {amount}")
            
            # 잔액 업데이트
            new_balance = wallet.balance - amount
            wallet.balance = new_balance
            
            # 트랜잭션 기록
            transaction = Transaction(
                id=str(uuid.uuid4()),
                wallet_id=wallet.id,
                transaction_id=transaction_id,
                type="debit",
                amount=amount,
                balance_after=new_balance,
                description=description,
                reference_id=reference_id,
                game_id=game_id
            )
            self.session.add(transaction)
            
            # 지갑 정보 반환
            return {
                "wallet_id": wallet.id,
                "player_id": wallet.player_id,
                "balance": wallet.balance,
                "currency": wallet.currency,
                "created_at": wallet.created_at.isoformat(),
                "updated_at": wallet.updated_at.isoformat(),
                "transaction_id": transaction_id
            }
            
        except NoResultFound:
            # 지갑이 존재하지 않는 경우
            raise ValueError(f"플레이어 {player_id}의 지갑이 존재하지 않습니다")
    
    async def get_transaction_history(
        self, 
        player_id: str, 
        limit: int = 10, 
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        플레이어 트랜잭션 내역 조회
        
        Args:
            player_id: 플레이어 ID
            limit: 조회할 항목 수
            offset: 조회 시작 오프셋
            
        Returns:
            Tuple[List[Dict[str, Any]], int]: 트랜잭션 목록과 총 항목 수
            
        Raises:
            ValueError: 플레이어 지갑이 존재하지 않을 경우
        """
        # 지갑 조회 쿼리
        wallet_query = select(Wallet).where(Wallet.player_id == player_id)
        wallet_result = await self.session.execute(wallet_query)
        
        try:
            # 지갑 정보 추출
            wallet = wallet_result.scalar_one()
            
            # 트랜잭션 내역 조회 쿼리
            transaction_query = (
                select(Transaction)
                .where(Transaction.wallet_id == wallet.id)
                .order_by(Transaction.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            transaction_result = await self.session.execute(transaction_query)
            transactions = transaction_result.scalars().all()
            
            # 총 항목 수 조회 쿼리
            count_query = (
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.wallet_id == wallet.id)
            )
            count_result = await self.session.execute(count_query)
            total_count = count_result.scalar_one()
            
            # 트랜잭션 목록 반환
            history = []
            for transaction in transactions:
                history.append({
                    "id": transaction.id,
                    "transaction_id": transaction.transaction_id,
                    "type": transaction.type,
                    "amount": transaction.amount,
                    "balance_after": transaction.balance_after,
                    "description": transaction.description,
                    "reference_id": transaction.reference_id,
                    "game_id": transaction.game_id,
                    "created_at": transaction.created_at.isoformat()
                })
            
            return history, total_count
            
        except NoResultFound:
            # 지갑이 존재하지 않는 경우
            raise ValueError(f"플레이어 {player_id}의 지갑이 존재하지 않습니다") 