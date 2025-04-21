/**
 * mediasoup 서버
 * WebRTC 기반 실시간 스트리밍 처리 서버
 */

const mediasoup = require('mediasoup');
const { EventEmitter } = require('events');
const config = require('./config');
const os = require('os');

// AWS 서비스 통합
const { ElastiCacheService } = require('../aws/elastic_cache_service');
const redis = new ElastiCacheService();

class MediasoupServer extends EventEmitter {
  /**
   * mediasoup 서버 초기화
   */
  constructor() {
    super();
    
    this._closed = false;
    this.workers = [];
    this.nextWorkerIndex = 0;
    this.router = null;
    
    // 실행 중인 프로듀서 및 컨슈머 관리
    this.producers = new Map();
    this.consumers = new Map();
    
    // 룸 관리
    this.rooms = new Map();
    
    // 워커 건강 상태 체크 간격 (밀리초)
    this.healthCheckInterval = 30000;
    this.healthCheckIntervalId = null;
  }

  /**
   * mediasoup 서버 시작
   */
  async start() {
    if (this._closed) {
      throw new Error('서버가 이미 종료되었습니다');
    }
    
    try {
      // Redis 연결 초기화
      if (config.aws.elastiCache.enabled) {
        await redis.connect();
        console.log('ElastiCache(Redis) 연결 성공');
      }
      
      // Worker 생성 (설정에 지정된 개수만큼)
      const numWorkers = config.mediasoup.worker.numWorkers;
      console.log(`${numWorkers}개의 mediasoup Worker 생성 중...`);
      
      // 워커를 병렬로 생성하여 시작 시간 단축
      const workerPromises = Array(numWorkers).fill().map((_, i) => this._createWorker(i));
      this.workers = await Promise.all(workerPromises);
      
      console.log(`${this.workers.length}개의 mediasoup Worker 생성 완료`);
      
      // 워커 상태 모니터링 시작
      this._startHealthCheck();
      
      console.log('mediasoup 서버 시작 완료');
      
    } catch (error) {
      console.error('mediasoup 서버 시작 실패:', error);
      throw error;
    }
  }

  /**
   * Worker 생성
   * @param {number} index - 워커 인덱스
   * @returns {Promise<Object>} mediasoup Worker 인스턴스
   */
  async _createWorker(index) {
    const worker = await mediasoup.createWorker({
      logLevel: config.mediasoup.worker.logLevel,
      logTags: config.mediasoup.worker.logTags,
      rtcMinPort: config.mediasoup.worker.rtcMinPort,
      rtcMaxPort: config.mediasoup.worker.rtcMaxPort
    });
    
    worker.on('died', () => {
      console.error(`mediasoup Worker 종료됨: ${worker.pid}`);
      this.emit('workerDied', worker.pid);
      
      // 워커가 죽으면 워커 목록에서 제거
      this.workers = this.workers.filter(w => w.pid !== worker.pid);
      
      // 서버가 종료 상태가 아니라면 워커 재시작
      if (!this._closed) {
        this._createWorker(index).then(newWorker => {
          this.workers.push(newWorker);
          console.log(`mediasoup Worker ${index} 재시작됨 [pid: ${newWorker.pid}]`);
        }).catch(error => {
          console.error(`mediasoup Worker ${index} 재시작 실패:`, error);
        });
      }
    });
    
    console.log(`mediasoup Worker ${index} 생성됨 [pid: ${worker.pid}]`);
    
    return worker;
  }

  /**
   * 워커 상태 모니터링 시작
   * @private
   */
  _startHealthCheck() {
    if (this.healthCheckIntervalId) {
      clearInterval(this.healthCheckIntervalId);
    }
    
    this.healthCheckIntervalId = setInterval(async () => {
      try {
        // 각 워커의 리소스 사용량 확인
        const workerStats = await Promise.all(
          this.workers.map(async (worker) => {
            const usage = await worker.getResourceUsage();
            return {
              pid: worker.pid,
              cpu: usage.ru_utime + usage.ru_stime,
              memory: usage.ru_maxrss
            };
          })
        );
        
        // 리소스 사용량을 Redis에 저장 (AWS ElastiCache 통합)
        if (config.aws.elastiCache.enabled && redis.isConnected()) {
          await redis.set(
            `mediasoup:stats:${process.pid}`, 
            JSON.stringify({
              timestamp: Date.now(),
              workers: workerStats,
              rooms: this.rooms.size,
              producers: this.producers.size,
              consumers: this.consumers.size
            }),
            60 // 60초 만료 (TTL)
          );
        }
      } catch (error) {
        console.error('워커 상태 모니터링 오류:', error);
      }
    }, this.healthCheckInterval);
  }

  /**
   * 다음 Worker 가져오기 (라운드 로빈 방식)
   * @returns {Object} mediasoup Worker 인스턴스
   */
  _getNextWorker() {
    if (this.workers.length === 0) {
      throw new Error('사용 가능한 mediasoup Worker가 없습니다');
    }
    
    const worker = this.workers[this.nextWorkerIndex];
    
    this.nextWorkerIndex = (this.nextWorkerIndex + 1) % this.workers.length;
    
    return worker;
  }

  /**
   * 라우터 생성 또는 가져오기
   * @param {string} roomId - 룸 식별자
   * @returns {Promise<Object>} mediasoup Router 인스턴스
   */
  async getRouter(roomId) {
    // 기존 룸이 있는 경우 해당 라우터 반환
    if (this.rooms.has(roomId)) {
      return this.rooms.get(roomId).router;
    }
    
    // Redis에서 기존 룸 정보 찾기 (다중 서버 환경 지원)
    if (config.aws.elastiCache.enabled && redis.isConnected()) {
      const cachedRoomData = await redis.get(`room:${roomId}`);
      if (cachedRoomData) {
        try {
          const roomData = JSON.parse(cachedRoomData);
          console.log(`Redis에서 기존 룸 정보 복원: ${roomId}`);
          // 이미 다른 서버에서 룸이 생성된 경우 처리 로직 추가 가능
        } catch (error) {
          console.error(`룸 정보 파싱 오류: ${roomId}`, error);
        }
      }
    }
    
    // 새 라우터 생성
    const worker = this._getNextWorker();
    
    const router = await worker.createRouter({
      mediaCodecs: config.mediasoup.router.mediaCodecs
    });
    
    // 룸 정보 저장
    const roomInfo = {
      id: roomId,
      router,
      peers: new Map(),
      createdAt: Date.now()
    };
    
    this.rooms.set(roomId, roomInfo);
    
    // Redis에 룸 정보 저장 (다중 서버 환경 지원)
    if (config.aws.elastiCache.enabled && redis.isConnected()) {
      await redis.set(
        `room:${roomId}`,
        JSON.stringify({
          id: roomId,
          workerId: worker.pid,
          createdAt: roomInfo.createdAt
        }),
        // 24시간 만료 (TTL)
        60 * 60 * 24
      );
    }
    
    console.log(`룸 생성됨: ${roomId}`);
    
    return router;
  }

  /**
   * WebRTC 트랜스포트 생성
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @returns {Promise<Object>} transport 객체
   */
  async createWebRtcTransport(roomId, peerId) {
    const router = await this.getRouter(roomId);
    
    const transport = await router.createWebRtcTransport({
      listenIps: config.mediasoup.webRtcTransport.listenIps,
      enableUdp: true,
      enableTcp: true,
      preferUdp: true,
      initialAvailableOutgoingBitrate: config.mediasoup.webRtcTransport.initialAvailableOutgoingBitrate,
      minimumAvailableOutgoingBitrate: config.mediasoup.webRtcTransport.minimumAvailableOutgoingBitrate,
      maximumAvailableOutgoingBitrate: config.mediasoup.webRtcTransport.maximumAvailableOutgoingBitrate
    });
    
    // 최대 수신 비트레이트 설정
    if (config.mediasoup.webRtcTransport.maxIncomingBitrate) {
      await transport.setMaxIncomingBitrate(config.mediasoup.webRtcTransport.maxIncomingBitrate);
    }

    // 네트워크 품질 모니터링 설정
    this._setupNetworkMonitoring(transport, roomId, peerId);
    
    // 피어 정보 가져오기
    let peer = this._getPeer(roomId, peerId);
    
    if (!peer) {
      // 피어 정보 생성
      peer = {
        id: peerId,
        transports: new Map(),
        producers: new Map(),
        consumers: new Map(),
        data: {}
      };
      
      this.rooms.get(roomId).peers.set(peerId, peer);
    }
    
    // 트랜스포트에 이벤트 리스너 등록
    transport.on('dtlsstatechange', dtlsState => {
      if (dtlsState === 'closed') {
        console.log(`Transport ${transport.id} for peer ${peerId} closed`);
      }
    });
    
    transport.on('close', () => {
      console.log(`Transport ${transport.id} for peer ${peerId} closed`);
      
      // 피어의 트랜스포트 목록에서 제거
      peer.transports.delete(transport.id);
    });
    
    // 피어의 트랜스포트 목록에 추가
    peer.transports.set(transport.id, transport);
    
    return {
      id: transport.id,
      iceParameters: transport.iceParameters,
      iceCandidates: transport.iceCandidates,
      dtlsParameters: transport.dtlsParameters,
      sctpParameters: transport.sctpParameters
    };
  }

  /**
   * 네트워크 품질 모니터링 및 적응형 비트레이트 설정
   * @param {Object} transport - WebRTC 트랜스포트
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @private
   */
  _setupNetworkMonitoring(transport, roomId, peerId) {
    if (!config.mediasoup.adaptiveBitrate || !config.mediasoup.adaptiveBitrate.enabled) {
      return;
    }

    const { detectionInterval, minRtt, decreaseFactor, increaseFactor, adjustmentThrottleMs, stableNetworkThreshold } = config.mediasoup.adaptiveBitrate;
    let lastAdjustmentTime = Date.now();
    let lastStats = null;
    let stableNetworkCount = 0;

    // 주기적으로 네트워크 상태 확인
    const intervalId = setInterval(async () => {
      try {
        // 트랜스포트가 닫혔는지 확인
        if (transport.closed) {
          clearInterval(intervalId);
          return;
        }

        // 트랜스포트 상태 가져오기
        const stats = await transport.getStats();
        
        if (!lastStats) {
          lastStats = stats;
          return;
        }

        // RTT (Round Trip Time) 분석
        const currentRtt = stats.find(s => s.type === 'outbound-rtp' && s.kind === 'video')?.roundTripTime;
        const lastRtt = lastStats.find(s => s.type === 'outbound-rtp' && s.kind === 'video')?.roundTripTime;

        if (!currentRtt || !lastRtt) {
          return;
        }

        // 현재 시간 확인 (조절 너무 잦지 않도록)
        const now = Date.now();
        if (now - lastAdjustmentTime < adjustmentThrottleMs) {
          return;
        }

        // 네트워크 상태 분석 및 비트레이트 조정
        const currentBitrate = await transport.getMaxOutgoingBitrate();
        const minimumAvailableBitrate = config.mediasoup.webRtcTransport.minimumAvailableOutgoingBitrate;
        const maximumAvailableBitrate = config.mediasoup.webRtcTransport.maximumAvailableOutgoingBitrate;

        // RTT 증가 감지 (네트워크 품질 악화 - 개선된 알고리즘)
        const sensitivityFactor = 1.2;
        if (currentRtt > lastRtt * sensitivityFactor && currentRtt > minRtt * 1.5) {
          // 비트레이트 감소 (혼잡 상황)
          const newBitrate = Math.max(
            minimumAvailableBitrate,
            Math.floor(currentBitrate * decreaseFactor)
          );
          
          await transport.setMaxOutgoingBitrate(newBitrate);
          console.log(`네트워크 혼잡 감지 - 비트레이트 급속 조정: ${currentBitrate} → ${newBitrate}`);
          lastAdjustmentTime = now;
          stableNetworkCount = 0; // 안정 카운터 리셋
        } 
        // 네트워크 상태 개선 감지 - 점진적 증가 (안정화 기간 확인)
        else if (currentRtt < minRtt * 1.2) {
          stableNetworkCount++;
          
          // 네트워크가 일정 기간 동안 안정적인 경우에만 비트레이트 증가
          if (stableNetworkCount >= stableNetworkThreshold) {
            const newBitrate = Math.min(
              maximumAvailableBitrate,
              Math.floor(currentBitrate * increaseFactor)
            );
            
            await transport.setMaxOutgoingBitrate(newBitrate);
            console.log(`네트워크 상태 안정적 - 비트레이트 점진적 증가: ${currentBitrate} → ${newBitrate}`);
            lastAdjustmentTime = now;
            stableNetworkCount = 0; // 안정 카운터 리셋
          }
        }
        // 네트워크 상태가 안정적이지 않은 경우
        else {
          stableNetworkCount = 0; // 안정 카운터 리셋
        }

        lastStats = stats;
      } catch (error) {
        console.error('네트워크 모니터링 오류:', error);
      }
    }, detectionInterval);

    // 룸 또는 피어 정보에 인터벌 ID 저장 (정리를 위해)
    const peer = this._getPeer(roomId, peerId);
    if (peer) {
      if (!peer.data.intervals) {
        peer.data.intervals = [];
      }
      peer.data.intervals.push(intervalId);
    }
  }

  /**
   * Plain RTP 트랜스포트 생성 (HLS 변환용)
   * @param {string} roomId - 룸 식별자
   * @returns {Promise<Object>} RTP 트랜스포트 객체
   */
  async createPlainRtpTransport(roomId) {
    const router = await this.getRouter(roomId);
    
    const transport = await router.createPlainTransport({
      ...config.mediasoup.plainTransportOptions
    });
    
    transport.on('close', () => {
      console.log(`RTP Transport ${transport.id} closed`);
    });
    
    return {
      id: transport.id,
      ip: transport.tuple.localIp,
      port: transport.tuple.localPort
    };
  }

  /**
   * 프로듀서 생성
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @param {string} transportId - 트랜스포트 식별자
   * @param {Object} rtpParameters - RTP 매개변수
   * @param {string} kind - 미디어 종류 (audio/video)
   * @returns {Promise<Object>} Producer 객체
   */
  async createProducer(roomId, peerId, transportId, rtpParameters, kind) {
    const peer = this._getPeer(roomId, peerId);
    
    if (!peer) {
      throw new Error(`Peer ${peerId} not found`);
    }
    
    const transport = peer.transports.get(transportId);
    
    if (!transport) {
      throw new Error(`Transport ${transportId} not found`);
    }
    
    // 프로듀서 옵션 설정
    const producerOptions = {
      kind,
      rtpParameters
    };

    // 비디오에 SVC 설정 적용 (개선된 SVC 설정)
    if (kind === 'video' && config.mediasoup.svc && config.mediasoup.svc.enabled) {
      // SVC 설정
      const { numSpatialLayers, numTemporalLayers } = config.mediasoup.svc;
      const scalabilityMode = `L${numSpatialLayers}T${numTemporalLayers}`;
      
      // VP9, AV1 같은 고급 코덱인 경우 SVC 설정을 더 세밀하게 적용
      const codec = rtpParameters.codecs[0].mimeType.toLowerCase();
      const isSvcSupportedCodec = codec.includes('vp9') || codec.includes('av1') || codec.includes('vp8');

      producerOptions.encodings = [
        {
          // 스케일러빌리티 모드 설정
          scalabilityMode: isSvcSupportedCodec ? scalabilityMode : 'L1T3',
          // 비트레이트 제한
          maxBitrate: config.mediasoup.svc.highProfile.maxBitrate,
          // 네트워크 효율성 향상을 위한 설정
          dtx: true,
          // 프레임 레이트와 품질 최적화
          adaptivePtime: true,
          priority: 'high'
        }
      ];
      
      // 디버그 로그
      console.log(`SVC 설정 적용 - 코덱: ${codec}, 스케일러빌리티: ${scalabilityMode}`);
    }
    
    const producer = await transport.produce(producerOptions);
    
    // 프로듀서에 이벤트 리스너 등록
    producer.on('score', score => {
      // 스코어 로깅은 개발 모드에서만 활성화
      if (process.env.NODE_ENV === 'development') {
        console.log(`Producer ${producer.id} score: ${JSON.stringify(score)}`);
      }
    });
    
    producer.on('videoorientationchange', orientation => {
      console.log(`Producer ${producer.id} video orientation changed`);
    });
    
    producer.on('close', () => {
      console.log(`Producer ${producer.id} closed`);
      
      // 피어의 프로듀서 목록에서 제거
      peer.producers.delete(producer.id);
      
      // 전체 프로듀서 목록에서 제거
      this.producers.delete(producer.id);
    });
    
    // 피어의 프로듀서 목록에 추가
    peer.producers.set(producer.id, producer);
    
    // 전체 프로듀서 목록에 추가
    this.producers.set(producer.id, producer);
    
    return {
      id: producer.id,
      kind: producer.kind
    };
  }

  /**
   * 컨슈머 생성
   * @param {string} roomId - 룸 식별자
   * @param {string} consumerPeerId - 컨슈머 피어 식별자
   * @param {string} producerPeerId - 프로듀서 피어 식별자
   * @param {string} producerId - 프로듀서 식별자
   * @param {string} transportId - 트랜스포트 식별자
   * @returns {Promise<Object>} Consumer 객체
   */
  async createConsumer(roomId, consumerPeerId, producerPeerId, producerId, transportId) {
    const consumerPeer = this._getPeer(roomId, consumerPeerId);
    
    if (!consumerPeer) {
      throw new Error(`Consumer peer ${consumerPeerId} not found`);
    }
    
    const room = this.rooms.get(roomId);
    const producerPeer = room.peers.get(producerPeerId);
    
    if (!producerPeer) {
      throw new Error(`Producer peer ${producerPeerId} not found`);
    }
    
    const producer = producerPeer.producers.get(producerId);
    
    if (!producer) {
      throw new Error(`Producer ${producerId} not found`);
    }
    
    const transport = consumerPeer.transports.get(transportId);
    
    if (!transport) {
      throw new Error(`Transport ${transportId} not found`);
    }
    
    const router = await this.getRouter(roomId);
    
    // RTP 기능 확인
    let rtpCapabilities;
    try {
      rtpCapabilities = consumerPeer.data.rtpCapabilities;
      if (!rtpCapabilities) {
        throw new Error('No RTP capabilities');
      }
    } catch (error) {
      throw new Error(`Consumer peer ${consumerPeerId} has no RTP capabilities`);
    }
    
    // 소비 가능 여부 확인
    if (!router.canConsume({
      producerId: producer.id,
      rtpCapabilities
    })) {
      throw new Error(`Consumer peer ${consumerPeerId} cannot consume producer ${producerId}`);
    }
    
    // 컨슈머 생성
    const consumer = await transport.consume({
      producerId: producer.id,
      rtpCapabilities,
      paused: false // 자동 시작
    });
    
    // 컨슈머에 이벤트 리스너 등록
    consumer.on('transportclose', () => {
      console.log(`Consumer ${consumer.id} transport closed`);
    });
    
    consumer.on('producerclose', () => {
      console.log(`Consumer ${consumer.id} producer closed`);
      
      // 피어의 컨슈머 목록에서 제거
      consumerPeer.consumers.delete(consumer.id);
      
      // 전체 컨슈머 목록에서 제거
      this.consumers.delete(consumer.id);
      
      // 이벤트 발생
      this.emit('consumerClosed', {
        roomId,
        peerId: consumerPeerId,
        consumerId: consumer.id
      });
    });
    
    consumer.on('score', score => {
      // console.log(`Consumer ${consumer.id} score: ${JSON.stringify(score)}`);
    });
    
    consumer.on('layerschange', layers => {
      console.log(`Consumer ${consumer.id} layers changed: ${JSON.stringify(layers)}`);
    });
    
    // 피어의 컨슈머 목록에 추가
    consumerPeer.consumers.set(consumer.id, consumer);
    
    // 전체 컨슈머 목록에 추가
    this.consumers.set(consumer.id, consumer);
    
    return {
      id: consumer.id,
      producerId: producer.id,
      kind: consumer.kind,
      rtpParameters: consumer.rtpParameters,
      type: consumer.type
    };
  }

  /**
   * 피어 정보 가져오기
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @returns {Object} 피어 객체
   */
  _getPeer(roomId, peerId) {
    const room = this.rooms.get(roomId);
    
    if (!room) {
      return null;
    }
    
    return room.peers.get(peerId);
  }

  /**
   * RTP 기능 설정
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @param {Object} rtpCapabilities - RTP 기능
   */
  setRtpCapabilities(roomId, peerId, rtpCapabilities) {
    const peer = this._getPeer(roomId, peerId);
    
    if (!peer) {
      throw new Error(`Peer ${peerId} not found`);
    }
    
    peer.data.rtpCapabilities = rtpCapabilities;
  }

  /**
   * 트랜스포트 연결
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @param {string} transportId - 트랜스포트 식별자
   * @param {Object} dtlsParameters - DTLS 매개변수
   * @returns {Promise<boolean>} 성공 여부
   */
  async connectTransport(roomId, peerId, transportId, dtlsParameters) {
    const peer = this._getPeer(roomId, peerId);
    
    if (!peer) {
      throw new Error(`Peer ${peerId} not found`);
    }
    
    const transport = peer.transports.get(transportId);
    
    if (!transport) {
      throw new Error(`Transport ${transportId} not found`);
    }
    
    await transport.connect({ dtlsParameters });
    
    return true;
  }

  /**
   * 컨슈머 일시 중지/재개
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @param {string} consumerId - 컨슈머 식별자
   * @param {boolean} pause - 일시 중지 여부
   * @returns {Promise<boolean>} 성공 여부
   */
  async pauseConsumer(roomId, peerId, consumerId, pause) {
    const peer = this._getPeer(roomId, peerId);
    
    if (!peer) {
      throw new Error(`Peer ${peerId} not found`);
    }
    
    const consumer = peer.consumers.get(consumerId);
    
    if (!consumer) {
      throw new Error(`Consumer ${consumerId} not found`);
    }
    
    if (pause) {
      await consumer.pause();
    } else {
      await consumer.resume();
    }
    
    return true;
  }

  /**
   * 프로듀서 일시 중지/재개
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   * @param {string} producerId - 프로듀서 식별자
   * @param {boolean} pause - 일시 중지 여부
   * @returns {Promise<boolean>} 성공 여부
   */
  async pauseProducer(roomId, peerId, producerId, pause) {
    const peer = this._getPeer(roomId, peerId);
    
    if (!peer) {
      throw new Error(`Peer ${peerId} not found`);
    }
    
    const producer = peer.producers.get(producerId);
    
    if (!producer) {
      throw new Error(`Producer ${producerId} not found`);
    }
    
    if (pause) {
      await producer.pause();
    } else {
      await producer.resume();
    }
    
    return true;
  }

  /**
   * 피어 종료
   * @param {string} roomId - 룸 식별자
   * @param {string} peerId - 피어 식별자
   */
  closePeer(roomId, peerId) {
    const peer = this._getPeer(roomId, peerId);
    
    if (!peer) {
      return;
    }
    
    console.log(`Closing peer ${peerId} in room ${roomId}`);
    
    // 트랜스포트 종료
    for (const transport of peer.transports.values()) {
      transport.close();
    }
    
    // 룸에서 피어 제거
    const room = this.rooms.get(roomId);
    room.peers.delete(peerId);
    
    // 빈 룸인 경우 룸 제거
    if (room.peers.size === 0) {
      console.log(`Room ${roomId} is empty, closing it`);
      room.router.close();
      this.rooms.delete(roomId);
    }
    
    // 이벤트 발생
    this.emit('peerClosed', {
      roomId,
      peerId
    });
  }

  /**
   * mediasoup 서버 종료
   */
  async close() {
    if (this._closed) {
      return;
    }
    
    this._closed = true;
    
    // 워커 상태 체크 중지
    if (this.healthCheckIntervalId) {
      clearInterval(this.healthCheckIntervalId);
      this.healthCheckIntervalId = null;
    }
    
    // 모든 룸 닫기
    for (const roomId of this.rooms.keys()) {
      try {
        // Redis에서 룸 정보 삭제
        if (config.aws.elastiCache.enabled && redis.isConnected()) {
          await redis.del(`room:${roomId}`);
        }
      } catch (error) {
        console.error(`룸 정보 삭제 오류: ${roomId}`, error);
      }
    }
    
    // 모든 워커 종료
    if (this.workers.length > 0) {
      const workerClosePromises = this.workers.map(worker => worker.close());
      await Promise.all(workerClosePromises);
      this.workers = [];
    }
    
    // Redis 연결 종료
    if (config.aws.elastiCache.enabled && redis.isConnected()) {
      await redis.disconnect();
      console.log('ElastiCache(Redis) 연결 종료');
    }
    
    console.log('mediasoup 서버 종료 완료');
  }
}

module.exports = MediasoupServer; 