#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PEP(정치적 노출인물) 및 고위험 국가 거래 테스트 스크립트
주요 기능:
- PEP 플레이어 생성 및 트랜잭션 생성
- 고위험 국가 플레이어 생성 및 트랜잭션 생성
- 트랜잭션 AML 분석
- 알림 생성 확인

실행: python test_pep_riskcountry.py

개선사항:
1. 코드 주석 보강
2. 로깅 간소화
3. 오류 처리 개선
"""

import requests
import json
import time
import uuid
import sys
from datetime import datetime
from decimal import Decimal

# 공통 유틸리티 임포트
from test_utils import (
    BASE_URL, TEST_PLAYER_ID, ADMIN_HEADERS, TEST_ENV,
    print_response, track_test_result, print_test_summary, reset_test_results,
    generate_unique_id, create_test_transaction
)

def test_pep_transaction():
    """
    PEP(정치적 노출 인물) 플레이어 관련 트랜잭션 테스트
    
    테스트 단계:
    1. PEP 플레이어 트랜잭션 생성 (플레이어 자동 생성)
    2. 트랜잭션 AML 분석
    3. 분석 결과에서 PEP 감지 확인
    4. 알림 ID 존재 확인
    
    Returns:
        테스트 성공 여부
    """
    print("\n===== PEP 플레이어 트랜잭션 테스트 =====")
    
    # PEP 플레이어 ID
    pep_player_id = "pep_player_test"
    
    try:
        # 1. PEP 플레이어 트랜잭션 생성 - 이 과정에서 플레이어도 자동으로 생성됨
        tx_amount = 50000.0  # 적당한 금액 설정
        
        # PEP 메타데이터 설정
        pep_metadata = {
            "is_pep": True,
            "pep_position": "국회의원",
            "pep_jurisdiction": "KR",
            "pep_since": "2020-01-01",
            "country": "KR",
            "currency": "KRW"
        }
        
        # 트랜잭션 생성
        transaction_id = generate_unique_id("pep_tx")
        transaction_data = {
            "transaction_id": transaction_id,
            "player_id": pep_player_id,
            "amount": tx_amount,
            "transaction_type": "deposit",
            "source": "pep_test",
            "metadata": pep_metadata
        }
        
        response = requests.post(
            f"{BASE_URL}/test/mock-transaction",
            headers=ADMIN_HEADERS,
            json=transaction_data
        )
        
        if response.status_code != 201:
            print(f"PEP 트랜잭션 생성 실패: {response.status_code}")
            print_response(response)
            track_test_result("PEP 트랜잭션 생성", False, response)
            return False
            
        print(f"PEP 트랜잭션 생성 성공: {transaction_id}")
        print(f"금액: {tx_amount}")
        track_test_result("PEP 트랜잭션 생성", True, response)
        
        # 2. 트랜잭션 AML 분석
        analyze_url = f"{BASE_URL}/aml/analyze-transaction/{transaction_id}"
        response = requests.post(
            analyze_url,
            headers=ADMIN_HEADERS
        )
        
        if response.status_code != 200:
            print(f"PEP 트랜잭션 AML 분석 실패: {response.status_code}")
            print_response(response)
            track_test_result("PEP 트랜잭션 AML 분석", False, response)
            return False
        
        analysis_result = response.json()
        print_response(response, "PEP 트랜잭션 AML 분석 결과")
        
        # 3. 분석 결과 검증
        risk_score = analysis_result.get("risk_score", 0)
        pep_detected = analysis_result.get("risk_factors", {}).get("is_pep", False)
        
        if risk_score >= 60.0 and pep_detected:
            print(f"PEP 플레이어 감지 성공: 위험점수 {risk_score}")
            print(f"위험 요소: {analysis_result.get('risk_factors', [])}")
            track_test_result("PEP 플레이어 감지", True, response)
        else:
            print(f"PEP 플레이어 감지 실패: 위험점수 {risk_score}")
            print(f"위험 요소: {analysis_result.get('risk_factors', [])}")
            track_test_result("PEP 플레이어 감지", False, response)
            return False
        
        # 4. 알림 ID 확인
        alert_id = analysis_result.get("analysis_details", {}).get("alert_id") or analysis_result.get("alert")
        
        if alert_id:
            print(f"PEP 관련 알림 ID: {alert_id}")
            track_test_result("PEP 관련 알림 생성", True, response)
            
            # 트랜잭션 및 플레이어 정보 캐싱
            TEST_ENV.setdefault("pep_players", {})[pep_player_id] = {
                "transaction_id": transaction_id,
                "alert_id": alert_id,
                "risk_score": risk_score,
                "created_at": datetime.now().isoformat()
            }
            
            return True
        else:
            print("PEP 관련 알림 ID가 없음")
            track_test_result("PEP 관련 알림 생성", False, response)
            return False
            
    except Exception as e:
        print(f"PEP 트랜잭션 테스트 중 오류 발생: {str(e)}")
        track_test_result("PEP 트랜잭션 테스트", False, error=e)
        return False

def test_high_risk_country():
    """
    고위험 국가 플레이어 관련 트랜잭션 테스트
    
    테스트 단계:
    1. 고위험 국가 플레이어 트랜잭션 생성 (플레이어 자동 생성)
    2. 트랜잭션 AML 분석
    3. 분석 결과에서 고위험 국가 감지 확인
    4. 알림 ID 존재 확인
    
    Returns:
        테스트 성공 여부
    """
    print("\n===== 고위험 국가 플레이어 트랜잭션 테스트 =====")
    
    # 고위험 국가 플레이어 ID
    risk_country_player_id = "risk_country_player_test"
    
    # 고위험 국가 설정 (FATF 회색 목록 국가 중 하나)
    risk_country = "YE"  # 예멘 (고위험 국가 예시)
    
    try:
        # 1. 고위험 국가 플레이어 트랜잭션 생성 - 이 과정에서 플레이어도 자동으로 생성됨
        tx_amount = 50000.0  # 적당한 금액 설정
        
        # 고위험 국가 메타데이터
        country_metadata = {
            "country": risk_country,
            "residence": risk_country,
            "citizenship": risk_country,
            "currency": "USD",
            "high_risk_jurisdiction": True
        }
        
        # 트랜잭션 생성
        transaction_id = generate_unique_id("risk_country_tx")
        transaction_data = {
            "transaction_id": transaction_id,
            "player_id": risk_country_player_id,
            "amount": tx_amount,
            "transaction_type": "deposit",
            "source": "risk_country_test",
            "metadata": country_metadata
        }
        
        response = requests.post(
            f"{BASE_URL}/test/mock-transaction",
            headers=ADMIN_HEADERS,
            json=transaction_data
        )
        
        if response.status_code != 201:
            print(f"고위험 국가 트랜잭션 생성 실패: {response.status_code}")
            print_response(response)
            track_test_result("고위험 국가 트랜잭션 생성", False, response)
            return False
            
        print(f"고위험 국가 트랜잭션 생성 성공: {transaction_id}")
        print(f"금액: {tx_amount}")
        track_test_result("고위험 국가 트랜잭션 생성", True, response)
        
        # 2. 트랜잭션 AML 분석
        analyze_url = f"{BASE_URL}/aml/analyze-transaction/{transaction_id}"
        response = requests.post(
            analyze_url,
            headers=ADMIN_HEADERS
        )
        
        if response.status_code != 200:
            print(f"고위험 국가 트랜잭션 AML 분석 실패: {response.status_code}")
            print_response(response)
            track_test_result("고위험 국가 트랜잭션 AML 분석", False, response)
            return False
        
        analysis_result = response.json()
        print_response(response, "고위험 국가 트랜잭션 AML 분석 결과")
        
        # 3. 분석 결과 검증
        risk_score = analysis_result.get("risk_score", 0)
        risk_country_detected = analysis_result.get("risk_factors", {}).get("is_high_risk_country", False)
        
        if risk_score >= 60.0 and risk_country_detected:
            print(f"고위험 국가 감지 성공: 위험점수 {risk_score}")
            print(f"위험 요소: {analysis_result.get('risk_factors', [])}")
            track_test_result("고위험 국가 감지", True, response)
        else:
            print(f"고위험 국가 감지 실패: 위험점수 {risk_score}")
            print(f"위험 요소: {analysis_result.get('risk_factors', [])}")
            track_test_result("고위험 국가 감지", False, response)
            return False
        
        # 4. 알림 ID 확인
        alert_id = analysis_result.get("analysis_details", {}).get("alert_id") or analysis_result.get("alert")
        
        if alert_id:
            print(f"고위험 국가 관련 알림 ID: {alert_id}")
            track_test_result("고위험 국가 관련 알림 생성", True, response)
            
            # 트랜잭션 및 플레이어 정보 캐싱
            TEST_ENV.setdefault("risk_country_players", {})[risk_country_player_id] = {
                "transaction_id": transaction_id,
                "alert_id": alert_id,
                "risk_score": risk_score,
                "country": risk_country,
                "created_at": datetime.now().isoformat()
            }
            
            return True
        else:
            print("고위험 국가 관련 알림 ID가 없음")
            track_test_result("고위험 국가 관련 알림 생성", False, response)
            return False
            
    except Exception as e:
        print(f"고위험 국가 트랜잭션 테스트 중 오류 발생: {str(e)}")
        track_test_result("고위험 국가 트랜잭션 테스트", False, error=e)
        return False

def main():
    """
    테스트 메인 실행 함수
    
    실행 순서:
    1. PEP 플레이어 트랜잭션 테스트
    2. 고위험 국가 플레이어 트랜잭션 테스트
    3. 테스트 결과 출력
    """
    print("\n===== PEP 및 고위험 국가 AML 테스트 시작 =====")
    print(f"테스트 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"서버 URL: {BASE_URL}")
    
    # 테스트 결과 초기화
    reset_test_results()
    
    try:
        # 1. PEP 플레이어 테스트
        pep_success = test_pep_transaction()
        
        # 2. 고위험 국가 플레이어 테스트
        country_success = test_high_risk_country()
        
        # 3. 테스트 결과 요약
        result = print_test_summary()
        
        # 4. 종합 결과
        if pep_success and country_success:
            print("\n✅ 모든 테스트 성공!")
            return True
        else:
            print("\n❌ 일부 테스트 실패")
            failed_tests = [test["name"] for test in TEST_ENV.get("TEST_RESULTS", {}).get("tests", []) if not test.get("success")]
            print(f"실패한 테스트: {', '.join(failed_tests)}")
            return False
            
    except Exception as e:
        print(f"\n테스트 실행 중 예상치 못한 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 