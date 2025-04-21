from sqlalchemy import Column, String, DECIMAL, ForeignKey, TIMESTAMP, func, Integer, JSON, Index
from sqlalchemy.orm import relationship, foreign, remote
from backend.database import Base, engine
from backend.models.user import Player # Player 모델 임포트

class Wallet(Base):
    __tablename__ = "wallets"

    player_id = Column(String(50), ForeignKey("players.id"), primary_key=True)
    balance = Column(DECIMAL(10, 2), nullable=False, default=0.00, server_default='0.00')
    currency = Column(String(3), nullable=False) # CHAR 대신 String 사용 (SQLAlchemy 일반적)

    # Player 모델과의 관계 설정
    player = relationship("Player", back_populates="wallet")
    
    # 거래 목록과의 관계 설정 - foreign 함수 사용하여 명시적 외래 키 참조
    transactions = relationship(
        "Transaction", 
        back_populates="wallet",
        primaryjoin="foreign(Wallet.player_id)==Transaction.player_id",
        viewonly=True  # 단방향 관계로 설정
    )

class Transaction(Base):
    __tablename__ = "transactions"

    # SERIAL PRIMARY KEY는 Integer + primary_key=True + autoincrement=True로 표현
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(String(50), ForeignKey("players.id"), nullable=False, index=True) # player_id에도 인덱스 추가
    transaction_type = Column(String(10), nullable=False, index=True)  # 'debit', 'credit', 'cancel'
    amount = Column(DECIMAL(10, 2), nullable=False)
    currency = Column(String(3), nullable=False) # 통화 코드 추가
    # 외부 시스템 연동을 위한 거래 고유 식별자 필드 추가
    transaction_id = Column(String(100), index=True, unique=True, nullable=False)
    # 취소 기능 구현 시 원본 트랜잭션 ID 참조 필드
    ref_transaction_id = Column(String(100), nullable=True, index=True) # original_transaction_id -> ref_transaction_id 로 변경되었을 수 있음, API 코드 확인 필요
    # 거래 상태 (예: pending, completed, failed, canceled)
    status = Column(String(10), nullable=False, default='completed', server_default='completed', index=True)
    # 잔액 변경 전/후 기록
    original_balance = Column(DECIMAL(10, 2), nullable=True) 
    updated_balance = Column(DECIMAL(10, 2), nullable=True)
    
    # 외부 게임 통합을 위한 추가 필드
    # 게임 제공자 (예: 'external', 'internal')
    provider = Column(String(20), nullable=True, index=True)
    # 게임 ID
    game_id = Column(String(50), nullable=True, index=True)
    # 게임 세션 ID
    session_id = Column(String(100), nullable=True, index=True)
    # 추가 메타데이터 (JSON 형식)
    transaction_metadata = Column(JSON, nullable=True)

    # 타임스탬프 필드 (기본값 설정)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False, index=True)

    # Player 모델과의 관계 설정
    player = relationship("Player", back_populates="transactions")
    # 지갑과의 관계 설정 - overlaps 매개변수 추가
    wallet = relationship(
        "Wallet",
        back_populates="transactions",
        primaryjoin="Transaction.player_id==foreign(Wallet.player_id)",
        overlaps="player,wallet"
    )
    
    # 복합 인덱스 추가
    __table_args__ = (
        # 플레이어별 트랜잭션 타입 조회 최적화
        Index('ix_transactions_player_type', player_id, transaction_type),
        # 플레이어별 날짜 조회 최적화
        Index('ix_transactions_player_date', player_id, created_at.desc()),
        # 게임별 트랜잭션 조회 최적화
        Index('ix_transactions_game_date', game_id, created_at.desc()),
        # 세션별 트랜잭션 조회 최적화
        Index('ix_transactions_session_date', session_id, created_at.desc()),
    )

# 스키마 업데이트 함수
def add_missing_columns():
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    with engine.connect() as conn:
        try:
            # original_transaction_id 컬럼 추가 시도
            conn.execute(text("""
                ALTER TABLE transactions 
                ADD COLUMN IF NOT EXISTS original_transaction_id VARCHAR(100)
            """))
            
            # provider 컬럼 추가 시도
            conn.execute(text("""
                ALTER TABLE transactions 
                ADD COLUMN IF NOT EXISTS provider VARCHAR(20)
            """))
            
            # game_id 컬럼 추가 시도
            conn.execute(text("""
                ALTER TABLE transactions 
                ADD COLUMN IF NOT EXISTS game_id VARCHAR(50)
            """))
            
            # session_id 컬럼 추가 시도
            conn.execute(text("""
                ALTER TABLE transactions 
                ADD COLUMN IF NOT EXISTS session_id VARCHAR(100)
            """))
            
            # transaction_metadata 컬럼 추가 시도
            conn.execute(text("""
                ALTER TABLE transactions 
                ADD COLUMN IF NOT EXISTS transaction_metadata JSONB
            """))
            
            conn.commit()
            print("트랜잭션 테이블 스키마 업데이트가 완료되었습니다.")
        except ProgrammingError as e:
            print(f"컬럼 추가 중 오류 발생: {e}")
            conn.rollback()

# 서버 시작 시 스키마 업데이트
add_missing_columns() 