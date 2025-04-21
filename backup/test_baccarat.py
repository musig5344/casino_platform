import requests
import json

# 서버 URL
BASE_URL = "http://127.0.0.1:8000"

def test_baccarat_game():
    # 바카라 게임 테스트
    room_id = "test_room_123"
    
    # 바카라 게임 플레이
    play_url = f"{BASE_URL}/games/baccarat/{room_id}/play"
    play_params = {
        "player_bet": 100,
        "banker_bet": 50,
        "tie_bet": 10
    }
    
    print("바카라 게임 플레이 시도...")
    play_response = requests.post(play_url, params=play_params)
    
    print(f"상태 코드: {play_response.status_code}")
    if play_response.status_code == 200:
        result = play_response.json()
        print("게임 결과:")
        print(f"- 플레이어 카드: {result.get('player_cards', [])}")
        print(f"- 뱅커 카드: {result.get('banker_cards', [])}")
        print(f"- 플레이어 점수: {result.get('player_score', 0)}")
        print(f"- 뱅커 점수: {result.get('banker_score', 0)}")
        print(f"- 결과: {result.get('result', '')}")
    else:
        print(f"오류: {play_response.text}")
    
    # 바카라 게임 통계 확인
    stats_url = f"{BASE_URL}/games/baccarat/{room_id}/stats"
    
    print("\n바카라 게임 통계 확인...")
    stats_response = requests.get(stats_url)
    
    if stats_response.status_code == 200:
        stats = stats_response.json()
        print("게임 통계:")
        print(f"- 총 라운드: {stats.get('total_games', 0)}")
        print(f"- 플레이어 승률: {stats.get('player_win_percentage', 0):.1f}%")
        print(f"- 뱅커 승률: {stats.get('banker_win_percentage', 0):.1f}%")
        print(f"- 무승부 확률: {stats.get('tie_percentage', 0):.1f}%")
    else:
        print(f"통계 조회 오류: {stats_response.text}")

if __name__ == "__main__":
    test_baccarat_game() 