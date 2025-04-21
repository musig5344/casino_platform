import random
import json
import uuid
import threading
from datetime import datetime
from typing import Dict, List, Any, Union, Optional

from backend.cache import get_redis_client


class Card:
    def __init__(self, suit: str, value: str):
        self.suit = suit
        self.value = value
        
    def get_numeric_value(self) -> int:
        if self.value in ['J', 'Q', 'K', '10']:
            return 0
        elif self.value == 'A':
            return 1
        else:
            return int(self.value)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'suit': self.suit,
            'value': self.value,
            'numeric_value': self.get_numeric_value()
        }


class CardShoe:
    def __init__(self, num_decks=8):
        self.num_decks = num_decks
        self.cards = []
        self.shuffle_thread = None
        self.shuffle_count = 0  # 셔플 횟수 추적
        self.creation_time = datetime.now()
        self.last_shuffle_time = None
        self.init_shoe()
        
    def init_shoe(self):
        """카드 슈 초기화 및 고급 셔플 알고리즘 적용"""
        suits = ['Hearts', 'Diamonds', 'Clubs', 'Spades']
        values = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        
        self.cards = []
        for _ in range(self.num_decks):
            for suit in suits:
                for value in values:
                    self.cards.append(Card(suit, value))
        
        # 고급 셔플 알고리즘 적용
        self.advanced_shuffle()
        self.shuffle_count += 1
        self.last_shuffle_time = datetime.now()
    
    def advanced_shuffle(self):
        """고급 셔플 알고리즘 - 실제 카지노 수준의 무작위성 구현"""
        # 1. 시드 초기화 (시간 기반)
        current_time = datetime.now()
        seed_value = int(current_time.timestamp() * 1000000)
        # 추가 엔트로피
        import os
        try:
            seed_value = seed_value ^ os.getpid()
            if hasattr(os, 'urandom'):
                seed_value = seed_value ^ int.from_bytes(os.urandom(4), byteorder='big')
        except Exception:
            pass
        
        random.seed(seed_value)
        
        # 2. 다중 셔플 적용
        # 2.1 Fisher-Yates 셔플
        n = len(self.cards)
        for i in range(n-1, 0, -1):
            j = random.randint(0, i)
            self.cards[i], self.cards[j] = self.cards[j], self.cards[i]
        
        # 2.2 리플 셔플
        temp = []
        half = n // 2
        for i in range(half):
            if i < half:
                temp.append(self.cards[i])
                temp.append(self.cards[i + half])
        
        if n % 2 != 0:
            temp.append(self.cards[-1])
        
        self.cards = temp
        
        # 2.3 블록 셔플
        block_size = 20
        for start in range(0, n, block_size):
            end = min(start + block_size, n)
            block = self.cards[start:end]
            for i in range(len(block)-1, 0, -1):
                j = random.randint(0, i)
                block[i], block[j] = block[j], block[i]
            self.cards[start:end] = block
            
        # 3. 최종 셔플
        self.shuffle()
    
    def shuffle(self):
        """기본 Fisher-Yates 셔플 알고리즘 적용"""
        n = len(self.cards)
        for i in range(n-1, 0, -1):
            j = random.randint(0, i)
            self.cards[i], self.cards[j] = self.cards[j], self.cards[i]
    
    def draw_card(self):
        """카드 한 장 뽑기 - 슈 상태 체크 포함"""
        if len(self.cards) <= 50 and (self.shuffle_thread is None or not self.shuffle_thread.is_alive()):
            self.shuffle_thread = threading.Thread(target=self.init_shoe)
            self.shuffle_thread.start()
            if len(self.cards) <= 10:
                self.shuffle_thread.join(0.2)
        
        if not self.cards:
            self.init_shoe()
            
        return self.cards.pop()
    
    def remaining_cards(self):
        """남은 카드 수 반환"""
        return len(self.cards)
        
    def get_metrics(self):
        """슈 메트릭 정보 반환 (감사 목적)"""
        return {
            'shoe_id': id(self),
            'num_decks': self.num_decks,
            'remaining_cards': len(self.cards),
            'shuffle_count': self.shuffle_count,
            'creation_time': self.creation_time.isoformat(),
            'last_shuffle_time': self.last_shuffle_time.isoformat() if self.last_shuffle_time else None,
            'total_cards': self.num_decks * 52,
            'usage_percentage': (1 - len(self.cards) / (self.num_decks * 52)) * 100
        }


class BaccaratGame:
    def __init__(self, room_id=None, tie_payout=8.0, bonus_payout=0.2):
        self.room_id = room_id or str(uuid.uuid4())
        self.shoes = [CardShoe(), CardShoe()]  # 2개의 카드 슈 생성
        self.current_shoe_index = 0
        self.hand_value_cache = {}  # 합계 캐시 추가
        self.total_games = 0
        self.game_results = {'player': 0, 'banker': 0, 'tie': 0}
        self.total_bets = {'player': 0, 'banker': 0, 'tie': 0}
        self.total_payouts = {'player': 0, 'banker': 0, 'tie': 0}
        self.start_time = datetime.now()
        
        # Redis 클라이언트 초기화
        self.redis_client = get_redis_client()
        
        # 배당률 설정
        self.payouts = {
            'player': 1.0,    # 플레이어 배당 1:1
            'banker': 0.95,   # 뱅커 배당 0.95:1 (5% 수수료)
            'tie': tie_payout  # 무승부 배당 8:1
        }
        
        # 바카라 룰 테이블 (3번째 카드 뽑는 룰)
        self.player_rule = {0: True, 1: True, 2: True, 3: True, 4: True, 5: True, 6: False, 7: False, 8: False, 9: False}
        self.banker_rule = {
            0: {0: True, 1: True, 2: True, 3: True, 4: True, 5: True, 6: True, 7: True, 8: True, 9: True},
            1: {0: True, 1: True, 2: True, 3: True, 4: True, 5: True, 6: True, 7: True, 8: True, 9: True},
            2: {0: True, 1: True, 2: True, 3: True, 4: True, 5: True, 6: True, 7: True, 8: True, 9: True},
            3: {0: True, 1: True, 2: True, 3: True, 4: True, 5: True, 6: True, 7: True, 8: False, 9: True},
            4: {0: False, 1: False, 2: True, 3: True, 4: True, 5: True, 6: True, 7: True, 8: False, 9: False},
            5: {0: False, 1: False, 2: False, 3: False, 4: True, 5: True, 6: True, 7: True, 8: False, 9: False},
            6: {0: False, 1: False, 2: False, 3: False, 4: False, 5: False, 6: True, 7: True, 8: False, 9: False},
            7: {0: False, 1: False, 2: False, 3: False, 4: False, 5: False, 6: False, 7: False, 8: False, 9: False},
        }
        
        self.game_history = []  # 최근 게임 결과 저장
        
        # 최근 결과 초기화
        self.redis_key_prefix = f"baccarat:{self.room_id}:"
        self.redis_client.set(f"{self.redis_key_prefix}recent_results", json.dumps([]))
        
        # bonus_payout 설정
        self.bonus_payout = bonus_payout
    
    def get_current_shoe(self):
        return self.shoes[self.current_shoe_index]
    
    def switch_shoe(self):
        # 다른 슈로 전환
        self.current_shoe_index = 1 - self.current_shoe_index
        
        # 전환한 슈의 카드가 50장 이하인지 확인하고, 그렇다면 초기화
        current_shoe = self.shoes[self.current_shoe_index]
        if current_shoe.remaining_cards() <= 50 and (current_shoe.shuffle_thread is None or not current_shoe.shuffle_thread.is_alive()):
            current_shoe.shuffle_thread = threading.Thread(target=current_shoe.init_shoe)
            current_shoe.shuffle_thread.start()
    
    def calculate_hand_value(self, cards):
        # 카드 값을 튜플로 변환하여 캐시 키로 사용
        card_tuple = tuple(card.get_numeric_value() for card in cards)
        
        if card_tuple not in self.hand_value_cache:
            total = sum(card.get_numeric_value() for card in cards)
            self.hand_value_cache[card_tuple] = total % 10  # 바카라 규칙: 합계의 1의 자리만 사용
        
        return self.hand_value_cache[card_tuple]
    
    def play_round(self, player_bet=0, banker_bet=0, tie_bet=0, user_id=None):
        # 시작 시간 기록
        start_time = datetime.now()
        
        # 현재 슈에서 카드 뽑기
        shoe = self.get_current_shoe()
        initial_remaining = shoe.remaining_cards()
        
        # 슈 교체 필요 여부 먼저 확인
        shoe_changed = False
        if initial_remaining < 14 or initial_remaining == 0: 
            old_shoe_index = self.current_shoe_index
            self.switch_shoe()
            shoe_changed = (old_shoe_index != self.current_shoe_index)
            shoe = self.get_current_shoe()
            initial_remaining = shoe.remaining_cards()

        # 플레이어와 뱅커에게 교대로 2장씩 카드 배분
        try:
            player_cards_obj = [shoe.draw_card(), shoe.draw_card()]
            banker_cards_obj = [shoe.draw_card(), shoe.draw_card()]
        except IndexError:
             self.switch_shoe()
             shoe = self.get_current_shoe()
             player_cards_obj = [shoe.draw_card(), shoe.draw_card()]
             banker_cards_obj = [shoe.draw_card(), shoe.draw_card()]             

        # 초기 점수 계산
        player_value = self.calculate_hand_value(player_cards_obj)
        banker_value = self.calculate_hand_value(banker_cards_obj)
        
        # 자연 8, 9 확인
        natural = (player_value >= 8 or banker_value >= 8)
        
        player_third = None
        
        # 추가 카드 규칙 적용
        if not natural:
            # 플레이어 추가 카드 규칙
            if self.player_rule[player_value]:
                try:
                    player_third = shoe.draw_card()
                    player_cards_obj.append(player_third)
                    player_value = self.calculate_hand_value(player_cards_obj)
                except IndexError:
                     pass
            
            # 뱅커 추가 카드 규칙
            banker_needs_third = False
            if player_third is None:
                if banker_value <= 5:
                    banker_needs_third = True
            else:
                player_third_value = player_third.get_numeric_value()
                if banker_value < 7 and self.banker_rule[banker_value].get(player_third_value, False):
                     banker_needs_third = True
            
            if banker_needs_third:
                 try:
                    banker_cards_obj.append(shoe.draw_card())
                    banker_value = self.calculate_hand_value(banker_cards_obj)
                 except IndexError:
                     pass
        
        # 승자 결정
        if player_value > banker_value:
            result = 'player'
        elif banker_value > player_value:
            result = 'banker'
        else:
            result = 'tie'
        
        # 게임 결과 기록
        self.total_games += 1
        self.game_results[result] += 1
        self.game_history.append(result[0].upper())
        if len(self.game_history) > 100:
             self.game_history.pop(0)
        
        # 최종 남은 카드 수 확인
        final_remaining = shoe.remaining_cards()

        # 소요 시간 계산
        end_time = datetime.now()
        elapsed_ms = (end_time - start_time).total_seconds() * 1000

        # 프론트엔드로 보낼 결과 데이터 구성
        game_data_for_frontend = {
            'result': result,
            'player_cards': [f"{card.value}{card.suit[0]}" for card in player_cards_obj],
            'banker_cards': [f"{card.value}{card.suit[0]}" for card in banker_cards_obj],
            'player_score': player_value,
            'banker_score': banker_value,
            'natural': natural,
            'shoe_changed': shoe_changed,
            'shoe_number': self.current_shoe_index + 1,
            'cards_remaining': final_remaining,
        }

        # 최근 결과 업데이트 (Redis)
        try:
            recent_results_json = self.redis_client.get(f"{self.redis_key_prefix}recent_results")
            if recent_results_json:
                if isinstance(recent_results_json, bytes):
                    recent_results_json = recent_results_json.decode('utf-8')
                recent_results = json.loads(recent_results_json)
            else:
                recent_results = []
                
            recent_results.insert(0, result[0].upper())
            if len(recent_results) > 20:
                recent_results = recent_results[:20]
                
            self.redis_client.set(f"{self.redis_key_prefix}recent_results", json.dumps(recent_results))
            
            # 슈 결과 업데이트
            shoe_results_key = f"{self.redis_key_prefix}shoe:{self.current_shoe_index}"
            shoe_results_json = self.redis_client.get(shoe_results_key)
            
            if shoe_results_json:
                if isinstance(shoe_results_json, bytes):
                    shoe_results_json = shoe_results_json.decode('utf-8')
                shoe_results = json.loads(shoe_results_json)
            else:
                shoe_results = []
                
            shoe_results.append({
                'result': result[0].upper(),
                'player_score': player_value,
                'banker_score': banker_value,
                'cards_remaining': final_remaining,
                'timestamp': datetime.now().isoformat()
            })
            
            self.redis_client.set(shoe_results_key, json.dumps(shoe_results))
            
        except Exception as e:
            print(f"Error updating Redis: {e}")

        return game_data_for_frontend

    def get_stats_and_recent_results(self):
        # 통계 계산
        stats = {
            'player_wins': self.game_results.get('player', 0),
            'banker_wins': self.game_results.get('banker', 0),
            'tie_wins': self.game_results.get('tie', 0)
        }
        
        # 최근 결과 가져오기
        try:
            recent_results_json = self.redis_client.get(f"{self.redis_key_prefix}recent_results")
            if recent_results_json:
                if isinstance(recent_results_json, bytes):
                     recent_results_json = recent_results_json.decode('utf-8')
                recent_results = json.loads(recent_results_json)
            else:
                recent_results = []
        except Exception as e:
             print(f"Error fetching recent results: {e}")
             recent_results = []
             
        current_shoe = self.get_current_shoe()

        # 마지막 슈 결과 가져오기
        try:
            shoe_results_key = f"{self.redis_key_prefix}shoe:{self.current_shoe_index}"
            shoe_results_json = self.redis_client.get(shoe_results_key)
            
            if shoe_results_json:
                if isinstance(shoe_results_json, bytes):
                    shoe_results_json = shoe_results_json.decode('utf-8')
                shoe_results = json.loads(shoe_results_json)
                last_shoe_results = [item['result'] for item in shoe_results]
            else:
                last_shoe_results = []
        except Exception as e:
            print(f"Error fetching shoe results: {e}")
            last_shoe_results = []

        # 승률 계산
        total_games = self.total_games
        if total_games > 0:
            player_win_percentage = (self.game_results.get('player', 0) / total_games) * 100
            banker_win_percentage = (self.game_results.get('banker', 0) / total_games) * 100
            tie_percentage = (self.game_results.get('tie', 0) / total_games) * 100
        else:
            player_win_percentage = banker_win_percentage = tie_percentage = 0

        return {
            'statistics': stats,
            'recent_results': recent_results,
            'game_history': list(self.game_history),
            'shoe_number': self.current_shoe_index + 1,
            'cards_remaining': current_shoe.remaining_cards(),
            'player_win_percentage': player_win_percentage,
            'banker_win_percentage': banker_win_percentage,
            'tie_percentage': tie_percentage,
            'total_games': total_games,
            'last_shoe_results': last_shoe_results
        }
        
    def calculate_payout(self, bet_type, bet_amount):
        """베팅 유형과 금액에 따른 배당금 계산"""
        if bet_type not in self.payouts:
            return 0
        
        return bet_amount * self.payouts[bet_type]


# 게임 인스턴스 관리를 위한 글로벌 딕셔너리
_baccarat_games = {}

def get_baccarat_game(room_id: str) -> BaccaratGame:
    """방 ID에 해당하는 바카라 게임 인스턴스를 반환 또는 생성"""
    if room_id not in _baccarat_games:
        _baccarat_games[room_id] = BaccaratGame(room_id=room_id)
    return _baccarat_games[room_id]

def remove_baccarat_game(room_id: str) -> None:
    """방 ID에 해당하는 바카라 게임 인스턴스 제거"""
    if room_id in _baccarat_games:
        del _baccarat_games[room_id] 