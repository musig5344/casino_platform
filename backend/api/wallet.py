# backend/api/wallet.py
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models.wallet import Wallet as WalletModel, Transaction as TransactionModel
from backend.schemas.wallet import (
    BalanceRequest, BalanceResponse, 
    CheckRequest, CheckResponse,
    DebitRequest, CreditRequest, CancelRequest, WalletActionResponse
)
from backend.api.deps import get_current_player_id
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from backend.cache import redis_client, CACHE_TTL
import logging
from backend.config.database import settings
import time
from backend.schemas.api import (
    ExternalBalanceRequest, ExternalBalanceResponse, 
    ExternalDebitRequest, ExternalCreditRequest, 
    ExternalCancelRequest, ExternalTransactionResponse,
    ResponseStatus
)
from typing import Optional, Dict, Any, Tuple
from backend.i18n import Translator, get_translator
from contextlib import contextmanager

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["Wallet"]
)

# 캐시 키 접두사 상수화
WALLET_CACHE_PREFIX = "wallet"

# ==================== 에러 처리 클래스 ====================
class WalletErrors:
    """일관된 에러 응답을 생성하는 클래스"""
    
    @staticmethod
    def player_id_mismatch(translator: Translator) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=translator('errors.error.player_id_mismatch')
        )
    
    @staticmethod
    def player_not_found(translator: Translator, player_id: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translator('errors.error.player_not_found', player_id=player_id)
        )
    
    @staticmethod
    def wallet_not_found(translator: Translator, player_id: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translator('errors.error.wallet_not_found', player_id=player_id)
        )
    
    @staticmethod
    def transaction_not_found(translator: Translator, transaction_id: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translator('errors.error.transaction_not_found', transaction_id=transaction_id)
        )
    
    @staticmethod
    def transaction_already_processed(translator: Translator, transaction_id: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=translator('errors.error.transaction_already_processed', transaction_id=transaction_id)
        )
    
    @staticmethod
    def insufficient_funds(translator: Translator) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translator('errors.error.insufficient_funds')
        )
    
    @staticmethod
    def internal_server_error(translator: Translator) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator('errors.error.internal_server_error')
        )

# ==================== 트랜잭션 관리 ====================
@contextmanager
def get_transaction_session(db: Session):
    """명시적 트랜잭션 관리를 위한 컨텍스트 매니저"""
    try:
        yield db
        db.commit()
        logger.debug("Transaction committed successfully")
    except Exception as e:
        db.rollback()
        logger.error(f"Transaction rollback due to error: {e}", exc_info=True)
        raise

# ==================== 지갑 서비스 클래스 ====================
class WalletService:
    """지갑 관련 비즈니스 로직을 처리하는 서비스 클래스"""
    
    def __init__(self, db: Session, translator: Translator):
        self.db = db
        self.translator = translator
    
    def get_wallet(self, player_id: str, for_update: bool = False) -> Optional[WalletModel]:
        """플레이어의 지갑을 조회합니다. for_update가 True면 비관적 잠금 적용"""
        query = self.db.query(WalletModel).filter(WalletModel.player_id == player_id)
        if for_update:
            query = query.with_for_update()
        return query.first()
    
    def get_player(self, player_id: str) -> Optional[Any]:
        """플레이어 정보를 조회합니다."""
        from backend.models.user import Player
        return self.db.query(Player).filter(Player.id == player_id).first()
    
    def get_transaction(self, transaction_id: str) -> Optional[TransactionModel]:
        """트랜잭션 정보를 조회합니다."""
        return self.db.query(TransactionModel).filter(
            TransactionModel.transaction_id == transaction_id
        ).first()
    
    def create_wallet(self, player_id: str, currency: str = 'KRW') -> WalletModel:
        """새로운 지갑을 생성합니다."""
        wallet = WalletModel(
            player_id=player_id,
            balance=Decimal("0.0"),
            currency=currency
        )
        self.db.add(wallet)
        self.db.flush()  # 새 지갑 ID 확보를 위해 flush
        logger.info(f"New wallet created for player {player_id} with currency {currency}")
        return wallet
    
    def ensure_wallet_exists(self, player_id: str, for_update: bool = False) -> Tuple[WalletModel, bool]:
        """지갑이 존재하는지 확인하고, 없으면 생성합니다. (생성 여부 반환)"""
        wallet = self.get_wallet(player_id, for_update)
        created = False
        
        if not wallet:
            player = self.get_player(player_id)
            if not player:
                raise WalletErrors.player_not_found(self.translator, player_id)
                
            currency = getattr(player, 'currency', 'KRW')
            wallet = self.create_wallet(player_id, currency)
            created = True
            
        return wallet, created
    
    def create_transaction(self, player_id: str, tx_type: str, amount: Decimal, 
                          transaction_id: str, wallet: WalletModel, 
                          original_balance: Decimal, ref_transaction_id: str = None,
                          metadata: Dict = None) -> TransactionModel:
        """새 트랜잭션 기록을 생성합니다."""
        transaction = TransactionModel(
            transaction_id=transaction_id,
            player_id=player_id,
            transaction_type=tx_type,
            amount=amount,
            currency=wallet.currency,
            status="completed",
            original_balance=original_balance,
            updated_balance=wallet.balance,
            ref_transaction_id=ref_transaction_id,
            transaction_metadata=metadata or {}
        )
        self.db.add(transaction)
        return transaction
    
    def process_debit(self, player_id: str, amount: Decimal, transaction_id: str, 
                      uuid: str, metadata: Dict = None) -> WalletActionResponse:
        """출금(차감) 처리 로직"""
        # 트랜잭션 중복 확인
        existing_tx = self.get_transaction(transaction_id)
        if existing_tx:
            raise WalletErrors.transaction_already_processed(self.translator, transaction_id)

        with get_transaction_session(self.db) as session:
            # 지갑 조회 (비관적 잠금 적용)
            wallet = self.get_wallet(player_id, for_update=True)
            if not wallet:
                raise WalletErrors.wallet_not_found(self.translator, player_id)
            
            # 잔액 충분한지 확인
            if wallet.balance < amount:
                raise WalletErrors.insufficient_funds(self.translator)
            
            # 잔액 차감
            original_balance = wallet.balance
            wallet.balance -= amount
            
            # 트랜잭션 기록 생성
            self.create_transaction(
                player_id=player_id,
                tx_type="debit",
                amount=amount,
                transaction_id=transaction_id,
                wallet=wallet,
                original_balance=original_balance,
                metadata=metadata
            )
        
        # 성공 응답
        return WalletActionResponse(
            status="OK",
            balance=wallet.balance,
            currency=wallet.currency,
            transaction_id=transaction_id,
            uuid=uuid,
            player_id=player_id
        )
    
    def process_credit(self, player_id: str, amount: Decimal, transaction_id: str, 
                       uuid: str, metadata: Dict = None) -> WalletActionResponse:
        """입금(추가) 처리 로직"""
        # 트랜잭션 중복 확인 (멱등성 처리)
        existing_tx = self.get_transaction(transaction_id)
        if existing_tx:
            logger.warning(f"Credit transaction {transaction_id} already exists for player {player_id}. Returning current balance.")
            wallet = self.get_wallet(player_id)
            if wallet:
                return WalletActionResponse(
                    status="OK",
                    balance=wallet.balance,
                    currency=wallet.currency,
                    transaction_id=transaction_id,
                    uuid=uuid,
                    player_id=player_id,
                    amount=existing_tx.amount,
                    type='credit'
                )
            else:
                raise WalletErrors.wallet_not_found(self.translator, player_id)

        with get_transaction_session(self.db) as session:
            # 지갑 확보 (없으면 생성)
            wallet, created = self.ensure_wallet_exists(player_id, for_update=True)
            
            # 잔액 증가
            original_balance = wallet.balance
            wallet.balance += amount
            
            # 트랜잭션 기록 생성
            self.create_transaction(
                player_id=player_id,
                tx_type="credit",
                amount=amount,
                transaction_id=transaction_id,
                wallet=wallet,
                original_balance=original_balance,
                metadata=metadata
            )
        
        # 성공 응답
        return WalletActionResponse(
            status="OK",
            balance=wallet.balance,
            currency=wallet.currency,
            transaction_id=transaction_id,
            uuid=uuid,
            player_id=player_id
        )
    
    def process_cancel(self, player_id: str, transaction_id: str, original_transaction_id: str, 
                       uuid: str) -> WalletActionResponse:
        """트랜잭션 취소 처리 로직"""
        # 원본 트랜잭션 조회
        original_tx = self.db.query(TransactionModel).filter(
            TransactionModel.transaction_id == original_transaction_id,
            TransactionModel.player_id == player_id
        ).first()
        
        if not original_tx:
            raise WalletErrors.transaction_not_found(self.translator, original_transaction_id)
        
        # 이미 취소되었는지 확인
        if original_tx.status != 'completed' or original_tx.transaction_type not in ['debit', 'credit']:
            raise WalletErrors.transaction_already_processed(self.translator, original_transaction_id)
        
        # 이미 해당 트랜잭션이 취소되었는지 확인
        already_canceled = self.db.query(TransactionModel).filter(
            TransactionModel.ref_transaction_id == original_transaction_id,
            TransactionModel.transaction_type == 'cancel'
        ).first()
        
        if already_canceled:
            wallet = self.get_wallet(player_id)
            logger.warning(f"Transaction {original_transaction_id} already canceled. Returning current balance.")
            return WalletActionResponse(
                status="OK",
                balance=wallet.balance if wallet else None,
                currency=wallet.currency if wallet else None,
                transaction_id=already_canceled.transaction_id,
                uuid=uuid,
                player_id=player_id,
                ref_transaction_id=original_transaction_id
            )
        
        # 취소 트랜잭션 중복 확인
        existing_cancel = self.get_transaction(transaction_id)
        if existing_cancel:
            wallet = self.get_wallet(player_id)
            return WalletActionResponse(
                status="OK",
                balance=wallet.balance,
                currency=wallet.currency,
                transaction_id=transaction_id,
                uuid=uuid,
                player_id=player_id,
                ref_transaction_id=original_transaction_id
            )
        
        with get_transaction_session(self.db) as session:
            # 지갑 조회 (비관적 잠금 적용)
            wallet = self.get_wallet(player_id, for_update=True)
            if not wallet:
                raise WalletErrors.wallet_not_found(self.translator, player_id)
            
            original_balance = wallet.balance
            amount_to_restore = original_tx.amount
            
            # 원본 트랜잭션 타입에 따라 잔액 조정
            if original_tx.transaction_type == 'debit':
                # 출금 취소 = 잔액 증가
                wallet.balance += amount_to_restore
            elif original_tx.transaction_type == 'credit':
                # 입금 취소 = 잔액 감소
                if wallet.balance < amount_to_restore:
                    raise WalletErrors.insufficient_funds(self.translator)
                wallet.balance -= amount_to_restore
            
            # 원본 트랜잭션 상태 업데이트
            original_tx.status = 'canceled'
            
            # 취소 트랜잭션 생성
            self.create_transaction(
                player_id=player_id,
                tx_type="cancel",
                amount=amount_to_restore,
                transaction_id=transaction_id,
                wallet=wallet,
                original_balance=original_balance,
                ref_transaction_id=original_transaction_id
            )
        
        # 성공 응답
        return WalletActionResponse(
            status="OK",
            balance=wallet.balance,
            currency=wallet.currency,
            transaction_id=transaction_id,
            uuid=uuid,
            player_id=player_id,
            ref_transaction_id=original_transaction_id
        )

# ==================== 캐시 관리 ====================
class CacheManager:
    """지갑 캐시 관리 클래스"""
    
    @staticmethod
    def get_wallet_cache_key(player_id: str) -> str:
        """플레이어 ID에 대한 캐시 키를 생성합니다."""
        return f"{WALLET_CACHE_PREFIX}:{player_id}"
    
    @staticmethod
    def get_wallet_balance(player_id: str) -> Optional[Dict]:
        """지갑 잔액 정보를 캐시에서 조회합니다."""
        cache_key = CacheManager.get_wallet_cache_key(player_id)
        cached_data = redis_client.get_json(cache_key)
        if cached_data and isinstance(cached_data, dict) and 'balance' in cached_data:
            logger.debug(f"Cache hit for player {player_id}'s wallet balance")
            return cached_data
        logger.debug(f"Cache miss for player {player_id}'s wallet balance")
        return None
    
    @staticmethod
    def set_wallet_balance(player_id: str, wallet: WalletModel, background_tasks: BackgroundTasks) -> None:
        """지갑 잔액 정보를 캐시에 저장합니다. (백그라운드 작업)"""
        cache_key = CacheManager.get_wallet_cache_key(player_id)
        cache_data = {
            "balance": float(wallet.balance),
            "currency": wallet.currency,
            "_cached_at": time.time()
        }
        
        def _cache_task():
            try:
                redis_client.set(cache_key, cache_data, ttl=CACHE_TTL.get('wallet', 60))
                logger.debug(f"Wallet balance cached for player {player_id}")
            except Exception as e:
                logger.error(f"Failed to cache wallet balance for player {player_id}: {e}")
        
        background_tasks.add_task(_cache_task)
    
    @staticmethod
    def invalidate_wallet_balance(player_id: str, background_tasks: BackgroundTasks) -> None:
        """지갑 잔액 캐시를 무효화합니다. (백그라운드 작업)"""
        cache_key = CacheManager.get_wallet_cache_key(player_id)
        
        def _invalidate_task():
            try:
                deleted = redis_client.delete(cache_key)
                logger.debug(f"Cache invalidation for player {player_id}: {deleted} keys deleted")
            except Exception as e:
                logger.error(f"Failed to invalidate wallet cache for player {player_id}: {e}")
        
        background_tasks.add_task(_invalidate_task)

# ==================== API 엔드포인트 ====================
@router.post("/balance", response_model=BalanceResponse)
async def get_player_balance(
    request: BalanceRequest,
    current_player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    현재 인증된 플레이어의 지갑 잔액을 조회합니다.
    """
    # 플레이어 ID 검증
    if hasattr(request, 'player_id') and request.player_id != current_player_id:
        raise WalletErrors.player_id_mismatch(translator)
    
    # 캐시에서 지갑 정보 조회 시도
    cached_data = CacheManager.get_wallet_balance(current_player_id)
    if cached_data:
        return BalanceResponse(
            status="OK",
            balance=cached_data["balance"],
            currency=cached_data["currency"],
            uuid=request.uuid,
            player_id=current_player_id,
            cache_hit=True
        )
    
    # 캐시 미스: DB에서 조회
    logger.info(f"Cache miss: Querying DB for player {current_player_id}'s wallet balance")
    wallet_service = WalletService(db, translator)
    wallet = wallet_service.get_wallet(current_player_id)

    if not wallet:
        raise WalletErrors.wallet_not_found(translator, current_player_id)
    
    # 캐시에 지갑 정보 저장 (백그라운드 작업)
    CacheManager.set_wallet_balance(current_player_id, wallet, background_tasks)

    return BalanceResponse(
        status="OK",
        balance=wallet.balance,
        currency=wallet.currency,
        uuid=request.uuid,
        player_id=current_player_id,
        cache_hit=False
    )

@router.post("/check", response_model=CheckResponse)
async def check_player(
    request: CheckRequest,
    current_player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어 인증 및 존재 여부를 확인합니다.
    """
    # 토큰의 player_id와 요청 본문의 player_id가 일치하는지 확인
    if request.player_id != current_player_id:
        raise WalletErrors.player_id_mismatch(translator)

    # 플레이어가 존재하는지 확인
    wallet_service = WalletService(db, translator)
    wallet = wallet_service.get_wallet(current_player_id)
    if not wallet:
        # 지갑이 없으면 플레이어 존재 여부 추가 확인
        player = wallet_service.get_player(current_player_id)
        if not player:
            raise WalletErrors.player_not_found(translator, current_player_id)

    # 성공 응답
    return CheckResponse(
        status="OK",
        uuid=request.uuid,
        player_id=current_player_id
    )

@router.post("/debit", response_model=WalletActionResponse)
async def debit_funds(
    request: DebitRequest,
    current_player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어의 지갑에서 자금을 차감합니다.
    """
    # 토큰의 player_id와 요청 본문의 player_id가 일치하는지 확인
    if request.player_id != current_player_id:
        raise WalletErrors.player_id_mismatch(translator)
    
    try:
        # 서비스 계층에 처리 위임
        wallet_service = WalletService(db, translator)
        response = wallet_service.process_debit(
            player_id=current_player_id,
            amount=request.amount, 
            transaction_id=request.transaction_id,
            uuid=request.uuid,
            metadata=request.metadata if hasattr(request, 'metadata') else None
        )
        
        # 캐시 무효화 (커밋 후 백그라운드로 처리)
        CacheManager.invalidate_wallet_balance(current_player_id, background_tasks)
        
        return response
    
    except HTTPException as http_exc:
        # HTTP 예외는 그대로 전달
        raise http_exc
    except IntegrityError as e:
        # 중복 트랜잭션 ID 등 DB 제약 조건 위반
        logger.error(f"Debit failed due to integrity error: {e}", exc_info=True)
        raise WalletErrors.transaction_already_processed(translator, request.transaction_id)
    except Exception as e:
        # 기타 예상치 못한 오류
        logger.error(f"Debit operation failed unexpectedly: {e}", exc_info=True)
        raise WalletErrors.internal_server_error(translator)

@router.post("/credit", response_model=WalletActionResponse)
async def credit_funds(
    request: CreditRequest,
    current_player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어의 지갑에 자금을 추가합니다.
    """
    # 토큰의 player_id와 요청 본문의 player_id가 일치하는지 확인
    if request.player_id != current_player_id:
        raise WalletErrors.player_id_mismatch(translator)
    
    try:
        # 서비스 계층에 처리 위임
        wallet_service = WalletService(db, translator)
        response = wallet_service.process_credit(
            player_id=current_player_id,
            amount=request.amount, 
            transaction_id=request.transaction_id,
            uuid=request.uuid,
            metadata=request.metadata if hasattr(request, 'metadata') else None
        )
        
        # 캐시 무효화 (커밋 후 백그라운드로 처리)
        CacheManager.invalidate_wallet_balance(current_player_id, background_tasks)
        
        return response
    
    except HTTPException as http_exc:
        # HTTP 예외는 그대로 전달
        raise http_exc
    except IntegrityError as e:
        # 중복 트랜잭션 등으로 인한 DB 제약 조건 위반
        logger.warning(f"Credit failed due to integrity error: {e}")
        # 멱등성을 위해 409 대신 현재 상태 반환
        wallet = db.query(WalletModel).filter(WalletModel.player_id == current_player_id).first()
        if wallet:
            return WalletActionResponse(
                status="OK",
                balance=wallet.balance,
                currency=wallet.currency,
                transaction_id=request.transaction_id,
                uuid=request.uuid,
                player_id=current_player_id
            )
        else:
            raise WalletErrors.wallet_not_found(translator, current_player_id)
    except Exception as e:
        # 기타 예상치 못한 오류
        logger.error(f"Credit failed unexpectedly: {e}", exc_info=True)
        raise WalletErrors.internal_server_error(translator)

@router.post("/cancel", response_model=WalletActionResponse)
async def cancel_transaction(
    request: CancelRequest,
    current_player_id: str = Depends(get_current_player_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    이전 트랜잭션을 취소합니다.
    """
    # 토큰의 player_id와 요청 본문의 player_id가 일치하는지 확인
    if request.player_id != current_player_id:
        raise WalletErrors.player_id_mismatch(translator)
    
    try:
        # 서비스 계층에 처리 위임
        wallet_service = WalletService(db, translator)
        response = wallet_service.process_cancel(
            player_id=current_player_id,
            transaction_id=request.transaction_id,
            original_transaction_id=request.original_transaction_id,
            uuid=request.uuid
        )
        
        # 캐시 무효화 (커밋 후 백그라운드로 처리)
        CacheManager.invalidate_wallet_balance(current_player_id, background_tasks)
        
        return response
    
    except HTTPException as http_exc:
        # HTTP 예외는 그대로 전달
        raise http_exc
    except IntegrityError as e:
        # 중복 트랜잭션 ID 등 DB 제약 조건 위반
        logger.error(f"Cancel failed due to integrity error: {e}", exc_info=True)
        raise WalletErrors.transaction_already_processed(translator, request.transaction_id)
    except Exception as e:
        # 기타 예상치 못한 오류
        logger.error(f"Cancel operation failed unexpectedly: {e}", exc_info=True)
        raise WalletErrors.internal_server_error(translator)

# ==================== 외부 API 엔드포인트 ====================
@router.post("/external/balance", response_model=ExternalBalanceResponse)
async def external_balance(
    request: ExternalBalanceRequest,
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """외부 게임에서 플레이어 잔액 확인"""
    wallet_service = WalletService(db, translator)
    player = wallet_service.get_player(request.player_id)
    
    if not player:
        return ExternalBalanceResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            currency="KRW",
            cash="0",
            bonus="0",
            error={"code": "PLAYER_NOT_FOUND", "message": "플레이어를 찾을 수 없습니다."}
        )
    
    # 지갑 정보 조회
    wallet = wallet_service.get_wallet(request.player_id)
    
    if not wallet:
        return ExternalBalanceResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            currency="KRW",
            cash="0",
            bonus="0",
            error={"code": "WALLET_NOT_FOUND", "message": "지갑을 찾을 수 없습니다."}
        )
    
    return ExternalBalanceResponse(
        status=ResponseStatus.OK,
        playerId=request.player_id,
        currency=wallet.currency,
        cash=str(wallet.balance),
        bonus="0"
    )

@router.post("/external/debit", response_model=ExternalTransactionResponse)
async def external_debit(
    request: ExternalDebitRequest,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """외부 게임에서 플레이어 잔액 차감"""
    wallet_service = WalletService(db, translator)
    
    # 플레이어 존재 확인
    player = wallet_service.get_player(request.player_id)
    if not player:
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "PLAYER_NOT_FOUND", "message": "플레이어를 찾을 수 없습니다."}
        )
    
    # 지갑 확인
    wallet = wallet_service.get_wallet(request.player_id)
    if not wallet:
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "WALLET_NOT_FOUND", "message": "지갑을 찾을 수 없습니다."}
        )
    
    # 트랜잭션 중복 확인
    existing_tx = wallet_service.get_transaction(request.transaction_id)
    if existing_tx:
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "DUPLICATE_TRANSACTION", "message": "중복된 거래 ID입니다."}
        )
    
    try:
        # Decimal 변환
        amount = Decimal(str(request.amount))
        
        # 메타데이터 구성
        metadata = {
            "game_id": request.game_id,
            "round_id": request.round_id,
            "table_id": request.table_id
        }
        
        # 트랜잭션 처리
        with get_transaction_session(db) as session:
            # 지갑 조회 (비관적 잠금 적용)
            wallet = wallet_service.get_wallet(request.player_id, for_update=True)
            
            # 잔액 확인
            if wallet.balance < amount:
                return ExternalTransactionResponse(
                    status=ResponseStatus.ERROR,
                    playerId=request.player_id,
                    currency=wallet.currency,
                    cash=str(wallet.balance),
                    bonus="0",
                    transactionId=request.transaction_id,
                    error={"code": "INSUFFICIENT_FUNDS", "message": "잔액이 부족합니다."}
                )
            
            # 잔액 차감
            original_balance = wallet.balance
            wallet.balance -= amount
            
            # 트랜잭션 기록
            wallet_service.create_transaction(
                player_id=request.player_id,
                tx_type="debit",
                amount=amount,
                transaction_id=request.transaction_id,
                wallet=wallet,
                original_balance=original_balance,
                metadata=metadata
            )
        
        # 캐시 무효화
        CacheManager.invalidate_wallet_balance(request.player_id, background_tasks)
        
        # 성공 응답
        return ExternalTransactionResponse(
            status=ResponseStatus.OK,
            playerId=request.player_id,
            currency=wallet.currency,
            cash=str(wallet.balance),
            bonus="0",
            transactionId=request.transaction_id
        )
    
    except Exception as e:
        logger.error(f"External debit failed: {e}", exc_info=True)
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "SERVER_ERROR", "message": "서버 오류가 발생했습니다."}
        )

@router.post("/external/credit", response_model=ExternalTransactionResponse)
async def external_credit(
    request: ExternalCreditRequest,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """외부 게임에서 플레이어 잔액 증가"""
    wallet_service = WalletService(db, translator)
    
    # 플레이어 존재 확인
    player = wallet_service.get_player(request.player_id)
    if not player:
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "PLAYER_NOT_FOUND", "message": "플레이어를 찾을 수 없습니다."}
        )
    
    # 트랜잭션 중복 확인
    existing_tx = wallet_service.get_transaction(request.transaction_id)
    if existing_tx:
        # 이미 처리된 트랜잭션인 경우 현재 상태 반환 (멱등성)
        wallet = wallet_service.get_wallet(request.player_id)
        if wallet:
            return ExternalTransactionResponse(
                status=ResponseStatus.OK,
                playerId=request.player_id,
                currency=wallet.currency,
                cash=str(wallet.balance),
                bonus="0",
                transactionId=request.transaction_id
            )
        else:
            return ExternalTransactionResponse(
                status=ResponseStatus.ERROR,
                playerId=request.player_id,
                transactionId=request.transaction_id,
                error={"code": "WALLET_NOT_FOUND", "message": "지갑을 찾을 수 없습니다."}
            )
    
    try:
        # Decimal 변환
        amount = Decimal(str(request.amount))
        
        # 메타데이터 구성
        metadata = {
            "game_id": request.game_id,
            "round_id": request.round_id,
            "table_id": request.table_id
        }
        
        # 트랜잭션 처리
        with get_transaction_session(db) as session:
            # 지갑 확보 (없으면 생성)
            wallet, created = wallet_service.ensure_wallet_exists(request.player_id, for_update=True)
            
            # 잔액 증가
            original_balance = wallet.balance
            wallet.balance += amount
            
            # 트랜잭션 기록
            wallet_service.create_transaction(
                player_id=request.player_id,
                tx_type="credit",
                amount=amount,
                transaction_id=request.transaction_id,
                wallet=wallet,
                original_balance=original_balance,
                metadata=metadata
            )
        
        # 캐시 무효화
        CacheManager.invalidate_wallet_balance(request.player_id, background_tasks)
        
        # 성공 응답
        return ExternalTransactionResponse(
            status=ResponseStatus.OK,
            playerId=request.player_id,
            currency=wallet.currency,
            cash=str(wallet.balance),
            bonus="0",
            transactionId=request.transaction_id
        )
    
    except Exception as e:
        logger.error(f"External credit failed: {e}", exc_info=True)
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "SERVER_ERROR", "message": "서버 오류가 발생했습니다."}
        )

@router.post("/external/cancel", response_model=ExternalTransactionResponse)
async def external_cancel(
    request: ExternalCancelRequest,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """외부 게임에서 발생한 트랜잭션 취소"""
    wallet_service = WalletService(db, translator)
    
    # 플레이어 존재 확인
    player = wallet_service.get_player(request.player_id)
    if not player:
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "PLAYER_NOT_FOUND", "message": "플레이어를 찾을 수 없습니다."}
        )
    
    # 지갑 확인
    wallet = wallet_service.get_wallet(request.player_id)
    if not wallet:
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "WALLET_NOT_FOUND", "message": "지갑을 찾을 수 없습니다."}
        )
    
    # 원본 트랜잭션 확인
    original_tx = db.query(TransactionModel).filter(
        TransactionModel.transaction_id == request.original_transaction_id
    ).first()
    
    if not original_tx:
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "TRANSACTION_NOT_FOUND", "message": "원본 트랜잭션을 찾을 수 없습니다."}
        )
    
    # 취소 트랜잭션 중복 확인
    existing_tx = wallet_service.get_transaction(request.transaction_id)
    if existing_tx:
        # 이미 처리된 취소 트랜잭션인 경우 현재 상태 반환 (멱등성)
        return ExternalTransactionResponse(
            status=ResponseStatus.OK,
            playerId=request.player_id,
            currency=wallet.currency,
            cash=str(wallet.balance),
            bonus="0",
            transactionId=request.transaction_id
        )
    
    try:
        with get_transaction_session(db) as session:
            # 지갑 조회 (비관적 잠금 적용)
            wallet = wallet_service.get_wallet(request.player_id, for_update=True)
            
            # 트랜잭션 타입에 따라 잔액 조정
            original_balance = wallet.balance
            cancel_amount = original_tx.amount
            
            # 출금 취소 = 잔액 증가, 입금 취소 = 잔액 감소
            if original_tx.transaction_type == 'debit':
                wallet.balance += cancel_amount
            elif original_tx.transaction_type == 'credit':
                if wallet.balance < cancel_amount:
                    return ExternalTransactionResponse(
                        status=ResponseStatus.ERROR,
                        playerId=request.player_id,
                        transactionId=request.transaction_id,
                        error={"code": "INSUFFICIENT_FUNDS", "message": "잔액이 부족합니다."}
                    )
                wallet.balance -= cancel_amount
            
            # 원본 트랜잭션 상태 업데이트
            original_tx.status = 'canceled'
            
            # 취소 트랜잭션 기록
            new_tx = TransactionModel(
                player_id=request.player_id,
                transaction_type="cancel",
                amount=cancel_amount,
                transaction_id=request.transaction_id,
                original_balance=original_balance,
                updated_balance=wallet.balance,
                ref_transaction_id=request.original_transaction_id,
                currency=wallet.currency,
                status="completed",
                transaction_metadata={
                    "original_transaction_id": original_tx.transaction_id
                }
            )
            db.add(new_tx)
        
        # 캐시 무효화
        CacheManager.invalidate_wallet_balance(request.player_id, background_tasks)
        
        # 성공 응답
        return ExternalTransactionResponse(
            status=ResponseStatus.OK,
            playerId=request.player_id,
            currency=wallet.currency,
            cash=str(wallet.balance),
            bonus="0",
            transactionId=request.transaction_id
        )
    
    except Exception as e:
        logger.error(f"External cancel failed: {e}", exc_info=True)
        return ExternalTransactionResponse(
            status=ResponseStatus.ERROR,
            playerId=request.player_id,
            transactionId=request.transaction_id,
            error={"code": "SERVER_ERROR", "message": "서버 오류가 발생했습니다."}
        )