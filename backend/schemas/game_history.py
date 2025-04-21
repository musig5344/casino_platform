from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class BaccaratRoundCreate(BaseModel):
    room_id: str
    player_cards: List[str]
    banker_cards: List[str]
    player_score: int
    banker_score: int
    result: str
    shoe_number: int


class BaccaratRoundResponse(BaccaratRoundCreate):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GameHistoryCreate(BaseModel):
    user_id: str
    game_type: str
    room_id: str
    bet_amount: float
    bet_type: str
    result: str
    payout: float
    game_data: Optional[Dict[str, Any]] = None


class GameHistoryResponse(GameHistoryCreate):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserGameHistoryResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[GameHistoryResponse]


class BaccaratRoundsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[BaccaratRoundResponse]


class BaccaratStats(BaseModel):
    player_wins: int = Field(0, description="플레이어 승리 횟수")
    banker_wins: int = Field(0, description="뱅커 승리 횟수")
    tie_wins: int = Field(0, description="무승부 횟수")
    total_rounds: int = Field(0, description="총 게임 횟수")
    player_win_percentage: float = Field(0.0, description="플레이어 승률")
    banker_win_percentage: float = Field(0.0, description="뱅커 승률")
    tie_percentage: float = Field(0.0, description="무승부 비율")
    last_shoe_results: List[str] = Field([], description="마지막 슈의 결과")
    
    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "player_wins": 42,
                "banker_wins": 45,
                "tie_wins": 9,
                "total_rounds": 96,
                "player_win_percentage": 43.75,
                "banker_win_percentage": 46.88,
                "tie_percentage": 9.38,
                "last_shoe_results": ["B", "P", "T", "B", "B", "P", "B", "P", "B", "P"]
            }
        }
    ) 