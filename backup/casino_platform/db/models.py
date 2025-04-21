from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from enum import Enum
import uuid
import enum

from sqlalchemy import Column, String, Boolean, Float, DateTime, ForeignKey, Enum as SQLAlchemyEnum, Integer, Numeric, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class UserRole(str, Enum):
    """사용자 역할 정의"""
    PLAYER = "PLAYER"
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"

class TransactionType(enum.Enum):
    """트랜잭션 유형"""
    CREDIT = "credit"  # 입금
    DEBIT = "debit"    # 출금
    BONUS = "bonus"    # 보너스 
    WAGER = "wager"    # 베팅
    WIN = "win"        # 승리
    REFUND = "refund"  # 환불

class User(Base):
    """사용자 모델"""
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLAlchemyEnum(UserRole), nullable=False, default=UserRole.PLAYER)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    
    # 관계 정의
    player = relationship("Player", back_populates="user", uselist=False)
    
    def __repr__(self):
        return f"<User {self.username}>"

class Player(Base):
    """플레이어 모델"""
    __tablename__ = "players"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(50))
    last_name = Column(String(50))
    date_of_birth = Column(DateTime)
    country = Column(String(2))  # ISO 국가 코드
    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 관계 정의
    user = relationship("User", back_populates="player")
    wallet = relationship("Wallet", back_populates="player", uselist=False)
    transactions = relationship("Transaction", back_populates="player")
    sessions = relationship("GameSession", back_populates="player")
    
    def __repr__(self):
        return f"<Player {self.username}>"

class Wallet(Base):
    """플레이어 지갑 모델"""
    __tablename__ = "wallets"
    
    player_id = Column(String(36), primary_key=True)
    balance = Column(Numeric(precision=18, scale=8), default=0, nullable=False)
    currency = Column(String(3), default="KRW", nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    
    def __repr__(self):
        return f"<Wallet(player_id={self.player_id}, balance={self.balance}, currency={self.currency})>"

class Transaction(Base):
    """트랜잭션 모델"""
    __tablename__ = "transactions"
    
    transaction_id = Column(String(64), primary_key=True)
    player_id = Column(String(36), ForeignKey("wallets.player_id"), nullable=False)
    amount = Column(Numeric(precision=18, scale=8), nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False)
    balance_after = Column(Numeric(precision=18, scale=8), nullable=False)
    currency = Column(String(3), default="KRW", nullable=False)
    description = Column(Text, nullable=True)
    game_id = Column(String(36), nullable=True)
    reference_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    
    def __repr__(self):
        return f"<Transaction(id={self.transaction_id}, player_id={self.player_id}, type={self.transaction_type}, amount={self.amount})>"

class Game(Base):
    """게임 모델"""
    __tablename__ = "games"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(Text)
    provider = Column(String(50), nullable=False)
    category = Column(String(50))
    rtp = Column(Float, nullable=True)  # Return To Player 비율
    max_win = Column(Numeric(18, 6), nullable=True)
    min_bet = Column(Numeric(18, 6), nullable=False)
    max_bet = Column(Numeric(18, 6), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    thumbnail_url = Column(String(255))
    
    # 관계 정의
    sessions = relationship("GameSession", back_populates="game")
    transactions = relationship("Transaction", back_populates="game")
    
    def __repr__(self):
        return f"<Game {self.name}>"

class GameSession(Base):
    """게임 세션 모델"""
    __tablename__ = "game_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id = Column(String(36), ForeignKey("players.id"), nullable=False)
    game_id = Column(String(36), ForeignKey("games.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime)
    total_wager = Column(Numeric(precision=15, scale=2), default=0)
    total_win = Column(Numeric(precision=15, scale=2), default=0)
    status = Column(String(20), default="active")  # active, completed, terminated
    currency = Column(String(3), nullable=False)
    
    # 관계 정의
    player = relationship("Player", back_populates="sessions")
    game = relationship("Game", back_populates="sessions")
    transactions = relationship("Transaction")
    
    def __repr__(self):
        return f"<GameSession {self.id}: {self.player_id} playing {self.game_id}>" 