from sqlalchemy import Column, String, event
from sqlalchemy.orm import relationship
from backend.database import Base # Adjusted import path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class Player(Base):
    __tablename__ = "players"

    id = Column(String(50), primary_key=True, index=True)
    # 이름과 성 필드
    first_name = Column(String(200), nullable=False)
    last_name = Column(String(200), nullable=False)
    country = Column(String(2), nullable=False)
    currency = Column(String(3), nullable=False)
    
    # 관계 설정
    game_history = relationship("GameHistory", back_populates="player", cascade="all, delete-orphan")
    wallet = relationship("Wallet", back_populates="player", uselist=False, cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="player", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        """객체를 딕셔너리로 변환"""
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "country": self.country,
            "currency": self.currency
        }

# 사용자 모델
class User(Base):
    __tablename__ = "users"
    
    id = Column(String(50), primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)
    is_active = Column(String(10), default="true", nullable=False)
    is_admin = Column(String(10), default="false", nullable=False) 