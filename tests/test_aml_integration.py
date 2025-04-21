#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AML API 통합 테스트 스크립트
주요 기능:
- 인증 토큰 획득
- 단일 및 대량 트랜잭션 생성
- 트랜잭션 AML 분석
- 알림 생성 및 조회
- 플레이어 위험 프로필 조회
- AML 보고서 생성

실행: python test_aml_integration.py

개선사항:
1. 코드 간소화 및 중복 함수 제거
2. 로깅 간소화
3. 주석 보강
"""

import requests
import json
import uuid
import random
from datetime import datetime, timedelta
import time
import sys
import traceback
from decimal import Decimal

# 공통 유틸리티 임포트
from test_utils import (
    BASE_URL, TEST_PLAYER_ID, ADMIN_HEADERS, TEST_ENV,
    print_response, track_test_result, print_test_summary, reset_test_results,
    get_auth_token, generate_unique_id, create_test_transaction
)

def init_wallet():
    """지갑 초기화"""
    print("\n===== 지갑 초기화 =====")
    
    # 지갑 초기화 요청 데이터
    try:
        # 먼저 출금으로 잔액 초기화
        reset_withdrawal = {
            "transaction_id": generate_unique_id("reset_withdrawal"),
            "player_id": TEST_PLAYER_ID,
            "amount": 99000000.0,  # 큰 금액으로 설정
            "transaction_type": "withdrawal",
            "source": "wallet_reset"
        }
        
        # 출금 요청 전송
        response = requests.post(
            f"{BASE_URL}/test/mock-transaction",
            headers=ADMIN_HEADERS,
            json=reset_withdrawal
        )
        
        # 새 입금으로 초기 잔액 설정
        deposit_data = {
            "transaction_id": generate_unique_id("reset_deposit"),
            "player_id": TEST_PLAYER_ID,
            "amount": 10000.0,  # 초기 금액을 작게 설정
            "transaction_type": "deposit",
            "source": "wallet_reset"
        }
        
        response = requests.post(
            f"{BASE_URL}/test/mock-transaction",
            headers=ADMIN_HEADERS,
            json=deposit_data
        )
        
        if response.status_code == 201:
            result = response.json()
            print(f"지갑 초기화 완료: 잔액 = {result.get('transaction', {}).get('wallet_balance', 0)}")
            track_test_result("지갑 초기화", True, response)
            return True
        else:
            print(f"지갑 초기화 오류: {response.status_code}")
            track_test_result("지갑 초기화", False, response)
            return False
    except Exception as e:
        print(f"지갑 초기화 중 예외 발생: {str(e)}")
        track_test_result("지갑 초기화", False, error=e)
        return False

def create_mock_transaction(amount=10000, transaction_type="deposit"):
    """
    테스트용 모의 트랜잭션 생성
    """
    print(f"\n===== 목 트랜잭션 생성 (금액: {amount}, 유형: {transaction_type}) =====")
    try:
        success, transaction_id = create_test_transaction(
            amount=amount,
            transaction_type=transaction_type,
            player_id=TEST_PLAYER_ID,
            metadata={"source": "aml_test"}
        )
        
        if success:
            print(f"목 트랜잭션 생성 성공: {transaction_id}")
            print(f"트랜잭션 유형: {transaction_type}")
            print(f"금액: {amount}")
            return transaction_id
        else:
            print(f"목 트랜잭션 생성 실패")
            return None
    except Exception as e:
        print(f"목 트랜잭션 생성 중 오류: {str(e)}")
        track_test_result("목 트랜잭션 생성", False, error=e)
        return None

def create_bulk_transactions(count=3, min_amount=500000, max_amount=3000000):
    """
    대량의 트랜잭션 생성 테스트
    """
    print(f"\n===== 대량 트랜잭션 생성 테스트 (개수: {count}) =====")
    
    # 트랜잭션 데이터 설정
    data = {
        "player_id": TEST_PLAYER_ID,
        "transaction_count": count,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "transaction_type": "deposit",
        "source": "bulk_test"
    }
    
    # 지갑 초기화 
    init_wallet()
    
    try:
        # API 호출
        response = requests.post(
            f"{BASE_URL}/test/bulk-transactions",
            headers=ADMIN_HEADERS,
            json=data
        )
        
        # 응답 확인
        print(f"상태 코드: {response.status_code}")
        if response.status_code == 201:
            result = response.json()
            print(f"생성된 트랜잭션 수: {len(result.get('transactions', []))}")
            print(f"현재 지갑 잔액: {result.get('wallet_balance')}")
            # 생성된 트랜잭션 ID 목록
            transaction_ids = [tx.get('transaction_id') for tx in result.get('transactions', [])]
            track_test_result("대량 트랜잭션 생성", True, response)
            return transaction_ids
        else:
            print(f"오류 응답: {response.text}")
            track_test_result("대량 트랜잭션 생성", False, response)
            return []
    except Exception as e:
        print(f"대량 트랜잭션 생성 중 오류: {str(e)}")
        track_test_result("대량 트랜잭션 생성", False, error=e)
        return []

def test_analyze_transaction(transaction_id, token=None):
    """트랜잭션 분석 엔드포인트를 테스트합니다."""
    print(f"\n===== 트랜잭션 분석 테스트 (ID: {transaction_id}) =====")
    try:
        # 헤더 설정
        headers = {**ADMIN_HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # API 엔드포인트
        url = f"{BASE_URL}/aml/analyze-transaction/{transaction_id}"
        print(f"트랜잭션 분석 시도: {url}")
        response = requests.post(url, headers=headers)
        
        if response.status_code == 200:
            print_response(response, "트랜잭션 분석 테스트 성공")
            track_test_result("트랜잭션 분석", True, response)
            return True, response
        else:
            print_response(response, f"트랜잭션 분석 실패")
            track_test_result("트랜잭션 분석", False, response)
            return False, response
            
    except Exception as e:
        print(f"테스트 중 오류 발생: {str(e)}")
        print(f"오류 유형: {type(e).__name__}")
        track_test_result("트랜잭션 분석", False, error=e)
        return False, None

def test_get_alerts(token=None):
    """알림 조회 엔드포인트를 테스트합니다."""
    print("\n===== 알림 조회 테스트 =====")
    try:
        # 헤더 설정
        headers = {**ADMIN_HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # API 호출
        url = f"{BASE_URL}/aml/alerts"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            alerts = response.json()
            print(f"조회된 알림 수: {len(alerts)}")
            
            # 간략한 정보 출력
            if alerts:
                for i, alert in enumerate(alerts[:5], 1):  # 최대 5개만 표시
                    print(f"알림 {i}: ID={alert.get('id')}, 유형={alert.get('alert_type')}, 심각도={alert.get('alert_severity')}")
                
                if len(alerts) > 5:
                    print(f"... 외 {len(alerts) - 5}개")
            
            track_test_result("알림 조회", True, response)
            return True, alerts
        else:
            print_response(response, "알림 조회 실패")
            track_test_result("알림 조회", False, response)
            return False, None
    except Exception as e:
        print(f"알림 조회 중 오류 발생: {str(e)}")
        track_test_result("알림 조회", False, error=e)
        return False, None

def test_get_player_risk_profile(player_id=TEST_PLAYER_ID, token=None):
    """플레이어 위험 프로필 조회 엔드포인트를 테스트합니다."""
    print(f"\n===== 플레이어 위험 프로필 조회 테스트 (ID: {player_id}) =====")
    try:
        # 헤더 설정
        headers = {**ADMIN_HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # API 호출
        url = f"{BASE_URL}/aml/player/{player_id}/risk-profile"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            profile = response.json()
            
            # 중요 정보 추출 및 출력
            print("위험 프로필 정보:")
            print(f"  - 전체 위험 점수: {profile.get('overall_risk_score')}")
            print(f"  - 입금 위험 점수: {profile.get('deposit_risk_score')}")
            print(f"  - 출금 위험 점수: {profile.get('withdrawal_risk_score')}")
            print(f"  - 최근 7일 입금: {profile.get('deposit_count_7d')}회, {profile.get('deposit_amount_7d')}원")
            print(f"  - 최근 30일 입금: {profile.get('deposit_count_30d')}회, {profile.get('deposit_amount_30d')}원")
            
            track_test_result("플레이어 위험 프로필 조회", True, response)
            return True, profile
        else:
            print_response(response, "플레이어 위험 프로필 조회 실패")
            track_test_result("플레이어 위험 프로필 조회", False, response)
            return False, None
    except Exception as e:
        print(f"플레이어 위험 프로필 조회 중 오류 발생: {str(e)}")
        track_test_result("플레이어 위험 프로필 조회", False, error=e)
        return False, None

def test_create_aml_report(player_id=TEST_PLAYER_ID, token=None):
    """AML 보고서 생성 엔드포인트를 테스트합니다."""
    print("\n===== AML 보고서 생성 테스트 =====")
    try:
        # 헤더 설정
        headers = {**ADMIN_HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # 보고서 데이터 설정
        report_data = {
            "player_id": player_id,
            "report_type": "STR",  # Suspicious Transaction Report
            "jurisdiction": "MT",  # Malta
            "notes": "테스트 보고서입니다."
        }
        
        # API 호출
        url = f"{BASE_URL}/aml/report"
        response = requests.post(url, headers=headers, json=report_data)
        
        if response.status_code in [200, 201]:
            report = response.json()
            print(f"보고서 생성 성공: ID={report.get('report_id')}")
            track_test_result("AML 보고서 생성", True, response)
            return True, report
        else:
            print_response(response, "AML 보고서 생성 실패")
            track_test_result("AML 보고서 생성", False, response)
            return False, None
    except Exception as e:
        print(f"AML 보고서 생성 중 오류 발생: {str(e)}")
        track_test_result("AML 보고서 생성", False, error=e)
        return False, None

def test_get_high_risk_players(token=None):
    """고위험 플레이어 목록 조회 엔드포인트를 테스트합니다."""
    print("\n===== 고위험 플레이어 조회 테스트 =====")
    try:
        # 헤더 설정
        headers = {**ADMIN_HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # API 호출
        url = f"{BASE_URL}/aml/high-risk-players"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            players = response.json()
            print(f"고위험 플레이어 수: {len(players)}")
            
            if players:
                for i, player in enumerate(players[:3], 1):  # 최대 3명만 표시
                    print(f"플레이어 {i}: ID={player.get('player_id')}, 위험점수={player.get('overall_risk_score')}")
                
                if len(players) > 3:
                    print(f"... 외 {len(players) - 3}명")
            
            track_test_result("고위험 플레이어 조회", True, response)
            return True, players
        else:
            print_response(response, "고위험 플레이어 조회 실패")
            track_test_result("고위험 플레이어 조회", False, response)
            return False, None
    except Exception as e:
        print(f"고위험 플레이어 조회 중 오류 발생: {str(e)}")
        track_test_result("고위험 플레이어 조회", False, error=e)
        return False, None

def test_get_player_alerts(player_id=TEST_PLAYER_ID, token=None):
    """플레이어 관련 알림 조회 엔드포인트를 테스트합니다."""
    print(f"\n===== 플레이어 알림 조회 테스트 (ID: {player_id}) =====")
    try:
        # 헤더 설정
        headers = {**ADMIN_HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # API 호출
        url = f"{BASE_URL}/aml/player/{player_id}/alerts"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            alerts = response.json()
            print(f"조회된 알림 수: {len(alerts)}")
            
            if alerts:
                for i, alert in enumerate(alerts[:5], 1):  # 최대 5개만 표시
                    print(f"알림 {i}: ID={alert.get('id')}, 유형={alert.get('alert_type')}, 심각도={alert.get('alert_severity')}")
                
                if len(alerts) > 5:
                    print(f"... 외 {len(alerts) - 5}개")
            
            track_test_result("플레이어 알림 조회", True, response)
            return True, alerts
        else:
            print_response(response, "플레이어 알림 조회 실패")
            track_test_result("플레이어 알림 조회", False, response)
            return False, None
    except Exception as e:
        print(f"플레이어 알림 조회 중 오류 발생: {str(e)}")
        track_test_result("플레이어 알림 조회", False, error=e)
        return False, None

def analyze_transactions(transaction_ids):
    """여러 트랜잭션을 분석합니다."""
    print("\n===== 대량 트랜잭션 분석 =====")
    
    results = []
    for tx_id in transaction_ids:
        success, response = test_analyze_transaction(tx_id)
        if success:
            results.append(response.json())
        time.sleep(0.5)  # 서버 부하 방지를 위한 간격
    
    return results

def inspect_alert_schema():
    """알림 스키마를 분석합니다."""
    print("\n===== API 스키마 분석 =====")
    try:
        # 알림 조회
        success, alerts = test_get_alerts()
        if not success or not alerts:
            print("알림 스키마 분석을 위한 알림이 없습니다.")
            return False
        
        # 첫 번째 알림 분석
        alert = alerts[0]
        print("알림 스키마 필드:")
        
        # 주요 필드 출력
        fields = []
        for key, value in alert.items():
            field_type = type(value).__name__
            fields.append(f"{key} ({field_type})")
        
        # 컬럼 형태로 출력
        columns = 3
        for i in range(0, len(fields), columns):
            row = fields[i:i+columns]
            print("  " + "  |  ".join(row))
        
        return True
    except Exception as e:
        print(f"알림 스키마 분석 중 오류 발생: {str(e)}")
        return False

def reset_wallet_after_test():
    """테스트 후 지갑 잔액 초기화"""
    print("\n테스트 후 지갑 초기화 중...")
    
    # 최대 금액 출금으로 잔액 초기화
    reset_data = {
        "transaction_id": generate_unique_id("reset"),
        "player_id": TEST_PLAYER_ID,
        "amount": 99000000.0,  # 큰 금액
        "transaction_type": "withdrawal",
        "source": "cleanup"
    }
    
    try:
        # 출금 요청 전송
        response = requests.post(
            f"{BASE_URL}/test/mock-transaction",
            headers=ADMIN_HEADERS,
            json=reset_data
        )
        
        if response.status_code == 201:
            print("지갑 초기화 완료")
        else:
            print(f"지갑 초기화 실패: {response.status_code}")
    except Exception as e:
        print(f"지갑 초기화 중 오류: {str(e)}")

def main():
    """
    메인 테스트 실행 함수
    실행 순서:
    1. 인증 토큰 획득
    2. API 스키마 확인
    3. 모의 트랜잭션 생성
    4. 트랜잭션 분석
    5. 알림 조회
    6. 플레이어 위험 프로필 조회
    7. AML 보고서 생성
    8. 고위험 플레이어 조회
    9. 플레이어 알림 조회
    10. 테스트 결과 출력
    """
    print("\n===== AML 통합 테스트 시작 =====")
    print(f"테스트 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"서버 URL: {BASE_URL}")
    
    # 테스트 결과 초기화
    reset_test_results()
    
    try:
        # 1. 인증 토큰 획득
        token = get_auth_token()
        
        # 2. API 스키마 확인
        inspect_alert_schema()
        
        # 3. 모의 트랜잭션 생성
        transaction_id = create_mock_transaction(amount=500000, transaction_type="deposit")
        if not transaction_id:
            print("모의 트랜잭션 생성 실패, 테스트를 계속합니다.")
        
        # 4. 트랜잭션 분석
        if transaction_id:
            test_analyze_transaction(transaction_id, token)
        
        # 5. 알림 조회
        test_get_alerts(token)
        
        # 6. 플레이어 위험 프로필 조회
        test_get_player_risk_profile(player_id=TEST_PLAYER_ID, token=token)
        
        # 7. AML 보고서 생성
        test_create_aml_report(player_id=TEST_PLAYER_ID, token=token)
        
        # 8. 고위험 플레이어 조회
        test_get_high_risk_players(token)
        
        # 9. 플레이어 알림 조회
        test_get_player_alerts(player_id=TEST_PLAYER_ID, token=token)
        
    except Exception as e:
        error_info = traceback.format_exc()
        print(f"테스트 실행 중 오류 발생: \n{error_info}")
    finally:
        # 10. 지갑 상태 복원
        reset_wallet_after_test()
        
        # 11. 테스트 결과 출력
        result = print_test_summary()
        return result

# 스크립트 직접 실행 시 메인 함수 호출
if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
