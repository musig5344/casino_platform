import uuid
from decimal import Decimal
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import Column, Integer, Float, String, Numeric, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship

from casino_platform.database import Base
from casino_platform.schemas.wallet import TransactionType, TransactionStatus


class Wallet(Base):
    """플레이어 지갑 모델"""
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    balance = Column(Float, default=0.0, nullable=False)
    currency = Column(String(3), default="KRW", nullable=False)
    version = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 관계 설정
    user = relationship("User", back_populates="wallet")
    transactions = relationship("Transaction", back_populates="wallet", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Wallet(id={self.id}, user_id={self.user_id}, balance={self.balance}, currency={self.currency})>"


class Transaction(Base):
    """지갑 트랜잭션 모델"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    type = Column(Enum(TransactionType), nullable=False)
    status = Column(Enum(TransactionStatus), default=TransactionStatus.COMPLETED, nullable=False)
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="KRW")
    description = Column(String, nullable=True)
    reference_id = Column(String(64), nullable=True)
    game_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 관계 설정
    wallet = relationship("Wallet", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction(id={self.id}, wallet_id={self.wallet_id}, type={self.type}, amount={self.amount}, currency={self.currency})>" 