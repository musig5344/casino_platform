from typing import Optional, Dict
from enum import Enum
from pydantic import BaseModel
from datetime import datetime

# 외부 게임 관련 요청/응답 스키마
class ResponseStatus(str, Enum):
    OK = "OK"
    ERROR = "ERROR"

class ExternalBalanceRequest(BaseModel):
    player_id: str

class ExternalBalanceResponse(BaseModel):
    status: ResponseStatus
    playerId: str
    currency: str
    cash: str
    bonus: str
    error: Optional[Dict[str, str]] = None

class ExternalDebitRequest(BaseModel):
    player_id: str
    transaction_id: str
    amount: float
    game_id: str
    round_id: str
    table_id: Optional[str] = None

class ExternalCreditRequest(BaseModel):
    player_id: str
    transaction_id: str
    amount: float
    game_id: str
    round_id: str
    table_id: Optional[str] = None

class ExternalCancelRequest(BaseModel):
    player_id: str
    transaction_id: str
    original_transaction_id: str

class ExternalTransactionResponse(BaseModel):
    status: ResponseStatus
    playerId: str
    currency: str = "KRW"
    cash: str = "0"
    bonus: str = "0"
    transactionId: str
    error: Optional[Dict[str, str]] = None

class GameLaunchRequest(BaseModel):
    player_id: str
    game_id: str
    currency: str = "KRW"
    language: str = "ko"
    return_url: Optional[str] = None
    platform: str = "DESKTOP"

class GameLaunchResponse(BaseModel):
    success: bool
    game_url: Optional[str] = None
    session_id: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[datetime] = None
    error: Optional[str] = None 