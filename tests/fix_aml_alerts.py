#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AML 알림 생성 및 문제 해결 스크립트

이 스크립트는 다음을 수행합니다:
1. 기존 AML 알림 확인
2. 직접 데이터베이스에 알림 추가
3. 트랜잭션 ID로 알림 생성 테스트
"""

import os
import sys
import logging
import argparse
import json
from datetime import datetime, timedelta
import uuid
import requests
from decimal import Decimal

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AML_ALERT_FIX")

# DB 연결 설정
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Float, Boolean, JSON, Table, MetaData, ARRAY, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import text

# .env에서 환경 변수 로드
from dotenv import load_dotenv
load_dotenv()

# DB 설정 - 환경 변수에서 DB_URL 가져오기
DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/casino_db")
logger.info(f"데이터베이스 URL: {DB_URL}")

try:
    engine = create_engine(DB_URL)
    Base = declarative_base()
    Session = sessionmaker(bind=engine)
    logger.info("데이터베이스 엔진 초기화 완료")
except Exception as e:
    logger.error(f"데이터베이스 엔진 초기화 오류: {str(e)}")
    sys.exit(1)

# API 설정
BASE_URL = "http://localhost:8000"
ADMIN_HEADERS = {"X-Admin": "true", "Content-Type": "application/json"}

# 모델 정의 (필수 테이블만)
class Player(Base):
    __tablename__ = "players"
    id = Column(String, primary_key=True)
    username = Column(String)
    email = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Wallet(Base):
    __tablename__ = "wallets"
    player_id = Column(String, primary_key=True)
    balance = Column(Float)
    currency = Column(String)
    
class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    player_id = Column(String)
    transaction_type = Column(String)
    amount = Column(Float)
    transaction_id = Column(String)
    created_at = Column(DateTime)
    original_transaction_id = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    game_id = Column(String, nullable=True)
    session_id = Column(String, nullable=True)
    transaction_metadata = Column(JSON, nullable=True)

class AMLTransaction(Base):
    __tablename__ = "aml_transactions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String)
    player_id = Column(String)
    risk_score = Column(Float, default=0.0)
    risk_factors = Column(JSON, default=dict)
    is_suspicious = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class AMLAlert(Base):
    __tablename__ = "aml_alerts"
    id = Column(Integer, primary_key=True)
    player_id = Column(String)
    alert_type = Column(String)  # USER-DEFINED 타입이지만 String으로 처리
    alert_severity = Column(String)  # severity 대신 alert_severity
    alert_status = Column(String)  # status 대신 alert_status
    description = Column(Text)
    detection_rule = Column(String)
    risk_score = Column(Float)
    created_at = Column(DateTime)
    reviewed_by = Column(String, nullable=True)  # created_by 대신 reviewed_by
    review_notes = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    transaction_ids = Column(ARRAY(String))  # ARRAY 타입
    transaction_details = Column(JSON, nullable=True)
    alert_data = Column(JSON, nullable=True)
    reported_at = Column(DateTime, nullable=True)
    report_reference = Column(String, nullable=True)

class AMLRiskProfile(Base):
    __tablename__ = "aml_risk_profiles"
    id = Column(Integer, primary_key=True)
    player_id = Column(String)
    overall_risk_score = Column(Float, default=50.0)
    deposit_risk_score = Column(Float, default=50.0)
    withdrawal_risk_score = Column(Float, default=50.0)
    gameplay_risk_score = Column(Float, default=50.0)
    is_active = Column(Boolean, default=True)
    last_deposit_at = Column(DateTime, nullable=True)
    last_withdrawal_at = Column(DateTime, nullable=True)
    last_played_at = Column(DateTime, nullable=True)
    deposit_count_7d = Column(Integer, default=0)
    deposit_amount_7d = Column(Float, default=0.0)
    withdrawal_count_7d = Column(Integer, default=0)
    withdrawal_amount_7d = Column(Float, default=0.0)
    deposit_count_30d = Column(Integer, default=0)
    deposit_amount_30d = Column(Float, default=0.0)
    withdrawal_count_30d = Column(Integer, default=0)
    withdrawal_amount_30d = Column(Float, default=0.0)
    wager_to_deposit_ratio = Column(Float, default=0.0)
    withdrawal_to_deposit_ratio = Column(Float, default=0.0)
    risk_factors = Column(JSON, default=dict)
    risk_mitigation = Column(JSON, default=dict)
    last_assessment_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class AMLFixer:
    def __init__(self):
        """초기화"""
        try:
            self.session = Session()
            logger.info("AML 알림 문제 해결 도구 초기화 완료")
        except Exception as e:
            logger.error(f"데이터베이스 세션 초기화 실패: {str(e)}")
            raise
    
    def close(self):
        """세션 종료"""
        self.session.close()
        logger.info("세션 종료")
    
    def check_alerts(self):
        """기존 AML 알림 확인"""
        try:
            # 직접 SQL 쿼리로 알림 조회
            result = self.session.execute(text("SELECT COUNT(*) FROM aml_alerts"))
            count = result.scalar()
            logger.info(f"기존 알림 수: {count}")
            
            # 알림 목록 가져오기
            if count > 0:
                result = self.session.execute(text("SELECT id, player_id, alert_type, alert_severity, alert_status, created_at FROM aml_alerts ORDER BY created_at DESC LIMIT 10"))
                alerts = result.fetchall()
                logger.info("최근 알림 10개:")
                for alert in alerts:
                    logger.info(f"  ID: {alert[0]}, 플레이어: {alert[1]}, 유형: {alert[2]}, 심각도: {alert[3]}, 상태: {alert[4]}, 생성: {alert[5]}")
            
            # API 호출을 통한 확인도 시도
            try:
                response = requests.get(f"{BASE_URL}/aml/alerts", headers=ADMIN_HEADERS)
                if response.status_code == 200:
                    api_alerts = response.json()
                    logger.info(f"API를 통해 조회된 알림 수: {len(api_alerts)}")
                else:
                    logger.warning(f"API 호출 오류: 상태 코드 {response.status_code}")
            except Exception as e:
                logger.error(f"API 호출 중 오류: {str(e)}")
            
            return count
        except Exception as e:
            logger.error(f"알림 확인 중 오류: {str(e)}")
            return 0
    
    def create_large_transaction(self, player_id="test_player_123", amount=10000000.0):
        """테스트를 위한 대규모 거래 생성"""
        try:
            # 지갑 조회
            wallet = self.session.query(Wallet).filter(Wallet.player_id == player_id).first()
            
            if not wallet:
                logger.error(f"플레이어 ID {player_id}에 대한 지갑을 찾을 수 없습니다.")
                return None
            
            # 거래 ID 생성
            tx_id = str(uuid.uuid4())
            
            # 거래 생성
            transaction = Transaction(
                player_id=player_id,
                transaction_type="withdrawal",
                amount=-amount,  # 출금은 음수
                transaction_id=tx_id,
                created_at=datetime.utcnow(),
                transaction_metadata={"description": "테스트 대규모 출금", "test": True}
            )
            
            # 지갑 잔액이 충분한지 확인
            if wallet.balance + amount < 0:
                # 자금이 부족하면 먼저 입금
                deposit_tx_id = str(uuid.uuid4())
                
                deposit = Transaction(
                    player_id=player_id,
                    transaction_type="deposit",
                    amount=amount + 1000000,  # 충분한 금액 입금
                    transaction_id=deposit_tx_id,
                    created_at=datetime.utcnow() - timedelta(minutes=5),  # 5분 전에 입금
                    transaction_metadata={"description": "테스트 입금", "test": True}
                )
                
                wallet.balance += amount + 1000000
                self.session.add(deposit)
                self.session.commit()
                logger.info(f"입금 거래가 생성되었습니다. ID: {deposit.id}, 금액: {amount + 1000000}")
            
            # 출금 거래 추가 및 지갑 업데이트
            wallet.balance += amount  # 출금은 음수
            self.session.add(transaction)
            self.session.commit()
            
            logger.info(f"대규모 거래가 생성되었습니다. ID: {transaction.id}, 금액: {amount}")
            return transaction
        except Exception as e:
            self.session.rollback()
            logger.error(f"거래 생성 중 오류: {str(e)}")
            return None
    
    def create_alert_directly(self, transaction, alert_type="LARGE_WITHDRAWAL", severity="high"):
        """직접 DB에 알림 생성"""
        try:
            if not transaction:
                logger.error("거래 정보가 없습니다.")
                return None
            
            # 먼저 AML 거래 생성
            aml_transaction = AMLTransaction(
                id=str(uuid.uuid4()),
                transaction_id=transaction.id,
                player_id=transaction.wallet.player_id,
                risk_score=85.0,
                risk_factors={"large_amount": True, "unusual_pattern": False},
                is_suspicious=True,
                created_at=datetime.utcnow()
            )
            
            self.session.add(aml_transaction)
            self.session.commit()
            logger.info(f"AML 거래가 생성되었습니다. ID: {aml_transaction.id}")
            
            # transaction_ids는 배열이어야 합니다
            transaction_dict = {
                "id": transaction.id,
                "amount": transaction.amount,
                "type": transaction.transaction_type,
                "currency": transaction.currency,
                "timestamp": transaction.created_at.isoformat() if hasattr(transaction.created_at, 'isoformat') else str(transaction.created_at)
            }
            
            # 알림 생성
            alert = AMLAlert(
                player_id=transaction.wallet.player_id,
                transaction_ids=[transaction.id],  # 배열로 전달
                alert_type=alert_type,
                alert_severity=severity,
                alert_status="open",
                description=f"대규모 거래 감지: {abs(transaction.amount):,.2f} {transaction.currency}",
                detection_rule="large_withdrawal_threshold",
                risk_score=85.0,
                created_at=datetime.utcnow(),
                reviewed_by="system",
                review_notes="자동 생성된 알림",
                reviewed_at=None,
                transaction_details=transaction_dict,
                alert_data={"risk_score": 85.0, "risk_factors": {"large_amount": True, "unusual_pattern": False}},
                reported_at=None,
                report_reference=None
            )
            
            self.session.add(alert)
            self.session.commit()
            logger.info(f"알림이 직접 생성되었습니다. ID: {alert.id}")
            
            return alert
        except Exception as e:
            self.session.rollback()
            logger.error(f"알림 직접 생성 중 오류: {str(e)}")
            return None
    
    def analyze_transaction(self, transaction_id):
        """거래 분석 API 호출 테스트"""
        try:
            response = requests.post(
                f"{BASE_URL}/aml/analyze-transaction/{transaction_id}",
                headers=ADMIN_HEADERS
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"거래 분석 성공: {json.dumps(result, indent=2)}")
                return result
            else:
                logger.warning(f"거래 분석 API 오류: 상태 코드 {response.status_code}")
                logger.warning(f"응답: {response.text}")
                return None
        except Exception as e:
            logger.error(f"거래 분석 API 호출 중 오류: {str(e)}")
            return None
    
    def fix_risk_profile(self, player_id="test_player_123"):
        """위험 프로필 업데이트"""
        try:
            # 위험 프로필 조회
            risk_profile = self.session.query(AMLRiskProfile).filter(AMLRiskProfile.player_id == player_id).first()
            
            if not risk_profile:
                logger.error(f"플레이어 ID {player_id}에 대한 위험 프로필을 찾을 수 없습니다.")
                # 위험 프로필이 없으면 새로 생성
                risk_profile = AMLRiskProfile(
                    player_id=player_id,
                    overall_risk_score=50.0,
                    deposit_risk_score=50.0,
                    withdrawal_risk_score=50.0,
                    gameplay_risk_score=50.0,
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                self.session.add(risk_profile)
                self.session.commit()
                logger.info(f"플레이어 ID {player_id}에 대한 위험 프로필을 생성했습니다.")
                return risk_profile
            
            # 거래 집계 (7일 전부터 현재까지)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            
            # 7일 동안의 거래 집계
            deposits = self.session.query(Transaction).filter(
                Transaction.player_id == player_id,
                Transaction.transaction_type == "deposit",
                Transaction.created_at >= seven_days_ago
            ).all()
            
            withdrawals = self.session.query(Transaction).filter(
                Transaction.player_id == player_id,
                Transaction.transaction_type == "withdrawal",
                Transaction.created_at >= seven_days_ago
            ).all()
            
            bets = self.session.query(Transaction).filter(
                Transaction.player_id == player_id,
                Transaction.transaction_type == "bet",
                Transaction.created_at >= seven_days_ago
            ).all()
            
            # 집계 데이터 저장
            risk_profile.deposit_count_7d = len(deposits)
            risk_profile.deposit_amount_7d = sum(abs(t.amount) for t in deposits)
            risk_profile.withdrawal_count_7d = len(withdrawals)
            risk_profile.withdrawal_amount_7d = sum(abs(t.amount) for t in withdrawals)
            
            # 30일 통계도 추가
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            
            deposits_30d = self.session.query(Transaction).filter(
                Transaction.player_id == player_id,
                Transaction.transaction_type == "deposit",
                Transaction.created_at >= thirty_days_ago,
                Transaction.created_at < seven_days_ago
            ).all()
            
            withdrawals_30d = self.session.query(Transaction).filter(
                Transaction.player_id == player_id,
                Transaction.transaction_type == "withdrawal",
                Transaction.created_at >= thirty_days_ago,
                Transaction.created_at < seven_days_ago
            ).all()
            
            risk_profile.deposit_count_30d = len(deposits_30d) + risk_profile.deposit_count_7d
            risk_profile.deposit_amount_30d = sum(abs(t.amount) for t in deposits_30d) + risk_profile.deposit_amount_7d
            risk_profile.withdrawal_count_30d = len(withdrawals_30d) + risk_profile.withdrawal_count_7d
            risk_profile.withdrawal_amount_30d = sum(abs(t.amount) for t in withdrawals_30d) + risk_profile.withdrawal_amount_7d
            
            # 최신 거래 시간 업데이트
            if deposits:
                latest_deposit = max(deposits, key=lambda x: x.created_at)
                risk_profile.last_deposit_at = latest_deposit.created_at
            
            if withdrawals:
                latest_withdrawal = max(withdrawals, key=lambda x: x.created_at)
                risk_profile.last_withdrawal_at = latest_withdrawal.created_at
            
            if bets:
                latest_bet = max(bets, key=lambda x: x.created_at)
                risk_profile.last_played_at = latest_bet.created_at
            
            # 위험 점수 업데이트 (간단한 예시)
            if risk_profile.withdrawal_amount_7d > 5000000:  # 500만원 이상 출금
                risk_profile.withdrawal_risk_score = 80.0
            
            bet_amount = sum(abs(t.amount) for t in bets)
            if risk_profile.deposit_amount_7d > 0:
                # 베팅/입금 비율 계산
                risk_profile.wager_to_deposit_ratio = bet_amount / risk_profile.deposit_amount_7d
                # 출금/입금 비율 계산
                risk_profile.withdrawal_to_deposit_ratio = risk_profile.withdrawal_amount_7d / risk_profile.deposit_amount_7d
                
                if risk_profile.wager_to_deposit_ratio < 0.5:  # 베팅이 입금의 50% 미만
                    risk_profile.gameplay_risk_score = 75.0
            
            # 위험 요소 업데이트
            risk_factors = {
                "large_withdrawals": risk_profile.withdrawal_amount_7d > 5000000,
                "low_wager_ratio": risk_profile.wager_to_deposit_ratio < 0.5 if risk_profile.deposit_amount_7d > 0 else False,
                "frequent_deposits": risk_profile.deposit_count_7d > 5,
                "frequent_withdrawals": risk_profile.withdrawal_count_7d > 3
            }
            risk_profile.risk_factors = risk_factors
            
            # 위험 점수 종합
            risk_profile.overall_risk_score = (
                risk_profile.deposit_risk_score + 
                risk_profile.withdrawal_risk_score + 
                risk_profile.gameplay_risk_score
            ) / 3
            
            # 평가 시간 업데이트
            risk_profile.last_assessment_at = datetime.utcnow()
            risk_profile.updated_at = datetime.utcnow()
            
            self.session.commit()
            logger.info(f"위험 프로필이 업데이트되었습니다. 플레이어 ID: {player_id}")
            
            return risk_profile
        except Exception as e:
            self.session.rollback()
            logger.error(f"위험 프로필 업데이트 중 오류: {str(e)}")
            return None
    
    def check_risk_profile(self, player_id="test_player_123"):
        """위험 프로필 조회"""
        try:
            # 직접 DB 조회
            risk_profile = self.session.query(AMLRiskProfile).filter(AMLRiskProfile.player_id == player_id).first()
            
            if risk_profile:
                logger.info(f"위험 프로필 (DB): 플레이어 ID {player_id}, 위험 점수: {risk_profile.overall_risk_score}")
                logger.info(f"상세 위험 점수: 입금={risk_profile.deposit_risk_score}, "
                           f"출금={risk_profile.withdrawal_risk_score}, "
                           f"게임플레이={risk_profile.gameplay_risk_score}")
                logger.info(f"마지막 입금: {risk_profile.last_deposit_at}")
                logger.info(f"마지막 출금: {risk_profile.last_withdrawal_at}")
                logger.info(f"마지막 게임: {risk_profile.last_played_at}")
                logger.info(f"7일 통계: 입금 {risk_profile.deposit_count_7d}건 ({risk_profile.deposit_amount_7d:,.2f}), "
                           f"출금 {risk_profile.withdrawal_count_7d}건 ({risk_profile.withdrawal_amount_7d:,.2f})")
                logger.info(f"생성 시간: {risk_profile.created_at}, 마지막 평가: {risk_profile.last_assessment_at}")
            else:
                logger.warning(f"플레이어 ID {player_id}에 대한 위험 프로필을 찾을 수 없습니다.")
            
            # API 호출을 통한 조회
            try:
                response = requests.get(
                    f"{BASE_URL}/aml/player/{player_id}/risk-profile",
                    headers=ADMIN_HEADERS
                )
                
                if response.status_code == 200:
                    api_profile = response.json()
                    logger.info(f"위험 프로필 (API): 플레이어 ID {player_id}, 위험 점수: {api_profile.get('overall_risk_score')}")
                else:
                    logger.warning(f"위험 프로필 API 오류: 상태 코드 {response.status_code}")
            except Exception as e:
                logger.error(f"위험 프로필 API 호출 중 오류: {str(e)}")
            
            return risk_profile
        except Exception as e:
            logger.error(f"위험 프로필 조회 중 오류: {str(e)}")
            return None

def main():
    parser = argparse.ArgumentParser(description="AML 알림 문제 해결 도구")
    parser.add_argument("--check-only", action="store_true", help="기존 알림만 확인")
    parser.add_argument("--player-id", default="test_player_123", help="테스트할 플레이어 ID")
    parser.add_argument("--amount", type=float, default=10000000.0, help="테스트 거래 금액")
    parser.add_argument("--check-schema", action="store_true", help="테이블 스키마 확인")
    args = parser.parse_args()
    
    logger.info("AML 알림 문제 해결 시작...")
    
    if args.check_schema:
        # 데이터베이스에 직접 연결하여 테이블 스키마 확인
        try:
            engine = create_engine(DB_URL)
            conn = engine.connect()
            
            # 테이블 목록 확인
            result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
            tables = [row[0] for row in result]
            logger.info(f"데이터베이스 테이블 목록: {', '.join(tables)}")
            
            # 각 테이블별 스키마 확인
            for table_name in ['aml_alerts', 'aml_risk_profiles', 'wallets', 'transactions']:
                if table_name in tables:
                    result = conn.execute(text(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table_name}'"))
                    columns = list(result)
                    logger.info(f"\n{table_name.upper()} 테이블 스키마: ({len(columns)}개 컬럼)")
                    for row in columns:
                        logger.info(f"  {row[0]} - {row[1]}")
                else:
                    logger.info(f"{table_name} 테이블이 존재하지 않습니다.")
            
            conn.close()
            return
        except Exception as e:
            logger.error(f"스키마 확인 중 오류: {str(e)}")
            return
    
    fixer = AMLFixer()
    
    try:
        # 1. 기존 알림 확인
        logger.info("기존 알림 확인 중...")
        existing_alerts = fixer.check_alerts()
        
        if args.check_only:
            logger.info("확인 모드 종료")
            fixer.close()
            return
        
        # 아래 코드는 주석처리하고 check_only 모드만 실행
        """
        # 2. 위험 프로필 조회
        logger.info("위험 프로필 조회 중...")
        fixer.check_risk_profile(args.player_id)
        
        # 3. 대규모 거래 생성
        logger.info(f"테스트 거래 생성 중... (금액: {args.amount:,.2f})")
        transaction = fixer.create_large_transaction(args.player_id, args.amount)
        
        if transaction:
            # 4. API로 거래 분석 시도
            logger.info("API로 거래 분석 중...")
            analysis_result = fixer.analyze_transaction(transaction.id)
            
            # 5. API 결과에 따라 직접 알림 생성 여부 결정
            if not analysis_result or "alert_created" not in analysis_result or not analysis_result["alert_created"]:
                logger.warning("API 분석에서 알림이 생성되지 않음. 직접 알림 생성 시도...")
                fixer.create_alert_directly(transaction)
            
            # 6. 최종 알림 확인
            logger.info("최종 알림 확인 중...")
            final_alerts = fixer.check_alerts()
            
            # 7. 위험 프로필 업데이트
            logger.info("위험 프로필 업데이트 중...")
            fixer.fix_risk_profile(args.player_id)
            
            # 8. 업데이트된 위험 프로필 확인
            logger.info("업데이트된 위험 프로필 확인 중...")
            fixer.check_risk_profile(args.player_id)
        """
        
        logger.info("AML 알림 문제 해결 완료")
    finally:
        fixer.close()

if __name__ == "__main__":
    main() 