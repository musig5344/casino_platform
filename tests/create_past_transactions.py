#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import json

# 서버 URL
BASE_URL = "http://localhost:8000"
ADMIN_HEADERS = {"X-Admin": "true", "Content-Type": "application/json"}

def create_past_transactions():
    """과거 날짜의 트랜잭션 데이터 생성"""
    print("\n===== 과거 트랜잭션 생성 =====")
    
    # 7일 전 데이터
    data_7_days = {
        "player_id": "test_player_123",
        "transaction_count": 5,
        "min_amount": 100000,
        "max_amount": 500000,
        "transaction_type": "deposit",
        "source": "past_test",
        "days_ago": 7
    }
    
    # 30일 전 데이터
    data_30_days = {
        "player_id": "test_player_123",
        "transaction_count": 10,
        "min_amount": 200000,
        "max_amount": 800000,
        "transaction_type": "deposit",
        "source": "past_test",
        "days_ago": 30
    }
    
    # 7일 전 데이터 생성
    print("7일 전 트랜잭션 생성 중...")
    response = requests.post(
        f"{BASE_URL}/test/bulk-transactions",
        headers=ADMIN_HEADERS,
        json=data_7_days
    )
    
    if response.status_code == 201:
        result = response.json()
        print(f"7일 전 트랜잭션 생성 완료: {len(result.get('transactions', []))}개")
    else:
        print(f"7일 전 트랜잭션 생성 실패: {response.status_code}")
        print(f"오류: {response.text}")
    
    # 30일 전 데이터 생성
    print("\n30일 전 트랜잭션 생성 중...")
    response = requests.post(
        f"{BASE_URL}/test/bulk-transactions",
        headers=ADMIN_HEADERS,
        json=data_30_days
    )
    
    if response.status_code == 201:
        result = response.json()
        print(f"30일 전 트랜잭션 생성 완료: {len(result.get('transactions', []))}개")
    else:
        print(f"30일 전 트랜잭션 생성 실패: {response.status_code}")
        print(f"오류: {response.text}")
    
    # 위험 프로필 확인
    print("\n위험 프로필 확인 중...")
    response = requests.get(
        f"{BASE_URL}/aml/player/test_player_123/risk-profile",
        headers=ADMIN_HEADERS
    )
    
    if response.status_code == 200:
        profile = response.json()
        print("\n플레이어 위험 프로필:")
        print(f"  - 전체 위험 점수: {profile.get('overall_risk_score')}")
        print(f"  - 입금 위험 점수: {profile.get('deposit_risk_score')}")
        print(f"  - 출금 위험 점수: {profile.get('withdrawal_risk_score')}")
        print(f"  - 7일 입금 횟수: {profile.get('deposit_count_7d')}")
        print(f"  - 7일 입금 총액: {profile.get('deposit_amount_7d')}")
        print(f"  - 30일 입금 횟수: {profile.get('deposit_count_30d')}")
        print(f"  - 30일 입금 총액: {profile.get('deposit_amount_30d')}")
    else:
        print(f"위험 프로필 조회 실패: {response.status_code}")
        print(f"오류: {response.text}")

if __name__ == "__main__":
    create_past_transactions() 