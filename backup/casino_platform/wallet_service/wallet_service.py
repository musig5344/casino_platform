import logging
import uuid
from decimal import Decimal
from typing import Dict, Any, List, Tuple, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from casino_platform.wallet_service.wallet_repository import WalletRepository
from casino_platform.models.wallet import Wallet, Transaction, TransactionType
from casino_platform.models.user import User

logger = logging.getLogger(__name__)

class WalletService:
    """
    지갑 서비스 - 입금, 출금, 베팅, 정산 등 모든 금액 관련 처리 담당
    """
    
    def __init__(self, session: AsyncSession):
        """
        지갑 서비스 초기화
        
        Args:
            session: 데이터베이스 세션
        """
        self.session = session
        self.repository = WalletRepository(session)
    
    async def get_player_balance(self, player_id: str) -> Dict[str, Any]:
        """
        플레이어 잔액 조회
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Dict[str, Any]: 지갑 정보
            
        Raises:
            HTTPException: 지갑이 존재하지 않을 경우
        """
        try:
            # 지갑 조회
            return await self.repository.get_player_balance(player_id)
            
        except ValueError as e:
            logger.warning(f"잔액 조회 실패: 플레이어 {player_id}, 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )
            
        except Exception as e:
            logger.error(f"잔액 조회 중 예상치 못한 오류 발생: 플레이어 {player_id}, 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="서비스 처리 중 오류가 발생했습니다"
            )
    
    async def credit(
        self, 
        player_id: str, 
        amount: Decimal, 
        transaction_id: Optional[str] = None,
        description: Optional[str] = None,
        reference_id: Optional[str] = None,
        game_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        플레이어 계정에 금액 입금
        
        Args:
            player_id: 플레이어 ID
            amount: 입금액
            transaction_id: 트랜잭션 ID (없을 경우 자동 생성)
            description: 설명
            reference_id: 참조 ID
            game_id: 게임 ID
            
        Returns:
            Dict[str, Any]: 업데이트된 지갑 정보
            
        Raises:
            HTTPException: 입금 처리 중 오류 발생 시
        """
        try:
            # 금액 검증
            if amount <= 0:
                raise ValueError("입금액은 0보다 커야 합니다")
            
            # 트랜잭션 ID 생성 (제공되지 않은 경우)
            if not transaction_id:
                transaction_id = str(uuid.uuid4())
            
            # 입금 처리
            result = await self.repository.credit(
                player_id=player_id,
                amount=amount,
                transaction_id=transaction_id,
                description=description,
                reference_id=reference_id,
                game_id=game_id
            )
            
            return result
            
        except ValueError as e:
            logger.warning(f"입금 실패: 플레이어 {player_id}, 금액 {amount}, 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
            
        except Exception as e:
            logger.error(f"입금 처리 중 예상치 못한 오류 발생: 플레이어 {player_id}, 금액 {amount}, 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="서비스 처리 중 오류가 발생했습니다"
            )
    
    async def debit(
        self, 
        player_id: str, 
        amount: Decimal, 
        transaction_id: Optional[str] = None,
        description: Optional[str] = None,
        reference_id: Optional[str] = None,
        game_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        플레이어 계정에서 금액 출금
        
        Args:
            player_id: 플레이어 ID
            amount: 출금액
            transaction_id: 트랜잭션 ID (없을 경우 자동 생성)
            description: 설명
            reference_id: 참조 ID
            game_id: 게임 ID
            
        Returns:
            Dict[str, Any]: 업데이트된 지갑 정보
            
        Raises:
            HTTPException: 출금 처리 중 오류 발생 시
        """
        try:
            # 금액 검증
            if amount <= 0:
                raise ValueError("출금액은 0보다 커야 합니다")
            
            # 트랜잭션 ID 생성 (제공되지 않은 경우)
            if not transaction_id:
                transaction_id = str(uuid.uuid4())
            
            # 출금 처리
            result = await self.repository.debit(
                player_id=player_id,
                amount=amount,
                transaction_id=transaction_id,
                description=description,
                reference_id=reference_id,
                game_id=game_id
            )
            
            return result
            
        except ValueError as e:
            logger.warning(f"출금 실패: 플레이어 {player_id}, 금액 {amount}, 오류: {str(e)}")
            
            # 잔액 부족 오류의 경우 적절한 상태 코드 반환
            if "잔액이 부족합니다" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=str(e)
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e)
                )
            
        except Exception as e:
            logger.error(f"출금 처리 중 예상치 못한 오류 발생: 플레이어 {player_id}, 금액 {amount}, 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="서비스 처리 중 오류가 발생했습니다"
            )
    
    async def get_transaction_history(
        self, 
        player_id: str, 
        limit: int = 10, 
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        플레이어 트랜잭션 내역 조회
        
        Args:
            player_id: 플레이어 ID
            limit: 항목 수 제한
            offset: 조회 시작 오프셋
            
        Returns:
            Dict[str, Any]: 트랜잭션 내역 및 페이지네이션 정보
        """
        try:
            # 트랜잭션 내역 조회
            transactions, total_count = await self.repository.get_transaction_history(
                player_id=player_id,
                limit=limit,
                offset=offset
            )
            
            # 응답 구성
            return {
                "items": transactions,
                "pagination": {
                    "total": total_count,
                    "limit": limit,
                    "offset": offset
                }
            }
            
        except ValueError as e:
            logger.warning(f"트랜잭션 내역 조회 실패: 플레이어 {player_id}, 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
            
        except Exception as e:
            logger.error(f"트랜잭션 내역 조회 중 예상치 못한 오류 발생: 플레이어 {player_id}, 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="서비스 처리 중 오류가 발생했습니다"
            )
    
    async def create_wallet(
        self, 
        player_id: str, 
        initial_balance: Decimal = Decimal("0.00"),
        currency: str = "KRW"
    ) -> Dict[str, Any]:
        """
        새 지갑 생성
        
        Args:
            player_id: 플레이어 ID
            initial_balance: 초기 잔액
            currency: 통화
            
        Returns:
            Dict[str, Any]: 생성된 지갑 정보
            
        Raises:
            ValueError: 잘못된 입력값
            Exception: 데이터베이스 오류
        """
        try:
            # 입력값 검증
            if initial_balance < 0:
                raise ValueError("초기 잔액은 음수가 될 수 없습니다")
            
            # 신규 지갑 생성
            wallet = Wallet(
                id=str(uuid.uuid4()),
                player_id=player_id,
                balance=initial_balance,
                currency=currency
            )
            
            # 지갑 저장
            self.session.add(wallet)
            await self.session.commit()
            await self.session.refresh(wallet)
            
            # 생성된 지갑 데이터 반환
            return {
                "wallet_id": wallet.id,
                "player_id": wallet.player_id,
                "balance": wallet.balance,
                "currency": wallet.currency,
                "created_at": wallet.created_at.isoformat(),
                "updated_at": wallet.updated_at.isoformat()
            }
            
        except Exception as e:
            # 롤백 및 예외 발생
            await self.session.rollback()
            logger.error(f"지갑 생성 실패: {str(e)}")
            raise

    async def get_or_create_wallet(self, player_id: str, currency: str = "KRW") -> Wallet:
        """
        플레이어 ID로 지갑을 조회하거나 없으면 새로 생성
        """
        # 먼저 사용자가 존재하는지 확인
        user_result = await self.session.execute(select(User).where(User.id == player_id))
        user = user_result.scalars().first()
        if not user:
            raise ValueError(f"사용자 ID {player_id}가 존재하지 않습니다")

        # 지갑 조회
        result = await self.session.execute(select(Wallet).where(Wallet.player_id == player_id))
        wallet = result.scalars().first()

        # 지갑이 없으면 생성
        if not wallet:
            wallet = Wallet(
                id=str(uuid.uuid4()),
                player_id=player_id,
                balance=Decimal("0.00"),
                currency=currency
            )
            self.session.add(wallet)
            await self.session.commit()
            logger.info(f"플레이어 {player_id}의 새 지갑 생성: {wallet.id}")

        return wallet

    async def get_balance(self, player_id: str) -> Dict[str, Any]:
        """
        플레이어의 현재 잔액 조회
        """
        wallet = await self._get_wallet(player_id)
        return {
            "wallet_id": wallet.id,
            "player_id": wallet.player_id,
            "balance": wallet.balance,
            "currency": wallet.currency,
            "created_at": wallet.created_at.isoformat(),
            "updated_at": wallet.updated_at.isoformat()
        }

    async def create_wallet(self, player_id: str, currency: str = "KRW") -> Dict[str, Any]:
        """
        새로운 지갑 생성 (이미 있으면 에러)
        """
        # 먼저 사용자가 존재하는지 확인
        user_result = await self.session.execute(select(User).where(User.id == player_id))
        user = user_result.scalars().first()
        if not user:
            raise ValueError(f"사용자 ID {player_id}가 존재하지 않습니다")

        # 이미 지갑이 있는지 확인
        result = await self.session.execute(select(Wallet).where(Wallet.player_id == player_id))
        existing_wallet = result.scalars().first()
        if existing_wallet:
            raise ValueError(f"플레이어 {player_id}는 이미 지갑을 가지고 있습니다")

        # 새 지갑 생성
        wallet = Wallet(
            id=str(uuid.uuid4()),
            player_id=player_id,
            balance=Decimal("0.00"),
            currency=currency
        )
        self.session.add(wallet)
        await self.session.commit()
        logger.info(f"플레이어 {player_id}의 새 지갑 생성: {wallet.id}")

        return {
            "wallet_id": wallet.id,
            "player_id": wallet.player_id,
            "balance": wallet.balance,
            "currency": wallet.currency,
            "created_at": wallet.created_at.isoformat(),
            "updated_at": wallet.updated_at.isoformat()
        }

    async def deposit(
        self, 
        player_id: str, 
        amount: Decimal, 
        transaction_id: Optional[str] = None,
        description: Optional[str] = None,
        reference_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        플레이어 지갑에 금액 입금
        """
        if amount <= 0:
            raise ValueError("입금 금액은 0보다 커야 합니다")

        wallet = await self._get_wallet(player_id)
        
        # 트랜잭션 ID 생성 (없으면)
        if not transaction_id:
            transaction_id = f"DEP-{uuid.uuid4()}"
            
        # 기존 트랜잭션 확인 (중복 방지)
        if await self._transaction_exists(transaction_id):
            raise ValueError(f"트랜잭션 ID {transaction_id}는 이미 존재합니다")
            
        balance_before = wallet.balance
        wallet.balance += amount
        
        # 트랜잭션 생성
        transaction = Transaction(
            id=str(uuid.uuid4()),
            wallet_id=wallet.id,
            transaction_id=transaction_id,
            type=TransactionType.DEPOSIT,
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            description=description,
            reference_id=reference_id
        )
        
        self.session.add(transaction)
        await self.session.commit()
        logger.info(f"플레이어 {player_id} 입금: {amount}, 잔액: {wallet.balance}")
        
        return {
            "wallet_id": wallet.id,
            "player_id": wallet.player_id,
            "balance": wallet.balance,
            "currency": wallet.currency,
            "created_at": wallet.created_at.isoformat(),
            "updated_at": wallet.updated_at.isoformat()
        }

    async def withdraw(
        self, 
        player_id: str, 
        amount: Decimal, 
        transaction_id: Optional[str] = None,
        description: Optional[str] = None,
        reference_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        플레이어 지갑에서 금액 출금
        """
        if amount <= 0:
            raise ValueError("출금 금액은 0보다 커야 합니다")

        wallet = await self._get_wallet(player_id)
        
        # 잔액 확인
        if wallet.balance < amount:
            raise ValueError(f"잔액 부족: 필요한 금액 {amount}, 현재 잔액 {wallet.balance}")
        
        # 트랜잭션 ID 생성 (없으면)
        if not transaction_id:
            transaction_id = f"WD-{uuid.uuid4()}"
            
        # 기존 트랜잭션 확인 (중복 방지)
        if await self._transaction_exists(transaction_id):
            raise ValueError(f"트랜잭션 ID {transaction_id}는 이미 존재합니다")
            
        balance_before = wallet.balance
        wallet.balance -= amount
        
        # 트랜잭션 생성
        transaction = Transaction(
            id=str(uuid.uuid4()),
            wallet_id=wallet.id,
            transaction_id=transaction_id,
            type=TransactionType.WITHDRAW,
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            description=description,
            reference_id=reference_id
        )
        
        self.session.add(transaction)
        await self.session.commit()
        logger.info(f"플레이어 {player_id} 출금: {amount}, 잔액: {wallet.balance}")
        
        return {
            "wallet_id": wallet.id,
            "player_id": wallet.player_id,
            "balance": wallet.balance,
            "currency": wallet.currency,
            "created_at": wallet.created_at.isoformat(),
            "updated_at": wallet.updated_at.isoformat()
        }

    async def transfer(
        self, 
        from_player_id: str, 
        to_player_id: str,
        amount: Decimal,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        한 플레이어에서 다른 플레이어로 금액 이체
        """
        if amount <= 0:
            raise ValueError("이체 금액은 0보다 커야 합니다")
            
        if from_player_id == to_player_id:
            raise ValueError("자신에게 이체할 수 없습니다")
            
        # 출금할 지갑 확인
        from_wallet = await self._get_wallet(from_player_id)
        
        # 잔액 확인
        if from_wallet.balance < amount:
            raise ValueError(f"잔액 부족: 필요한 금액 {amount}, 현재 잔액 {from_wallet.balance}")
            
        # 입금할 지갑 확인
        to_wallet = await self._get_wallet(to_player_id)
        
        # 공통 트랜잭션 ID 생성
        base_transaction_id = f"TRF-{uuid.uuid4()}"
        from_transaction_id = f"{base_transaction_id}-OUT"
        to_transaction_id = f"{base_transaction_id}-IN"
        
        try:
            # 출금 지갑 처리
            from_balance_before = from_wallet.balance
            from_wallet.balance -= amount
            
            # 출금 트랜잭션 생성
            from_transaction = Transaction(
                id=str(uuid.uuid4()),
                wallet_id=from_wallet.id,
                transaction_id=from_transaction_id,
                type=TransactionType.TRANSFER_OUT,
                amount=amount,
                balance_before=from_balance_before,
                balance_after=from_wallet.balance,
                description=description or f"이체 to {to_player_id}"
            )
            
            # 입금 지갑 처리
            to_balance_before = to_wallet.balance
            to_wallet.balance += amount
            
            # 입금 트랜잭션 생성
            to_transaction = Transaction(
                id=str(uuid.uuid4()),
                wallet_id=to_wallet.id,
                transaction_id=to_transaction_id,
                type=TransactionType.TRANSFER_IN,
                amount=amount,
                balance_before=to_balance_before,
                balance_after=to_wallet.balance,
                description=description or f"이체 from {from_player_id}"
            )
            
            self.session.add_all([from_transaction, to_transaction])
            await self.session.commit()
            
            logger.info(f"이체 완료: {from_player_id} -> {to_player_id}, 금액: {amount}")
            
            return {
                "from_wallet": {
                    "player_id": from_wallet.player_id,
                    "balance": from_wallet.balance
                },
                "to_wallet": {
                    "player_id": to_wallet.player_id,
                    "balance": to_wallet.balance
                },
                "amount": amount,
                "transaction_id": base_transaction_id
            }
            
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"이체 실패: {e}")
            raise ValueError(f"이체 처리 중 오류가 발생했습니다: {str(e)}")

    async def place_bet(
        self, 
        player_id: str, 
        amount: Decimal, 
        game_id: str,
        transaction_id: Optional[str] = None,
        reference_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        게임에 베팅 금액 설정 (출금과 유사하지만 게임 정보 포함)
        """
        if amount <= 0:
            raise ValueError("베팅 금액은 0보다 커야 합니다")

        wallet = await self._get_wallet(player_id)
        
        # 잔액 확인
        if wallet.balance < amount:
            raise ValueError(f"잔액 부족: 필요한 금액 {amount}, 현재 잔액 {wallet.balance}")
        
        # 트랜잭션 ID 생성 (없으면)
        if not transaction_id:
            transaction_id = f"BET-{game_id}-{uuid.uuid4()}"
            
        # 기존 트랜잭션 확인 (중복 방지)
        if await self._transaction_exists(transaction_id):
            raise ValueError(f"트랜잭션 ID {transaction_id}는 이미 존재합니다")
            
        balance_before = wallet.balance
        wallet.balance -= amount
        
        # 트랜잭션 생성
        transaction = Transaction(
            id=str(uuid.uuid4()),
            wallet_id=wallet.id,
            transaction_id=transaction_id,
            type=TransactionType.BET,
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            description=f"베팅: 게임 {game_id}",
            reference_id=reference_id,
            game_id=game_id
        )
        
        self.session.add(transaction)
        await self.session.commit()
        logger.info(f"플레이어 {player_id} 베팅: {amount}, 게임: {game_id}, 잔액: {wallet.balance}")
        
        return {
            "wallet_id": wallet.id,
            "player_id": wallet.player_id,
            "balance": wallet.balance,
            "currency": wallet.currency,
            "created_at": wallet.created_at.isoformat(),
            "updated_at": wallet.updated_at.isoformat()
        }

    async def win_payout(
        self, 
        player_id: str, 
        amount: Decimal, 
        game_id: str,
        transaction_id: Optional[str] = None,
        reference_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        게임 승리 시 정산 금액 (입금과 유사하지만 게임 정보 포함)
        """
        if amount <= 0:
            raise ValueError("정산 금액은 0보다 커야 합니다")

        wallet = await self._get_wallet(player_id)
        
        # 트랜잭션 ID 생성 (없으면)
        if not transaction_id:
            transaction_id = f"WIN-{game_id}-{uuid.uuid4()}"
            
        # 기존 트랜잭션 확인 (중복 방지)
        if await self._transaction_exists(transaction_id):
            raise ValueError(f"트랜잭션 ID {transaction_id}는 이미 존재합니다")
            
        balance_before = wallet.balance
        wallet.balance += amount
        
        # 트랜잭션 생성
        transaction = Transaction(
            id=str(uuid.uuid4()),
            wallet_id=wallet.id,
            transaction_id=transaction_id,
            type=TransactionType.WIN,
            amount=amount,
            balance_before=balance_before,
            balance_after=wallet.balance,
            description=f"정산: 게임 {game_id}",
            reference_id=reference_id,
            game_id=game_id
        )
        
        self.session.add(transaction)
        await self.session.commit()
        logger.info(f"플레이어 {player_id} 정산: {amount}, 게임: {game_id}, 잔액: {wallet.balance}")
        
        return {
            "wallet_id": wallet.id,
            "player_id": wallet.player_id,
            "balance": wallet.balance,
            "currency": wallet.currency,
            "created_at": wallet.created_at.isoformat(),
            "updated_at": wallet.updated_at.isoformat()
        }

    async def get_transaction_history(
        self, 
        player_id: str, 
        limit: int = 10, 
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        플레이어의 트랜잭션 내역 조회
        """
        wallet = await self._get_wallet(player_id)
        
        # 총 트랜잭션 수 조회
        count_query = select(Transaction).where(Transaction.wallet_id == wallet.id)
        total_count = (await self.session.execute(count_query)).all()
        total_count = len(total_count)
        
        # 트랜잭션 조회 (최신순)
        query = select(Transaction).where(
            Transaction.wallet_id == wallet.id
        ).order_by(
            Transaction.created_at.desc()
        ).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        transactions = result.scalars().all()
        
        transaction_list = []
        for tx in transactions:
            transaction_list.append({
                "id": tx.id,
                "transaction_id": tx.transaction_id,
                "type": tx.type.value,
                "amount": tx.amount,
                "balance_after": tx.balance_after,
                "description": tx.description,
                "reference_id": tx.reference_id,
                "game_id": tx.game_id,
                "created_at": tx.created_at.isoformat()
            })
        
        return {
            "player_id": player_id,
            "transactions": transaction_list,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
        }

    async def _get_wallet(self, player_id: str) -> Wallet:
        """
        지갑 조회 (없으면 에러)
        """
        result = await self.session.execute(select(Wallet).where(Wallet.player_id == player_id))
        wallet = result.scalars().first()
        if not wallet:
            raise ValueError(f"플레이어 {player_id}의 지갑을 찾을 수 없습니다")
        return wallet

    async def _transaction_exists(self, transaction_id: str) -> bool:
        """
        트랜잭션 ID가 이미 존재하는지 확인
        """
        result = await self.session.execute(
            select(Transaction).where(Transaction.transaction_id == transaction_id)
        )
        return result.scalars().first() is not None