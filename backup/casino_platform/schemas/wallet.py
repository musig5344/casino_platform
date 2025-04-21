from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, validator
from enum import Enum

class Currency(str, Enum):
    """지원되는 통화 유형"""
    KRW = "KRW"
    USD = "USD"
    EUR = "EUR"
    JPY = "JPY"
    CNY = "CNY"
    GBP = "GBP"

class TransactionType(str, Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    BET = "bet"
    WIN = "win"
    BONUS = "bonus"
    REFUND = "refund"

class TransactionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Language(str, Enum):
    """지원되는 언어"""
    KO = "ko"
    EN = "en"
    JA = "ja"
    ZH = "zh"
    ES = "es"

class TimeZone(str, Enum):
    """지원되는 시간대 샘플"""
    UTC = "UTC"
    ASIA_SEOUL = "Asia/Seoul"
    ASIA_TOKYO = "Asia/Tokyo"
    AMERICA_NEW_YORK = "America/New_York"
    EUROPE_LONDON = "Europe/London"

class TransactionBase(BaseModel):
    amount: float = Field(..., gt=0, description="거래 금액")
    description: Optional[str] = Field(None, description="거래 설명")
    currency: Currency = Field(Currency.KRW, description="통화")

class TransactionCreate(TransactionBase):
    reference_id: Optional[str] = Field(None, description="외부 참조 ID")
    game_id: Optional[str] = Field(None, description="게임 ID")

class TransactionResponse(TransactionBase):
    id: int
    wallet_id: int
    type: TransactionType
    status: TransactionStatus
    balance_after: float
    created_at: datetime
    updated_at: Optional[datetime] = None
    reference_id: Optional[str] = None
    game_id: Optional[str] = None

    class Config:
        orm_mode = True

class WalletBase(BaseModel):
    currency: Currency = Field(Currency.KRW, description="지갑 통화")

class WalletCreate(WalletBase):
    initial_balance: float = Field(0.0, ge=0, description="초기 잔액")

class WalletBalance(BaseModel):
    balance: float = Field(..., description="현재 지갑 잔액")
    currency: Currency = Field(..., description="통화")

class WalletResponse(BaseModel):
    wallet_id: int
    user_id: int
    balance: float
    currency: Currency
    created_at: datetime
    updated_at: datetime
    recent_transactions: List[TransactionResponse]

    class Config:
        orm_mode = True

class UserPreference(BaseModel):
    """사용자 환경설정"""
    language: Language = Field(Language.KO, description="선호 언어")
    timezone: TimeZone = Field(TimeZone.UTC, description="선호 시간대")
    currency: Currency = Field(Currency.KRW, description="선호 통화") 