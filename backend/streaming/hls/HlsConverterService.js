/**
 * HLS 변환 서비스
 * FFmpeg를 사용한 WebRTC/RTP → HLS 변환
 * AWS S3 버킷으로 세그먼트 자동 업로드 기능 포함
 */

const fs = require('fs');
const path = require('path');
const { promisify } = require('util');
const { spawn } = require('child_process');
const { 
  S3Client, 
  PutObjectCommand,
  DeleteObjectCommand,
  ListObjectsV2Command,
  HeadBucketCommand 
} = require('@aws-sdk/client-s3');
const { 
  CloudFrontClient, 
  CreateInvalidationCommand 
} = require('@aws-sdk/client-cloudfront');
const crypto = require('crypto');
const mime = require('mime-types');
const config = require('../mediasoup/config');
const { ElastiCacheService } = require('../aws/elastic_cache_service');

// Promisify fs 함수
const mkdir = promisify(fs.mkdir);
const access = promisify(fs.access);
const rm = promisify(fs.rm);
const readFile = promisify(fs.readFile);
const readdir = promisify(fs.readdir);
const stat = promisify(fs.stat);

class HlsConverterService {
  /**
   * HLS 변환 서비스 초기화
   */
  constructor() {
    // 변환 프로세스 관리
    this.conversions = new Map();
    
    // S3 클라이언트 초기화 (S3 업로드가 활성화된 경우)
    if (config.aws.s3.enabled) {
      this.s3Client = new S3Client({
        region: config.aws.region,
        credentials: {
          accessKeyId: config.aws.s3.accessKeyId,
          secretAccessKey: config.aws.s3.secretAccessKey
        },
        maxAttempts: 3 // 재시도 설정
      });
      
      // CloudFront 클라이언트 초기화 (CloudFront가 활성화된 경우)
      if (config.aws.cloudFront.enabled) {
        this.cloudFrontClient = new CloudFrontClient({
          region: config.aws.region,
          credentials: {
            accessKeyId: config.aws.s3.accessKeyId,
            secretAccessKey: config.aws.s3.secretAccessKey
          }
        });
      }
      
      // ElastiCache 서비스 초기화
      if (config.aws.elastiCache.enabled) {
        this.redis = new ElastiCacheService();
        this.redis.connect().catch(err => {
          console.error('Redis 연결 실패:', err);
        });
      }
      
      // S3 동기화 실패 시 로컬 폴백 설정
      this.localFallback = true;
      
      // S3 버킷 접근성 확인
      this._validateS3Bucket();
      
      console.log('AWS S3 및 CloudFront 통합이 활성화되었습니다.');
    }
    
    // 세그먼트 자동 정리 인터벌
    this.cleanupInterval = null;
    
    // 초기화 완료 시 세그먼트 정리 시작
    this._startCleanupInterval();
  }
  
  /**
   * S3 버킷 접근성 확인
   * @private
   */
  async _validateS3Bucket() {
    if (!this.s3Client) return;
    
    try {
      await this.s3Client.send(new HeadBucketCommand({
        Bucket: config.aws.s3.bucket
      }));
      console.log(`S3 버킷 '${config.aws.s3.bucket}' 접근 확인 완료`);
    } catch (error) {
      console.error(`S3 버킷 '${config.aws.s3.bucket}' 접근 실패:`, error);
      console.warn('로컬 스토리지로 폴백됩니다.');
    }
  }

  /**
   * 룸의 HLS 변환 시작
   * @param {string} roomId - 룸 ID
   * @param {Object} router - Mediasoup 라우터
   * @param {Object} producer - Mediasoup 프로듀서
   * @returns {Promise<Object>} HLS 변환 정보
   */
  async startConversion(roomId, router, producer) {
    try {
      // 기존 변환 확인
      const conversionId = `${roomId}-${producer.id}`;
      if (this.conversions.has(conversionId)) {
        console.log(`기존 변환 사용: ${conversionId}`);
        return this.conversions.get(conversionId);
      }
      
      console.log(`HLS 변환 시작: ${conversionId} (${producer.kind})`);
      
      // 출력 디렉토리 설정
      const outputDir = path.join(config.hls.outputPath, roomId, producer.id);
      await mkdir(outputDir, { recursive: true });
      
      // RTP 전송 설정
      const rtpTransport = await router.createPlainTransport({
        listenIp: config.mediasoup.plainTransportOptions.listenIp,
        rtcpMux: true
      });
      
      // RTP 컨슈머 생성
      const rtpConsumer = await producer.consume({
        producerId: producer.id,
        rtpCapabilities: router.rtpCapabilities,
        paused: false
      });
      
      // RTP 트랜스포트 연결
      await rtpTransport.connect({
        ip: '127.0.0.1',
        port: rtpConsumer.rtpParameters.encodings[0].ssrc
      });
      
      // FFmpeg 프로세스 시작
      const rtpPort = rtpConsumer.rtpParameters.encodings[0].ssrc;
      const ffmpegProcess = await this._spawnFfmpeg(
        roomId,
        rtpPort,
        '127.0.0.1',
        producer.kind,
        outputDir
      );
      
      // HLS URL 결정
      let hlsUrl;
      if (config.aws.cloudFront.enabled && config.aws.cloudFront.domain) {
        hlsUrl = `https://${config.aws.cloudFront.domain}/hls/${roomId}/${producer.id}/playlist.m3u8`;
      } else if (config.aws.s3.enabled) {
        hlsUrl = `https://${config.aws.s3.bucket}.s3.${config.aws.region}.amazonaws.com/hls/${roomId}/${producer.id}/playlist.m3u8`;
      } else {
        hlsUrl = `${config.hls.baseUrl}/${roomId}/${producer.id}/playlist.m3u8`;
      }
      
      // 변환 정보 저장
      const conversion = {
        id: conversionId,
        roomId,
        producerId: producer.id,
        outputDir,
        transport: rtpTransport,
        consumer: rtpConsumer,
        ffmpegProcess,
        hlsUrl,
        startedAt: new Date(),
        s3Uploading: config.aws.s3.enabled
      };
      
      this.conversions.set(conversionId, conversion);
      
      // S3 파일 업로드 워커 시작 (필요한 경우)
      if (config.aws.s3.enabled) {
        this._startS3Uploader(conversion);
      }
      
      // S3 메타데이터 저장 (Redis에 저장)
      if (this.redis && this.redis.isConnected()) {
        await this.redis.set(
          `hls:conversion:${conversionId}`,
          JSON.stringify({
            id: conversionId,
            roomId,
            producerId: producer.id,
            hlsUrl,
            startedAt: conversion.startedAt,
            mediaKind: producer.kind
          }),
          // 24시간 TTL
          60 * 60 * 24
        );
      }
      
      // FFmpeg 종료 이벤트 처리
      ffmpegProcess.on('exit', (code, signal) => {
        console.log(`FFmpeg 프로세스 종료: ${conversionId} (코드: ${code}, 시그널: ${signal})`);
        if (code !== 0 && !this._closed) {
          console.warn(`FFmpeg 비정상 종료. 재시작 시도 중...`);
          // 10초 후 FFmpeg 재시작 시도
          setTimeout(() => {
            if (this.conversions.has(conversionId) && !this._closed) {
              this._restartFFmpeg(conversion).catch(err => {
                console.error('FFmpeg 재시작 실패:', err);
              });
            }
          }, 10000);
        }
      });
      
      return conversion;
      
    } catch (error) {
      console.error(`HLS 변환 시작 실패 (${roomId}):`, error);
      throw error;
    }
  }

  /**
   * FFmpeg 프로세스 재시작
   * @param {Object} conversion - 변환 정보
   * @returns {Promise<void>}
   * @private
   */
  async _restartFFmpeg(conversion) {
    try {
      // 기존 프로세스 정리
      if (conversion.ffmpegProcess) {
        conversion.ffmpegProcess.kill('SIGKILL');
      }
      
      // FFmpeg 다시 시작
      const rtpPort = conversion.consumer.rtpParameters.encodings[0].ssrc;
      conversion.ffmpegProcess = await this._spawnFfmpeg(
        conversion.roomId,
        rtpPort,
        '127.0.0.1',
        conversion.consumer.kind,
        conversion.outputDir
      );
      
      console.log(`FFmpeg 프로세스 재시작됨: ${conversion.id}`);
      
      // 종료 이벤트 다시 등록
      conversion.ffmpegProcess.on('exit', (code, signal) => {
        console.log(`FFmpeg 프로세스 종료: ${conversion.id} (코드: ${code}, 시그널: ${signal})`);
        if (code !== 0 && !this._closed) {
          console.warn(`FFmpeg 비정상 종료. 재시작 시도 중...`);
          setTimeout(() => {
            if (this.conversions.has(conversion.id) && !this._closed) {
              this._restartFFmpeg(conversion).catch(err => {
                console.error('FFmpeg 재시작 실패:', err);
              });
            }
          }, 10000);
        }
      });
      
    } catch (error) {
      console.error(`FFmpeg 재시작 실패 (${conversion.id}):`, error);
      throw error;
    }
  }
  
  /**
   * S3 업로더 시작
   * @param {Object} conversion - 변환 정보
   * @private
   */
  _startS3Uploader(conversion) {
    const { roomId, producerId, outputDir } = conversion;
    let timeout;
    
    const uploadLoop = async () => {
      if (!this.conversions.has(conversion.id) || this._closed) {
        return;
      }
      
      try {
        const files = await readdir(outputDir);
        
        // 새 파일 업로드
        const uploadPromises = files
          .filter(file => file.endsWith('.ts') || file.endsWith('.m3u8'))
          .map(async file => {
            const localPath = path.join(outputDir, file);
            const s3Key = `hls/${roomId}/${producerId}/${file}`;
            
            try {
              // 파일 읽기
              const fileContent = await readFile(localPath);
              
              // 컨텐츠 타입 결정
              const contentType = file.endsWith('.m3u8') 
                ? 'application/vnd.apple.mpegurl'
                : 'video/MP2T';
              
              // S3에 업로드
              await this.s3Client.send(new PutObjectCommand({
                Bucket: config.aws.s3.bucket,
                Key: s3Key,
                Body: fileContent,
                ContentType: contentType,
                CacheControl: file.endsWith('.m3u8') 
                  ? 'max-age=5' // 재생 목록은 자주 갱신
                  : 'max-age=3600' // 세그먼트는 더 오래 캐싱
              }));
              
              // 로컬 폴백이 비활성화된 경우 로컬 파일 삭제
              if (!this.localFallback && file.endsWith('.ts') && !file.includes('init')) {
                await rm(localPath);
              }
              
            } catch (error) {
              console.error(`S3 업로드 실패 (${file}):`, error);
            }
          });
        
        await Promise.all(uploadPromises);
        
      } catch (error) {
        if (error.code !== 'ENOENT') {
          console.error(`S3 업로드 루프 오류 (${conversion.id}):`, error);
        }
      }
      
      // 다음 실행 예약 (5초마다)
      timeout = setTimeout(uploadLoop, 5000);
    };
    
    // 첫 실행
    uploadLoop();
    
    // timeout 참조 저장
    conversion.s3UploaderTimeout = timeout;
  }
  
  /**
   * CloudFront 캐시 무효화
   * @param {string} roomId - 룸 ID
   * @param {string} producerId - 프로듀서 ID
   * @returns {Promise<void>}
   */
  async invalidateCloudFrontCache(roomId, producerId) {
    if (!this.cloudFrontClient || !config.aws.cloudFront.enabled) {
      return;
    }
    
    try {
      const paths = [
        `/hls/${roomId}/${producerId}/playlist.m3u8`,
        `/hls/${roomId}/${producerId}/*`
      ];
      
      await this.cloudFrontClient.send(new CreateInvalidationCommand({
        DistributionId: config.aws.cloudFront.distributionId,
        InvalidationBatch: {
          CallerReference: `hls-invalidation-${Date.now()}`,
          Paths: {
            Quantity: paths.length,
            Items: paths
          }
        }
      }));
      
      console.log(`CloudFront 캐시 무효화 요청 완료: ${roomId}/${producerId}`);
    } catch (error) {
      console.error('CloudFront 캐시 무효화 실패:', error);
    }
  }

  /**
   * 룸의 HLS 변환 중지
   * @param {string} roomId - 룸 ID
   * @param {string} producerId - 프로듀서 ID
   * @returns {Promise<void>}
   */
  async stopConversion(roomId, producerId) {
    const conversionId = `${roomId}-${producerId}`;
    
    if (!this.conversions.has(conversionId)) {
      console.warn(`존재하지 않는 변환 중지 요청: ${conversionId}`);
      return;
    }
    
    const conversion = this.conversions.get(conversionId);
    
    try {
      console.log(`HLS 변환 중지: ${conversionId}`);
      
      // FFmpeg 프로세스 종료
      if (conversion.ffmpegProcess) {
        conversion.ffmpegProcess.kill('SIGKILL');
      }
      
      // S3 업로더 타이머 정리
      if (conversion.s3UploaderTimeout) {
        clearTimeout(conversion.s3UploaderTimeout);
      }
      
      // Mediasoup 리소스 정리
      if (conversion.consumer) {
        conversion.consumer.close();
      }
      
      if (conversion.transport) {
        conversion.transport.close();
      }
      
      // Redis에서 메타데이터 삭제
      if (this.redis && this.redis.isConnected()) {
        await this.redis.del(`hls:conversion:${conversionId}`);
      }
      
      // 변환 목록에서 제거
      this.conversions.delete(conversionId);
      
      console.log(`HLS 변환 중지 완료: ${conversionId}`);
      
    } catch (error) {
      console.error(`HLS 변환 중지 중 오류 (${conversionId}):`, error);
    }
  }

  /**
   * FFmpeg 명령 실행
   * @param {string} roomId - 룸 ID
   * @param {number} rtpPort - RTP 포트
   * @param {string} rtpHost - RTP 호스트
   * @param {string} mediaKind - 미디어 종류 (audio 또는 video)
   * @param {string} outputDir - 출력 디렉토리
   * @returns {Promise<import('child_process').ChildProcess>} FFmpeg 프로세스
   * @private
   */
  _spawnFfmpeg(roomId, rtpPort, rtpHost, mediaKind, outputDir) {
    return new Promise((resolve, reject) => {
      // FFmpeg 명령 인자 구성
      const args = [
        // 입력 옵션
        '-re',
        '-protocol_whitelist', 'file,rtp,udp',
        '-fflags', '+genpts',
        
        // RTP 수신 설정
        '-i', `rtp://${rtpHost}:${rtpPort}`,
        
        // 비디오 인코딩 설정 (비디오인 경우)
        ...(mediaKind === 'video' ? [
          '-c:v', 'libx264',
          '-preset', config.hls.videoPreset || 'veryfast',
          '-crf', (config.hls.videoCrf || 23).toString(),
          '-profile:v', 'main',
          '-level', '4.1',
          '-tune', 'zerolatency',
          '-pix_fmt', 'yuv420p',
          '-r', '30',
          // 저지연을 위한 GOP 크기 축소 (10)
          '-g', (config.hls.gopSize || 10).toString(),
          '-keyint_min', (config.hls.gopSize || 10).toString(),
          // 저지연 스트리밍 최적화
          '-sc_threshold', '0',
          // 적응형 비트레이트를 위한 버퍼 설정
          '-bufsize', '1500k',
          '-maxrate', '2500k',
          // fMP4 및 저지연 최적화
          '-movflags', 'frag_keyframe+empty_moov+default_base_moof+faststart'
        ] : []),
        
        // 오디오 인코딩 설정
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '48000',
        
        // HLS 출력 설정
        '-f', 'hls',
        // 마이크로 세그먼트 도입 (0.5초)
        '-hls_time', (config.hls.segmentDuration || 0.5).toString(),
        '-hls_list_size', (config.hls.listSize || 4).toString(),
        '-hls_flags', 'delete_segments+append_list+discont_start+program_date_time+omit_endlist',
        
        // fMP4 세그먼트 적용
        '-hls_segment_type', config.hls.useFragmentedMp4 ? 'fmp4' : 'mpegts',
      ];
      
      // fMP4 관련 설정 (사용하는 경우)
      if (config.hls.useFragmentedMp4) {
        args.push(
          '-hls_fmp4_init_filename', 'init.mp4',
          // CMAF 호환성 (Apple 기기 최적화)
          '-tag:v', 'hvc1'
        );
      } else {
        args.push(
          '-hls_segment_filename', path.join(outputDir, 'segment_%03d.ts')
        );
      }
      
      // 공통 HLS 설정 추가
      args.push(
        // 저지연 HLS를 위한 추가 옵션
        '-hls_init_time', '0.5',
        '-hls_playlist_type', 'event',
        '-start_number', '0',
        '-hls_allow_cache', '0',
        '-max_muxing_queue_size', '1024',
        '-vsync', '1',
        // 오디오/비디오 동기화 최적화
        '-async', '1',
        // 생성된 HLS 플레이리스트 경로
        path.join(outputDir, 'playlist.m3u8')
      );
      
      // FFmpeg 시작
      const ffmpegProcess = spawn(config.hls.ffmpegPath || 'ffmpeg', args);
      
      // 로그 수집
      ffmpegProcess.stderr.on('data', (data) => {
        const logData = data.toString().trim();
        
        // 중요 오류 확인 및 출력 제한
        if (logData.includes('Error') || logData.includes('error') || logData.includes('failed')) {
          console.error(`FFmpeg 오류 (${roomId}): ${logData}`);
        } else if (logData.includes('segment') && (logData.includes('.ts') || logData.includes('.mp4'))) {
          // 세그먼트 생성 로그
          console.log(`FFmpeg: 새 세그먼트 생성 (${roomId})`);
        }
      });
      
      // FFmpeg 프로세스가 바로 종료되면 오류 발생
      const errorTimeout = setTimeout(() => {
        ffmpegProcess.removeListener('exit', earlyExitHandler);
      }, 3000);
      
      const earlyExitHandler = (code) => {
        clearTimeout(errorTimeout);
        reject(new Error(`FFmpeg 프로세스가 조기 종료됨 (코드: ${code})`));
      };
      
      ffmpegProcess.once('exit', earlyExitHandler);
      
      // FFmpeg 프로세스 종료 핸들러 (일정 시간 후)
      ffmpegProcess.on('close', (code) => {
        // 정상 종료된 경우 무시
        if (errorTimeout._destroyed) return;
        
        // 비정상 종료된 경우 재시작 로직
        if (code !== 0 && code !== null) {
          console.error(`FFmpeg 프로세스 비정상 종료 (${roomId}), 코드: ${code}`);
          console.log(`FFmpeg 프로세스 재시작 시도 (${roomId})...`);
          
          // 2초 후 재시작 시도
          setTimeout(() => {
            this._spawnFfmpeg(roomId, rtpPort, rtpHost, mediaKind, outputDir)
              .then(newProcess => {
                console.log(`FFmpeg 프로세스 재시작 성공 (${roomId})`);
              })
              .catch(error => {
                console.error(`FFmpeg 재시작 실패 (${roomId}):`, error);
              });
          }, 2000);
        }
      });
      
      // 3초 후에 프로세스가 종료되지 않았다면 성공으로 간주
      ffmpegProcess.once('spawn', () => {
        setTimeout(() => {
          clearTimeout(errorTimeout);
          ffmpegProcess.removeListener('exit', earlyExitHandler);
          resolve(ffmpegProcess);
        }, 1000);
      });
    });
  }

  /**
   * 세그먼트 정리 간격 시작
   * @private
   */
  _startCleanupInterval() {
    // 기존 인터벌 정리
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
    }
    
    // AWS S3 세그먼트 정리
    const startS3Cleanup = async () => {
      if (!this.s3Client || !config.aws.s3.enabled) {
        return;
      }
      
      try {
        // 만료된 HLS 세그먼트 찾기
        const expirationTimestamp = Date.now() - (config.aws.s3.expirationDays * 86400 * 1000);
        
        // S3 객체 나열
        const listResponse = await this.s3Client.send(new ListObjectsV2Command({
          Bucket: config.aws.s3.bucket,
          Prefix: 'hls/',
          MaxKeys: 1000
        }));
        
        if (!listResponse.Contents || listResponse.Contents.length === 0) {
          return;
        }
        
        // 만료된 객체 필터링
        const expiredObjects = listResponse.Contents.filter(obj => 
          obj.LastModified && obj.LastModified.getTime() < expirationTimestamp
        );
        
        if (expiredObjects.length === 0) {
          return;
        }
        
        console.log(`${expiredObjects.length}개의 만료된 HLS 세그먼트 삭제 중...`);
        
        // 100개씩 나누어 삭제
        for (let i = 0; i < expiredObjects.length; i += 100) {
          const batch = expiredObjects.slice(i, i + 100);
          
          await Promise.all(batch.map(obj => 
            this.s3Client.send(new DeleteObjectCommand({
              Bucket: config.aws.s3.bucket,
              Key: obj.Key
            }))
          ));
        }
        
        console.log(`${expiredObjects.length}개의 만료된 HLS 세그먼트 삭제 완료`);
        
      } catch (error) {
        console.error('S3 세그먼트 정리 중 오류:', error);
      }
    };
    
    // 로컬 세그먼트 정리
    const startLocalCleanup = async () => {
      try {
        const baseDir = config.hls.outputPath;
        
        // 폴더가 존재하는지 확인
        try {
          await access(baseDir);
        } catch {
          return;
        }
        
        // 현재 활성 룸 ID 모음
        const activeRoomIds = new Set(
          Array.from(this.conversions.values()).map(conv => conv.roomId)
        );
        
        // 기본 디렉토리 내 모든 룸 디렉토리 읽기
        const roomDirs = await readdir(baseDir);
        
        for (const roomDir of roomDirs) {
          const roomPath = path.join(baseDir, roomDir);
          const roomStat = await stat(roomPath);
          
          // 디렉토리만 처리
          if (!roomStat.isDirectory()) {
            continue;
          }
          
          // 활성 룸이 아니고 24시간 이상 지난 경우 삭제
          if (!activeRoomIds.has(roomDir)) {
            const dirAge = Date.now() - roomStat.mtime.getTime();
            
            if (dirAge > 24 * 60 * 60 * 1000) {
              console.log(`오래된 HLS 디렉토리 삭제: ${roomPath}`);
              await rm(roomPath, { recursive: true, force: true });
            }
          }
        }
      } catch (error) {
        console.error('로컬 세그먼트 정리 중 오류:', error);
      }
    };
    
    // 2시간마다 정리 작업 실행
    this.cleanupInterval = setInterval(async () => {
      await Promise.all([
        startS3Cleanup(),
        startLocalCleanup()
      ]);
    }, 2 * 60 * 60 * 1000);
    
    // 초기 정리 작업 실행
    setTimeout(async () => {
      await Promise.all([
        startS3Cleanup(),
        startLocalCleanup()
      ]);
    }, 5 * 60 * 1000);
  }
  
  /**
   * 서비스 종료
   */
  async close() {
    this._closed = true;
    
    // 정리 인터벌 중지
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
      this.cleanupInterval = null;
    }
    
    // 모든 변환 중지
    const stopPromises = Array.from(this.conversions.values()).map(conversion => 
      this.stopConversion(conversion.roomId, conversion.producerId)
    );
    
    await Promise.all(stopPromises);
    
    // Redis 연결 종료
    if (this.redis && this.redis.isConnected()) {
      await this.redis.disconnect();
    }
    
    console.log('HLS 변환 서비스가 종료되었습니다.');
  }
}

module.exports = HlsConverterService; 