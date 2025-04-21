from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.database import Base


class GameHistory(Base):
    __tablename__ = "game_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), ForeignKey("players.id"), nullable=False, index=True)
    game_type = Column(String, nullable=False, index=True)  # "baccarat", "roulette", 등
    room_id = Column(String, nullable=False, index=True)
    bet_amount = Column(Float, nullable=False)
    bet_type = Column(String, nullable=False)  # "player", "banker", "tie" 등
    result = Column(String, nullable=False)  # "win", "lose", "tie" 등
    payout = Column(Float, nullable=False)
    game_data = Column(JSON, nullable=True)  # 게임 세부 정보
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 관계 설정
    player = relationship("Player", back_populates="game_history")
    
    # 복합 인덱스 추가
    __table_args__ = (
        # 사용자별 게임 타입 조회 최적화
        Index('ix_game_history_user_game_type', user_id, game_type),
        # 날짜별 조회 최적화
        Index('ix_game_history_user_date', user_id, created_at.desc()),
        # 게임 타입별 날짜 조회 최적화
        Index('ix_game_history_game_type_date', game_type, created_at.desc()),
    )
    
    def to_dict(self):
        """GameHistory 객체를 직렬화 가능한 사전으로 변환합니다."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "game_type": self.game_type,
            "room_id": self.room_id,
            "bet_amount": self.bet_amount,
            "bet_type": self.bet_type, 
            "result": self.result,
            "payout": self.payout,
            "game_data": self.game_data,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class BaccaratRound(Base):
    __tablename__ = "baccarat_rounds"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String, nullable=False, index=True)
    player_cards = Column(JSON, nullable=False)
    banker_cards = Column(JSON, nullable=False)
    player_score = Column(Integer, nullable=False)
    banker_score = Column(Integer, nullable=False)
    result = Column(String, nullable=False, index=True)  # "player", "banker", "tie"
    shoe_number = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # 복합 인덱스 추가
    __table_args__ = (
        # 방별 슈 번호 조회 최적화
        Index('ix_baccarat_rounds_room_shoe', room_id, shoe_number),
        # 방별 날짜 조회 최적화
        Index('ix_baccarat_rounds_room_date', room_id, created_at.desc()),
    )
    
    def to_dict(self):
        """BaccaratRound 객체를 직렬화 가능한 사전으로 변환합니다."""
        return {
            "id": self.id,
            "room_id": self.room_id,
            "player_cards": self.player_cards,
            "banker_cards": self.banker_cards,
            "player_score": self.player_score,
            "banker_score": self.banker_score,
            "result": self.result,
            "shoe_number": self.shoe_number,
            "created_at": self.created_at.isoformat() if self.created_at else None
        } 