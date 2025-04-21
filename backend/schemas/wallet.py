from pydantic import BaseModel, Field, constr, condecimal, validator, field_validator, ConfigDict
from typing import Literal, Optional
from datetime import datetime
from decimal import Decimal # Use Decimal for financial values

# ==== Request Models ====

# 기본 요청 클래스 (모든 API 요청에 공통적으로 필요한 필드)
class BaseRequest(BaseModel):
    uuid: constr(min_length=1) = Field(..., description="고유 요청 식별자")

# Balance API 요청 스키마
class BalanceRequest(BaseRequest):
    # player_id 필드 추가: 최소/최대 길이 제한 및 유효 문자 검증 (예: 영숫자 및 하이픈)
    player_id: constr(
        min_length=1, 
        max_length=50, 
        pattern=r'^[a-zA-Z0-9_-]+$'
    ) = Field(..., description="플레이어 ID (영숫자, _, - 허용)")

# Check API 요청 스키마
class CheckRequest(BaseRequest):
    player_id: constr(min_length=1) = Field(..., description="플레이어 ID")
    session_id: Optional[constr(min_length=1)] = Field(None, description="세션 ID (선택적)")

# 트랜잭션 기본 요청 스키마
class TransactionBaseRequest(BaseRequest):
    player_id: constr(min_length=1) = Field(..., description="플레이어 ID")
    transaction_id: constr(min_length=1) = Field(..., description="거래 고유 식별자")

# Debit API 요청 스키마
class DebitRequest(TransactionBaseRequest):
    amount: condecimal(gt=Decimal("0.00"), max_digits=10, decimal_places=2) = Field(..., description="차감할 금액 (양수)")
    
    @field_validator('amount')
    @classmethod
    def validate_amount_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0.00"):
            raise ValueError("금액은 0보다 커야 합니다")
        return v

# Credit API 요청 스키마
class CreditRequest(TransactionBaseRequest):
    amount: condecimal(gt=Decimal("0.00"), max_digits=10, decimal_places=2) = Field(..., description="추가할 금액 (양수)")
    
    @field_validator('amount')
    @classmethod
    def validate_amount_positive(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0.00"):
            raise ValueError("금액은 0보다 커야 합니다")
        return v

# Cancel API 요청 스키마
class CancelRequest(TransactionBaseRequest):
    original_transaction_id: constr(min_length=1) = Field(..., description="취소할 원본 트랜잭션 ID")

# ==== Response Models ====

# 기본 응답 클래스
class BaseResponse(BaseModel):
    status: str = "OK"
    uuid: str
    timestamp: Optional[str] = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="응답 생성 시간"
    )

# Balance API 응답 스키마
class BalanceResponse(BaseResponse):
    balance: Decimal
    currency: str
    player_id: str
    updated_at: Optional[str] = None
    cache_hit: Optional[bool] = Field(None, description="캐시 적중 여부 (디버깅용)")

# Check API 응답 스키마
class CheckResponse(BaseResponse):
    player_id: str

# Debit, Credit, Cancel API 응답 스키마 (공통)
class WalletActionResponse(BaseResponse):
    balance: Decimal
    currency: str
    transaction_id: Optional[str] = None
    player_id: str
    amount: Optional[Decimal] = None
    type: Optional[str] = None  # 'debit', 'credit', 'cancel'

# ==== Model Properties ====

# 지갑 모델 공통 속성
class WalletBase(BaseModel):
    currency: constr(min_length=3, max_length=3) # ISO 4217

# 지갑 생성 속성
class WalletCreate(WalletBase):
    player_id: constr(min_length=1, max_length=50)
    balance: condecimal(max_digits=10, decimal_places=2) = Decimal("0.00")

# 지갑 조회 응답 속성
class Wallet(WalletBase):
    player_id: str
    balance: Decimal

    model_config = ConfigDict(from_attributes=True)

# 트랜잭션 모델 속성
class Transaction(BaseModel):
    id: int
    player_id: str
    transaction_type: Literal['debit', 'credit', 'cancel']
    amount: Decimal
    transaction_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True) 