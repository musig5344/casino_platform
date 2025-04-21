# locustfiles/wallet_perf_test.py
import uuid
import random
from locust import HttpUser, task, between, events
from urllib.parse import urlparse, parse_qs

# --- Configuration ---
BASE_URL = "http://localhost:8000" # 실제 테스트 대상 호스트로 변경 필요
CASINO_KEY = "MY_CASINO"
API_TOKEN = "qwqw6171"
DEFAULT_HEADERS = {"Host": "localhost"} # 필요시 테스트 환경 호스트명으로 변경

# --- Helper Functions ---
def get_auth_token(http_client, player_id):
    """Authenticates a player and returns the token."""
    auth_endpoint = f"/ua/v1/{CASINO_KEY}/{API_TOKEN}"
    auth_data = {
        "uuid": str(uuid.uuid4()),
        "player": {
            "id": player_id,
            "firstName": "Load",
            "lastName": player_id.split('_')[-1],
            "country": "KR", "currency": "KRW",
            "session": {"id": f"load_session_{uuid.uuid4()}", "ip": "127.0.0.1"}
        },
        "config": {}
    }
    try:
        # name 인자를 추가하여 Locust UI에서 엔드포인트 그룹화
        response = http_client.post(auth_endpoint, json=auth_data, headers=DEFAULT_HEADERS, name="/ua/v1/auth")
        response.raise_for_status()
        entry_url = response.json().get("entry")
        if not entry_url: return None
        token = parse_qs(urlparse(entry_url).query).get("params", [None])[0]
        return token
    except Exception as e:
        events.request_failure.fire(
            request_type="POST", name=auth_endpoint, response_time=0,
            exception=e, response=None
        )
        return None

# --- Locust User Class ---
class WalletUser(HttpUser):
    wait_time = between(0.5, 1.5) # 사용자별 요청 간격 (초)
    host = BASE_URL

    def on_start(self):
        """Locust 워커 시작 시 호출"""
        self.player_id = f"load_user_{uuid.uuid4()}"
        self.token = get_auth_token(self.client, self.player_id)
        if not self.token:
            print(f"플레이어 {self.player_id} 인증 실패, 사용자 중지.")
            self.environment.runner.quit()
            return

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            **DEFAULT_HEADERS
        }
        self.recent_transaction_ids = [] # 취소 가능한 최근 거래 ID 저장
        self.balance = 0.0 # 간단한 잔액 추적 (정확하지 않을 수 있음)
        print(f"사용자 {self.player_id} 시작됨.")
        # 초기 지갑 생성 및 잔액 확보를 위한 Credit 호출
        self.credit_funds(initial=True)

    def credit_funds(self, initial=False):
        """Credit API 호출 태스크"""
        if not self.token: return
        tx_id = f"cred_{uuid.uuid4()}"
        amount = random.uniform(10.0, 500.0)
        payload = {
            "uuid": str(uuid.uuid4()),
            "transaction_id": tx_id,
            "player_id": self.player_id,
            "amount": round(amount, 2),
            "currency": "KRW"
        }
        # name 인자를 사용하여 Locust UI에서 그룹화
        with self.client.post("/api/credit", json=payload, headers=self.headers, catch_response=True, name="/api/credit") as response:
            if response.ok:
                self.balance += amount
                if not initial:
                     self.recent_transaction_ids.append(tx_id)
                response.success()
            else:
                response.failure(f"Credit 실패 {response.status_code}")

    def debit_funds(self):
        """Debit API 호출 태스크"""
        if not self.token or self.balance < 1.0: return
        tx_id = f"deb_{uuid.uuid4()}"
        max_debit = max(1.0, self.balance * 0.8)
        amount = random.uniform(1.0, max_debit)

        payload = {
            "uuid": str(uuid.uuid4()),
            "transaction_id": tx_id,
            "player_id": self.player_id,
            "amount": round(amount, 2),
            "currency": "KRW"
        }
        with self.client.post("/api/debit", json=payload, headers=self.headers, catch_response=True, name="/api/debit") as response:
            if response.ok:
                self.balance -= amount
                self.recent_transaction_ids.append(tx_id)
                response.success()
            elif response.status_code == 400: # 잔액 부족으로 예상
                # 잔액 부족도 실패로 간주할지, 별도 처리할지 결정 필요
                response.failure(f"Debit 실패 - 잔액 부족?")
            else:
                response.failure(f"Debit 실패 {response.status_code}")

    def cancel_transaction(self):
        """Cancel API 호출 태스크"""
        if not self.token or not self.recent_transaction_ids: return

        original_tx_id = random.choice(self.recent_transaction_ids)
        cancel_tx_id = f"cancel_{uuid.uuid4()}"
        payload = {
            "uuid": str(uuid.uuid4()),
            "transaction_id": cancel_tx_id,
            "player_id": self.player_id,
            "original_transaction_id": original_tx_id
        }
        with self.client.post("/api/cancel", json=payload, headers=self.headers, catch_response=True, name="/api/cancel") as response:
            if response.ok:
                if original_tx_id in self.recent_transaction_ids:
                     self.recent_transaction_ids.remove(original_tx_id)
                response.success()
            elif response.status_code == 404: # 취소 대상 거래 없음
                 response.failure(f"Cancel 실패 - 대상 Tx({original_tx_id}) 없음?")
                 if original_tx_id in self.recent_transaction_ids:
                      self.recent_transaction_ids.remove(original_tx_id)
            else:
                response.failure(f"Cancel 실패 {response.status_code}")

    # 태스크 비율 설정 (총합 100 기준)
    @task(4) # 40%
    def credit_task(self):
        self.credit_funds()

    @task(5) # 50%
    def debit_task(self):
        self.debit_funds()

    @task(1) # 10%
    def cancel_task(self):
         self.cancel_transaction()
