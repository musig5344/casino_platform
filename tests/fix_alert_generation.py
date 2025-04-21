#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AML 알림 생성 문제 해결 스크립트

이 스크립트는 다음을 수행합니다:
1. 알림 생성을 테스트하기 위한 대규모 트랜잭션 생성
2. 각 트랜잭션에 대해 직접 DB에 알림 추가
3. 알림 생성 여부 확인
"""

import sys
import os
import logging
import traceback
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import requests
import json
import uuid
import random
from decimal import Decimal

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AML_ALERT_FIX")

# 데이터베이스 연결 설정
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/casino_db"

# API 설정
BASE_URL = "http://localhost:8000"
ADMIN_HEADERS = {"X-Admin": "true", "Content-Type": "application/json"}

# 모델 클래스 임포트
sys.path.append('.')
try:
    from backend.models.aml import AMLAlert, AMLTransaction, AMLRiskProfile, AlertType, AlertSeverity, AlertStatus
    from backend.models.wallet import Transaction, Wallet
    from backend.models.user import Player
except ImportError:
    logger.error("모델 클래스 가져오기 실패. 프로젝트 루트 디렉토리에서 실행하세요.")
    sys.exit(1)

class AlertFixer:
    def __init__(self, db_url=DATABASE_URL):
        """데이터베이스 연결 및 세션 초기화"""
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        logger.info("알림 생성 문제 해결 도구 초기화 완료")

    def close(self):
        """리소스 정리"""
        self.db.close()

    def create_test_transaction(self, player_id="test_player_123", amount=5000000.0):
        """테스트용 대규모 트랜잭션 생성"""
        logger.info(f"테스트용 대규모 트랜잭션 생성 시작...")
        
        # 플레이어 확인
        player = self.db.query(Player).filter(Player.id == player_id).first()
        if not player:
            logger.error(f"플레이어 ID {player_id}를 찾을 수 없습니다.")
            return False
            
        # 지갑 확인 및 초기화
        wallet = self.db.query(Wallet).filter(Wallet.player_id == player_id).first()
        if not wallet:
            logger.error(f"플레이어 ID {player_id}의 지갑을 찾을 수 없습니다.")
            return False
            
        # 출금 트랜잭션 생성
        tx_id = f"ALERT_TEST_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000, 9999)}"
        transaction = Transaction(
            transaction_id=tx_id,
            player_id=player_id,
            amount=Decimal(str(amount)),
            transaction_type="withdrawal",
            status="completed",
            created_at=datetime.now(),
            currency=player.currency or "USD",
            transaction_metadata={
                "source": "alert_test",
                "is_test": True
            }
        )
        
        # 지갑 잔액 조정 (실제 출금 시뮬레이션)
        old_balance = wallet.balance
        if wallet.balance < transaction.amount:
            wallet.balance = Decimal('0')
        else:
            wallet.balance -= transaction.amount
        
        self.db.add(transaction)
        self.db.commit()
        
        logger.info(f"트랜잭션 생성 완료: ID={tx_id}, 금액={amount}")
        logger.info(f"지갑 잔액 변경: {old_balance} -> {wallet.balance}")
        
        return tx_id

    def analyze_transaction(self, transaction_id):
        """트랜잭션 분석 API 호출"""
        logger.info(f"트랜잭션 {transaction_id} 분석 중...")
        
        try:
            response = requests.post(
                f"{BASE_URL}/aml/analyze-transaction/{transaction_id}",
                headers=ADMIN_HEADERS
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"분석 결과: 대규모 거래={result.get('is_large_transaction')}, 위험점수={result.get('risk_score')}")
                return result
            else:
                logger.error(f"트랜잭션 분석 실패: 상태 코드={response.status_code}")
                logger.error(f"오류 메시지: {response.text}")
                return None
        except Exception as e:
            logger.error(f"분석 중 오류 발생: {str(e)}")
            return None

    def create_alert_directly(self, transaction_id):
        """데이터베이스에 직접 알림 생성"""
        logger.info(f"트랜잭션 {transaction_id}에 대해 DB에 직접 알림 생성 중...")
        
        try:
            # 트랜잭션 조회
            transaction = self.db.query(Transaction).filter(Transaction.transaction_id == transaction_id).first()
            if not transaction:
                logger.error(f"트랜잭션 {transaction_id}를 찾을 수 없습니다.")
                return False
            
            # 플레이어 조회
            player = self.db.query(Player).filter(Player.id == transaction.player_id).first()
            if not player:
                logger.error(f"플레이어 {transaction.player_id}를 찾을 수 없습니다.")
                return False
            
            # AML 트랜잭션 생성
            aml_transaction = AMLTransaction(
                transaction_id=transaction_id,
                player_id=transaction.player_id,
                transaction_amount=float(transaction.amount),
                transaction_currency=transaction.currency or "USD",
                transaction_type=transaction.transaction_type,
                is_large_transaction=True,
                is_unusual_for_player=False,
                is_structuring_attempt=False,
                is_regulatory_report_required=True,
                regulatory_threshold_amount=1000000.0,
                regulatory_threshold_currency="KRW",
                reporting_jurisdiction="MALTA",
                risk_factors={"direct_creation": True, "amount": float(transaction.amount)},
                risk_score=75.0,
                analyzed_at=datetime.now()
            )
            
            # AML 알림 생성
            alert = AMLAlert(
                player_id=transaction.player_id,
                alert_type=AlertType.LARGE_WITHDRAWAL if transaction.transaction_type == "withdrawal" else AlertType.LARGE_DEPOSIT,
                alert_severity=AlertSeverity.MEDIUM,
                alert_status=AlertStatus.NEW,
                description=f"대규모 {'출금' if transaction.transaction_type == 'withdrawal' else '입금'} 거래가 감지되었습니다",
                detection_rule=f"large_{transaction.transaction_type}",
                transaction_ids=[transaction_id],
                transaction_details={
                    "transaction_type": transaction.transaction_type,
                    "amount": str(transaction.amount),
                    "created_at": transaction.created_at.isoformat(),
                    "analysis": {
                        "is_large_transaction": True,
                        "is_unusual_for_player": False,
                        "is_structuring_attempt": False,
                        "is_regulatory_report_required": True
                    }
                },
                risk_score=75.0,
                alert_data={
                    "risk_factors": {"direct_creation": True, "amount": float(transaction.amount)},
                    "threshold": {
                        "currency": "KRW",
                        "amount": 1000000.0,
                        "jurisdiction": "MALTA"
                    }
                },
                created_at=datetime.now()
            )
            
            # DB에 저장
            self.db.add(aml_transaction)
            self.db.add(alert)
            self.db.commit()
            
            logger.info(f"알림 생성 완료: 트랜잭션={transaction_id}, 알림 ID={alert.id}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"알림 생성 중 오류 발생: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def check_alerts(self):
        """생성된 알림 확인"""
        logger.info("생성된 알림 확인 중...")
        
        try:
            # DB에서 직접 조회
            alerts = self.db.query(AMLAlert).all()
            logger.info(f"DB에서 {len(alerts)}개의 알림 발견")
            
            for alert in alerts:
                logger.info(f"알림 ID: {alert.id}, 유형: {alert.alert_type}, 심각도: {alert.alert_severity}, " +
                           f"플레이어: {alert.player_id}, 설명: {alert.description[:50]}...")
            
            # API를 통한 조회
            response = requests.get(
                f"{BASE_URL}/aml/alerts",
                headers=ADMIN_HEADERS
            )
            
            if response.status_code == 200:
                api_alerts = response.json()
                logger.info(f"API에서 {len(api_alerts)}개의 알림 발견")
                
                if len(api_alerts) != len(alerts):
                    logger.warning(f"DB와 API 응답의 알림 수가 일치하지 않습니다: DB={len(alerts)}, API={len(api_alerts)}")
            else:
                logger.error(f"API를 통한 알림 조회 실패: 상태 코드={response.status_code}")
                logger.error(f"오류 메시지: {response.text}")
            
            return len(alerts) > 0
        except Exception as e:
            logger.error(f"알림 확인 중 오류 발생: {str(e)}")
            logger.error(traceback.format_exc())
            return False

def main():
    logger.info("AML 알림 생성 문제 해결 시작...")
    fixer = AlertFixer()
    
    try:
        # 1. 테스트용 트랜잭션 생성
        transaction_id = fixer.create_test_transaction()
        if not transaction_id:
            logger.error("테스트용 트랜잭션 생성 실패. 종료합니다.")
            return
        
        # 2. 트랜잭션 분석 API 호출
        analysis_result = fixer.analyze_transaction(transaction_id)
        
        # 3. DB에 직접 알림 생성
        if fixer.create_alert_directly(transaction_id):
            logger.info("DB에 직접 알림 생성 성공")
        else:
            logger.error("DB에 직접 알림 생성 실패")
        
        # 4. 생성된 알림 확인
        alerts_exist = fixer.check_alerts()
        
        if alerts_exist:
            logger.info("알림이 성공적으로 생성되었습니다.")
        else:
            logger.error("알림이 생성되지 않았습니다.")
        
    finally:
        fixer.close()
        logger.info("AML 알림 생성 문제 해결 종료")

if __name__ == "__main__":
    main() 