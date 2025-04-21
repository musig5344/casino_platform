#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AML 시스템 문제 해결 스크립트

1. 알림 생성 문제 해결
2. 위험 점수 계산 문제 해결
3. API 엔드포인트 경로 일관성 확인
"""

import sys
import os
import logging
import traceback
from datetime import datetime, timedelta
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker
import asyncio
import json
import httpx
import random
import argparse

# 시스템 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AML_FIX")

# 데이터베이스 연결 설정
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/casino_db"

# API 설정
API_BASE_URL = "http://localhost:8000"
API_AUTH_TOKEN = "test_auth_token"  # 실제 환경에서는 보안 토큰 사용

# 모델 클래스 임포트 (필요시 backend 모듈 경로 추가)
sys.path.append('.')
try:
    from backend.models.aml import AMLAlert, AMLTransaction, AMLRiskProfile, AlertType, AlertSeverity, AlertStatus
    from backend.models.wallet import Transaction, Wallet
    from backend.models.user import Player
except ImportError:
    logger.error("모델 클래스 가져오기 실패. 프로젝트 루트 디렉토리에서 실행하세요.")
    sys.exit(1)

class AMLFixer:
    def __init__(self, db_url=DATABASE_URL):
        """데이터베이스 연결 및 세션 초기화"""
        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.SessionLocal()
        self.http_client = httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0)
        logger.info("AML 시스템 문제 해결 도구 초기화 완료")

    async def close(self):
        """리소스 정리"""
        await self.http_client.aclose()
        self.db.close()

    async def test_api_endpoints(self):
        """API 엔드포인트 경로 일관성 테스트"""
        logger.info("API 엔드포인트 경로 테스트 시작...")
        
        # 테스트할 엔드포인트 경로들
        endpoints = [
            "/aml/analyze-transaction/",
            "/api/aml/analyze-transaction/",
            "/aml/alerts",
            "/api/aml/alerts"
        ]
        
        for endpoint in endpoints:
            try:
                # 간단한 GET 요청으로 엔드포인트 존재 여부 확인
                response = await self.http_client.get(
                    f"{endpoint}",
                    headers={"Authorization": f"Bearer {API_AUTH_TOKEN}"}
                )
                logger.info(f"엔드포인트 {endpoint}: 상태 코드 {response.status_code}")
                
                # 404가 아닌 경우는 엔드포인트가 존재하는 것 (401, 403 등은 인증 문제일 수 있음)
                if response.status_code != 404:
                    logger.info(f"엔드포인트 {endpoint}가 존재합니다. 상태 코드: {response.status_code}")
                else:
                    logger.warning(f"엔드포인트 {endpoint}가 존재하지 않습니다.")
            except Exception as e:
                logger.error(f"엔드포인트 {endpoint} 테스트 중 오류: {str(e)}")
                
        logger.info("API 엔드포인트 테스트 완료")
    
    async def generate_large_transactions(self, player_id, count=3, min_amount=1_000_000, max_amount=9_000_000):
        """대규모 트랜잭션 생성 테스트"""
        logger.info(f"플레이어 {player_id}에 대해 {count}개의 대규모 트랜잭션 생성 시작...")
        
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
            
        # 지갑에 충분한 금액 추가
        initial_deposit_amount = max_amount * count * 2
        deposit_tx = Transaction(
            transaction_id=f"DEPOSIT_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000, 9999)}",
            player_id=player_id,
            amount=initial_deposit_amount,
            transaction_type="deposit",
            status="completed",
            created_at=datetime.now() - timedelta(days=1),  # 1일 전 입금
            currency=player.currency or "USD"
        )
        wallet.balance += initial_deposit_amount
        self.db.add(deposit_tx)
        self.db.commit()
        logger.info(f"초기 입금 완료: {initial_deposit_amount}")
        
        # 대규모 트랜잭션 생성
        transaction_ids = []
        for i in range(count):
            # 랜덤 대규모 금액 생성
            amount = random.uniform(min_amount, max_amount)
            
            # 출금 트랜잭션 생성
            tx_id = f"LARGE_WITHDRAWAL_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i+1}_{random.randint(1000, 9999)}"
            withdrawal_tx = Transaction(
                transaction_id=tx_id,
                player_id=player_id,
                amount=amount,
                transaction_type="withdrawal",
                status="completed",
                created_at=datetime.now(),
                currency=player.currency or "USD"
            )
            wallet.balance -= amount
            self.db.add(withdrawal_tx)
            transaction_ids.append(tx_id)
            logger.info(f"대규모 출금 트랜잭션 생성 완료: {tx_id}, 금액: {amount}")
            
            # 시간차를 두고 생성 (1-3시간 간격의 과거 트랜잭션)
            await asyncio.sleep(0.5)  # 실제 시간은 빠르게 처리
        
        self.db.commit()
        logger.info(f"{count}개의 대규모 트랜잭션 생성 완료")
        return transaction_ids
    
    async def analyze_transactions(self, transaction_ids):
        """생성된 트랜잭션 분석"""
        logger.info(f"{len(transaction_ids)}개 트랜잭션 분석 시작...")
        
        results = []
        for tx_id in transaction_ids:
            try:
                # AML 분석 API 호출
                response = await self.http_client.post(
                    f"/aml/analyze-transaction/{tx_id}",
                    headers={"Authorization": f"Bearer {API_AUTH_TOKEN}"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"트랜잭션 분석 성공: {tx_id}")
                    logger.info(f"분석 결과: 대규모 거래={result.get('is_large_transaction')}, "
                               f"위험점수={result.get('risk_score')}")
                    results.append(result)
                else:
                    logger.error(f"트랜잭션 분석 실패: {tx_id}, 상태 코드: {response.status_code}")
                    logger.error(f"오류 메시지: {response.text}")
            except Exception as e:
                logger.error(f"트랜잭션 {tx_id} 분석 중 오류: {str(e)}")
                
        logger.info(f"트랜잭션 분석 완료, 성공: {len(results)}/{len(transaction_ids)}")
        return results
    
    async def check_alerts(self):
        """생성된 알림 확인"""
        logger.info("알림 확인 시작...")
        
        try:
            # 데이터베이스에서 직접 알림 조회
            alerts = self.db.query(AMLAlert).all()
            logger.info(f"데이터베이스에서 {len(alerts)}개 알림 발견")
            
            for alert in alerts:
                logger.info(f"알림 ID: {alert.id}, 유형: {alert.alert_type}, 심각도: {alert.alert_severity}, "
                           f"상태: {alert.alert_status}, 생성일: {alert.created_at}")
                
            # API를 통한 알림 조회
            response = await self.http_client.get(
                "/aml/alerts",
                headers={"Authorization": f"Bearer {API_AUTH_TOKEN}"}
            )
            
            if response.status_code == 200:
                api_alerts = response.json()
                logger.info(f"API에서 {len(api_alerts)}개 알림 발견")
            else:
                logger.error(f"API 알림 조회 실패, 상태 코드: {response.status_code}")
                logger.error(f"오류 메시지: {response.text}")
                
            return alerts
        except Exception as e:
            logger.error(f"알림 확인 중 오류: {str(e)}")
            return []
    
    async def check_risk_profiles(self, player_id):
        """플레이어 위험 프로필 확인"""
        logger.info(f"플레이어 {player_id}의 위험 프로필 확인 시작...")
        
        try:
            # 데이터베이스에서 직접 위험 프로필 조회
            profile = self.db.query(AMLRiskProfile).filter(AMLRiskProfile.player_id == player_id).first()
            
            if profile:
                logger.info(f"위험 프로필 찾음: 전체 위험 점수={profile.overall_risk_score}")
                logger.info(f"입금 위험={profile.deposit_risk_score}, 출금 위험={profile.withdrawal_risk_score}")
                logger.info(f"7일 입금 건수={profile.deposit_count_7d}, 금액={profile.deposit_amount_7d}")
                logger.info(f"7일 출금 건수={profile.withdrawal_count_7d}, 금액={profile.withdrawal_amount_7d}")
                logger.info(f"30일 입금 건수={profile.deposit_count_30d}, 금액={profile.deposit_amount_30d}")
                logger.info(f"30일 출금 건수={profile.withdrawal_count_30d}, 금액={profile.withdrawal_amount_30d}")
                
                # API를 통한 위험 프로필 조회
                response = await self.http_client.get(
                    f"/aml/player/{player_id}/risk-profile",
                    headers={"Authorization": f"Bearer {API_AUTH_TOKEN}"}
                )
                
                if response.status_code == 200:
                    api_profile = response.json()
                    logger.info(f"API에서 위험 프로필 조회 성공")
                    
                    # DB와 API 결과 비교
                    if abs(float(profile.overall_risk_score) - float(api_profile.get('overall_risk_score', 0))) > 0.01:
                        logger.warning(f"DB와 API 위험 점수 불일치: DB={profile.overall_risk_score}, API={api_profile.get('overall_risk_score')}")
                else:
                    logger.error(f"API 위험 프로필 조회 실패, 상태 코드: {response.status_code}")
                
                return profile
            else:
                logger.error(f"플레이어 {player_id}의 위험 프로필을 찾을 수 없습니다.")
                return None
        except Exception as e:
            logger.error(f"위험 프로필 확인 중 오류: {str(e)}")
            return None
    
    async def fix_transaction_analysis_issues(self):
        """거래 분석 관련 문제 수정"""
        # 여기서는 문제를 진단하고 로깅만 수행합니다.
        # 실제 수정은 소스 코드 업데이트가 필요할 수 있습니다.
        
        logger.info("거래 분석 관련 문제 진단 시작...")
        
        # 문제 1: _update_risk_profile_from_transaction 함수의 파라미터 불일치 확인
        
        # 소스 코드 체크
        param_issue = """
        [문제점] 함수 _update_risk_profile_from_transaction 의 파라미터가 호출부와 선언부에서 일치하지 않음
        
        - 호출: await self._update_risk_profile_from_transaction(aml_transaction)
        - 선언: async def _update_risk_profile_from_transaction(self, transaction: Transaction, risk_profile: AMLRiskProfile, transaction_risk_score: float)
        
        [해결책] 파라미터를 맞추거나 적절한 변환 로직 추가 필요
        """
        logger.warning(param_issue)
        
        # 문제 2: _create_alert_from_transaction 함수의 매개변수와 반환값 체크
        alert_issue = """
        [문제점] 알림 생성 함수에서 외래키 제약 조건 위반 또는 DB 커밋 문제 발생 가능성
        
        1. alert.id 값이 제대로 설정되지 않을 가능성
        2. transaction_ids 필드가 외래키 제약조건을 위반할 가능성
        3. DB 커밋 시점과 flush 시점 사이에 문제 발생 가능성
        
        [해결책] 
        1. alert 객체 생성 후 명시적 flush 확인
        2. transaction_ids 값의 유효성 검사 추가
        3. 예외 처리시 에러 메시지를 보다 구체적으로 로깅
        """
        logger.warning(alert_issue)
        
        return param_issue, alert_issue

async def main():
    parser = argparse.ArgumentParser(description="AML 시스템 문제 해결 스크립트")
    parser.add_argument("--player", help="테스트할 플레이어 ID", default="test_player_1")
    parser.add_argument("--tx-count", type=int, help="생성할 트랜잭션 수", default=3)
    parser.add_argument("--check-only", action="store_true", help="기존 데이터만 확인")
    parser.add_argument("--fix", action="store_true", help="문제 수정 시도")
    args = parser.parse_args()
    
    fixer = AMLFixer()
    
    try:
        # API 엔드포인트 테스트
        await fixer.test_api_endpoints()
        
        if not args.check_only:
            # 대규모 트랜잭션 생성
            transaction_ids = await fixer.generate_large_transactions(args.player, args.tx_count)
            
            if transaction_ids:
                # 트랜잭션 분석
                analysis_results = await fixer.analyze_transactions(transaction_ids)
                
                # 알림 확인
                alerts = await fixer.check_alerts()
                logger.info(f"분석 후 {len(alerts)}개의 알림 발견")
                
                # 위험 프로필 확인
                await fixer.check_risk_profiles(args.player)
        else:
            # 기존 데이터만 확인
            alerts = await fixer.check_alerts()
            logger.info(f"{len(alerts)}개의 알림 발견")
            await fixer.check_risk_profiles(args.player)
        
        if args.fix:
            # 문제 수정 시도
            issues = await fixer.fix_transaction_analysis_issues()
            logger.info("문제 진단 완료. 소스 코드 수정이 필요할 수 있습니다.")
            
    finally:
        await fixer.close()
        logger.info("스크립트 종료")

if __name__ == "__main__":
    asyncio.run(main()) 