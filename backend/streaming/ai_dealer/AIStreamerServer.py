import asyncio
import uuid
import logging
import json
import os
import boto3
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import socketio
import uvicorn
from pydantic import BaseModel, Field
from botocore.exceptions import ClientError

from .AIDealer import AIDealer
from .AIWebRTCBridge import AIWebRTCBridge
from ..aws.media_live_service import MediaLiveService
from ..aws.elastic_cache_service import ElastiCacheService

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 모델 정의
class DealerInfo(BaseModel):
    dealer_id: str = Field(..., description="AI 딜러 고유 ID")
    game_type: str = Field(..., description="게임 유형 (blackjack, roulette, baccarat 등)")
    media_live_channel_id: Optional[str] = Field(None, description="AWS MediaLive 채널 ID (없으면 새로 생성)")
    fps: int = Field(30, description="초당 프레임 수")
    resolution: List[int] = Field([1280, 720], description="비디오 해상도 (width, height)")

class WebRTCSessionRequest(BaseModel):
    dealer_id: str = Field(..., description="AI 딜러 고유 ID")
    client_id: Optional[str] = Field(None, description="클라이언트 ID (없으면 자동 생성)")

class RTCSessionDescription(BaseModel):
    sdp: str = Field(..., description="SDP 설명")
    type: str = Field(..., description="SDP 유형 (offer/answer)")

class ICECandidate(BaseModel):
    candidate: str = Field(..., description="ICE 후보")
    sdpMid: str = Field(..., description="SDP 미디어 ID")
    sdpMLineIndex: int = Field(..., description="SDP 미디어 라인 인덱스")

class GameStateUpdate(BaseModel):
    state: Dict[str, Any] = Field(..., description="게임 상태 업데이트")

# FastAPI 앱 생성
app = FastAPI(
    title="AI 딜러 스트리밍 서버",
    description="AWS MediaLive를 활용한 AI 딜러 스트리밍 서비스",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Socket.IO 서버 생성
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*"
)
socket_app = socketio.ASGIApp(sio)

# AWS 서비스 클라이언트 및 관리 객체 초기화
media_live_service = None
elastic_cache_service = None
bridge = AIWebRTCBridge()

# 소켓 클라이언트 연결 관리
connected_clients = {}

# 초기화 완료 이벤트
server_ready = asyncio.Event()

@app.on_event("startup")
async def startup_event():
    global media_live_service, elastic_cache_service
    
    # AWS 자격 증명 확인 및 서비스 초기화
    try:
        # MediaLive 서비스 초기화
        media_live_service = MediaLiveService()
        logger.info("AWS MediaLive 서비스 초기화됨")
        
        # ElastiCache 서비스 초기화
        elastic_cache_service = ElastiCacheService()
        logger.info("AWS ElastiCache 서비스 초기화됨")
        
    except Exception as e:
        logger.error(f"AWS 서비스 초기화 실패: {str(e)}")
    
    # 서버 준비 완료
    server_ready.set()
    logger.info("AI 딜러 스트리밍 서버 시작됨")

@app.on_event("shutdown")
async def shutdown_event():
    # 모든 연결 종료
    await bridge.close_all_connections()
    logger.info("AI 딜러 스트리밍 서버 종료됨")

@app.get("/")
async def get_root():
    return {
        "message": "AI 딜러 스트리밍 서버",
        "status": "online",
        "docs": "/docs"
    }

# 딜러 관리 API
@app.post("/dealers")
async def create_dealer(dealer_info: DealerInfo):
    """AI 딜러 생성 및 등록"""
    try:
        # MediaLive 채널 ID 확인
        media_live_channel_id = dealer_info.media_live_channel_id
        
        # 채널 ID가 없으면 새로 생성
        if not media_live_channel_id and media_live_service:
            try:
                # MediaLive 채널 생성
                channel_name = f"ai-dealer-{dealer_info.dealer_id}-{dealer_info.game_type}"
                channel_info = await media_live_service.create_channel(
                    name=channel_name,
                    resolution=tuple(dealer_info.resolution),
                    fps=dealer_info.fps
                )
                media_live_channel_id = channel_info.get("channel_id")
                logger.info(f"새 MediaLive 채널 생성됨: {media_live_channel_id}")
            except Exception as e:
                logger.error(f"MediaLive 채널 생성 실패: {str(e)}")
                raise HTTPException(status_code=500, detail=f"MediaLive 채널 생성 실패: {str(e)}")
        
        # AI 딜러 인스턴스 생성
        ai_dealer = AIDealer(
            dealer_id=dealer_info.dealer_id,
            game_type=dealer_info.game_type,
            media_live_channel_id=media_live_channel_id,
            fps=dealer_info.fps,
            resolution=tuple(dealer_info.resolution)
        )
        
        # WebRTC 브릿지에 딜러 등록
        await bridge.register_ai_dealer(ai_dealer)
        
        # AI 딜러 시작
        await ai_dealer.start()
        
        return {
            "status": "success",
            "message": f"AI 딜러 {dealer_info.dealer_id} 생성됨",
            "dealer_id": dealer_info.dealer_id,
            "media_live_channel_id": media_live_channel_id,
            "stream_info": ai_dealer.get_stream_info()
        }
        
    except Exception as e:
        logger.error(f"AI 딜러 생성 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/dealers/{dealer_id}")
async def delete_dealer(dealer_id: str):
    """AI 딜러 등록 해제"""
    try:
        # 딜러 등록 해제
        success = await bridge.unregister_ai_dealer(dealer_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"딜러 ID {dealer_id}를 찾을 수 없습니다")
        
        return {
            "status": "success",
            "message": f"AI 딜러 {dealer_id} 삭제됨"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI 딜러 삭제 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dealers")
async def list_dealers():
    """등록된 모든 AI 딜러 목록 반환"""
    try:
        stats = bridge.get_stats()
        
        return {
            "status": "success",
            "dealers": stats["ai_dealers"],
            "total": stats["total_dealers"]
        }
        
    except Exception as e:
        logger.error(f"딜러 목록 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dealers/{dealer_id}")
async def get_dealer(dealer_id: str):
    """특정 AI 딜러 정보 조회"""
    try:
        # AI 딜러 확인
        if dealer_id not in bridge.ai_dealers:
            raise HTTPException(status_code=404, detail=f"딜러 ID {dealer_id}를 찾을 수 없습니다")
        
        ai_dealer = bridge.ai_dealers[dealer_id]
        
        return {
            "status": "success",
            "dealer": {
                "stream_info": ai_dealer.get_stream_info(),
                "game_state": ai_dealer.get_game_state()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"딜러 정보 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/dealers/{dealer_id}/game-state")
async def update_game_state(dealer_id: str, update: GameStateUpdate):
    """AI 딜러 게임 상태 업데이트"""
    try:
        # AI 딜러 확인
        if dealer_id not in bridge.ai_dealers:
            raise HTTPException(status_code=404, detail=f"딜러 ID {dealer_id}를 찾을 수 없습니다")
        
        ai_dealer = bridge.ai_dealers[dealer_id]
        
        # 게임 상태 업데이트
        updated_state = ai_dealer.update_game_state(update.state)
        
        # 연결된 클라이언트에 상태 변경 알림
        await sio.emit('game_state_update', {
            'dealer_id': dealer_id,
            'state': updated_state
        })
        
        return {
            "status": "success",
            "message": f"게임 상태 업데이트됨: {dealer_id}",
            "updated_state": updated_state
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"게임 상태 업데이트 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# WebRTC API
@app.post("/webrtc/session")
async def create_webrtc_session(request: WebRTCSessionRequest):
    """WebRTC 세션 생성 (AWS MediaLive/MediaConnect 활용)"""
    try:
        # AI 딜러 확인
        dealer_id = request.dealer_id
        if dealer_id not in bridge.ai_dealers:
            raise HTTPException(status_code=404, detail=f"딜러 ID {dealer_id}를 찾을 수 없습니다")
        
        # 클라이언트 ID 생성 (또는 기존 ID 사용)
        client_id = request.client_id or str(uuid.uuid4())
        
        # WebRTC 세션 생성
        session_info = await bridge.create_webrtc_session(dealer_id, client_id)
        
        logger.info(f"WebRTC 세션 생성됨: 클라이언트 {client_id}, 딜러 {dealer_id}")
        
        return {
            "status": "success",
            "session": session_info
        }
        
    except ValueError as e:
        logger.error(f"WebRTC 세션 생성 실패: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"WebRTC 세션 생성 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/webrtc/session/{client_id}")
async def close_webrtc_session(client_id: str):
    """WebRTC 세션 종료"""
    try:
        # 세션 종료
        success = await bridge.close_webrtc_session(client_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"클라이언트 ID {client_id}를 찾을 수 없습니다")
        
        logger.info(f"WebRTC 세션 종료됨: 클라이언트 {client_id}")
        
        return {
            "status": "success",
            "message": f"WebRTC 세션이 종료되었습니다: {client_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"WebRTC 세션 종료 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/webrtc/{dealer_id}/hls-fallback")
async def get_hls_fallback(dealer_id: str):
    """HLS 폴백 URL 조회 (WebRTC 연결 실패 시 사용)"""
    try:
        # HLS URL 목록 조회
        hls_urls = await bridge.get_hls_fallback_urls(dealer_id)
        
        if not hls_urls:
            return {
                "status": "warning",
                "message": "HLS 스트림을 찾을 수 없습니다",
                "urls": []
            }
        
        return {
            "status": "success",
            "urls": hls_urls
        }
        
    except Exception as e:
        logger.error(f"HLS 폴백 URL 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# WebSocket 및 Socket.IO 이벤트 핸들러
@sio.event
async def connect(sid, environ):
    """Socket.IO 클라이언트 연결"""
    logger.info(f"Socket.IO 클라이언트 연결됨: {sid}")
    connected_clients[sid] = {
        "sid": sid,
        "connected_at": asyncio.get_event_loop().time(),
        "dealer_id": None
    }

@sio.event
async def disconnect(sid):
    """Socket.IO 클라이언트 연결 종료"""
    logger.info(f"Socket.IO 클라이언트 연결 종료됨: {sid}")
    if sid in connected_clients:
        del connected_clients[sid]

@sio.event
async def join_dealer_room(sid, data):
    """딜러 방 입장"""
    try:
        dealer_id = data.get("dealer_id")
        
        if not dealer_id:
            return {"status": "error", "message": "딜러 ID가 필요합니다"}
        
        # AI 딜러 확인
        if dealer_id not in bridge.ai_dealers:
            return {"status": "error", "message": f"딜러 ID {dealer_id}를 찾을 수 없습니다"}
        
        # 방 입장
        sio.enter_room(sid, f"dealer:{dealer_id}")
        
        # 클라이언트 정보 업데이트
        if sid in connected_clients:
            connected_clients[sid]["dealer_id"] = dealer_id
        
        logger.info(f"클라이언트 {sid}가 딜러 방 {dealer_id}에 입장했습니다")
        
        # 현재 게임 상태 반환
        ai_dealer = bridge.ai_dealers[dealer_id]
        game_state = ai_dealer.get_game_state()
        
        return {
            "status": "success",
            "message": f"딜러 방 {dealer_id}에 입장했습니다",
            "game_state": game_state
        }
        
    except Exception as e:
        logger.error(f"방 입장 실패: {str(e)}")
        return {"status": "error", "message": str(e)}

@sio.event
async def leave_dealer_room(sid, data):
    """딜러 방 퇴장"""
    try:
        dealer_id = data.get("dealer_id")
        
        if not dealer_id:
            return {"status": "error", "message": "딜러 ID가 필요합니다"}
        
        # 방 퇴장
        sio.leave_room(sid, f"dealer:{dealer_id}")
        
        # 클라이언트 정보 업데이트
        if sid in connected_clients and connected_clients[sid]["dealer_id"] == dealer_id:
            connected_clients[sid]["dealer_id"] = None
        
        logger.info(f"클라이언트 {sid}가 딜러 방 {dealer_id}에서 퇴장했습니다")
        
        return {
            "status": "success",
            "message": f"딜러 방 {dealer_id}에서 퇴장했습니다"
        }
        
    except Exception as e:
        logger.error(f"방 퇴장 실패: {str(e)}")
        return {"status": "error", "message": str(e)}

# Socket.IO 앱을 FastAPI에 마운트
app.mount("/socket.io", socket_app)

# AWS 통합 API
@app.get("/aws/services/status")
async def get_aws_services_status():
    """AWS 서비스 상태 조회"""
    try:
        status = {
            "media_live": media_live_service is not None,
            "elastic_cache": elastic_cache_service is not None
        }
        
        if media_live_service:
            try:
                # MediaLive 채널 목록 조회
                channels = await media_live_service.list_channels()
                status["media_live_channels"] = len(channels)
            except Exception as e:
                status["media_live_error"] = str(e)
        
        if elastic_cache_service:
            try:
                # ElastiCache 연결 상태 확인
                cache_status = await elastic_cache_service.check_connection()
                status["elastic_cache_connected"] = cache_status
            except Exception as e:
                status["elastic_cache_error"] = str(e)
        
        return {
            "status": "success",
            "services": status
        }
        
    except Exception as e:
        logger.error(f"AWS 서비스 상태 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 서버 시작 함수
def start_server(host="0.0.0.0", port=8000):
    """AI 딜러 스트리밍 서버 시작"""
    uvicorn.run("backend.streaming.ai_dealer.AIStreamerServer:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    # 직접 실행 시 서버 시작
    start_server() 