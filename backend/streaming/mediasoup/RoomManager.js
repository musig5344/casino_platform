/**
 * mediasoup 룸 관리자
 * WebRTC 방 및 미디어 관리
 */

const mediasoup = require('mediasoup');
const config = require('./config');
const HlsConverterService = require('../hls/HlsConverterService');

class RoomManager {
  /**
   * 룸 관리자 초기화
   */
  constructor() {
    // mediasoup 워커
    this.workers = [];
    this.nextWorkerIndex = 0;
    
    // 활성 룸 관리
    this.rooms = new Map();
    
    // HLS 변환 서비스
    this.hlsConverter = new HlsConverterService();
  }

  /**
   * mediasoup 워커 초기화
   * @returns {Promise<void>}
   */
  async initialize() {
    const { numWorkers } = config.worker;
    
    console.log(`${numWorkers}개의 mediasoup 워커 초기화 중...`);
    
    for (let i = 0; i < numWorkers; i++) {
      const worker = await mediasoup.createWorker({
        logLevel: config.worker.logLevel,
        logTags: config.worker.logTags,
        rtcMinPort: config.worker.rtcMinPort,
        rtcMaxPort: config.worker.rtcMaxPort
      });
      
      worker.on('died', () => {
        console.error(`mediasoup 워커가 예기치 않게 종료됨 (워커 ID: ${worker.pid})`);
        
        // 워커 재생성
        this._handleWorkerDeath(worker);
      });
      
      this.workers.push(worker);
      
      console.log(`mediasoup 워커 ${i + 1}/${numWorkers} 생성됨 (워커 ID: ${worker.pid})`);
    }
    
    console.log('mediasoup 워커 초기화 완료');
  }

  /**
   * 다음 워커 가져오기 (라운드 로빈)
   * @returns {Worker} mediasoup 워커
   */
  _getNextWorker() {
    const worker = this.workers[this.nextWorkerIndex];
    
    // 다음 워커 인덱스 업데이트 (라운드 로빈)
    this.nextWorkerIndex = (this.nextWorkerIndex + 1) % this.workers.length;
    
    return worker;
  }

  /**
   * 워커 오류 처리
   * @param {Worker} deadWorker - 종료된 워커
   * @private
   */
  async _handleWorkerDeath(deadWorker) {
    // 워커 인덱스 찾기
    const workerIndex = this.workers.findIndex(w => w === deadWorker);
    
    if (workerIndex === -1) {
      return;
    }
    
    console.log(`워커 ${workerIndex} 재생성 중...`);
    
    // 새 워커 생성
    const newWorker = await mediasoup.createWorker({
      logLevel: config.worker.logLevel,
      logTags: config.worker.logTags,
      rtcMinPort: config.worker.rtcMinPort,
      rtcMaxPort: config.worker.rtcMaxPort
    });
    
    newWorker.on('died', () => {
      console.error(`mediasoup 워커가 예기치 않게 종료됨 (워커 ID: ${newWorker.pid})`);
      this._handleWorkerDeath(newWorker);
    });
    
    // 워커 배열 업데이트
    this.workers[workerIndex] = newWorker;
    
    console.log(`워커 ${workerIndex} 재생성됨 (워커 ID: ${newWorker.pid})`);
    
    // 해당 워커에 있던 룸 처리
    // 이 구현은 복잡성을 위해 생략 (실제로는 룸 복구 로직이 필요)
  }

  /**
   * 룸 생성 또는 가져오기
   * @param {string} roomId - 룸 ID
   * @returns {Promise<Object>} 룸 정보
   */
  async getOrCreateRoom(roomId) {
    let room = this.rooms.get(roomId);
    
    // 기존 룸이 있으면 반환
    if (room) {
      return room;
    }
    
    // 워커 가져오기
    const worker = this._getNextWorker();
    
    // 라우터 생성
    const router = await worker.createRouter({
      mediaCodecs: config.router.mediaCodecs
    });
    
    // 룸 객체 생성
    room = {
      id: roomId,
      worker,
      router,
      producers: new Map(),
      consumers: new Map(),
      rtpTransports: new Map(),
      webRtcTransports: new Map()
    };
    
    // 룸 저장
    this.rooms.set(roomId, room);
    
    console.log(`룸이 생성됨: ${roomId}`);
    
    return room;
  }
  
  /**
   * WebRTC 트랜스포트 생성
   * @param {string} roomId - 룸 ID
   * @param {string} userId - 사용자 ID
   * @returns {Promise<Object>} WebRTC 트랜스포트 정보
   */
  async createWebRtcTransport(roomId, userId) {
    const room = await this.getOrCreateRoom(roomId);
    
    const transport = await room.router.createWebRtcTransport({
      listenIps: config.webRtcTransport.listenIps,
      initialAvailableOutgoingBitrate: config.webRtcTransport.initialAvailableOutgoingBitrate,
      minimumAvailableOutgoingBitrate: config.webRtcTransport.minimumAvailableOutgoingBitrate,
      maxSctpMessageSize: config.webRtcTransport.maxSctpMessageSize,
      enableUdp: true,
      enableTcp: true,
      preferUdp: true
    });
    
    // 트랜스포트에 사용자 ID 연결
    transport.userId = userId;
    
    // 트랜스포트 저장
    room.webRtcTransports.set(transport.id, transport);
    
    // ICE 상태 변경 이벤트
    transport.on('icestatechange', (iceState) => {
      console.log(`ICE 상태 변경 (룸: ${roomId}, 트랜스포트: ${transport.id}): ${iceState}`);
    });
    
    // DTLS 상태 변경 이벤트
    transport.on('dtlsstatechange', (dtlsState) => {
      console.log(`DTLS 상태 변경 (룸: ${roomId}, 트랜스포트: ${transport.id}): ${dtlsState}`);
      
      if (dtlsState === 'closed') {
        transport.close();
        room.webRtcTransports.delete(transport.id);
      }
    });
    
    // 연결 종료 이벤트
    transport.on('close', () => {
      console.log(`트랜스포트 닫힘 (룸: ${roomId}, 트랜스포트: ${transport.id})`);
      room.webRtcTransports.delete(transport.id);
    });
    
    console.log(`WebRTC 트랜스포트 생성됨 (룸: ${roomId}, 트랜스포트: ${transport.id})`);
    
    return {
      id: transport.id,
      iceParameters: transport.iceParameters,
      iceCandidates: transport.iceCandidates,
      dtlsParameters: transport.dtlsParameters,
      sctpParameters: transport.sctpParameters
    };
  }
  
  /**
   * Plain RTP 트랜스포트 생성 (FFmpeg용)
   * @param {string} roomId - 룸 ID
   * @returns {Promise<Object>} RTP 트랜스포트 정보
   */
  async createPlainRtpTransport(roomId) {
    const room = await this.getOrCreateRoom(roomId);
    
    // RTP 트랜스포트 생성
    const transport = await room.router.createPlainTransport({
      listenIp: config.plainRtpTransport.listenIp,
      rtcpMux: config.plainRtpTransport.rtcpMux,
      comedia: config.plainRtpTransport.comedia
    });
    
    // 고유 ID 생성
    const transportId = `rtp-${Date.now()}`;
    
    // 트랜스포트 저장
    room.rtpTransports.set(transportId, transport);
    
    // 연결 종료 이벤트
    transport.on('close', () => {
      console.log(`RTP 트랜스포트 닫힘 (룸: ${roomId}, 트랜스포트: ${transportId})`);
      room.rtpTransports.delete(transportId);
    });
    
    console.log(`RTP 트랜스포트 생성됨 (룸: ${roomId}, 트랜스포트: ${transportId})`);
    
    return {
      id: transportId,
      ip: transport.tuple.localIp,
      port: transport.tuple.localPort,
      rtcpPort: transport.rtcpTuple ? transport.rtcpTuple.localPort : null
    };
  }
  
  /**
   * 프로듀서 생성
   * @param {string} roomId - 룸 ID
   * @param {string} transportId - 트랜스포트 ID
   * @param {Object} producerOptions - 프로듀서 옵션
   * @returns {Promise<Object>} 프로듀서 정보
   */
  async createProducer(roomId, transportId, producerOptions) {
    const room = await this.getOrCreateRoom(roomId);
    
    // 트랜스포트 찾기
    const transport = room.webRtcTransports.get(transportId);
    
    if (!transport) {
      throw new Error(`트랜스포트를 찾을 수 없음: ${transportId}`);
    }
    
    // 프로듀서 생성
    const producer = await transport.produce(producerOptions);
    
    // 프로듀서 저장
    room.producers.set(producer.id, producer);
    
    // 프로듀서에 사용자 ID 연결
    producer.userId = transport.userId;
    
    // 연결 종료 이벤트
    producer.on('close', () => {
      console.log(`프로듀서 닫힘 (룸: ${roomId}, 프로듀서: ${producer.id})`);
      room.producers.delete(producer.id);
    });
    
    console.log(`프로듀서 생성됨 (룸: ${roomId}, 프로듀서: ${producer.id}, 종류: ${producer.kind})`);
    
    return {
      id: producer.id,
      kind: producer.kind,
      rtpParameters: producer.rtpParameters,
      type: producer.type,
      appData: producer.appData
    };
  }

  /**
   * 컨슈머 생성
   * @param {string} roomId - 룸 ID
   * @param {string} transportId - 트랜스포트 ID
   * @param {string} producerId - 프로듀서 ID
   * @param {Object} rtpCapabilities - RTP 기능
   * @returns {Promise<Object>} 컨슈머 정보
   */
  async createConsumer(roomId, transportId, producerId, rtpCapabilities) {
    const room = await this.getOrCreateRoom(roomId);
    
    // 라우터가 컨슈머를 생성할 수 있는지 확인
    if (!room.router.canConsume({
      producerId,
      rtpCapabilities
    })) {
      throw new Error('컨슈머를 생성할 수 없음: 호환되지 않는 RTP 기능');
    }
    
    // 트랜스포트 찾기
    const transport = room.webRtcTransports.get(transportId);
    
    if (!transport) {
      throw new Error(`트랜스포트를 찾을 수 없음: ${transportId}`);
    }
    
    // 프로듀서 찾기
    const producer = room.producers.get(producerId);
    
    if (!producer) {
      throw new Error(`프로듀서를 찾을 수 없음: ${producerId}`);
    }
    
    // 컨슈머 생성
    const consumer = await transport.consume({
      producerId,
      rtpCapabilities,
      paused: true
    });
    
    // 컨슈머 저장
    room.consumers.set(consumer.id, consumer);
    
    // 컨슈머에 사용자 ID 연결
    consumer.userId = transport.userId;
    consumer.producerId = producerId;
    
    // 연결 종료 이벤트
    consumer.on('close', () => {
      console.log(`컨슈머 닫힘 (룸: ${roomId}, 컨슈머: ${consumer.id})`);
      room.consumers.delete(consumer.id);
    });
    
    console.log(`컨슈머 생성됨 (룸: ${roomId}, 컨슈머: ${consumer.id}, 프로듀서: ${producerId})`);
    
    return {
      id: consumer.id,
      producerId,
      kind: consumer.kind,
      rtpParameters: consumer.rtpParameters,
      type: consumer.type,
      producerPaused: consumer.producerPaused
    };
  }
  
  /**
   * 룸의 모든 프로듀서 가져오기
   * @param {string} roomId - 룸 ID
   * @param {string} [excludeUserId] - 제외할 사용자 ID
   * @returns {Promise<Array>} 프로듀서 목록
   */
  async getProducers(roomId, excludeUserId) {
    const room = await this.getOrCreateRoom(roomId);
    
    const producers = [];
    
    for (const [producerId, producer] of room.producers) {
      if (excludeUserId && producer.userId === excludeUserId) {
        continue;
      }
      
      producers.push({
        id: producer.id,
        kind: producer.kind,
        userId: producer.userId
      });
    }
    
    return producers;
  }
  
  /**
   * HLS 스트림 시작
   * @param {string} roomId - 룸 ID
   * @param {string} producerId - 프로듀서 ID
   * @returns {Promise<string>} HLS URL
   */
  async startHlsStream(roomId, producerId) {
    const room = await this.getOrCreateRoom(roomId);
    
    // 프로듀서 찾기
    const producer = room.producers.get(producerId);
    
    if (!producer) {
      throw new Error(`프로듀서를 찾을 수 없음: ${producerId}`);
    }
    
    // 현재 미디어 종류 저장
    const kind = producer.kind;
    
    // RTP 트랜스포트 생성
    const rtpTransport = await this.createPlainRtpTransport(roomId);
    
    // RTP 컨슈머 생성
    const rtpConsumer = await room.router.createPlainTransport({
      producerId,
      rtpCapabilities: room.router.rtpCapabilities
    });
    
    // HLS 스트림 시작
    const hlsUrl = await this.hlsConverter.startConversion(
      roomId,
      rtpTransport.port,
      rtpTransport.ip,
      kind
    );
    
    console.log(`HLS 스트림 시작됨 (룸: ${roomId}, 프로듀서: ${producerId}, URL: ${hlsUrl})`);
    
    return hlsUrl;
  }
  
  /**
   * HLS 스트림 중지
   * @param {string} roomId - 룸 ID
   * @returns {Promise<boolean>} 중지 성공 여부
   */
  async stopHlsStream(roomId) {
    return await this.hlsConverter.stopConversion(roomId);
  }
  
  /**
   * 룸 닫기
   * @param {string} roomId - 룸 ID
   * @returns {Promise<boolean>} 성공 여부
   */
  async closeRoom(roomId) {
    const room = this.rooms.get(roomId);
    
    if (!room) {
      console.log(`룸을 찾을 수 없음: ${roomId}`);
      return false;
    }
    
    // HLS 스트림 중지
    await this.stopHlsStream(roomId);
    
    // 모든 프로듀서 닫기
    for (const producer of room.producers.values()) {
      producer.close();
    }
    
    // 모든 컨슈머 닫기
    for (const consumer of room.consumers.values()) {
      consumer.close();
    }
    
    // 모든 WebRTC 트랜스포트 닫기
    for (const transport of room.webRtcTransports.values()) {
      transport.close();
    }
    
    // 모든 RTP 트랜스포트 닫기
    for (const transport of room.rtpTransports.values()) {
      transport.close();
    }
    
    // 라우터 닫기
    room.router.close();
    
    // 룸 삭제
    this.rooms.delete(roomId);
    
    console.log(`룸 닫힘: ${roomId}`);
    
    return true;
  }
  
  /**
   * 리소스 정리
   */
  async close() {
    // 모든 룸 닫기
    for (const roomId of this.rooms.keys()) {
      await this.closeRoom(roomId);
    }
    
    // 모든 HLS 변환 중지
    await this.hlsConverter.stopAll();
    
    // 모든 워커 닫기
    for (const worker of this.workers) {
      worker.close();
    }
    
    this.workers = [];
    this.nextWorkerIndex = 0;
    
    console.log('RoomManager 종료됨');
  }
}

module.exports = RoomManager; 