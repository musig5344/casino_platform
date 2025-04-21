import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import asyncio
import hashlib
import hmac
import os

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from cache_provider import CacheProvider

logger = logging.getLogger(__name__)

class WalletService:
    """
    플레이어 지갑 관리 서비스
    지갑 잔액 조회, 입금, 출금 기능 구현
    캐싱을 통한 성능 최적화 지원
    """
    
    def __init__(self, db: Session, cache_provider: CacheProvider):
        """
        지갑 서비스 초기화
        
        Args:
            db: 데이터베이스 세션
            cache_provider: 캐시 서비스 제공자
        """
        self.db = db
        self.cache = cache_provider
        self.balance_cache_ttl = 60  # 잔액 캐시 유효 시간(초)
        self._locks = {}  # 동시성 제어를 위한 로크 저장소
        self.hmac_key = os.environ.get("WALLET_HMAC_KEY", "DEFAULT_KEY").encode()  # HMAC 키 (환경 변수에서 가져오거나 기본값 사용)
    
    async def get_balance(self, player_id: str) -> Dict[str, Any]:
        """
        플레이어 잔액 조회
        캐시에서 우선 조회하고, 없으면 DB에서 조회 후 캐싱
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Dict[str, Any]: 잔액 정보와 캐시 상태
        """
        # 입력 검증
        if not player_id:
            raise ValueError("플레이어 ID는 필수 항목입니다")
            
        cache_key = self.cache.get_player_balance_key(player_id)
        cache_hit = False
        
        # 1. 캐시에서 조회 시도
        cached_balance = self.cache.get(cache_key)
        if cached_balance is not None:
            # 데이터 무결성 검증
            if self._verify_balance_integrity(player_id, cached_balance):
                cache_hit = True
                logger.info(f"플레이어 {player_id}의 잔액을 캐시에서 가져왔습니다.")
                return {
                    "player_id": player_id,
                    "balance": cached_balance.get("balance", 0),
                    "currency": cached_balance.get("currency", "KRW"),
                    "updated_at": cached_balance.get("updated_at", datetime.now().isoformat()),
                    "cache_hit": True
                }
            else:
                logger.warning(f"플레이어 {player_id}의 캐시 데이터 무결성 검증 실패, DB에서 재조회")
        
        # 2. DB에서 조회
        try:
            # 실제 구현에서는 ORM 모델을 사용하여 조회
            # 여기서는 가상의 데이터로 대체
            db_balance = self._get_balance_from_db(player_id)
            
            # 3. 캐시에 저장
            balance_data = {
                "balance": db_balance["balance"],
                "currency": db_balance["currency"],
                "updated_at": datetime.now().isoformat(),
                "hash": self._generate_balance_hash(player_id, db_balance["balance"])
            }
            
            self.cache.set(cache_key, balance_data, ttl=self.balance_cache_ttl)
            logger.info(f"플레이어 {player_id}의 잔액을 캐시에 저장했습니다.")
            
            return {
                "player_id": player_id,
                "balance": db_balance["balance"],
                "currency": db_balance["currency"],
                "updated_at": db_balance["updated_at"],
                "cache_hit": False
            }
            
        except SQLAlchemyError as e:
            logger.error(f"DB에서 잔액 조회 중 오류 발생: {e}")
            raise ValueError(f"잔액 조회 실패: {str(e)}")
    
    async def credit(self, player_id: str, amount: float, reference_id: str = None) -> Dict[str, Any]:
        """
        플레이어 계정에 금액 입금
        
        Args:
            player_id: 플레이어 ID
            amount: 입금액 (양수여야 함)
            reference_id: 트랜잭션 참조 ID (기본값: 자동 생성)
            
        Returns:
            Dict[str, Any]: 거래 결과 및 새 잔액 정보
        """
        # 입력 검증
        if amount <= 0:
            raise ValueError("입금액은 0보다 커야 합니다.")
        
        if reference_id is None:
            reference_id = str(uuid.uuid4())
        
        # 플레이어별 잠금 획득 (동시성 제어)
        async with self._get_player_lock(player_id):
            try:
                # 1. DB에 트랜잭션 기록 및 잔액 업데이트
                new_balance = self._update_balance_in_db(player_id, amount, "credit", reference_id)
                
                # 2. 캐시 업데이트
                self._update_balance_cache(player_id, new_balance)
                
                return {
                    "transaction_id": reference_id,
                    "player_id": player_id,
                    "amount": amount,
                    "type": "credit",
                    "new_balance": new_balance["balance"],
                    "status": "completed",
                    "timestamp": datetime.now().isoformat()
                }
                
            except SQLAlchemyError as e:
                logger.error(f"입금 처리 중 오류 발생: {e}")
                raise ValueError(f"입금 실패: {str(e)}")
    
    async def debit(self, player_id: str, amount: float, reference_id: str = None) -> Dict[str, Any]:
        """
        플레이어 계정에서 금액 출금
        
        Args:
            player_id: 플레이어 ID
            amount: 출금액 (양수여야 함)
            reference_id: 트랜잭션 참조 ID (기본값: 자동 생성)
            
        Returns:
            Dict[str, Any]: 거래 결과 및 새 잔액 정보
        """
        # 입력 검증
        if amount <= 0:
            raise ValueError("출금액은 0보다 커야 합니다.")
        
        if reference_id is None:
            reference_id = str(uuid.uuid4())
        
        # 플레이어별 잠금 획득 (동시성 제어)
        async with self._get_player_lock(player_id):
            try:
                # 현재 잔액 확인
                current_balance = await self.get_balance(player_id)
                
                if current_balance["balance"] < amount:
                    raise ValueError("잔액 부족")
                
                # 1. DB에 트랜잭션 기록 및 잔액 업데이트
                new_balance = self._update_balance_in_db(player_id, -amount, "debit", reference_id)
                
                # 2. 캐시 업데이트
                self._update_balance_cache(player_id, new_balance)
                
                return {
                    "transaction_id": reference_id,
                    "player_id": player_id,
                    "amount": amount,
                    "type": "debit",
                    "new_balance": new_balance["balance"],
                    "status": "completed",
                    "timestamp": datetime.now().isoformat()
                }
                
            except ValueError as e:
                if str(e) == "잔액 부족":
                    logger.warning(f"플레이어 {player_id}의 잔액 부족: 요청 금액 {amount}")
                    return {
                        "transaction_id": reference_id,
                        "player_id": player_id,
                        "amount": amount,
                        "type": "debit",
                        "status": "failed",
                        "reason": "insufficient_funds",
                        "timestamp": datetime.now().isoformat()
                    }
                raise
                
            except SQLAlchemyError as e:
                logger.error(f"출금 처리 중 오류 발생: {e}")
                raise ValueError(f"출금 실패: {str(e)}")
    
    def _get_balance_from_db(self, player_id: str) -> Dict[str, Any]:
        """
        데이터베이스에서 플레이어 잔액 조회
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Dict[str, Any]: 잔액 정보
        """
        # 참고: 실제 구현에서는 DB 쿼리를 사용하여 조회
        # 여기서는 가상의 데이터로 대체
        
        # SELECT balance, currency, updated_at FROM player_wallets WHERE player_id = :player_id
        # 시뮬레이션용 데이터
        return {
            "balance": 10000,
            "currency": "KRW",
            "updated_at": datetime.now().isoformat()
        }
    
    def _update_balance_in_db(self, player_id: str, amount: float, tx_type: str, reference_id: str) -> Dict[str, Any]:
        """
        데이터베이스에서 플레이어 잔액 업데이트
        
        Args:
            player_id: 플레이어 ID
            amount: 변경 금액 (입금은 양수, 출금은 음수)
            tx_type: 트랜잭션 타입 ('credit' 또는 'debit')
            reference_id: 트랜잭션 참조 ID
            
        Returns:
            Dict[str, Any]: 새 잔액 정보
        """
        # 참고: 실제 구현에서는 DB 쿼리를 사용하여 업데이트
        # 여기서는 가상의 데이터로 대체
        
        try:
            # 트랜잭션 시작 - 실제 구현에서는 DB 트랜잭션 사용
            # self.db.begin()
            
            # 1. 잔액 업데이트
            # UPDATE player_wallets 
            # SET balance = balance + :amount, updated_at = NOW() 
            # WHERE player_id = :player_id
            # RETURNING balance, currency, updated_at;
            
            # 시뮬레이션용 데이터
            current_balance = self._get_balance_from_db(player_id)
            new_balance = current_balance["balance"] + amount
            
            if new_balance < 0:
                # 트랜잭션 롤백
                # self.db.rollback()
                raise ValueError("잔액 부족")
            
            # 2. 트랜잭션 기록 저장
            timestamp = datetime.now().isoformat()
            # INSERT INTO transactions (
            #     player_id, reference_id, type, amount, balance_before, balance_after, created_at
            # ) VALUES (
            #     :player_id, :reference_id, :tx_type, :amount, :balance_before, :new_balance, :timestamp
            # )
            
            # 트랜잭션 커밋
            # self.db.commit()
            
            balance_data = {
                "balance": new_balance,
                "currency": current_balance["currency"],
                "updated_at": timestamp
            }
            
            return balance_data
            
        except Exception as e:
            # 트랜잭션 롤백
            # self.db.rollback()
            raise e
    
    def _update_balance_cache(self, player_id: str, balance_data: Dict[str, Any]) -> bool:
        """
        캐시에 플레이어 잔액 정보 업데이트
        
        Args:
            player_id: 플레이어 ID
            balance_data: 잔액 정보
            
        Returns:
            bool: 성공 여부
        """
        cache_key = self.cache.get_player_balance_key(player_id)
        
        # 데이터 무결성 해시 추가
        cache_data = {
            "balance": balance_data["balance"],
            "currency": balance_data["currency"],
            "updated_at": balance_data["updated_at"],
            "hash": self._generate_balance_hash(player_id, balance_data["balance"])
        }
        
        success = self.cache.set(cache_key, cache_data, ttl=self.balance_cache_ttl)
        
        if success:
            logger.info(f"플레이어 {player_id}의 잔액 캐시를 업데이트했습니다.")
        else:
            logger.warning(f"플레이어 {player_id}의 잔액 캐시 업데이트에 실패했습니다.")
            
        return success
    
    def _get_player_lock(self, player_id: str):
        """
        플레이어별 잠금 객체 반환 - 동시성 제어용
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Lock: 비동기 잠금 객체
        """
        if player_id not in self._locks:
            self._locks[player_id] = asyncio.Lock()
        return self._locks[player_id]
    
    def _generate_balance_hash(self, player_id: str, balance: float) -> str:
        """
        잔액 데이터 무결성 검증을 위한 해시 생성
        
        Args:
            player_id: 플레이어 ID
            balance: 잔액
            
        Returns:
            str: HMAC SHA-256 해시
        """
        message = f"{player_id}:{balance}".encode()
        digest = hmac.new(self.hmac_key, message, hashlib.sha256).hexdigest()
        return digest
    
    def _verify_balance_integrity(self, player_id: str, balance_data: Dict[str, Any]) -> bool:
        """
        잔액 데이터 무결성 검증
        
        Args:
            player_id: 플레이어 ID
            balance_data: 잔액 데이터
            
        Returns:
            bool: 무결성 검증 결과
        """
        if "hash" not in balance_data:
            return False
            
        stored_hash = balance_data["hash"]
        expected_hash = self._generate_balance_hash(player_id, balance_data["balance"])
        
        return hmac.compare_digest(stored_hash, expected_hash) 