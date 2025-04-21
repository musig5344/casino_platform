/**
 * mediasoup WebRTC 서버
 * AI 딜러 영상 스트리밍을 위한 WebRTC 서버
 */

const express = require('express');
const https = require('https');
const fs = require('fs');
const cors = require('cors');
const { Server } = require('socket.io');
const mediasoup = require('mediasoup');
const config = require('./config');
const awsMediaLive = require('../aws/media-live-service');
const hlsConverter = require('../hls/converter');
const Redis = require('redis');
const { promisify } = require('util');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

// Redis 클라이언트 설정
const redisClient = Redis.createClient({
  url: process.env.REDIS_URL || 'redis://localhost:6379',
  password: process.env.REDIS_PASSWORD,
  socket: {
    reconnectStrategy: (retries) => Math.min(retries * 50, 1000)
  }
});

redisClient.on('error', (err) => console.error('Redis 클라이언트 에러:', err));
redisClient.on('connect', () => console.log('Redis 서버에 연결됨'));

const redisGetAsync = promisify(redisClient.get).bind(redisClient);
const redisSetAsync = promisify(redisClient.set).bind(redisClient);
const redisDelAsync = promisify(redisClient.del).bind(redisClient);

// Express 앱 생성 및 보안 강화
const app = express();
app.use(cors({
  origin: process.env.ALLOWED_ORIGINS ? process.env.ALLOWED_ORIGINS.split(',') : '*',
  methods: ['GET', 'POST'],
  credentials: true
}));
app.use(helmet());
app.use(express.json({ limit: '1mb' }));
app.use(express.static('public'));

// API 호출 속도 제한
const apiLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15분
  max: 100, // IP당 요청 수
  standardHeaders: true,
  legacyHeaders: false
});

app.use('/api', apiLimiter);

// HTTPS 서버 생성
const httpsServer = https.createServer({
  key: fs.readFileSync(process.env.SSL_KEY_PATH || './ssl/private.key'),
  cert: fs.readFileSync(process.env.SSL_CERT_PATH || './ssl/certificate.crt'),
  // 추가적인 SSL 옵션 (보안 강화)
  minVersion: 'TLSv1.2'
}, app);

// Socket.io 서버 생성
const io = new Server(httpsServer, {
  cors: {
    origin: process.env.ALLOWED_ORIGINS ? process.env.ALLOWED_ORIGINS.split(',') : '*',
    methods: ['GET', 'POST'],
    credentials: true
  },
  pingTimeout: 30000,
  pingInterval: 10000,
  transports: ['websocket', 'polling']
});

// mediasoup 오브젝트
let workers = [];
const routers = new Map();
const rooms = new Map();

// AWS MediaLive 스트림 정보
const liveStreams = new Map();

// AI 딜러 소스 - HLS 스트림
let aiDealerStreamUrl = '';

/**
 * mediasoup 워커 생성
 */
async function createWorkers() {
  const { numWorkers } = config.mediasoup;
  
  console.log(`${numWorkers}개의 mediasoup 워커 생성 중...`);
  
  try {
    for (let i = 0; i < numWorkers; i++) {
      const worker = await mediasoup.createWorker({
        logLevel: config.mediasoup.workerSettings.logLevel,
        logTags: config.mediasoup.workerSettings.logTags,
        rtcMinPort: config.mediasoup.workerSettings.rtcMinPort,
        rtcMaxPort: config.mediasoup.workerSettings.rtcMaxPort
      });
      
      worker.on('died', () => {
        console.error(`워커 ${i}가 종료됨, 메모리: ${process.memoryUsage().heapUsed / 1024 / 1024} MB`);
        
        // 워커 목록에서 제거
        workers = workers.filter(w => w !== worker);
        
        // 새 워커 생성
        createWorker(i).catch(error => {
          console.error('mediasoup 워커 재생성 오류:', error);
        });
      });
      
      workers.push(worker);
      console.log(`워커 ${i} 생성됨`);
    }
    
    console.log(`${workers.length}개의 mediasoup 워커 생성 완료`);
  } catch (error) {
    console.error('워커 생성 중 오류 발생:', error);
    throw error;
  }
}

/**
 * 단일 워커 생성 함수
 */
async function createWorker(index) {
  try {
    const worker = await mediasoup.createWorker({
      logLevel: config.mediasoup.workerSettings.logLevel,
      logTags: config.mediasoup.workerSettings.logTags,
      rtcMinPort: config.mediasoup.workerSettings.rtcMinPort,
      rtcMaxPort: config.mediasoup.workerSettings.rtcMaxPort
    });
    
    worker.on('died', () => {
      console.error(`워커 ${index}가 종료됨`);
      workers = workers.filter(w => w !== worker);
      createWorker(index).catch(error => {
        console.error('mediasoup 워커 재생성 오류:', error);
      });
    });
    
    workers.push(worker);
    console.log(`워커 ${index} 재생성됨`);
    return worker;
  } catch (error) {
    console.error(`워커 ${index} 생성 중 오류:`, error);
    throw error;
  }
}

/**
 * 워커 로드 밸런싱 - CPU 부하가 가장 적은 워커 선택
 */
async function getNextWorker() {
  if (workers.length === 0) {
    throw new Error('사용 가능한 워커가 없습니다');
  }
  
  // 간단한 라운드 로빈 방식 사용
  const workerIdx = Math.floor(Math.random() * workers.length);
  return workers[workerIdx];
}

/**
 * 라우터 생성 - 각 게임 테이블 별로 1개의 라우터
 */
async function createRouter() {
  try {
    const worker = await getNextWorker();
    return await worker.createRouter(config.mediasoup.routerOptions);
  } catch (error) {
    console.error('라우터 생성 오류:', error);
    throw error;
  }
}

/**
 * 게임 룸 생성 및 초기화
 */
async function createRoom(roomId) {
  try {
    // 캐시에서 기존 룸 확인
    const cachedRoom = await redisGetAsync(`room:${roomId}`);
    if (cachedRoom) {
      return JSON.parse(cachedRoom);
    }
    
    if (rooms.has(roomId)) {
      return rooms.get(roomId);
    }
    
    const router = await createRouter();
    
    const room = {
      id: roomId,
      router,
      transports: new Map(),
      producers: new Map(),
      consumers: new Map(),
      aiDealer: {
        transport: null,
        producer: {},
        streamActive: false,
        streamUrl: null
      },
      createdAt: Date.now()
    };
    
    rooms.set(roomId, room);
    // Redis에 룸 정보 캐싱 (직렬화 가능한 정보만)
    const roomCache = {
      id: roomId,
      createdAt: room.createdAt,
      aiDealer: {
        streamActive: room.aiDealer.streamActive,
        streamUrl: room.aiDealer.streamUrl
      }
    };
    
    await redisSetAsync(`room:${roomId}`, JSON.stringify(roomCache), 'EX', 3600); // 1시간 캐싱
    
    console.log(`룸 ${roomId} 생성됨`);
    return room;
  } catch (error) {
    console.error(`룸 ${roomId} 생성 오류:`, error);
    throw error;
  }
}

/**
 * AI 딜러 스트림 초기화 함수
 */
async function setupAIDealerStream(roomId, streamUrl) {
  try {
    const roomInfo = rooms.get(roomId);
    if (!roomInfo) {
      throw new Error(`존재하지 않는 룸 ID: ${roomId}`);
    }
    
    // 기존 설정이 있으면 정리
    if (roomInfo.aiDealer.transport) {
      await roomInfo.aiDealer.transport.close();
    }
    
    // AI 딜러 전용 전송 생성 (PlainTransport - 서버 내부 RTP 스트림 수신용)
    const transport = await roomInfo.router.createPlainTransport({
      listenIp: config.mediasoup.plainTransportOptions.listenIp,
      rtcpMux: config.mediasoup.plainTransportOptions.rtcpMux,
      comedia: config.mediasoup.plainTransportOptions.comedia
    });
    
    // 전송 및 RTP 파라미터 설정
    roomInfo.aiDealer.transport = transport;
    roomInfo.aiDealer.streamUrl = streamUrl;
    
    // Redis 캐시 업데이트
    const roomCache = await redisGetAsync(`room:${roomId}`);
    if (roomCache) {
      const parsed = JSON.parse(roomCache);
      parsed.aiDealer.streamUrl = streamUrl;
      await redisSetAsync(`room:${roomId}`, JSON.stringify(parsed), 'EX', 3600);
    }
    
    console.log(`AI 딜러 스트림 설정 완료 (룸 ID: ${roomId})`);
    
    return {
      transportId: transport.id,
      ip: transport.tuple.localIp,
      port: transport.tuple.localPort
    };
  } catch (error) {
    console.error(`AI 딜러 스트림 설정 오류 (룸 ID: ${roomId}):`, error);
    throw error;
  }
}

/**
 * AI 딜러 미디어 프로듀서 생성
 */
async function createAIDealerProducer(roomId, kind, rtpParameters) {
  try {
    const roomInfo = rooms.get(roomId);
    if (!roomInfo || !roomInfo.aiDealer.transport) {
      throw new Error(`AI 딜러 전송이 설정되지 않음 (룸 ID: ${roomId})`);
    }
    
    // 프로듀서 생성
    const producer = await roomInfo.aiDealer.transport.produce({
      kind,
      rtpParameters
    });
    
    // 프로듀서 정보 저장
    roomInfo.aiDealer.producer = roomInfo.aiDealer.producer || {};
    roomInfo.aiDealer.producer[kind] = producer;
    roomInfo.aiDealer.streamActive = true;
    
    // HLS 변환 시작 (선택적)
    hlsConverter.addProducer(producer, roomId);
    
    // Redis 캐시 업데이트
    const roomCache = await redisGetAsync(`room:${roomId}`);
    if (roomCache) {
      const parsed = JSON.parse(roomCache);
      parsed.aiDealer.streamActive = true;
      await redisSetAsync(`room:${roomId}`, JSON.stringify(parsed), 'EX', 3600);
    }
    
    console.log(`AI 딜러 ${kind} 프로듀서 생성됨 (룸 ID: ${roomId}, 프로듀서 ID: ${producer.id})`);
    
    return { id: producer.id };
  } catch (error) {
    console.error(`AI 딜러 프로듀서 생성 오류 (룸 ID: ${roomId}):`, error);
    throw error;
  }
}

/**
 * 플레이어 WebRTC 전송 생성
 */
async function createWebRtcTransport(router) {
  try {
    const { webRtcTransportOptions } = config.mediasoup;
    const transport = await router.createWebRtcTransport(webRtcTransportOptions);
    
    transport.on('dtlsstatechange', (dtlsState) => {
      if (dtlsState === 'closed') {
        transport.close();
      }
    });
    
    transport.on('close', () => {
      console.log(`WebRTC 전송이 닫힘 (ID: ${transport.id})`);
    });
    
    return {
      transport,
      params: {
        id: transport.id,
        iceParameters: transport.iceParameters,
        iceCandidates: transport.iceCandidates,
        dtlsParameters: transport.dtlsParameters
      }
    };
  } catch (error) {
    console.error('WebRTC 전송 생성 오류:', error);
    throw error;
  }
}

/**
 * AI 딜러 비디오/오디오 스트림을 플레이어에게 소비 설정
 */
async function consumeAIDealerStream(roomId, socketId, transportId, rtpCapabilities) {
  try {
    const roomInfo = rooms.get(roomId);
    
    if (!roomInfo) {
      throw new Error(`룸을 찾을 수 없음 (ID: ${roomId})`);
    }
    
    if (!roomInfo.aiDealer.producer || 
        !roomInfo.aiDealer.producer.video || 
        !roomInfo.aiDealer.producer.audio) {
      throw new Error('AI 딜러 스트림이 아직 설정되지 않았습니다');
    }
    
    // 클라이언트 전송 찾기
    const clientTransport = roomInfo.transports.get(transportId);
    if (!clientTransport || !clientTransport.transport) {
      throw new Error(`전송을 찾을 수 없음 (ID: ${transportId})`);
    }
    
    // 라우터가 소비자를 지원하는지 확인
    if (!roomInfo.router.canConsume({
      producerId: roomInfo.aiDealer.producer.video.id,
      rtpCapabilities
    })) {
      throw new Error('RTP 호환성 문제로 비디오를 소비할 수 없습니다');
    }
    
    // 비디오 소비자 생성
    const videoConsumer = await clientTransport.transport.consume({
      producerId: roomInfo.aiDealer.producer.video.id,
      rtpCapabilities,
      paused: true
    });
    
    // 오디오 소비자 생성
    const audioConsumer = await clientTransport.transport.consume({
      producerId: roomInfo.aiDealer.producer.audio.id,
      rtpCapabilities,
      paused: true
    });
    
    // 소비자 정보 저장
    if (!roomInfo.consumers.has(socketId)) {
      roomInfo.consumers.set(socketId, new Map());
    }
    
    const socketConsumers = roomInfo.consumers.get(socketId);
    socketConsumers.set(videoConsumer.id, {
      consumer: videoConsumer,
      kind: 'video'
    });
    socketConsumers.set(audioConsumer.id, {
      consumer: audioConsumer,
      kind: 'audio'
    });
    
    // 소비자 이벤트 처리
    videoConsumer.on('transportclose', () => {
      videoConsumer.close();
      socketConsumers.delete(videoConsumer.id);
    });
    
    audioConsumer.on('transportclose', () => {
      audioConsumer.close();
      socketConsumers.delete(audioConsumer.id);
    });
    
    return {
      videoConsumerId: videoConsumer.id,
      videoProducerId: roomInfo.aiDealer.producer.video.id,
      videoRtpParameters: videoConsumer.rtpParameters,
      audioConsumerId: audioConsumer.id,
      audioProducerId: roomInfo.aiDealer.producer.audio.id,
      audioRtpParameters: audioConsumer.rtpParameters
    };
  } catch (error) {
    console.error(`AI 딜러 스트림 소비 오류 (룸 ID: ${roomId}):`, error);
    throw error;
  }
}

/**
 * 소비자 재생 시작
 */
async function resumeConsumer(roomId, socketId, consumerId) {
  const roomInfo = rooms.get(roomId);
  if (!roomInfo) {
    throw new Error(`존재하지 않는 룸 ID: ${roomId}`);
  }
  
  const peer = roomInfo.peers.get(socketId);
  if (!peer) {
    throw new Error(`존재하지 않는 피어 ID: ${socketId}`);
  }
  
  const consumer = peer.consumers.get(consumerId);
  if (!consumer) {
    throw new Error(`존재하지 않는 소비자 ID: ${consumerId}`);
  }
  
  await consumer.resume();
  console.log(`소비자 재생 시작 (룸 ID: ${roomId}, 소켓 ID: ${socketId}, 소비자 ID: ${consumerId})`);
}

/**
 * 클라이언트 연결 처리
 */
io.on('connection', async (socket) => {
  console.log(`클라이언트 연결됨 (소켓 ID: ${socket.id})`);
  
  // 각 소켓에 대한 정보 저장
  const socketData = {
    roomId: null,
    transportIds: new Set(),
    producerIds: new Set(),
    consumerIds: new Set()
  };
  
  /**
   * 사용자가 방에 참여할 때 호출
   */
  socket.on('joinRoom', async ({ roomId }, callback) => {
    try {
      // 방이 없으면 생성
      let roomInfo = await createRoom(roomId);
      
      // 소켓을 방에 조인
      socket.join(roomId);
      socketData.roomId = roomId;
      
      console.log(`클라이언트 ${socket.id}가 방 ${roomId}에 참여함`);
      
      // 클라이언트에게 라우터의 RTP 기능 전송
      callback({
        success: true,
        rtpCapabilities: roomInfo.router.rtpCapabilities
      });
    } catch (error) {
      console.error(`방 참여 오류 (룸 ID: ${roomId}):`, error);
      callback({ success: false, error: error.message });
    }
  });
  
  /**
   * 전송 생성 요청 처리
   */
  socket.on('createTransport', async ({ sender }, callback) => {
    try {
      if (!socketData.roomId) {
        throw new Error('방에 먼저 참여해야 합니다');
      }
      
      const roomInfo = rooms.get(socketData.roomId);
      if (!roomInfo) {
        throw new Error('방을 찾을 수 없습니다');
      }
      
      // 새 WebRTC 전송 생성
      const { transport, params } = await createWebRtcTransport(roomInfo.router);
      
      // 전송 정보 저장
      roomInfo.transports.set(transport.id, {
        transport,
        socketId: socket.id,
        isSender: sender
      });
      
      socketData.transportIds.add(transport.id);
      
      callback({ success: true, params });
    } catch (error) {
      console.error('전송 생성 오류:', error);
      callback({ success: false, error: error.message });
    }
  });
  
  /**
   * 전송 연결 정보 설정 (DtlsParameters)
   */
  socket.on('connectTransport', async ({ transportId, dtlsParameters }, callback) => {
    try {
      if (!socketData.roomId) {
        throw new Error('방에 먼저 참여해야 합니다');
      }
      
      const roomInfo = rooms.get(socketData.roomId);
      if (!roomInfo) {
        throw new Error('방을 찾을 수 없습니다');
      }
      
      const transportData = roomInfo.transports.get(transportId);
      if (!transportData) {
        throw new Error('전송을 찾을 수 없습니다');
      }
      
      // 전송 연결
      await transportData.transport.connect({ dtlsParameters });
      
      callback({ success: true });
    } catch (error) {
      console.error('전송 연결 오류:', error);
      callback({ success: false, error: error.message });
    }
  });
  
  /**
   * 프로듀서 생성 요청 처리 (클라이언트 -> 서버)
   */
  socket.on('produce', async ({ transportId, kind, rtpParameters }, callback) => {
    try {
      if (!socketData.roomId) {
        throw new Error('방에 먼저 참여해야 합니다');
      }
      
      const roomInfo = rooms.get(socketData.roomId);
      if (!roomInfo) {
        throw new Error('방을 찾을 수 없습니다');
      }
      
      const transportData = roomInfo.transports.get(transportId);
      if (!transportData) {
        throw new Error('존재하지 않는 전송입니다');
      }
      
      const producer = await transportData.transport.produce({
        kind,
        rtpParameters
      });
      
      // 프로듀서 이벤트 처리
      producer.on('transportclose', () => {
        producer.close();
        roomInfo.producers.delete(producer.id);
      });
      
      // 프로듀서 정보 저장
      roomInfo.producers.set(producer.id, {
        producer,
        socketId: socket.id,
        kind
      });
      
      socketData.producerIds.add(producer.id);
      
      callback({ success: true, id: producer.id });
      
      // 동일한 방의 다른 사용자들에게 새 프로듀서 알림
      socket.to(socketData.roomId).emit('newProducer', {
        producerId: producer.id,
        socketId: socket.id,
        kind
      });
    } catch (error) {
      console.error('프로듀서 생성 오류:', error);
      callback({ success: false, error: error.message });
    }
  });
  
  /**
   * 소비자 생성 요청 처리 (다른 클라이언트의 미디어 소비)
   */
  socket.on('consume', async ({ transportId, producerId, rtpCapabilities }, callback) => {
    try {
      if (!socketData.roomId) {
        throw new Error('방에 먼저 참여해야 합니다');
      }
      
      const roomInfo = rooms.get(socketData.roomId);
      if (!roomInfo) {
        throw new Error('방을 찾을 수 없습니다');
      }
      
      // 소비자를 지원하는지 확인
      if (!roomInfo.router.canConsume({
        producerId,
        rtpCapabilities
      })) {
        throw new Error('RTP 호환성 문제로 미디어를 소비할 수 없습니다');
      }
      
      const transportData = roomInfo.transports.get(transportId);
      if (!transportData) {
        throw new Error('전송을 찾을 수 없습니다');
      }
      
      const producerData = roomInfo.producers.get(producerId);
      if (!producerData) {
        throw new Error('프로듀서를 찾을 수 없습니다');
      }
      
      // 소비자 생성
      const consumer = await transportData.transport.consume({
        producerId,
        rtpCapabilities,
        paused: true
      });
      
      // 소비자 정보 저장
      if (!roomInfo.consumers.has(socket.id)) {
        roomInfo.consumers.set(socket.id, new Map());
      }
      
      const socketConsumers = roomInfo.consumers.get(socket.id);
      socketConsumers.set(consumer.id, {
        consumer,
        socketId: socket.id,
        producerId
      });
      
      socketData.consumerIds.add(consumer.id);
      
      // 소비자 이벤트 처리
      consumer.on('transportclose', () => {
        consumer.close();
        socketConsumers.delete(consumer.id);
      });
      
      callback({
        success: true,
        params: {
          id: consumer.id,
          producerId,
          kind: consumer.kind,
          rtpParameters: consumer.rtpParameters
        }
      });
    } catch (error) {
      console.error('소비자 생성 오류:', error);
      callback({ success: false, error: error.message });
    }
  });
  
  /**
   * AI 딜러 스트림 소비 요청 처리
   */
  socket.on('consumeAIDealer', async ({ transportId, rtpCapabilities }, callback) => {
    try {
      if (!socketData.roomId) {
        throw new Error('방에 먼저 참여해야 합니다');
      }
      
      const result = await consumeAIDealerStream(socketData.roomId, socket.id, transportId, rtpCapabilities);
      
      callback({
        success: true,
        params: result
      });
    } catch (error) {
      console.error('AI 딜러 스트림 소비 오류:', error);
      callback({ success: false, error: error.message });
    }
  });
  
  /**
   * 소비자 재생 시작 요청
   */
  socket.on('resumeConsumer', async ({ consumerId }, callback) => {
    try {
      if (!socketData.roomId) {
        throw new Error('방에 먼저 참여해야 합니다');
      }
      
      const roomInfo = rooms.get(socketData.roomId);
      if (!roomInfo) {
        throw new Error('방을 찾을 수 없습니다');
      }
      
      const socketConsumers = roomInfo.consumers.get(socket.id);
      if (!socketConsumers || !socketConsumers.has(consumerId)) {
        throw new Error('소비자를 찾을 수 없습니다');
      }
      
      const consumerData = socketConsumers.get(consumerId);
      await consumerData.consumer.resume();
      
      callback({ success: true });
    } catch (error) {
      console.error('소비자 재생 오류:', error);
      callback({ success: false, error: error.message });
    }
  });
  
  /**
   * 연결 종료 시 정리
   */
  socket.on('disconnect', async () => {
    console.log(`클라이언트 연결 종료됨 (소켓 ID: ${socket.id})`);
    
    if (socketData.roomId) {
      const roomInfo = rooms.get(socketData.roomId);
      if (roomInfo) {
        // 소켓과 관련된 모든 전송 닫기
        socketData.transportIds.forEach(transportId => {
          const transportData = roomInfo.transports.get(transportId);
          if (transportData) {
            transportData.transport.close();
            roomInfo.transports.delete(transportId);
          }
        });
        
        // 소켓과 관련된 모든 소비자 정리
        if (roomInfo.consumers.has(socket.id)) {
          const socketConsumers = roomInfo.consumers.get(socket.id);
          socketConsumers.forEach((data, consumerId) => {
            data.consumer.close();
          });
          roomInfo.consumers.delete(socket.id);
        }
        
        // 소켓과 관련된 모든 프로듀서 정리
        socketData.producerIds.forEach(producerId => {
          const producerData = roomInfo.producers.get(producerId);
          if (producerData && producerData.socketId === socket.id) {
            producerData.producer.close();
            roomInfo.producers.delete(producerId);
          }
        });
        
        // 방에 더 이상 활성 소켓이 없으면 방 정리
        const roomSockets = io.sockets.adapter.rooms.get(socketData.roomId);
        if (!roomSockets || roomSockets.size === 0) {
          // AI 딜러 스트림 정리
          if (roomInfo.aiDealer.transport) {
            roomInfo.aiDealer.transport.close();
          }
          
          // 관련 HLS 스트림 종료
          if (roomInfo.aiDealer.streamActive) {
            hlsConverter.removeProducer(socketData.roomId);
          }
          
          // Redis에서 룸 정보 삭제
          await redisDelAsync(`room:${socketData.roomId}`);
          
          // 라우터 및 룸 정리
          rooms.delete(socketData.roomId);
          console.log(`룸 ${socketData.roomId} 삭제됨 (마지막 사용자 퇴장)`);
        }
      }
    }
  });
});

/**
 * API 라우트
 */

// 상태 확인 엔드포인트
app.get('/api/health', (req, res) => {
  res.status(200).json({
    status: 'ok',
    workers: workers.length,
    rooms: rooms.size,
    uptime: process.uptime()
  });
});

// AI 딜러 스트림 설정 API
app.post('/api/rooms/:roomId/ai-dealer', async (req, res) => {
  try {
    const { roomId } = req.params;
    const { streamUrl } = req.body;
    
    if (!streamUrl) {
      return res.status(400).json({ error: '스트림 URL이 필요합니다' });
    }
    
    // 룸 확인 또는 생성
    await createRoom(roomId);
    
    // AI 딜러 스트림 설정
    const transportInfo = await setupAIDealerStream(roomId, streamUrl);
    
    // AWS MediaLive 연동 설정 (선택적)
    const mediaLiveInput = await awsMediaLive.createInput(roomId, transportInfo);
    
    res.status(200).json({
      success: true,
      transportInfo,
      mediaLiveInput
    });
  } catch (error) {
    console.error('AI 딜러 스트림 설정 API 오류:', error);
    res.status(500).json({ error: error.message });
  }
});

// 서버 시작
const PORT = process.env.PORT || 3000;

// 워커 생성 후 서버 시작
async function runServer() {
  try {
    await createWorkers();
    
    httpsServer.listen(PORT, () => {
      console.log(`WebRTC 스트리밍 서버가 포트 ${PORT}에서 실행 중...`);
    });
  } catch (error) {
    console.error('서버 시작 오류:', error);
    process.exit(1);
  }
}

// 정상적인 종료 처리
process.on('SIGINT', async () => {
  console.log('서버 종료 중...');
  
  // 모든 워커 종료
  for (const worker of workers) {
    worker.close();
  }
  
  // Redis 연결 종료
  redisClient.quit();
  
  // 서버 종료
  httpsServer.close(() => {
    console.log('서버가 안전하게 종료되었습니다');
    process.exit(0);
  });
});

// 서버 실행
runServer(); 