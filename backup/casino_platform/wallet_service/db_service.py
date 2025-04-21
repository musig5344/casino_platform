import logging
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

class DatabaseService:
    """
    데이터베이스 서비스
    
    지갑 관련 데이터베이스 작업 처리
    """
    
    def __init__(self, db_session: AsyncSession):
        """
        데이터베이스 서비스 초기화
        
        Args:
            db_session: SQLAlchemy 비동기 세션
        """
        self.db = db_session
    
    async def get_player_balance(self, player_id: str) -> Optional[Dict[str, Any]]:
        """
        플레이어 잔액 조회
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Optional[Dict[str, Any]]: 잔액 정보 또는 None
        """
        try:
            query = text("""
                SELECT 
                    player_id, 
                    balance, 
                    currency, 
                    updated_at as last_updated
                FROM 
                    player_wallets 
                WHERE 
                    player_id = :player_id
            """)
            
            result = await self.db.execute(query, {"player_id": player_id})
            wallet_data = result.fetchone()
            
            if not wallet_data:
                logger.warning(f"플레이어 {player_id}의 지갑 정보가 없습니다.")
                return None
            
            # 결과를 딕셔너리로 변환
            return {
                "player_id": wallet_data.player_id,
                "balance": wallet_data.balance,
                "currency": wallet_data.currency,
                "last_updated": wallet_data.last_updated.isoformat() if wallet_data.last_updated else None
            }
            
        except Exception as e:
            logger.error(f"잔액 조회 중 오류 발생: {e}")
            raise
    
    async def add_debit_transaction(
        self, 
        player_id: str, 
        amount: Decimal, 
        transaction_id: str
    ) -> Dict[str, Any]:
        """
        출금 트랜잭션 추가
        
        Args:
            player_id: 플레이어 ID
            amount: 출금액
            transaction_id: 트랜잭션 ID
            
        Returns:
            Dict[str, Any]: 업데이트된 잔액 정보
        """
        # 음수 금액 체크
        if amount <= 0:
            raise ValueError("출금 금액은 0보다 커야 합니다.")
        
        try:
            # 플레이어 잔액 조회
            balance_info = await self.get_player_balance(player_id)
            if not balance_info:
                raise ValueError(f"플레이어 {player_id}의 지갑을 찾을 수 없습니다.")
            
            current_balance = Decimal(balance_info["balance"])
            
            # 잔액 부족 확인
            if current_balance < amount:
                logger.warning(f"잔액 부족: 플레이어 {player_id}, 현재 잔액: {current_balance}, 출금 요청: {amount}")
                raise ValueError("잔액이 부족합니다")
            
            # 트랜잭션 시작
            async with self.db.begin():
                # 출금 처리 SQL
                debit_query = text("""
                    UPDATE player_wallets
                    SET 
                        balance = balance - :amount,
                        updated_at = NOW()
                    WHERE 
                        player_id = :player_id
                    RETURNING 
                        balance, 
                        currency, 
                        updated_at
                """)
                
                debit_result = await self.db.execute(
                    debit_query, 
                    {"player_id": player_id, "amount": amount}
                )
                
                result_row = debit_result.fetchone()
                if not result_row:
                    raise ValueError(f"플레이어 {player_id}의 지갑 업데이트에 실패했습니다.")
                
                new_balance = result_row.balance
                currency = result_row.currency
                updated_at = result_row.updated_at
                
                # 거래 기록 추가
                tx_query = text("""
                    INSERT INTO wallet_transactions
                    (transaction_id, player_id, amount, type, balance_after, created_at)
                    VALUES
                    (:transaction_id, :player_id, :amount, 'debit', :new_balance, NOW())
                """)
                
                await self.db.execute(
                    tx_query,
                    {
                        "transaction_id": transaction_id,
                        "player_id": player_id,
                        "amount": amount,
                        "new_balance": new_balance
                    }
                )
            
            # 거래 결과 반환
            return {
                "player_id": player_id,
                "balance": new_balance,
                "currency": currency,
                "last_updated": updated_at.isoformat()
            }
            
        except ValueError as e:
            # 잔액 부족 등 예상된 오류는 그대로 전달
            raise
            
        except Exception as e:
            logger.error(f"출금 처리 중 오류 발생: {e}")
            raise
    
    async def add_credit_transaction(
        self, 
        player_id: str, 
        amount: Decimal, 
        transaction_id: str
    ) -> Dict[str, Any]:
        """
        입금 트랜잭션 추가
        
        Args:
            player_id: 플레이어 ID
            amount: 입금액
            transaction_id: 트랜잭션 ID
            
        Returns:
            Dict[str, Any]: 업데이트된 잔액 정보
        """
        # 음수 금액 체크
        if amount <= 0:
            raise ValueError("입금 금액은 0보다 커야 합니다.")
        
        try:
            # 트랜잭션 시작
            async with self.db.begin():
                # 입금 처리 SQL
                credit_query = text("""
                    UPDATE player_wallets
                    SET 
                        balance = balance + :amount,
                        updated_at = NOW()
                    WHERE 
                        player_id = :player_id
                    RETURNING 
                        balance, 
                        currency, 
                        updated_at
                """)
                
                credit_result = await self.db.execute(
                    credit_query, 
                    {"player_id": player_id, "amount": amount}
                )
                
                result_row = credit_result.fetchone()
                if not result_row:
                    # 플레이어 지갑이 없는 경우 새로 생성
                    create_query = text("""
                        INSERT INTO player_wallets
                        (player_id, balance, currency, created_at, updated_at)
                        VALUES
                        (:player_id, :amount, 'USD', NOW(), NOW())
                        RETURNING 
                            balance, 
                            currency, 
                            updated_at
                    """)
                    
                    create_result = await self.db.execute(
                        create_query,
                        {"player_id": player_id, "amount": amount}
                    )
                    
                    result_row = create_result.fetchone()
                
                new_balance = result_row.balance
                currency = result_row.currency
                updated_at = result_row.updated_at
                
                # 거래 기록 추가
                tx_query = text("""
                    INSERT INTO wallet_transactions
                    (transaction_id, player_id, amount, type, balance_after, created_at)
                    VALUES
                    (:transaction_id, :player_id, :amount, 'credit', :new_balance, NOW())
                """)
                
                await self.db.execute(
                    tx_query,
                    {
                        "transaction_id": transaction_id,
                        "player_id": player_id,
                        "amount": amount,
                        "new_balance": new_balance
                    }
                )
            
            # 거래 결과 반환
            return {
                "player_id": player_id,
                "balance": new_balance,
                "currency": currency,
                "last_updated": updated_at.isoformat()
            }
            
        except Exception as e:
            logger.error(f"입금 처리 중 오류 발생: {e}")
            raise 