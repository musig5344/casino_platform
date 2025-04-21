/**
 * AWS ElastiCache(Redis) 연동 서비스
 * 캐싱 및 분산 세션 관리를 위한 최적화된 클라이언트
 */

const Redis = require('ioredis');
const config = require('../mediasoup/config');

class ElastiCacheService {
  /**
   * ElastiCache 서비스 초기화
   */
  constructor() {
    this.redisClient = null;
    this.connected = false;
    this.reconnecting = false;
    this.prefix = config.aws.elastiCache.prefix || 'casino:';
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10;
    this.reconnectTimeout = null;
    
    // 클러스터 모드 여부
    this.clusterMode = config.aws.elastiCache.cluster || false;
  }

  /**
   * Redis 서버 연결
   * @returns {Promise<boolean>} 연결 성공 여부
   */
  async connect() {
    if (this.connected) {
      return true;
    }
    
    try {
      // Redis 설정
      const redisOptions = {
        host: config.aws.elastiCache.host,
        port: config.aws.elastiCache.port,
        password: config.aws.elastiCache.password || undefined,
        db: 0,
        retryStrategy: (times) => {
          if (times > 10) {
            // 10번 이상 재시도시 오류 발생
            return new Error('Redis 연결 재시도 횟수 초과');
          }
          // 지수 백오프 (최대 30초)
          return Math.min(times * 1000, 30000);
        },
        // 명령 타임아웃 설정
        commandTimeout: 5000,
        // 연결 유지를 위한 하트비트
        enableOfflineQueue: true,
        connectTimeout: 10000,
        // 자동 파이프라이닝 활성화
        enableAutoPipelining: true,
        // 모니터링 활성화
        enablePerformanceMetrics: true,
        maxRetriesPerRequest: 3
      };
      
      // Redis 클라이언트 생성 (클러스터 모드 여부에 따라)
      if (this.clusterMode) {
        // 클러스터 모드
        const nodes = config.aws.elastiCache.nodes.map(node => ({
          host: node.host,
          port: node.port
        }));
        
        this.redisClient = new Redis.Cluster(nodes, {
          redisOptions,
          // 클러스터 특정 옵션
          scaleReads: 'slave',
          maxRedirections: 16,
          retryDelayOnFailover: 1000
        });
      } else {
        // 스탠드얼론 모드
        this.redisClient = new Redis(redisOptions);
      }
      
      // 연결 이벤트 처리
      this.redisClient.on('connect', () => {
        console.log('Redis 서버에 연결됨');
      });
      
      this.redisClient.on('ready', () => {
        console.log('Redis 서버 사용 준비 완료');
        this.connected = true;
        this.reconnectAttempts = 0;
      });
      
      this.redisClient.on('error', (err) => {
        console.error('Redis 오류:', err);
        if (this.connected) {
          this.connected = false;
        }
      });
      
      this.redisClient.on('close', () => {
        console.log('Redis 연결 종료됨');
        this.connected = false;
        this._scheduleReconnect();
      });
      
      this.redisClient.on('reconnecting', () => {
        console.log(`Redis 서버 재연결 시도 중... (${++this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        this.reconnecting = true;
      });
      
      // 초기 연결 테스트
      await this.redisClient.ping();
      this.connected = true;
      
      return true;
    } catch (error) {
      console.error('Redis 연결 실패:', error);
      this.connected = false;
      this._scheduleReconnect();
      return false;
    }
  }
  
  /**
   * 재연결 스케줄링
   * @private
   */
  _scheduleReconnect() {
    if (this.reconnecting || this.reconnectTimeout) {
      return;
    }
    
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(`최대 재시도 횟수(${this.maxReconnectAttempts}) 초과로 Redis 재연결 중단`);
      return;
    }
    
    // 지수 백오프 방식으로 재연결 간격 증가
    const delay = Math.min(Math.pow(2, this.reconnectAttempts) * 1000, 30000);
    console.log(`${delay}ms 후 Redis 재연결 시도 예정`);
    
    this.reconnectTimeout = setTimeout(async () => {
      this.reconnectTimeout = null;
      this.reconnecting = true;
      
      try {
        await this.connect();
        this.reconnecting = false;
      } catch (err) {
        this.reconnecting = false;
        this.reconnectAttempts++;
        this._scheduleReconnect();
      }
    }, delay);
  }

  /**
   * 키-값 저장
   * @param {string} key - 키
   * @param {string|Object} value - 값
   * @param {number} [ttl] - TTL(초)
   * @returns {Promise<boolean>} 성공 여부
   */
  async set(key, value, ttl = 0) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      
      // 객체인 경우 JSON 문자열로 변환
      const stringValue = typeof value === 'object' 
        ? JSON.stringify(value) 
        : String(value);
      
      if (ttl > 0) {
        // TTL 설정
        await this.redisClient.set(prefixedKey, stringValue, 'EX', ttl);
      } else {
        // TTL 없음
        await this.redisClient.set(prefixedKey, stringValue);
      }
      
      return true;
    } catch (error) {
      console.error(`Redis 값 설정 오류 (${key}):`, error);
      return false;
    }
  }

  /**
   * 값 조회
   * @param {string} key - 키
   * @param {boolean} [parseJson=true] - JSON 파싱 여부
   * @returns {Promise<any>} 저장된 값
   */
  async get(key, parseJson = true) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      const value = await this.redisClient.get(prefixedKey);
      
      if (value === null) {
        return null;
      }
      
      // JSON 파싱 시도
      if (parseJson) {
        try {
          return JSON.parse(value);
        } catch (e) {
          // JSON이 아니면 원래 값 반환
          return value;
        }
      }
      
      return value;
    } catch (error) {
      console.error(`Redis 값 조회 오류 (${key}):`, error);
      return null;
    }
  }

  /**
   * 키 삭제
   * @param {string} key - 키
   * @returns {Promise<boolean>} 성공 여부
   */
  async del(key) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      await this.redisClient.del(prefixedKey);
      return true;
    } catch (error) {
      console.error(`Redis 키 삭제 오류 (${key}):`, error);
      return false;
    }
  }

  /**
   * 해시 필드 설정
   * @param {string} key - 해시 키
   * @param {string} field - 필드
   * @param {string|Object} value - 값
   * @returns {Promise<boolean>} 성공 여부
   */
  async hSet(key, field, value) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      
      // 객체인 경우 JSON 문자열로 변환
      const stringValue = typeof value === 'object' 
        ? JSON.stringify(value) 
        : String(value);
      
      await this.redisClient.hset(prefixedKey, field, stringValue);
      return true;
    } catch (error) {
      console.error(`Redis 해시 필드 설정 오류 (${key}:${field}):`, error);
      return false;
    }
  }

  /**
   * 해시 필드 조회
   * @param {string} key - 해시 키
   * @param {string} field - 필드
   * @param {boolean} [parseJson=true] - JSON 파싱 여부
   * @returns {Promise<any>} 저장된 값
   */
  async hGet(key, field, parseJson = true) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      const value = await this.redisClient.hget(prefixedKey, field);
      
      if (value === null) {
        return null;
      }
      
      // JSON 파싱 시도
      if (parseJson) {
        try {
          return JSON.parse(value);
        } catch (e) {
          // JSON이 아니면 원래 값 반환
          return value;
        }
      }
      
      return value;
    } catch (error) {
      console.error(`Redis 해시 필드 조회 오류 (${key}:${field}):`, error);
      return null;
    }
  }

  /**
   * 해시 전체 조회
   * @param {string} key - 해시 키
   * @param {boolean} [parseJson=true] - JSON 파싱 여부
   * @returns {Promise<Object>} 해시 객체
   */
  async hGetAll(key, parseJson = true) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      const hash = await this.redisClient.hgetall(prefixedKey);
      
      if (!hash || Object.keys(hash).length === 0) {
        return {};
      }
      
      // JSON 파싱 시도
      if (parseJson) {
        const result = {};
        for (const [field, value] of Object.entries(hash)) {
          try {
            result[field] = JSON.parse(value);
          } catch (e) {
            result[field] = value;
          }
        }
        return result;
      }
      
      return hash;
    } catch (error) {
      console.error(`Redis 해시 전체 조회 오류 (${key}):`, error);
      return {};
    }
  }

  /**
   * 리스트에 값 추가 (오른쪽)
   * @param {string} key - 리스트 키
   * @param {string|Object} value - 값
   * @returns {Promise<boolean>} 성공 여부
   */
  async rPush(key, value) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      
      // 객체인 경우 JSON 문자열로 변환
      const stringValue = typeof value === 'object' 
        ? JSON.stringify(value) 
        : String(value);
      
      await this.redisClient.rpush(prefixedKey, stringValue);
      return true;
    } catch (error) {
      console.error(`Redis 리스트 추가 오류 (${key}):`, error);
      return false;
    }
  }

  /**
   * 리스트 범위 조회
   * @param {string} key - 리스트 키
   * @param {number} start - 시작 인덱스
   * @param {number} end - 종료 인덱스
   * @param {boolean} [parseJson=true] - JSON 파싱 여부
   * @returns {Promise<Array>} 리스트 항목
   */
  async lRange(key, start, end, parseJson = true) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      const items = await this.redisClient.lrange(prefixedKey, start, end);
      
      if (!items || items.length === 0) {
        return [];
      }
      
      // JSON 파싱 시도
      if (parseJson) {
        return items.map(item => {
          try {
            return JSON.parse(item);
          } catch (e) {
            return item;
          }
        });
      }
      
      return items;
    } catch (error) {
      console.error(`Redis 리스트 범위 조회 오류 (${key}):`, error);
      return [];
    }
  }

  /**
   * 원자적 카운터 증가
   * @param {string} key - 카운터 키
   * @param {number} [increment=1] - 증가량
   * @returns {Promise<number>} 증가 후 값
   */
  async incr(key, increment = 1) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      
      if (increment === 1) {
        return await this.redisClient.incr(prefixedKey);
      } else {
        return await this.redisClient.incrby(prefixedKey, increment);
      }
    } catch (error) {
      console.error(`Redis 카운터 증가 오류 (${key}):`, error);
      return -1;
    }
  }

  /**
   * 키 만료 시간 설정
   * @param {string} key - 키
   * @param {number} seconds - 만료 시간(초)
   * @returns {Promise<boolean>} 성공 여부
   */
  async expire(key, seconds) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      await this.redisClient.expire(prefixedKey, seconds);
      return true;
    } catch (error) {
      console.error(`Redis 만료 시간 설정 오류 (${key}):`, error);
      return false;
    }
  }

  /**
   * 키의 TTL 조회
   * @param {string} key - 키
   * @returns {Promise<number>} 남은 TTL(초)
   */
  async ttl(key) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedKey = this.prefix + key;
      return await this.redisClient.ttl(prefixedKey);
    } catch (error) {
      console.error(`Redis TTL 조회 오류 (${key}):`, error);
      return -1;
    }
  }

  /**
   * 패턴에 매칭되는 키 목록 조회
   * @param {string} pattern - 키 패턴 (예: "user:*")
   * @returns {Promise<Array<string>>} 키 목록
   */
  async keys(pattern) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const prefixedPattern = this.prefix + pattern;
      const keys = await this.redisClient.keys(prefixedPattern);
      
      // 프리픽스 제거하여 반환
      return keys.map(key => key.startsWith(this.prefix) 
        ? key.substring(this.prefix.length) 
        : key);
    } catch (error) {
      console.error(`Redis 키 목록 조회 오류 (${pattern}):`, error);
      return [];
    }
  }

  /**
   * 파이프라인을 사용한 일괄 작업
   * @param {Function} callback - 파이프라인 콜백 함수
   * @returns {Promise<Array>} 파이프라인 결과
   */
  async pipeline(callback) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const pipeline = this.redisClient.pipeline();
      await callback(pipeline, this.prefix);
      return await pipeline.exec();
    } catch (error) {
      console.error('Redis 파이프라인 실행 오류:', error);
      return [];
    }
  }

  /**
   * 트랜잭션을 사용한 원자적 작업
   * @param {Function} callback - 트랜잭션 콜백 함수
   * @returns {Promise<Array>} 트랜잭션 결과
   */
  async multi(callback) {
    if (!this.isConnected()) {
      await this.connect();
    }
    
    try {
      const multi = this.redisClient.multi();
      await callback(multi, this.prefix);
      return await multi.exec();
    } catch (error) {
      console.error('Redis 트랜잭션 실행 오류:', error);
      return [];
    }
  }

  /**
   * 연결이 활성화되어 있는지 확인
   * @returns {boolean} 연결 상태
   */
  isConnected() {
    return this.connected && this.redisClient !== null;
  }

  /**
   * 연결 상태 확인
   * @returns {Promise<boolean>} 연결 상태
   */
  async checkConnection() {
    if (!this.redisClient) {
      return false;
    }
    
    try {
      await this.redisClient.ping();
      return true;
    } catch (error) {
      return false;
    }
  }

  /**
   * 연결 종료
   * @returns {Promise<void>}
   */
  async disconnect() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    
    if (this.redisClient) {
      try {
        await this.redisClient.quit();
        console.log('Redis 연결 정상 종료');
      } catch (error) {
        console.error('Redis 연결 종료 오류:', error);
        // 강제 종료
        this.redisClient.disconnect();
      } finally {
        this.redisClient = null;
        this.connected = false;
        this.reconnecting = false;
      }
    }
  }
}

module.exports = { ElastiCacheService }; 