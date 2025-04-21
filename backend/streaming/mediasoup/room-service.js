/**
 * WebRTC 방 관리 서비스
 * mediasoup을 사용한 실시간 스트리밍 관리
 */

const mediasoup = require('mediasoup');
const config = require('./config');
const HlsService = require('../hls/hls-service');

class RoomService {
  constructor() {
    this.workers = [];
    this.nextWorkerIndex = 0;
    this.rooms = new Map(); // roomId => Room
    this.peers = new Map(); // peerId => Peer
  }

  /**
   * mediasoup workers 초기화
   */
  async initialize() {
    const { numWorkers } = config.mediasoup.worker;
    console.log(`${numWorkers}개의 mediasoup 워커를 생성합니다...`);

    for (let i = 0; i < numWorkers; i++) {
      const worker = await mediasoup.createWorker({
        logLevel: config.mediasoup.worker.logLevel,
        logTags: config.mediasoup.worker.logTags,
        rtcMinPort: config.mediasoup.worker.rtcMinPort,
        rtcMaxPort: config.mediasoup.worker.rtcMaxPort
      });

      worker.on('died', () => {
        console.error(`워커 ${i}가 예기치 않게 종료되었습니다!`);
        setTimeout(() => process.exit(1), 2000);
      });

      this.workers.push(worker);
      console.log(`워커 ${i} 생성됨 [pid: ${worker.pid}]`);
    }
  }

  /**
   * 다음 사용할 워커 가져오기 (라운드 로빈)
   */
  getNextWorker() {
    const worker = this.workers[this.nextWorkerIndex];
    this.nextWorkerIndex = (this.nextWorkerIndex + 1) % this.workers.length;
    return worker;
  }

  /**
   * 새로운 방 생성
   * @param {string} roomId - 고유 방 ID
   * @param {Object} options - 방 생성 옵션
   * @returns {Promise<Room>} 생성된 방 객체
   */
  async createRoom(roomId, options = {}) {
    if (this.rooms.has(roomId)) {
      return this.getRoom(roomId);
    }

    console.log(`새로운 방 생성: ${roomId}`);
    const worker = this.getNextWorker();

    // mediasoup 라우터 생성
    const router = await worker.createRouter({
      mediaCodecs: config.mediasoup.router.mediaCodecs
    });

    // 방 객체 생성
    const room = {
      id: roomId,
      worker,
      router,
      peers: new Map(),
      producers: new Map(),
      consumers: new Map(),
      options,
      creationTime: Date.now(),
      hlsService: new HlsService(router, roomId)
    };

    this.rooms.set(roomId, room);
    return room;
  }

  /**
   * 방 조회
   * @param {string} roomId - 방 ID
   * @returns {Room|undefined} 조회된 방 객체
   */
  getRoom(roomId) {
    return this.rooms.get(roomId);
  }

  /**
   * 방 삭제
   * @param {string} roomId - 방 ID
   */
  async closeRoom(roomId) {
    const room = this.getRoom(roomId);
    if (!room) {
      return;
    }

    console.log(`방 종료: ${roomId}`);

    // HLS 스트리밍 중지
    if (room.hlsService) {
      await room.hlsService.stop();
      await room.hlsService.cleanupFiles();
    }

    // 방의 모든 피어 종료
    for (const [peerId, peer] of room.peers) {
      this.closePeer(peerId, roomId);
    }

    this.rooms.delete(roomId);
  }

  /**
   * 피어(사용자) 생성
   * @param {string} peerId - 피어 ID
   * @param {string} roomId - 방 ID
   * @param {Object} options - 피어 옵션
   * @returns {Promise<Peer>} 생성된 피어 객체
   */
  async createPeer(peerId, roomId, options = {}) {
    const room = await this.createRoom(roomId);
    
    if (room.peers.has(peerId)) {
      return room.peers.get(peerId);
    }

    console.log(`새로운 피어 생성: ${peerId} (방: ${roomId})`);

    // 피어 객체 생성
    const peer = {
      id: peerId,
      roomId,
      transports: new Map(),
      producers: new Map(),
      consumers: new Map(),
      options,
      joinTime: Date.now()
    };

    room.peers.set(peerId, peer);
    this.peers.set(peerId, peer);

    return peer;
  }

  /**
   * 피어 조회
   * @param {string} peerId - 피어 ID
   * @returns {Peer|undefined} 조회된 피어 객체
   */
  getPeer(peerId) {
    return this.peers.get(peerId);
  }

  /**
   * 피어 종료
   * @param {string} peerId - 피어 ID
   * @param {string} roomId - 방 ID
   */
  closePeer(peerId, roomId) {
    const peer = this.getPeer(peerId);
    if (!peer) {
      return;
    }

    console.log(`피어 종료: ${peerId} (방: ${roomId})`);

    // 피어의 모든 컨슈머 종료
    for (const consumer of peer.consumers.values()) {
      consumer.close();
    }

    // 피어의 모든 프로듀서 종료
    for (const producer of peer.producers.values()) {
      producer.close();
    }

    // 피어의 모든 트랜스포트 종료
    for (const transport of peer.transports.values()) {
      transport.close();
    }

    // 피어 제거
    const room = this.getRoom(roomId);
    if (room) {
      room.peers.delete(peerId);
    }
    
    this.peers.delete(peerId);
  }

  /**
   * WebRTC 트랜스포트 생성
   * @param {string} peerId - 피어 ID
   * @param {string} roomId - 방 ID
   * @param {string} direction - 'send' 또는 'recv'
   * @returns {Promise<Object>} 트랜스포트 정보
   */
  async createWebRtcTransport(peerId, roomId, direction) {
    const peer = await this.createPeer(peerId, roomId);
    const room = this.getRoom(roomId);
    const router = room.router;

    // WebRTC 트랜스포트 생성
    const transport = await router.createWebRtcTransport(
      config.mediasoup.webRtcTransport
    );

    // 트랜스포트 이벤트 리스너 등록
    transport.on('dtlsstatechange', (dtlsState) => {
      if (dtlsState === 'closed') {
        console.log(`트랜스포트 종료: ${transport.id}`);
        transport.close();
      }
    });

    transport.on('close', () => {
      console.log(`트랜스포트 종료: ${transport.id}`);
      peer.transports.delete(transport.id);
    });

    // 피어와 트랜스포트 연결
    peer.transports.set(transport.id, transport);

    // 트랜스포트 정보 반환
    return {
      id: transport.id,
      iceParameters: transport.iceParameters,
      iceCandidates: transport.iceCandidates,
      dtlsParameters: transport.dtlsParameters,
      direction
    };
  }

  /**
   * 트랜스포트 연결
   * @param {string} peerId - 피어 ID
   * @param {string} transportId - 트랜스포트 ID
   * @param {Object} dtlsParameters - DTLS 파라미터
   */
  async connectTransport(peerId, transportId, dtlsParameters) {
    const peer = this.getPeer(peerId);
    if (!peer) {
      throw new Error(`피어를 찾을 수 없음: ${peerId}`);
    }

    const transport = peer.transports.get(transportId);
    if (!transport) {
      throw new Error(`트랜스포트를 찾을 수 없음: ${transportId}`);
    }

    // 트랜스포트 연결
    await transport.connect({ dtlsParameters });
    console.log(`트랜스포트 연결됨: ${transportId}`);
  }

  /**
   * 프로듀서 생성 (미디어 생성)
   * @param {string} peerId - 피어 ID
   * @param {string} transportId - 트랜스포트 ID
   * @param {Object} rtpParameters - RTP 파라미터
   * @param {string} kind - 'audio' 또는 'video'
   * @returns {Promise<Object>} 프로듀서 정보
   */
  async createProducer(peerId, transportId, rtpParameters, kind) {
    const peer = this.getPeer(peerId);
    if (!peer) {
      throw new Error(`피어를 찾을 수 없음: ${peerId}`);
    }

    const transport = peer.transports.get(transportId);
    if (!transport) {
      throw new Error(`트랜스포트를 찾을 수 없음: ${transportId}`);
    }

    // 프로듀서 생성
    const producer = await transport.produce({ kind, rtpParameters });

    // 프로듀서 이벤트 리스너 등록
    producer.on('transportclose', () => {
      console.log(`프로듀서 종료 (transportclose): ${producer.id}`);
      producer.close();
      peer.producers.delete(producer.id);
    });

    producer.on('close', () => {
      console.log(`프로듀서 종료: ${producer.id}`);
      peer.producers.delete(producer.id);
    });

    // 피어와 방에 프로듀서 연결
    peer.producers.set(producer.id, producer);
    
    const room = this.getRoom(peer.roomId);
    room.producers.set(producer.id, producer);

    return {
      id: producer.id,
      kind: producer.kind
    };
  }

  /**
   * 컨슈머 생성 (미디어 수신)
   * @param {string} peerId - 피어 ID
   * @param {string} transportId - 트랜스포트 ID
   * @param {string} producerId - 프로듀서 ID
   * @param {Object} rtpCapabilities - RTP 성능
   * @returns {Promise<Object>} 컨슈머 정보
   */
  async createConsumer(peerId, transportId, producerId, rtpCapabilities) {
    const peer = this.getPeer(peerId);
    if (!peer) {
      throw new Error(`피어를 찾을 수 없음: ${peerId}`);
    }

    const transport = peer.transports.get(transportId);
    if (!transport) {
      throw new Error(`트랜스포트를 찾을 수 없음: ${transportId}`);
    }

    const room = this.getRoom(peer.roomId);
    const producer = room.producers.get(producerId);
    if (!producer) {
      throw new Error(`프로듀서를, 찾을 수 없음: ${producerId}`);
    }

    // RTP 호환성 확인
    if (!room.router.canConsume({
      producerId: producer.id,
      rtpCapabilities
    })) {
      throw new Error('RTP 호환성 없음');
    }

    // 컨슈머 생성
    const consumer = await transport.consume({
      producerId: producer.id,
      rtpCapabilities,
      paused: true
    });

    // 컨슈머 이벤트 리스너 등록
    consumer.on('transportclose', () => {
      console.log(`컨슈머 종료 (transportclose): ${consumer.id}`);
      consumer.close();
      peer.consumers.delete(consumer.id);
    });

    consumer.on('producerclose', () => {
      console.log(`컨슈머 종료 (producerclose): ${consumer.id}`);
      consumer.close();
      peer.consumers.delete(consumer.id);
    });

    consumer.on('close', () => {
      console.log(`컨슈머 종료: ${consumer.id}`);
      peer.consumers.delete(consumer.id);
    });

    // 피어와 방에 컨슈머 연결
    peer.consumers.set(consumer.id, consumer);
    room.consumers.set(consumer.id, consumer);

    return {
      id: consumer.id,
      producerId: producer.id,
      kind: consumer.kind,
      rtpParameters: consumer.rtpParameters,
      type: consumer.type
    };
  }

  /**
   * 컨슈머 재생 시작
   * @param {string} peerId - 피어 ID
   * @param {string} consumerId - 컨슈머 ID
   */
  async resumeConsumer(peerId, consumerId) {
    const peer = this.getPeer(peerId);
    if (!peer) {
      throw new Error(`피어를 찾을 수 없음: ${peerId}`);
    }

    const consumer = peer.consumers.get(consumerId);
    if (!consumer) {
      throw new Error(`컨슈머를 찾을 수 없음: ${consumerId}`);
    }

    await consumer.resume();
    console.log(`컨슈머 재생 시작: ${consumerId}`);
  }

  /**
   * HLS 스트리밍 시작
   * @param {string} roomId - 방 ID
   * @param {string} videoProducerId - 비디오 프로듀서 ID
   * @param {string} audioProducerId - 오디오 프로듀서 ID
   * @returns {Promise<string>} HLS URL
   */
  async startHls(roomId, videoProducerId, audioProducerId) {
    const room = this.getRoom(roomId);
    if (!room) {
      throw new Error(`방을 찾을 수 없음: ${roomId}`);
    }

    const videoProducer = room.producers.get(videoProducerId);
    if (!videoProducer) {
      throw new Error(`비디오 프로듀서를 찾을 수 없음: ${videoProducerId}`);
    }

    let audioProducer = null;
    if (audioProducerId) {
      audioProducer = room.producers.get(audioProducerId);
      if (!audioProducer) {
        console.warn(`오디오 프로듀서를 찾을 수 없음: ${audioProducerId}`);
      }
    }

    await room.hlsService.start(videoProducer, audioProducer);
    return room.hlsService.getHlsUrl();
  }

  /**
   * HLS 스트리밍 중지
   * @param {string} roomId - 방 ID
   */
  async stopHls(roomId) {
    const room = this.getRoom(roomId);
    if (!room) {
      throw new Error(`방을 찾을 수 없음: ${roomId}`);
    }

    await room.hlsService.stop();
  }

  /**
   * HLS URL 조회
   * @param {string} roomId - 방 ID
   * @returns {string|null} HLS URL
   */
  getHlsUrl(roomId) {
    const room = this.getRoom(roomId);
    if (!room || !room.hlsService) {
      return null;
    }

    return room.hlsService.getHlsUrl();
  }

  /**
   * RTP 기능 가져오기
   * @returns {Object} RTP 기능
   */
  getRtpCapabilities(roomId) {
    const room = this.getRoom(roomId);
    if (!room) {
      throw new Error(`방을 찾을 수 없음: ${roomId}`);
    }

    return room.router.rtpCapabilities;
  }
}

module.exports = new RoomService(); 