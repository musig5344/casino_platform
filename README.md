# 온라인 카지노 플랫폼 기술 아키텍처 설계

## 1. 개요

본 문서는 실시간 라이브 카지노 게임(룰렛, 블랙잭 등), 사용자 인증, 지갑 관리, 게임 기록, 보안 통신 기능을 갖춘 온라인 카지노 플랫폼 구축을 위한 상세 기술 아키텍처 및 가이드라인을 제공합니다. ocasino API와의 통합을 전제로 하며, AI 에이전트를 활용하여 개발, 테스트, 최적화를 수행합니다. 업계 표준, ocasino 통합 문서 및 오픈소스 도구를 기반으로 설계되었습니다.

### 1.1. 목표
- 확장 가능하고 안전하며 실시간 성능을 보장하는 플랫폼 개발
- AI 에이전트를 통한 코드 생성, 테스트, 모니터링, 최적화 통합
- 보안 및 규제 요구사항(HTTPS, GDPR, IP 화이트리스팅 등) 준수
- 프론트엔드(Node.js) 및 백엔드(Python) 시스템과의 원활한 통합 및 ocasino API 연동

### 1.2. 대상 독자
- 플랫폼 개발자 및 아키텍트
- AI 에이전트 (코드 생성, 테스트, 배포 지원)
- 프로젝트 관리자 및 운영팀

---

## 2. 시스템 아키텍처

### 2.1. 고수준 아키텍처
플랫폼은 다음과 같은 주요 구성 요소로 구성됩니다:

- **프론트엔드**: Node.js 기반 UI (React/Vue 권장). 사용자 인터페이스, 게임 상호작용, 실시간 업데이트 담당.
- **백엔드**: Python 기반 서버 (FastAPI 권장). 비즈니스 로직, ocasino API 연동, 자체 API 제공, 데이터 관리 담당.
- **실시간 통신**: WebRTC (라이브 비디오/오디오 스트리밍) 및 WebSocket (게임 상태 업데이트, 채팅) 서버.
- **데이터베이스**: PostgreSQL (영구 데이터 저장 - 사용자, 게임 기록, 트랜잭션), Redis (세션 관리, 캐싱, 실시간 데이터 임시 저장).
- **메시지 큐**: Apache Kafka (이벤트 소싱, 로깅, 비동기 처리, 서비스 간 통신).
- **AI 에이전트**: 개발 지원, 테스트 자동화, 성능 최적화, 사용자 분석, 이상 탐지(사기, 어뷰징).
- **외부 서비스**: ocasino API, 결제 게이트웨이, 라이브 스트리밍 인프라, AML/KYC 솔루션, GeoIP 등.

### 2.2. 아키텍처 다이어그램

```mermaid
graph TD
    A[플레이어 브라우저/앱] -->|HTTPS/WebSocket/WebRTC| B(프론트엔드: Node.js - React/Vue)
    B -->|HTTP API/WebSocket| D(백엔드: Python - FastAPI)
    B <------> C(실시간 통신 서버: WebSocket/WebRTC)
    D -->|ocasino API 호출| J(ocasino API)
    D <------> E(AI 에이전트)
    D -->|DB 접근| F(데이터베이스: PostgreSQL)
    D -->|Cache 접근| G(캐시: Redis)
    D -->|이벤트 발행/소비| H(메시지 큐: Kafka)
    F <------> H
    G <------> H
    D -->|외부 API| I(기타 외부 서비스: 결제, AML/KYC 등)

    style J fill:#f9d,stroke:#333,stroke-width:2px
```
*(참고: 위 다이어그램은 mermaid 구문 예시입니다.)*

### 2.3. 기술 스택
- **프론트엔드**: Node.js, React/Vue.js, Socket.IO-Client, Axios, Tailwind CSS (권장)
- **백엔드**: Python 3.11+, FastAPI, SQLAlchemy, Pydantic, JWT
- **데이터베이스**: PostgreSQL, Redis
- **메시지 큐**: Apache Kafka
- **실시간 통신**: Socket.IO, WebRTC 라이브러리 (PeerJS, Kurento 등)
- **AI 도구**: LangChain, Pytest, TensorFlow/Scikit-learn
- **보안**: HTTPS, OAuth2/JWT, IP Whitelisting, AES-256, bcrypt
- **DevOps**: Docker, Kubernetes, GitHub Actions, Prometheus/Grafana

---

## 3. 핵심 구성 요소 상세

- **프론트엔드**: 사용자 인터페이스 제공, 게임 상호작용, 실시간 데이터 시각화.
- **백엔드**: 핵심 비즈니스 로직 처리, ocasino API 및 자체 API 관리, 데이터 관리, 외부 서비스 연동.
- **데이터베이스**: PostgreSQL (영구 데이터), Redis (세션/캐시/임시 데이터).
- **실시간 통신**: WebSocket (게임 상태 업데이트, 채팅), WebRTC (라이브 비디오/오디오).
- **메시지 큐**: Kafka (이벤트/로그 스트리밍, 비동기 처리, 시스템 분리).
- **AI 에이전트**: 개발 생산성 향상, 테스트/운영 자동화, 사용자 경험 개인화, 위험 관리.
- **외부 서비스**: ocasino API 연동 및 결제, AML/KYC, 스트리밍, GeoIP 등 전문 기능 활용.

---

## 4. 주요 기능 및 ocasino API 연동 설계

### 4.1. 사용자 인증 (ocasino User Authentication API 연동)
- **목적**: 플레이어 식별, 세션 생성, ocasino 게임 접근 제어.
- **ocasino Endpoint**: `POST https://<licensee_hostname>/ua/v1/{casino_key}/{api_token}`
- **핵심 기능**: 회원가입(연령 확인), 로그인 처리 후 ocasino 인증 요청, 세션 토큰(내부 JWT) 발급, ocasino 게임 실행 URL 생성 및 반환.
- **요청/응답**: ocasino 문서의 JSON 형식 준수. `player`, `config` 등 필요한 모든 파라미터 포함. 성공 시 `entry`, `entryEmbedded` URL 반환.
- **오류 처리**: ocasino 반환 오류 코드(예: `G.0`, `V.41`, `G.9`) 처리 및 로깅. 내부 유효성 검증(예: `INVALID_AGE`, `DUPLICATE_ACCOUNT`) 추가.
- **보안**: HTTPS 통신, ocasino 제공 `casino_key`, `api_token` 사용, 클라이언트 IP 화이트리스팅 필수. 사용자 브라우저 쿠키 활성화 필요.
- **규칙 연동**: 단일 계정 정책, 정확한 정보 입력 요구, 접속 정보(IP, 국가) 기록 및 전달. `config.urls.responsibleGaming` 필드 활용.

### 4.2. 지갑 관리 (ocasino One Wallet API 연동)
- **목적**: ocasino 게임 내 실시간 자금 처리(베팅, 승리 정산, 취소).
- **ocasino Base URL**: `https://<licensee_service_host>/api/`
- **ocasino Endpoints**: `/check`, `/balance`, `/debit`, `/credit`, `/cancel` (모두 POST, `authToken` 쿼리 파라미터 필요).
- **핵심 기능**: 각 엔드포인트에 대한 요청/응답 처리 로직 구현. ocasino 요청 형식(JSON, `uuid`, `sid`, `userid`, `transaction` 등) 준수.
- **응답 처리**: ocasino `StandardResponse` (`status`, `balance`, `bonus`, `uuid`) 처리. `OK` 외 상태 코드(예: `INSUFFICIENT_FUNDS`, `INVALID_PLAYER_ID`, `BET_ALREADY_EXIST`)에 따른 로직 분기.
- **정산 방식**: `Gamewise` 정산 (게임 라운드당 집계된 크레딧 요청) 지원.
- **재시도 정책**: Debit, Credit, Cancel 요청 시 ocasino 기본 재시도 정책(5회/1분 -> 10회/5분 -> 24회/10분) 또는 협의된 정책 구현. `INSUFFICIENT_FUNDS`, `INVALID_PLAYER_ID`는 재시도 불가.
- **보안**: HTTPS 통신, ocasino 제공 `authToken` 사용.
- **규칙 연동**: 본인 소유 결제 수단 확인 로직은 플랫폼 자체에서 처리 후 API 연동. 플랫폼 입출금 한도와 연계. 모든 거래 Kafka 로깅 (감사 추적용).

### 4.3. 게임 기록 (ocasino Game History API 연동)
- **목적**: ocasino 게임 기록 저장 및 조회 (플레이어/운영자용).
- **ocasino Base URL**: `https://<licensee_hostname>/api/gamehistory/v1`
- **ocasino Endpoints**: `/casino/daily-report`, `/casino/games`, `/casino/games/stream`, `/players/{playerId}/games/{gameId}` (모두 GET, HTTP Basic Auth 필요).
- **핵심 기능**: 필요한 리포트 및 게임 상세 정보 조회 기능 구현. 날짜, 게임 유형 등 필터링 파라미터 지원.
- **대용량 처리**: `/casino/games/stream` 엔드포인트 활용 시 청크(Chunked) 전송 처리 로직 구현.
- **보안**: HTTPS 통신, HTTP Basic Authentication (Base64 인코딩된 `casino_key:apiToken`).
- **데이터 활용**: 조회된 데이터를 플랫폼 DB(`game_history` 테이블 등)에 저장하거나, 필요시 실시간 조회하여 사용자에게 제공. `transactionId` 필드를 통해 `wallet_transactions`와 연동.
- **규칙 연동**: 감사 및 분쟁 해결을 위한 상세 정보(베팅 내역, 결과, 시간 등) 활용.

### 4.4. 실시간 게임 스트리밍 및 업데이트
- **목적**: 라이브 딜러 비디오 스트리밍 및 실시간 게임 상태 업데이트 제공.
- **기술**: WebRTC (비디오/오디오), WebSocket (게임 이벤트).
- **핵심 기능**: 저지연 비디오 스트리밍 인터페이스 제공, WebSocket을 통한 게임 이벤트(베팅 가능/종료, 결과 발표 등) 실시간 수신 및 프론트엔드 전파.
- **연동**: ocasino 게임 클라이언트가 제공하는 스트리밍 및 이벤트 활용. 플랫폼 자체 WebSocket 서버는 보조적인 역할(채팅, 플랫폼 알림 등) 수행 가능.

### 4.5. 보너스 및 프로모션 관리
- **목적**: 플랫폼 자체 보너스 및 프로모션 생성, 지급, 추적.
- **핵심 기능**: 보너스 조건 설정(웨이저링 등), 지급/회수 로직, 사용자별 상태 조회 API 제공.
- **규칙 연동**: ocasino API와는 별개로 플랫폼 내부 로직으로 구현. 보너스 약관 적용, 어뷰징 방지(다중 계정 확인 등) 로직 포함.
- **API (자체)**: `/api/bonuses`, `/api/bonuses/{bonus_id}/claim`, `/api/players/{player_id}/bonuses` (예시)

### 4.6. 책임감 있는 게임 기능
- **목적**: 건전한 게임 습관 지원 및 문제성 도박 예방.
- **핵심 기능**: 한도 설정(입금, 베팅, 세션), 현실 점검 알림, 자가 제외 신청/관리 기능 UI 및 API 제공.
- **규칙 연동**: 사용자 규칙 6항 준수. ocasino User Authentication API의 `config.urls.responsibleGaming` 파라미터 활용. 플랫폼 내부에서 한도 강제 적용 로직 구현.
- **API (자체)**: `/api/players/{player_id}/limits`, `/api/players/{player_id}/self-exclusion` (예시)

---

## 5. 데이터베이스 설계

### 5.1. PostgreSQL 스키마 (주요 테이블 요약)

- **players**: 플레이어 정보 (ID, 이름, 이메일, 생년월일, 국가, 통화, 상태 등). 비밀번호는 bcrypt 해싱.
- **sessions**: 사용자 세션 정보 (세션 ID, 플레이어 ID, IP 주소, 만료 시간 등).
- **wallet_transactions**: 지갑 거래 내역 (ID, UUID, 플레이어 ID, 거래 유형, 금액, 잔액, 게임 ID, 상태 등). ocasino `transaction.id` 연동.
- **game_history**: 게임 플레이 기록 (ID, 게임 ID, 플레이어 ID, 게임 유형, 베팅/지급액, 결과, 시간 등). ocasino 데이터 저장 또는 연동.
- **bonuses**: 보너스 정보 (코드, 유형, 금액/비율, 웨이저링 조건, 유효 기간 등).
- **player_bonuses**: 플레이어별 보너스 상태 (지급액, 웨이저링 진행률, 상태 등).
- **player_limits**: 책임감 있는 게임 설정 (입금/베팅/세션 한도, 자가 제외 기간 등).

*(상세 스키마 및 인덱스는 이전 버전 또는 설계 문서를 참조하십시오.)*

### 5.2. Redis 활용
- **세션 관리**: 빠른 인증 확인을 위한 세션 데이터 저장.
- **캐싱**: DB 부하 감소 (게임 목록, 사용자 잔액 등). 캐시 TTL 및 무효화 전략 필요.
- **실시간 데이터**: 진행 중 게임 상태 등 임시 데이터 저장/조회.
- **Rate Limiting**: API 요청 빈도 제한.
- **Pub/Sub**: 간단한 실시간 알림 또는 서버 간 메시지 전달.

---

## 6. 보안 요구사항

- **데이터 암호화**: 전송(HTTPS/WSS TLS 1.2+) 및 저장(AES-256, bcrypt) 시 암호화 필수.
- **인증/인가**:
    - ocasino API: 각 API별 인증 방식 준수 (API Key/Token, AuthToken, Basic Auth).
    - 플랫폼 내부: JWT/OAuth2 기반 인증, 역할 기반 접근 제어 (RBAC).
- **IP 화이트리스팅**: ocasino API 연동을 위한 서버 IP 등록 필수. 플랫폼 관리 기능 접근 제한.
- **입력값 검증**: 모든 외부 입력(API 요청, 사용자 입력) 유효성 검사 (SQL Injection, XSS 방지).
- **보안 헤더**: CSP, HSTS 등 보안 관련 HTTP 헤더 적용.
- **DDoS 방어**: 클라우드 인프라 또는 전문 솔루션 활용.
- **보안 감사**: 정기적인 코드 검토, 모의 해킹, 취약점 스캔.
- **로깅/모니터링**: 중요 활동(인증, 거래, 오류) 로깅 및 실시간 이상 행위 탐지.

---

## 7. AI 에이전트 활용 가이드

- **목적**: 개발 생산성 향상, 테스트 자동화, 운영 효율화.
- **활용 분야**:
    - **코드 생성**: API 엔드포인트, DB 모델, UI 컴포넌트 등 보일러플레이트 생성. (주의: ocasino 관련 로직은 문서 기반 검증 필수)
    - **테스트 생성**: 단위/통합/부하 테스트 스크립트 생성 (Pytest, Locust 등). ocasino 오류 케이스 포함.
    - **문서화**: API 명세(OpenAPI) 생성, README 초안 작성 지원.
    - **최적화**: DB 쿼리 분석 및 인덱스 제안, 캐싱 전략 추천.
    - **분석/탐지**: 로그 분석 통한 오류 예측, 사용자 행동 분석 기반 이상 탐지(사기, 어뷰징), 책임감 있는 게임 패턴 감지.
- **활용 규칙**:
    - **명확한 프롬프트**: 대상 API, 기술 스택, 제약 조건 명시.
    - **출력 검증**: 생성된 코드/테스트/문서는 반드시 ocasino 문서 및 플랫폼 설계 기준으로 검토 및 수정. 보안, 성능, 규정 준수 항목 중점 확인.
    - **범위 제한**: 복잡한 작업은 단계별로 분할하여 요청.
    - **표준 준수**: 코드 스타일(PEP 8, ESLint), API 명세 형식 등 표준 준수 요구.
- *(참고: 상세한 AI 활용 규칙 및 프롬프트 예시는 별도 문서 "CursorAI Integration Rules for ocasino API.markdown" 참조 - 파일명 변경 필요)*

---

## 8. 확장성 및 성능

- **수평 확장**: Stateless 서비스(API, WebSocket) 설계, Kubernetes HPA 활용, DB Read Replica 구성.
- **캐싱**: Redis 적극 활용 (세션, API 응답, 게임 데이터 등). 캐시 일관성 유지 전략 중요.
- **DB 최적화**: 인덱싱, 쿼리 튜닝, 파티셔닝(대용량 테이블), Connection Pooling.
- **비동기 처리**: FastAPI 비동기 활용, 무거운 작업(알림, 리포트 생성 등)은 Kafka/Celery 워커로 분리.
- **메시지 큐**: Kafka 통한 서비스 분리, 비동기 통신, 이벤트 소싱 패턴 구현.
- **CDN**: 정적 파일 및 비디오 스트리밍 전송 속도 개선, 서버 부하 감소.

---

## 9. 규정 준수 및 윤리

- **책임감 있는 게임**: 사용자 한도 설정, 현실 점검, 자가 제외 기능 필수 제공 및 강제.
- **데이터 프라이버시**: GDPR 등 법규 준수, 사용자 동의, 데이터 최소화, 익명화/가명화 처리.
- **연령 확인**: 신뢰성 있는 방법으로 가입 시 연령 확인.
- **지역 제한**: 라이선스 및 법규 기반 Geo-Blocking 구현 (GeoIP 활용).
- **AML/KYC**: 의심 거래 보고(STR), 고객 확인 절차, 외부 솔루션 연동.
- **공정한 게임**: RNG 인증 (ocasino 측 제공), 게임 규칙/RTP 투명성 보장.
- **감사 추적**: 모든 중요 이벤트(금융 거래, 계정 변경, 게임 결과 등) 변경 불가능한 형태로 로깅 및 규정 기간 보관.

---

## 10. 배포 및 운영 (DevOps)

- **컨테이너화**: Docker 기반 서비스 패키징.
- **오케스트레이션**: Kubernetes 활용 (배포, 스케일링, 관리 자동화).
- **CI/CD**: GitHub Actions 등 자동화 파이프라인 구축 (빌드, 테스트, 보안 스캔, 배포).
- **인프라 관리**: Terraform 등 IaC (Infrastructure as Code) 도구 활용.
- **모니터링/로깅**: Prometheus, Grafana, Loki/ELK 스택 활용, 분산 추적 시스템 도입.
- **알림**: PagerDuty, Slack 등 연동하여 실시간 오류 및 경고 알림.
- **백업/복구**: 정기적인 DB 백업, 복구 절차 수립 및 테스트, 재해 복구(DR) 계획.

---

## 11. 결론

본 문서는 ocasino API와 통합된 고성능 온라인 카지노 플랫폼 구축을 위한 기술 아키텍처 및 가이드라인을 제공합니다. 제시된 아키텍처, API 연동 방식, 보안 및 규정 준수 요구사항을 바탕으로, AI 에이전트의 지원을 받아 효율적이고 안정적인 시스템 개발을 목표로 합니다.

성공적인 프로젝트 수행을 위해 본 문서와 ocasino 공식 문서를 지속적으로 참조하고, 변경 사항 발생 시 문서를 업데이트해야 합니다. 추가 지원이 필요하면 관련 기술팀 또는 ocasino 지원팀에 문의하십시오.