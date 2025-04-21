from fastapi import FastAPI, Request, Depends
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.datastructures import URL
from starlette.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
import typing
from backend.api import auth, games, aml, test # test API 추가
from backend.api import wallet as wallet_api_router # Alias for wallet API router
from backend.api import game_history as game_history_api_router # Alias for game_history API router
from backend.database import engine, Base
# Import all models that use Base so they are registered before create_all
from backend.models import user, wallet, game_history, aml as aml_models, game # aml 모델 추가
import logging
from backend.config.database import settings
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from fastapi.exceptions import RequestValidationError, HTTPException
from contextlib import asynccontextmanager # lifespan을 위해 추가

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# IP 화이트리스트 미들웨어 클래스
class IPWhitelistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 화이트리스트가 비어있으면 모든 IP 허용
        if not settings.IP_WHITELIST:
            return await call_next(request)
        
        # 클라이언트 IP 주소 가져오기
        client_ip = request.client.host
        whitelist = settings.IP_WHITELIST.split(",")
        
        # 화이트리스트에 없는 IP면 403 반환
        if client_ip not in whitelist:
            logger.warning(f"허용되지 않은 IP에서의 접근 시도: {client_ip}")
            return RedirectResponse(
                url="/api/forbidden",
                status_code=403
            )
        
        return await call_next(request)

# --- DB 초기화 함수 (기존 on_startup에서 사용) ---
# 이 함수는 lifespan으로 이동
# def create_tables():
#     print("DB 테이블 생성 시도...")
#     try:
#         Base.metadata.create_all(bind=engine)
#         print("DB 테이블 생성 완료 (또는 이미 존재).")
#     except Exception as e:
#         print(f"DB 테이블 생성 중 오류 발생: {e}")
#         # 실제 프로덕션에서는 로깅 또는 다른 오류 처리 필요

# --- Lifespan 관리자 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 애플리케이션 시작 시 실행될 코드
    print("애플리케이션 시작 - Lifespan")
    # DB 테이블 생성 (기존 on_startup 작업)
    print("DB 테이블 생성 시도 (Lifespan)...")
    try:
        # 비동기 환경에서는 create_all을 직접 실행하는 것보다
        # alembic 같은 마이그레이션 도구를 사용하는 것이 더 일반적일 수 있음
        # 여기서는 동기 함수를 호출 (FastAPI가 처리해 줌)
        Base.metadata.create_all(bind=engine)
        print("DB 테이블 생성 완료 (또는 이미 존재) (Lifespan).")
    except Exception as e:
        print(f"DB 테이블 생성 중 오류 발생 (Lifespan): {e}")
        # 실제 프로덕션에서는 로깅 또는 다른 오류 처리 필요
        
    # 번역 데이터 로드 (i18n 로드 시점 변경 고려)
    # load_translations() # 이미 i18n.py에서 로드됨
    
    # 캐시 클라이언트 연결 (필요하다면)
    # await redis_client.ping() # 예시

    print("애플리케이션 준비 완료.")
    yield # 애플리케이션 실행
    # 애플리케이션 종료 시 실행될 코드
    print("애플리케이션 종료 - Lifespan")
    # 리소스 정리 (예: DB 연결 풀, 캐시 연결 종료)
    # await redis_client.close()

# --- FastAPI 애플리케이션 생성 ---
app = FastAPI(
    title="Casino Platform API",
    description="API for an online casino platform supporting user authentication, wallet management, and real-time gaming functionalities.",
    version="1.0.0",
    # on_startup=[create_tables], # 더 이상 사용하지 않음
    lifespan=lifespan # lifespan 컨텍스트 관리자 사용
)

# IP 화이트리스트 미들웨어 추가
if settings.IP_WHITELIST:
    app.add_middleware(IPWhitelistMiddleware)
    logger.info(f"IP 화이트리스트 미들웨어 활성화됨: {settings.IP_WHITELIST}")

# HTTPS 리다이렉션 미들웨어 추가 (프로덕션 환경에서만 활성화)
if settings.ENVIRONMENT.lower() == "production":
    app.add_middleware(HTTPSRedirectMiddleware)
    logger.info("HTTPS 리다이렉션 미들웨어 활성화됨")

# 신뢰할 수 있는 호스트 미들웨어 추가
app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=settings.ALLOWED_HOSTS.split(",")
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 포함 (Use aliases)
app.include_router(auth.router)
app.include_router(wallet_api_router.router) # Use wallet alias
app.include_router(games.router)
app.include_router(game_history_api_router.router) # Use game_history alias
app.include_router(aml.router)
app.include_router(test.router)

@app.get("/", tags=["Root"])
async def read_root():
    """
    Root endpoint providing a basic health check message.
    Confirms that the API is running.
    """
    return {"message": "Welcome to the Casino Platform API. It's running!"}

@app.get("/api/forbidden", include_in_schema=False)
async def forbidden():
    """
    403 Forbidden 응답에 대한 엔드포인트
    """
    return {"error": "Access denied. Your IP is not whitelisted."}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
