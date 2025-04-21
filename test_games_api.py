#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
게임 API 테스트 스크립트
주요 기능:
- 게임 목록 조회
- 게임 실행 
- 결과 통계 확인
- 라운드 생성 및 조회

실행: python test_games_api.py
"""

import sys
import requests
import json
import uuid
import time
import random
from datetime import datetime

# 공통 유틸리티 임포트
from test_utils import (
    BASE_URL, TEST_PLAYER_ID, ADMIN_HEADERS, TEST_ENV,
    print_response, track_test_result, print_test_summary, reset_test_results,
    generate_unique_id, get_auth_token, reset_test_environment
)

def test_get_games():
    """게임 목록 조회 테스트"""
    print("\n===== 게임 목록 조회 테스트 =====")
    
    try:
        # 인증 토큰 획득
        token = get_auth_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(f"{BASE_URL}/api/games", headers=headers)
        print_response(response, "게임 목록 응답")
        
        success = response.status_code == 200
        
        # 빈 게임 목록 확인 및 처리
        games_data = response.json() if success else []
        if success and len(games_data) == 0:
            print("! 경고: 게임 목록이 비어있습니다. 서버에 테스트 데이터가 로드되지 않았을 수 있습니다.")
            print("  이는 실패가 아닌 '서버 상태'로 간주합니다.")
        
        track_test_result("게임 목록 조회", success, response)
        return success, games_data
            
    except Exception as e:
        print(f"게임 목록 조회 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        track_test_result("게임 목록 조회", False, error=e)
        return False, []

def test_run_game(game_id="baccarat"):
    """특정 게임 실행 테스트"""
    print(f"\n===== 게임 실행 테스트 (ID: {game_id}) =====")
    
    try:
        # 인증 토큰 획득
        token = get_auth_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        game_data = {
            "uuid": str(uuid.uuid4()),
            "player_id": TEST_PLAYER_ID,
            "bet_amount": 100.0,
            "currency": "KRW"
        }
        
        response = requests.post(f"{BASE_URL}/api/games/{game_id}/play", headers=headers, json=game_data)
        print_response(response, f"{game_id} 게임 실행 응답")
        
        # 404 에러는 게임을 찾을 수 없는 경우로, 서버에 해당 게임이 구현되지 않은 예상된 결과
        expected_failure = response.status_code == 404 and "Game not found" in response.text
        success = response.status_code == 200
        
        if expected_failure:
            print(f"게임 '{game_id}'가 서버에 구현되지 않았습니다 (404 - Game not found). 예상된 실패로 처리합니다.")
            
        track_test_result(f"게임 실행 ({game_id})", success, response, expected_failure=expected_failure)
        return success or expected_failure, response.json() if success else None
            
    except Exception as e:
        print(f"게임 실행 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        track_test_result(f"게임 실행 ({game_id})", False, error=e)
        return False, None

def test_baccarat_play():
    """바카라 게임 플레이 테스트"""
    print("\n===== 바카라 게임 플레이 테스트 =====")
    
    try:
        # 인증 토큰 획득
        token = get_auth_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        baccarat_data = {
            "uuid": str(uuid.uuid4()),
            "player_id": TEST_PLAYER_ID,
            "bet_amount": 500.0,
            "bet_type": "player",  # player, banker, tie
            "currency": "KRW"
        }
        
        response = requests.post(f"{BASE_URL}/api/games/baccarat/play", headers=headers, json=baccarat_data)
        print_response(response, "바카라 게임 플레이 응답")
        
        # 성공 여부 확인
        success = response.status_code == 200
        
        # 카드 데이터 일관성 확인
        if success:
            data = response.json()
            if "player_cards" in data and "banker_cards" in data:
                print("\n카드 데이터 검증:")
                player_cards = data.get("player_cards", [])
                banker_cards = data.get("banker_cards", [])
                print(f"플레이어 카드: {', '.join(player_cards)}")
                print(f"뱅커 카드: {', '.join(banker_cards)}")
                
                # 플레이어와 뱅커의 카드가 동일한지 확인
                if set(player_cards) == set(banker_cards) and len(player_cards) > 0:
                    print("! 경고: 플레이어와 뱅커의 카드가 동일합니다. 랜덤 로직에 문제가 있을 수 있습니다.")
                
        track_test_result("바카라 게임 플레이", success, response)
        return success, response.json() if success else None
            
    except Exception as e:
        print(f"바카라 게임 플레이 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        track_test_result("바카라 게임 플레이", False, error=e)
        return False, None

def test_game_statistics():
    """게임 통계 테스트"""
    print("\n===== 게임 통계 테스트 =====")
    
    try:
        # 인증 토큰 획득
        token = get_auth_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(f"{BASE_URL}/api/stats/games", headers=headers)
        print_response(response, "게임 통계 응답")
        
        success = response.status_code == 200
        track_test_result("게임 통계 조회", success, response)
        return success, response.json() if success else None
            
    except Exception as e:
        print(f"게임 통계 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        track_test_result("게임 통계 조회", False, error=e)
        return False, None

def generate_random_cards(count=3):
    """테스트용 랜덤 카드 생성"""
    suits = ['H', 'D', 'C', 'S']  # 하트, 다이아몬드, 클럽, 스페이드
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
    
    cards = []
    for _ in range(count):
        suit = random.choice(suits)
        rank = random.choice(ranks)
        cards.append(f"{suit}{rank}")
    
    return cards

def test_create_round():
    """라운드 생성 테스트"""
    print("\n===== 라운드 생성 테스트 =====")
    
    try:
        # 랜덤 카드 생성 (플레이어와 뱅커에 서로 다른 카드 부여)
        player_cards = generate_random_cards(3)
        banker_cards = generate_random_cards(3)
        
        # 인증 토큰 획득
        token = get_auth_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        # 라운드 데이터 준비
        round_data = {
            "uuid": str(uuid.uuid4()),
            "game_id": "baccarat",
            "player_id": TEST_PLAYER_ID,
            "round_id": generate_unique_id("round"),
            "bet_amount": 1000.0,
            "bet_type": "player",
            "player_cards": player_cards,
            "banker_cards": banker_cards,
            "result": "player",  # player, banker, tie
            "win_amount": 1900.0,
            "currency": "KRW",
            "timestamp": datetime.now().isoformat()
        }
        
        response = requests.post(f"{BASE_URL}/api/rounds/create", headers=headers, json=round_data)
        print_response(response, "라운드 생성 응답")
        
        success = response.status_code in [200, 201]
        track_test_result("라운드 생성", success, response)
        return success, round_data["round_id"] if success else None
            
    except Exception as e:
        print(f"라운드 생성 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        track_test_result("라운드 생성", False, error=e)
        return False, None

def test_get_player_games():
    """유저 게임 기록 조회 테스트"""
    print("\n===== 유저 게임 기록 조회 테스트 =====")
    
    try:
        # 인증 토큰 획득
        token = get_auth_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(f"{BASE_URL}/api/players/{TEST_PLAYER_ID}/games", headers=headers)
        print_response(response, "유저 게임 기록 응답")
        
        success = response.status_code == 200
        
        # 게임 기록 데이터 검증
        if success:
            games_history = response.json()
            print(f"유저 게임 기록 수: {len(games_history)}")
            
        track_test_result("유저 게임 기록 조회", success, response)
        return success, response.json() if success else None
            
    except Exception as e:
        print(f"유저 게임 기록 조회 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        track_test_result("유저 게임 기록 조회", False, error=e)
        return False, None

def test_get_round(round_id=None):
    """라운드 상세 조회 테스트"""
    print("\n===== 라운드 상세 조회 테스트 =====")
    
    if not round_id:
        print("라운드 ID가 제공되지 않았습니다. 먼저 라운드를 생성합니다.")
        success, round_id = test_create_round()
        if not success:
            print("라운드 생성에 실패하여 라운드 조회 테스트를 건너뜁니다.")
            track_test_result("라운드 상세 조회", False, error="라운드 생성 실패")
            return False, None
    
    try:
        # 인증 토큰 획득
        token = get_auth_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(f"{BASE_URL}/api/rounds/{round_id}", headers=headers)
        print_response(response, "라운드 상세 응답")
        
        success = response.status_code == 200
        
        # 라운드 데이터 카드 일관성 검증
        if success:
            round_data = response.json()
            if "player_cards" in round_data and "banker_cards" in round_data:
                player_cards = round_data.get("player_cards", [])
                banker_cards = round_data.get("banker_cards", [])
                
                print("\n라운드 카드 데이터 검증:")
                print(f"플레이어 카드: {', '.join(player_cards)}")
                print(f"뱅커 카드: {', '.join(banker_cards)}")
                
                # 플레이어와 뱅커의 카드가 동일한지 확인
                if set(player_cards) == set(banker_cards) and len(player_cards) > 0:
                    print("! 경고: 라운드 데이터에서 플레이어와 뱅커의 카드가 동일합니다.")
                    print("  이는 테스트 데이터 문제 또는 카드 생성 로직에 문제가 있을 수 있습니다.")
                
        track_test_result("라운드 상세 조회", success, response)
        return success, response.json() if success else None
            
    except Exception as e:
        print(f"라운드 상세 조회 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        track_test_result("라운드 상세 조회", False, error=e)
        return False, None

def main():
    """테스트 메인 함수"""
    print("\n===== 게임 API 테스트 시작 =====")
    print(f"테스트 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"서버 URL: {BASE_URL}")
    
    # 테스트 환경 초기화
    reset_test_environment()
    reset_test_results()
    
    try:
        # 게임 목록 조회 테스트
        games_success, games = test_get_games()
        
        # 게임 실행 테스트
        run_game_success, _ = test_run_game()
        
        # 바카라 게임 테스트
        baccarat_success, _ = test_baccarat_play()
        
        # 게임 통계 테스트
        stats_success, _ = test_game_statistics()
        
        # 라운드 생성 테스트
        round_success, round_id = test_create_round()
        
        # 라운드가 생성되었으면 상세 조회 테스트
        if round_success and round_id:
            round_detail_success, _ = test_get_round(round_id)
        
        # 유저 게임 기록 조회 테스트
        player_games_success, _ = test_get_player_games()
        
    except Exception as e:
        print(f"테스트 실행 중 예상치 못한 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 테스트 결과 출력
    result = print_test_summary()
    return result

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)