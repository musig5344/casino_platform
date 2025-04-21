#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
게임 API 테스트 스크립트 (Pytest 스타일)
주요 기능:
- 게임 목록 조회
- 게임 실행 
- 결과 통계 확인
- 라운드 생성 및 조회

실행: python test_games_api.py
"""

import pytest
from fastapi.testclient import TestClient
import uuid
import sys
import requests
import json
import time
import random
from datetime import datetime
from backend.models.game import Game # active_game fixture 타입 힌트를 위해 추가

# 공통 유틸리티 및 상수 임포트
from test_utils import (
    BASE_URL, TEST_PLAYER_ID, # TEST_PLAYER_ID 임포트 확인
    ADMIN_HEADERS, TEST_ENV,
    print_response, track_test_result, print_test_summary, reset_test_results,
    generate_unique_id, get_auth_token, reset_test_environment
)

# --- Fixtures ---

# 인증 토큰 fixture (test_auth_api.py 또는 conftest.py 에서 가져오거나 여기서 정의)
# 여기서는 test_auth_api.py 에 정의된 default_auth_token 을 사용한다고 가정
# 실제로는 conftest.py 로 옮기는 것이 더 좋을 수 있음

# --- Test Functions ---

def test_get_games_list_success(client: TestClient, default_auth_token: str):
    """게임 목록 조회 성공 테스트 (Pytest 스타일)"""
    print("\n===== 게임 목록 조회 테스트 (성공) =====")
    if not default_auth_token:
        pytest.skip("기본 인증 토큰 없음")

    headers = {
        "Authorization": f"Bearer {default_auth_token}",
        "Accept-Language": "ko", # 한국어 요청
        "Host": "localhost"
    }
    
    response = client.get("/games/", headers=headers) # 실제 엔드포인트 경로 사용
    print_response(response, "게임 목록 응답 (ko)")

    assert response.status_code == 200
    games_data = response.json()
    assert isinstance(games_data, list)
    
    # 게임 데이터가 있다면, 첫 번째 게임의 번역 확인 (예시)
    if games_data:
        first_game = games_data[0]
        assert "id" in first_game
        assert "name" in first_game # 번역된 이름이 있어야 함
        assert "description" in first_game # 번역된 설명이 있어야 함
        # 실제 번역 값 확인은 어려우므로 필드 존재 여부 및 타입 위주로 검증
        assert isinstance(first_game["name"], str)
        print(f"첫 번째 게임 이름 (번역됨): {first_game['name']}")
    else:
        print("! 경고: 게임 목록이 비어 있습니다.")
        
    print("게임 목록 조회 (한국어) 성공")

def test_get_games_list_unauthorized(client: TestClient):
    """게임 목록 조회 미인증 테스트 (Pytest 스타일)"""
    print("\n===== 게임 목록 조회 테스트 (미인증) =====")
    
    headers = {
        "Accept-Language": "ko",
        "Host": "localhost"
    }
    
    response = client.get("/games/", headers=headers) # 실제 엔드포인트 경로 사용
    print_response(response, "게임 목록 응답 (미인증)")

    # /games/ 엔드포인트는 현재 인증이 필요하지 않으므로 200 OK 예상
    assert response.status_code == 200 
    print("게임 목록 조회 (미인증 시 200) 성공")

def test_launch_game_success(client: TestClient, default_auth_token: str, active_game: Game):
    """게임 실행 URL 생성 성공 테스트 (active_game fixture 사용)"""
    print("\n===== 게임 실행 URL 생성 테스트 (성공 - Fixture 사용) =====")
    if not default_auth_token:
        pytest.skip("기본 인증 토큰 없음")
    if not active_game:
        pytest.fail("테스트 사전 조건 실패: active_game fixture가 게임을 제공하지 못했습니다.")

    # active_game fixture 에서 생성된 게임 ID 사용
    test_game_id_str = str(active_game.id)
    print(f"Fixture 제공 테스트 게임 ID: {test_game_id_str}")

    headers = {
        "Authorization": f"Bearer {default_auth_token}",
        "Accept-Language": "ko",
        "Host": "localhost"
    }
    launch_data = {
        "player_id": TEST_PLAYER_ID, 
        "game_id": test_game_id_str
    }
    
    response = client.post("/games/launch", headers=headers, json=launch_data)
    print_response(response, f"게임 실행 URL 생성 응답 (Game ID: {test_game_id_str})")

    assert response.status_code == 200
    response_data = response.json()
    assert "game_url" in response_data
    assert isinstance(response_data["game_url"], str)
    assert response_data["game_url"].startswith("http") 
    assert f"token=" in response_data["game_url"]
    assert f"player_id={TEST_PLAYER_ID}" in response_data["game_url"]

    print("게임 실행 URL 생성 성공 (Fixture 사용)")

def test_launch_game_unauthorized(client: TestClient):
    """게임 실행 URL 생성 미인증 테스트 (Pytest 스타일)"""
    print("\n===== 게임 실행 URL 생성 테스트 (미인증) =====")
    test_game_id = "1" # 문자열 ID 사용
    headers = {
        "Accept-Language": "ko",
        "Host": "localhost"
    }
    launch_data = {
        "player_id": "some_player", # 실제 플레이어 ID 여부 무관
        "game_id": test_game_id
    }
    
    response = client.post("/games/launch", headers=headers, json=launch_data)
    print_response(response, f"게임 실행 URL 생성 응답 (미인증)")

    # get_current_user 의존성으로 인해 401 예상
    assert response.status_code == 401
    print("게임 실행 URL 생성 (미인증 시 401) 성공")

def test_get_baccarat_stats_success(client: TestClient):
    """바카라 통계 조회 성공 테스트 (Pytest 스타일)"""
    print("\n===== 바카라 통계 조회 테스트 (성공) =====")
    # 테스트용 룸 ID (실제 존재하는 룸 ID 또는 기본 룸 사용)
    test_room_id = "default_room"
    headers = {
        "Accept-Language": "ko",
        "Host": "localhost"
    }
    
    response = client.get(f"/games/baccarat/{test_room_id}/stats", headers=headers)
    print_response(response, f"바카라 통계 응답 (Room ID: {test_room_id})")

    # 바카라 게임 인스턴스가 없으면 500 오류 반환 가능 (get_baccarat_game 로직에 따라)
    # 여기서는 우선 200 OK를 기대
    assert response.status_code == 200
    stats_data = response.json()
    # BaccaratStats 스키마 필드 검증
    assert "player_wins" in stats_data
    assert "banker_wins" in stats_data
    assert "tie_wins" in stats_data
    assert "total_rounds" in stats_data
    assert "player_win_percentage" in stats_data
    assert "banker_win_percentage" in stats_data
    assert "tie_percentage" in stats_data
    assert "last_shoe_results" in stats_data
    assert isinstance(stats_data["last_shoe_results"], list)
    
    print(f"바카라 통계 (Room: {test_room_id}) 조회 성공")

def test_get_baccarat_stats_not_found(client: TestClient):
    """존재하지 않는 룸 ID로 바카라 통계 조회 테스트 (Pytest 스타일)"""
    print("\n===== 바카라 통계 조회 테스트 (존재하지 않는 룸) =====")
    non_existent_room_id = "room_does_not_exist_123"
    headers = {
        "Accept-Language": "ko",
        "Host": "localhost"
    }
    
    response = client.get(f"/games/baccarat/{non_existent_room_id}/stats", headers=headers)
    print_response(response, f"바카라 통계 응답 (Room ID: {non_existent_room_id})")

    # get_baccarat_game 구현에 따라 404 또는 다른 오류 코드 반환 가능
    # 현재 API 코드는 존재하지 않는 룸에 대해서도 새 게임 객체를 생성하므로 200 반환 예상
    # 만약 get_baccarat_game이 룸 존재 여부를 확인하고 404를 반환한다면 assert 404로 변경 필요
    assert response.status_code == 200 
    
    # 또는 특정 오류 메시지 확인 (API 구현에 따라)
    # assert response.status_code == 500
    # assert "internal_server_error" in response.text # 혹은 특정 오류 키
    
    print(f"존재하지 않는 룸 ID({non_existent_room_id})로 통계 조회 시 예상대로 동작 (현재 200 OK)")

def test_play_baccarat_success(client: TestClient):
    """바카라 게임 플레이 성공 테스트 (Pytest 스타일)"""
    print("\n===== 바카라 게임 플레이 테스트 (성공) =====")
    test_room_id = "default_room"
    headers = {
        "Accept-Language": "ko",
        "Host": "localhost"
    }
    params = {
        "player_bet": 10.0,
        "banker_bet": 0,
        "tie_bet": 0
    }
    
    response = client.post(f"/games/baccarat/{test_room_id}/play", headers=headers, params=params)
    print_response(response, f"바카라 플레이 응답 (Room ID: {test_room_id})")

    assert response.status_code == 200
    result_data = response.json()
    # 게임 결과 필수 필드 확인 (API 응답 스키마에 따라 조정)
    assert "player_cards" in result_data
    assert "banker_cards" in result_data
    assert "result" in result_data
    assert "payout" in result_data # payout 키 존재 확인 재활성화
    assert isinstance(result_data["player_cards"], list)
    assert isinstance(result_data["banker_cards"], list)
    assert isinstance(result_data["payout"], (int, float)) # payout 타입 확인 추가
    
    print(f"바카라 플레이 (Room: {test_room_id}) 성공")

def test_play_baccarat_invalid_bet(client: TestClient):
    """바카라 게임 플레이 잘못된 베팅 테스트 (Pytest 스타일)"""
    print("\n===== 바카라 게임 플레이 테스트 (잘못된 베팅) =====")
    test_room_id = "default_room"
    headers = {
        "Accept-Language": "ko", # 한국어 번역 확인
        "Host": "localhost"
    }
    params = {
        "player_bet": 0,
        "banker_bet": 0,
        "tie_bet": 0 # 모든 벳이 0
    }
    
    response = client.post(f"/games/baccarat/{test_room_id}/play", headers=headers, params=params)
    print_response(response, f"바카라 플레이 응답 (잘못된 베팅, Room ID: {test_room_id})")

    assert response.status_code == 400
    error_data = response.json()
    assert "detail" in error_data
    # 실제 번역된 오류 메시지 확인
    expected_error_message = "베팅 금액이 없습니다. 베팅을 해주세요."
    print(f"실제 반환된 메시지: {error_data['detail']} (예상: {expected_error_message})")
    assert error_data["detail"] == expected_error_message

# --- Payout Verification Tests ---

@pytest.mark.parametrize("bet_type, bet_amount, expected_winner, expected_payout_multiplier", [
    # Player Wins
    ("player", 10.0, "player", 1.0),  # Player bet wins, payout 1:1
    ("banker", 10.0, "player", 0.0),  # Banker bet loses
    ("tie",    10.0, "player", 0.0),  # Tie bet loses
    ("player", 10.0, "banker", 0.0),  # Player bet loses
    # Banker Wins
    ("player", 10.0, "banker", 0.0),  # Player bet loses
    ("banker", 10.0, "banker", 0.95), # Banker bet wins, payout 0.95:1 (commission)
    ("tie",    10.0, "banker", 0.0),  # Tie bet loses
    # Tie Wins
    ("player", 10.0, "tie", 0.0),     # Player bet loses (or push depending on rules, assume loss here)
    ("banker", 10.0, "tie", 0.0),     # Banker bet loses (or push, assume loss)
    ("tie",    10.0, "tie", 8.0),     # Tie bet wins, payout 8:1 (default)
])
def test_play_baccarat_payout(client: TestClient, bet_type, bet_amount, expected_winner, expected_payout_multiplier, mocker):
    """바카라 게임 플레이 페이아웃 검증 테스트"""
    test_room_id = f"payout_test_room_{bet_type}_{expected_winner}_{random.randint(1000,9999)}"
    test_name = f"페이아웃 검증 - Bet: {bet_type} ${bet_amount}, Winner: {expected_winner}"
    print(f"\n===== {test_name} =====")

    # Mock BaccaratGame.play_round to force a specific winner
    # This avoids randomness and directly tests payout logic based on winner
    mock_game_result = {
        'player_cards': ['S2', 'H5'], # Dummy cards
        'banker_cards': ['D10', 'CK'], # Dummy cards
        'result': expected_winner, # Force the winner
        # Other potential fields returned by play_round, add if needed
        'player_value': 7,
        'banker_value': 0,
        'shoe_metrics': {'remaining_cards': 400}, # Dummy metrics
        'duration': 0.1
    }
    # Ensure the mock returns a copy to avoid modification issues if reused
    mocker.patch('backend.games.baccarat.BaccaratGame.play_round', return_value=mock_game_result.copy())

    headers = {"Host": "localhost"}
    params = {"player_bet": 0, "banker_bet": 0, "tie_bet": 0}
    params[f"{bet_type}_bet"] = bet_amount # Set the specific bet type and amount

    response = client.post(f"/games/baccarat/{test_room_id}/play", headers=headers, params=params)
    print_response(response, f"{test_name} 응답")

    assert response.status_code == 200, f"{test_name} - Expected 200, got {response.status_code}"
    result_data = response.json()

    assert "payout" in result_data, f"{test_name} - Payout key missing in response"
    actual_payout = result_data["payout"]
    expected_payout = bet_amount * expected_payout_multiplier

    print(f"실제 페이아웃: {actual_payout}, 예상 페이아웃: {expected_payout}")
    # Use pytest.approx for floating point comparison
    assert actual_payout == pytest.approx(expected_payout), f"{test_name} - Payout mismatch"

    print(f"{test_name} 성공")

# --- Test Runner Logic (if needed, or use pytest directly) ---
# def run_game_tests():
# ... (rest of the file remains the same)