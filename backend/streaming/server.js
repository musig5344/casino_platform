/**
 * WebRTC 및 HLS 스트리밍 서버
 */

const path = require('path');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const { authenticateToken } = require('../auth/middleware');
const RoomManager = require('./mediasoup/RoomManager');
const MediaLiveService = require('./aws/MediaLiveService');
const app = express();

// 인스턴스 생성
const roomManager = new RoomManager();
let mediaLiveService;

// 환경 변수
const PORT = process.env.STREAMING_PORT || 4000;

// 미들웨어 설정
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// HLS 콘텐츠 정적 제공
app.use('/hls', express.static(path.join(__dirname, '..', '..', 'public', 'hls')));

// HTTP 서버 생성
const httpServer = http.createServer(app);

// Socket.IO 설정
const io = new Server(httpServer, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST']
  }
});

// API 인증 미들웨어
const authenticateApi = (req, res, next) => {
  if (process.env.NODE_ENV === 'development') {
    // 개발 환경에서는 인증 건너뛰기
    return next();
  }
  
  return authenticateToken(req, res, next);
};

/**
 * API 라우트 설정
 */
// 라우터 기능
app.get('/mediasoup/capabilities', authenticateApi, (req, res) => {
  try {
    // 샘플 룸을 가져와 라우터 기능 반환
    const sampleRoomId = 'sample-room';
    
    roomManager.getOrCreateRoom(sampleRoomId)
      .then(room => {
        res.json({
          success: true,
          data: {
            rtpCapabilities: room.router.rtpCapabilities
          }
        });
      })
      .catch(error => {
        console.error('라우터 기능 가져오기 실패:', error);
        res.status(500).json({
          success: false,
          error: '라우터 기능을 가져오는 중 오류가 발생했습니다'
        });
      });
  } catch (error) {
    console.error('라우터 기능 가져오기 실패:', error);
    res.status(500).json({
      success: false,
      error: '라우터 기능을 가져오는 중 오류가 발생했습니다'
    });
  }
});

// 활성 룸 목록
app.get('/rooms', authenticateApi, (req, res) => {
  try {
    const rooms = Array.from(roomManager.rooms.keys()).map(roomId => {
      const room = roomManager.rooms.get(roomId);
      return {
        id: roomId,
        producers: room.producers.size,
        consumers: room.consumers.size
      };
    });
    
    res.json({
      success: true,
      data: { rooms }
    });
  } catch (error) {
    console.error('룸 목록 가져오기 실패:', error);
    res.status(500).json({
      success: false,
      error: '룸 목록을 가져오는 중 오류가 발생했습니다'
    });
  }
});

// HLS 스트림 목록
app.get('/hls/streams', authenticateApi, (req, res) => {
  try {
    const streams = roomManager.hlsConverter.getAllConversionStatus();
    
    res.json({
      success: true,
      data: { streams }
    });
  } catch (error) {
    console.error('HLS 스트림 목록 가져오기 실패:', error);
    res.status(500).json({
      success: false,
      error: 'HLS 스트림 목록을 가져오는 중 오류가 발생했습니다'
    });
  }
});

// MediaLive 채널 상태
app.get('/aws/medialive/status', authenticateApi, async (req, res) => {
  try {
    if (!mediaLiveService) {
      return res.status(400).json({
        success: false,
        error: 'MediaLive 서비스가 초기화되지 않았습니다'
      });
    }
    
    const status = await mediaLiveService.getChannelStatus();
    
    res.json({
      success: true,
      data: { status }
    });
  } catch (error) {
    console.error('MediaLive 상태 가져오기 실패:', error);
    res.status(500).json({
      success: false,
      error: 'MediaLive 상태를 가져오는 중 오류가 발생했습니다'
    });
  }
});

// MediaLive 채널 시작
app.post('/aws/medialive/start', authenticateApi, async (req, res) => {
  try {
    if (!mediaLiveService) {
      return res.status(400).json({
        success: false,
        error: 'MediaLive 서비스가 초기화되지 않았습니다'
      });
    }
    
    const result = await mediaLiveService.startChannel();
    
    res.json({
      success: true,
      data: result
    });
  } catch (error) {
    console.error('MediaLive 채널 시작 실패:', error);
    res.status(500).json({
      success: false,
      error: 'MediaLive 채널을 시작하는 중 오류가 발생했습니다'
    });
  }
});

// MediaLive 채널 중지
app.post('/aws/medialive/stop', authenticateApi, async (req, res) => {
  try {
    if (!mediaLiveService) {
      return res.status(400).json({
        success: false,
        error: 'MediaLive 서비스가 초기화되지 않았습니다'
      });
    }
    
    const result = await mediaLiveService.stopChannel();
    
    res.json({
      success: true,
      data: result
    });
  } catch (error) {
    console.error('MediaLive 채널 중지 실패:', error);
    res.status(500).json({
      success: false,
      error: 'MediaLive 채널을 중지하는 중 오류가 발생했습니다'
    });
  }
});

// RTMP URL 가져오기
app.get('/aws/medialive/rtmp-url', authenticateApi, async (req, res) => {
  try {
    if (!mediaLiveService) {
      return res.status(400).json({
        success: false,
        error: 'MediaLive 서비스가 초기화되지 않았습니다'
      });
    }
    
    const rtmpUrl = await mediaLiveService.getRtmpUrl();
    
    res.json({
      success: true,
      data: { rtmpUrl }
    });
  } catch (error) {
    console.error('RTMP URL 가져오기 실패:', error);
    res.status(500).json({
      success: false,
      error: 'RTMP URL을 가져오는 중 오류가 발생했습니다'
    });
  }
});

/**
 * Socket.IO 이벤트 핸들러
 */
io.on('connection', socket => {
  console.log(`새 WebSocket 연결: ${socket.id}`);
  
  let userId;
  let roomId;
  
  // 인증 및 입장
  socket.on('joinRoom', async (data, callback) => {
    try {
      // 데이터 검증
      if (!data.roomId || !data.userId || !data.token) {
        return callback({
          success: false,
          error: '필수 정보가 누락되었습니다'
        });
      }
      
      // 토큰 검증 (실제 구현에서는 토큰 유효성 검사 필요)
      // 이 예제에서는 간단히 넘어갑니다
      
      roomId = data.roomId;
      userId = data.userId;
      
      // 룸에 소켓 입장
      socket.join(roomId);
      
      console.log(`사용자 ${userId}가 룸 ${roomId}에 입장했습니다`);
      
      // 룸 내의 다른 사용자에게 알림
      socket.to(roomId).emit('userJoined', {
        userId,
        socketId: socket.id
      });
      
      // 룸의 현재 프로듀서 목록 가져오기
      const producers = await roomManager.getProducers(roomId, userId);
      
      callback({
        success: true,
        data: {
          producers
        }
      });
    } catch (error) {
      console.error('룸 입장 실패:', error);
      callback({
        success: false,
        error: '룸 입장 중 오류가 발생했습니다'
      });
    }
  });
  
  // 라우터 기능 요청
  socket.on('getRouterRtpCapabilities', async (data, callback) => {
    try {
      if (!roomId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const room = await roomManager.getOrCreateRoom(roomId);
      
      callback({
        success: true,
        data: {
          rtpCapabilities: room.router.rtpCapabilities
        }
      });
    } catch (error) {
      console.error('라우터 기능 가져오기 실패:', error);
      callback({
        success: false,
        error: '라우터 기능을 가져오는 중 오류가 발생했습니다'
      });
    }
  });
  
  // WebRTC 트랜스포트 생성
  socket.on('createWebRtcTransport', async (data, callback) => {
    try {
      if (!roomId || !userId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const transport = await roomManager.createWebRtcTransport(roomId, userId);
      
      callback({
        success: true,
        data: transport
      });
    } catch (error) {
      console.error('WebRTC 트랜스포트 생성 실패:', error);
      callback({
        success: false,
        error: 'WebRTC 트랜스포트를 생성하는 중 오류가 발생했습니다'
      });
    }
  });
  
  // 트랜스포트 연결
  socket.on('connectWebRtcTransport', async (data, callback) => {
    try {
      if (!roomId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const { transportId, dtlsParameters } = data;
      
      if (!transportId || !dtlsParameters) {
        return callback({
          success: false,
          error: '필수 정보가 누락되었습니다'
        });
      }
      
      const room = await roomManager.getOrCreateRoom(roomId);
      const transport = room.webRtcTransports.get(transportId);
      
      if (!transport) {
        return callback({
          success: false,
          error: '트랜스포트를 찾을 수 없습니다'
        });
      }
      
      await transport.connect({ dtlsParameters });
      
      callback({
        success: true
      });
    } catch (error) {
      console.error('WebRTC 트랜스포트 연결 실패:', error);
      callback({
        success: false,
        error: 'WebRTC 트랜스포트를 연결하는 중 오류가 발생했습니다'
      });
    }
  });
  
  // 미디어 생산
  socket.on('produce', async (data, callback) => {
    try {
      if (!roomId || !userId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const { transportId, kind, rtpParameters, appData } = data;
      
      if (!transportId || !kind || !rtpParameters) {
        return callback({
          success: false,
          error: '필수 정보가 누락되었습니다'
        });
      }
      
      const producer = await roomManager.createProducer(roomId, transportId, {
        kind,
        rtpParameters,
        appData: { ...appData, userId }
      });
      
      // 룸 내의 다른 사용자에게 새 프로듀서 알림
      socket.to(roomId).emit('newProducer', {
        producerId: producer.id,
        userId,
        kind: producer.kind
      });
      
      callback({
        success: true,
        data: { id: producer.id }
      });
    } catch (error) {
      console.error('미디어 생산 실패:', error);
      callback({
        success: false,
        error: '미디어를 생산하는 중 오류가 발생했습니다'
      });
    }
  });
  
  // 미디어 소비
  socket.on('consume', async (data, callback) => {
    try {
      if (!roomId || !userId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const { transportId, producerId, rtpCapabilities } = data;
      
      if (!transportId || !producerId || !rtpCapabilities) {
        return callback({
          success: false,
          error: '필수 정보가 누락되었습니다'
        });
      }
      
      const consumer = await roomManager.createConsumer(
        roomId,
        transportId,
        producerId,
        rtpCapabilities
      );
      
      callback({
        success: true,
        data: consumer
      });
    } catch (error) {
      console.error('미디어 소비 실패:', error);
      callback({
        success: false,
        error: '미디어를 소비하는 중 오류가 발생했습니다'
      });
    }
  });
  
  // 소비 재개
  socket.on('resumeConsumer', async (data, callback) => {
    try {
      if (!roomId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const { consumerId } = data;
      
      if (!consumerId) {
        return callback({
          success: false,
          error: '컨슈머 ID가 누락되었습니다'
        });
      }
      
      const room = await roomManager.getOrCreateRoom(roomId);
      const consumer = room.consumers.get(consumerId);
      
      if (!consumer) {
        return callback({
          success: false,
          error: '컨슈머를 찾을 수 없습니다'
        });
      }
      
      await consumer.resume();
      
      callback({
        success: true
      });
    } catch (error) {
      console.error('컨슈머 재개 실패:', error);
      callback({
        success: false,
        error: '컨슈머를 재개하는 중 오류가 발생했습니다'
      });
    }
  });
  
  // HLS 스트림 시작
  socket.on('startHlsStream', async (data, callback) => {
    try {
      if (!roomId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const { producerId } = data;
      
      if (!producerId) {
        return callback({
          success: false,
          error: '프로듀서 ID가 누락되었습니다'
        });
      }
      
      const hlsUrl = await roomManager.startHlsStream(roomId, producerId);
      
      // 룸 내의 모든 사용자에게 새 HLS 스트림 알림
      io.to(roomId).emit('hlsStreamStarted', {
        roomId,
        producerId,
        hlsUrl
      });
      
      callback({
        success: true,
        data: { hlsUrl }
      });
    } catch (error) {
      console.error('HLS 스트림 시작 실패:', error);
      callback({
        success: false,
        error: 'HLS 스트림을 시작하는 중 오류가 발생했습니다'
      });
    }
  });
  
  // HLS 스트림 중지
  socket.on('stopHlsStream', async (data, callback) => {
    try {
      if (!roomId) {
        return callback({
          success: false,
          error: '먼저 룸에 입장해야 합니다'
        });
      }
      
      const result = await roomManager.stopHlsStream(roomId);
      
      // 룸 내의 모든 사용자에게 HLS 스트림 중지 알림
      io.to(roomId).emit('hlsStreamStopped', {
        roomId
      });
      
      callback({
        success: true,
        data: { result }
      });
    } catch (error) {
      console.error('HLS 스트림 중지 실패:', error);
      callback({
        success: false,
        error: 'HLS 스트림을 중지하는 중 오류가 발생했습니다'
      });
    }
  });
  
  // 연결 종료
  socket.on('disconnect', async () => {
    console.log(`WebSocket 연결 종료: ${socket.id}`);
    
    if (roomId && userId) {
      // 룸 내의 다른 사용자에게 알림
      socket.to(roomId).emit('userLeft', {
        userId,
        socketId: socket.id
      });
      
      // 룸에서 소켓 제거
      socket.leave(roomId);
      
      console.log(`사용자 ${userId}가 룸 ${roomId}에서 퇴장했습니다`);
      
      // TODO: 사용자와 관련된 리소스 정리
      // 실제 구현에서는 사용자가 생성한 프로듀서와 컨슈머를 정리해야 합니다
    }
  });
});

/**
 * 서버 시작
 */
const startServer = async () => {
  try {
    // RoomManager 초기화
    await roomManager.initialize();
    console.log('RoomManager가 초기화되었습니다');
    
    // MediaLive 서비스 초기화 (AWS 구성이 있는 경우)
    if (process.env.AWS_REGION && process.env.AWS_MEDIALIVE_CHANNEL_ID) {
      mediaLiveService = new MediaLiveService();
      console.log('MediaLive 서비스가 초기화되었습니다');
    } else {
      console.log('AWS MediaLive 구성이 없어 관련 기능이 비활성화됩니다');
    }
    
    // HTTP 서버 시작
    httpServer.listen(PORT, () => {
      console.log(`스트리밍 서버가 http://localhost:${PORT}에서 실행 중입니다`);
    });
    
    // 종료 시 리소스 정리
    process.on('SIGINT', async () => {
      console.log('서버 종료 중...');
      
      await roomManager.close();
      console.log('RoomManager가 종료되었습니다');
      
      process.exit(0);
    });
  } catch (error) {
    console.error('서버 시작 실패:', error);
    process.exit(1);
  }
};

// 서버 시작
startServer(); 