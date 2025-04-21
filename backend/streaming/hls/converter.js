/**
 * HLS 변환 모듈
 * WebRTC 스트림을 HLS로 변환하는 기능 제공
 * 보안 및 성능 최적화 버전
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { promisify } = require('util');
const config = require('../mediasoup/config');
const crypto = require('crypto');
const { 
  S3Client, 
  PutObjectCommand,
  DeleteObjectCommand,
  ListObjectsV2Command 
} = require('@aws-sdk/client-s3');

// promisify 비동기 함수들
const mkdir = promisify(fs.mkdir);
const access = promisify(fs.access);
const unlink = promisify(fs.unlink);
const readdir = promisify(fs.readdir);
const stat = promisify(fs.stat);
const readFile = promisify(fs.readFile);
const rm = promisify(fs.rm);

// FFmpeg 프로세스를 저장하는 맵
const ffmpegProcesses = new Map();
// 프로듀서 정보를 저장하는 맵
const producers = new Map();
// RTP 전송 포트 추적
const usedPorts = new Set();
// S3 클라이언트 (설정된 경우)
let s3Client = null;
// 포트 범위 설정
const minRtpPort = 10000;
const maxRtpPort = 59999;
// 보안 관련 설정
const securityOptions = {
  useSecureIds: true,
  logSensitiveInfo: false,
  fileCleanupAge: 30 * 60 * 1000, // 30분
};

// S3 클라이언트 초기화
if (config.aws && config.aws.s3 && config.aws.s3.enabled) {
  s3Client = new S3Client({
    region: config.aws.s3.region,
    credentials: {
      accessKeyId: config.aws.s3.accessKeyId,
      secretAccessKey: config.aws.s3.secretAccessKey,
    },
    maxAttempts: 3
  });
  
  console.log('S3 통합이 활성화되었습니다.');
}

/**
 * 사용 가능한 RTP 포트 할당
 * @returns {number} 사용 가능한 RTP 포트
 */
function allocateRtpPort() {
  // 랜덤 포트 선택 (보안 강화)
  let attempts = 0;
  let port;
  
  do {
    // 포트 범위 내에서 랜덤하게 선택
    port = Math.floor(Math.random() * (maxRtpPort - minRtpPort)) + minRtpPort;
    // 포트가 짝수인지 확인 (RTP 관례)
    if (port % 2 !== 0) port++;
    
    attempts++;
    // 최대 100번 시도 후 순차적 검색으로 전환
    if (attempts > 100) {
      port = minRtpPort;
      while (usedPorts.has(port) && port <= maxRtpPort) {
        port += 2;
      }
      break;
    }
  } while (usedPorts.has(port) && port <= maxRtpPort);
  
  if (port > maxRtpPort) {
    throw new Error('사용 가능한 RTP 포트가 없습니다');
  }
  
  usedPorts.add(port);
  return port;
}

/**
 * RTP 포트 해제
 * @param {number} port - 해제할 RTP 포트
 */
function releaseRtpPort(port) {
  usedPorts.delete(port);
}

/**
 * 보안 ID 생성
 * @param {string} prefix - ID 접두사
 * @returns {string} 생성된 보안 ID
 */
function generateSecureId(prefix = '') {
  const randomBytes = crypto.randomBytes(16);
  const secureId = randomBytes.toString('hex');
  return prefix ? `${prefix}-${secureId}` : secureId;
}

/**
 * WebRTC 미디어 프로듀서를 HLS로 변환
 * @param {Object} producer - mediasoup 프로듀서 객체
 * @param {string} roomId - 방 식별자
 * @returns {Promise<Object>} HLS 스트림 정보
 */
async function addProducer(producer, roomId) {
  try {
    // 보안 검증: 프로듀서와 룸ID 유효성 확인
    if (!producer || !producer.id || !roomId) {
      throw new Error('유효하지 않은 프로듀서 또는 룸ID');
    }
    
    // XSS 방지를 위한 입력 검증
    const sanitizedRoomId = roomId.replace(/[^\w-]/g, '');
    if (sanitizedRoomId !== roomId) {
      throw new Error('룸ID에 유효하지 않은 문자가 포함되어 있습니다');
    }
    
    // 고유 ID 생성 (보안 향상)
    const secureId = securityOptions.useSecureIds 
      ? generateSecureId()
      : crypto.randomBytes(8).toString('hex');
    
    const outputId = `${sanitizedRoomId}-${secureId}`;
    
    // 이미 등록된 프로듀서인지 확인
    if (producers.has(producer.id)) {
      console.log(`이미 등록된 프로듀서 (ID: ${producer.id})`);
      return producers.get(producer.id);
    }
    
    // 프로듀서 정보 저장
    const producerInfo = {
      id: producer.id,
      kind: producer.kind,
      roomId: sanitizedRoomId,
      outputId,
      createdAt: Date.now(),
      hlsUrl: null
    };
    
    producers.set(producer.id, producerInfo);
    
    // 출력 디렉토리 생성
    const outputDir = path.join(config.hls.outputPath, outputId);
    try {
      await mkdir(outputDir, { recursive: true });
    } catch (err) {
      console.error(`출력 디렉토리 생성 실패: ${err.message}`);
      throw err;
    }
    
    // 비디오 프로듀서만 처리
    if (producer.kind === 'video') {
      // RTP 미디어 서버로 리디렉션
      const rtpInfo = await setupRtpTransport(producer, sanitizedRoomId, outputId);
      producerInfo.rtpInfo = rtpInfo;
      
      // HLS URL 설정
      if (config.aws && config.aws.cloudFront && config.aws.cloudFront.domain) {
        producerInfo.hlsUrl = `https://${config.aws.cloudFront.domain}/hls/${outputId}/playlist.m3u8`;
      } else {
        producerInfo.hlsUrl = `${config.hls.baseUrl}/${outputId}/playlist.m3u8`;
      }
    }
    
    // 프로듀서 종료 이벤트 연결
    producer.observer.once('close', () => {
      removeProducer(producer.id).catch(err => {
        console.error(`프로듀서 제거 중 오류: ${err.message}`);
      });
    });
    
    console.log(`프로듀서 (${producer.id}, ${producer.kind}) HLS 변환 시작`);
    return producerInfo;
  } catch (error) {
    console.error('프로듀서 추가 오류:', error);
    throw error;
  }
}

/**
 * RTP 전송 설정
 * @param {Object} producer - mediasoup 프로듀서 객체
 * @param {string} roomId - 방 식별자
 * @param {string} outputId - 출력 식별자
 * @returns {Promise<Object>} RTP 설정 정보
 */
async function setupRtpTransport(producer, roomId, outputId) {
  try {
    // RTP 포트 할당
    const rtpPort = allocateRtpPort();
    
    // 출력 디렉토리
    const outputDir = path.join(config.hls.outputPath, outputId);
    
    // FFmpeg 프로세스 시작
    const ffmpegProcess = await startFFmpeg(rtpPort, outputDir, producer.id);
    ffmpegProcesses.set(producer.id, ffmpegProcess);
    
    // 보안 검증 추가: producer 종료 이벤트 핸들링
    producer.on('transportclose', () => {
      console.log(`프로듀서 전송 종료됨 (ID: ${producer.id})`);
      removeProducer(producer.id);
    });
    
    producer.on('producerclose', () => {
      console.log(`프로듀서 종료됨 (ID: ${producer.id})`);
      removeProducer(producer.id);
    });
    
    // S3 자동 업로드 설정 (구성된 경우)
    if (s3Client) {
      setupS3Upload(outputDir, outputId);
    }
    
    return {
      rtpPort,
      rtpHost: '127.0.0.1',
      outputDir
    };
  } catch (error) {
    console.error('RTP 전송 설정 오류:', error);
    throw error;
  }
}

/**
 * HLS 세그먼트 S3 업로드 설정
 * @param {string} outputDir - 출력 디렉토리
 * @param {string} outputId - 출력 식별자
 */
async function setupS3Upload(outputDir, outputId) {
  if (!s3Client || !config.aws.s3.enabled) {
    return;
  }
  
  // 디렉토리 변경 감지 함수
  const uploadNewFiles = async () => {
    try {
      // 디렉토리 내 파일 목록 확인
      const files = await readdir(outputDir);
      
      // 각 파일에 대해 처리
      for (const file of files) {
        if (!file.endsWith('.m3u8') && !file.endsWith('.ts')) {
          continue; // 관련 없는 파일 스킵
        }
        
        const filePath = path.join(outputDir, file);
        
        try {
          // 파일이 완전히 기록되었는지 확인
          await access(filePath, fs.constants.R_OK);
          
          // 파일이 아직 처리 중인지 확인하기 위해 최종 수정 시간 확인
          const fileStat = await stat(filePath);
          const now = Date.now();
          const fileModTime = fileStat.mtime.getTime();
          
          // 파일이 최근 0.5초 내에 수정되었다면 아직 완전히 기록되지 않았을 수 있음
          if (now - fileModTime < 500) {
            continue;
          }
          
          // 파일 MIME 유형 결정
          let contentType = 'application/octet-stream';
          if (file.endsWith('.m3u8')) {
            contentType = 'application/vnd.apple.mpegurl';
          } else if (file.endsWith('.ts')) {
            contentType = 'video/mp2t';
          }
          
          // 파일 내용 읽기
          const fileContent = await readFile(filePath);
          
          // S3에 업로드
          const s3Key = `hls/${outputId}/${file}`;
          const uploadParams = {
            Bucket: config.aws.s3.bucket,
            Key: s3Key,
            Body: fileContent,
            ContentType: contentType,
            CacheControl: file.endsWith('.m3u8') 
              ? 'max-age=3' // 플레이리스트는 짧은 캐시 TTL
              : 'max-age=31536000' // 세그먼트는 1년 캐시
          };
          
          await s3Client.send(new PutObjectCommand(uploadParams));
          
          if (!securityOptions.logSensitiveInfo) {
            console.log(`파일 업로드 완료: ${file}`);
          } else {
            console.log(`파일 ${file} S3에 업로드 완료 (키: ${s3Key})`);
          }
          
          // TS 세그먼트 파일은 업로드 후 로컬에서 삭제 가능 (옵션)
          // if (file.endsWith('.ts') && config.hls.deleteAfterUpload) {
          //   await unlink(filePath);
          // }
        } catch (error) {
          console.error(`파일 접근 또는 업로드 오류 (${file}):`, error);
        }
      }
    } catch (error) {
      console.error(`S3 업로드 모니터링 오류:`, error);
    }
  };
  
  // 파일 시스템 감시 설정
  const watcher = fs.watch(outputDir, (eventType, filename) => {
    if (!filename) return;
    
    // 새 파일이 생성되면 약간의 지연 후 업로드 시도
    if (eventType === 'rename' || eventType === 'change') {
      if (filename.endsWith('.m3u8') || filename.endsWith('.ts')) {
        setTimeout(() => {
          uploadNewFiles().catch(err => {
            console.error('파일 업로드 실패:', err);
          });
        }, 500);
      }
    }
  });
  
  // 전체 디렉토리 초기 업로드 (기존 파일)
  uploadNewFiles().catch(err => {
    console.error('초기 파일 업로드 실패:', err);
  });
  
  // 감시자 참조 저장
  const producerData = Array.from(producers.values())
    .find(p => p.outputId === outputId);
  
  if (producerData) {
    producerData.watcher = watcher;
  }
  
  // 정기적인 업로드 확인 (파일 시스템 이벤트 누락 방지)
  const uploadInterval = setInterval(() => {
    uploadNewFiles().catch(err => {
      console.error('정기 파일 업로드 실패:', err);
    });
  }, 10000); // 10초마다 확인
  
  // 인터벌 참조 저장
  if (producerData) {
    producerData.uploadInterval = uploadInterval;
  }
}

/**
 * FFmpeg를 사용하여 RTP 스트림을 HLS로 변환
 * @param {number} rtpPort - RTP 포트
 * @param {string} outputDir - 출력 디렉토리
 * @param {string} producerId - 프로듀서 ID
 * @returns {Promise<import('child_process').ChildProcess>} FFmpeg 프로세스
 */
async function startFFmpeg(rtpPort, outputDir, producerId) {
  try {
    // 최적의 초저지연 FFmpeg 설정 적용
    const ffmpegArgs = [
      // 입력 설정
      '-re',
      '-protocol_whitelist', 'file,rtp,udp',
      '-fflags', '+genpts',
      '-i', `rtp://127.0.0.1:${rtpPort}`,
      
      // 비디오 인코딩 설정
      '-c:v', 'libx264',
      '-preset', config.hls.videoPreset || 'veryfast',
      '-tune', 'zerolatency',
      '-profile:v', 'main',
      '-level', '4.1',
      '-crf', (config.hls.videoCrf || 23).toString(),
      // GOP 설정 (10으로 축소하여 저지연 최적화)
      '-g', (config.hls.gopSize || 10).toString(),
      '-keyint_min', (config.hls.gopSize || 10).toString(),
      '-sc_threshold', '0',
      '-r', '30',
      '-pix_fmt', 'yuv420p',
      // 적응형 비트레이트를 위한 멀티패스 버퍼 설정
      '-bufsize', '1500k',
      '-maxrate', '2500k',
      // 저지연 옵션
      '-movflags', 'frag_keyframe+empty_moov+default_base_moof+faststart',
      
      // 오디오 인코딩 설정
      '-c:a', 'aac',
      '-b:a', '128k',
      '-ar', '48000',
      
      // HLS 출력 설정
      '-f', 'hls',
      // 마이크로 세그먼트 (0.5초)로 설정하여 지연 시간 최소화
      '-hls_time', (config.hls.segmentDuration || 0.5).toString(),
      '-hls_list_size', (config.hls.listSize || 4).toString(),
      '-hls_flags', 'delete_segments+append_list+discont_start+program_date_time+omit_endlist',
      // fMP4 세그먼트 타입 사용 (브라우저 호환성 향상)
      '-hls_segment_type', config.hls.useFragmentedMp4 ? 'fmp4' : 'mpegts',
      config.hls.useFragmentedMp4 
        ? '-hls_fmp4_init_filename' 
        : '-hls_segment_filename', 
      config.hls.useFragmentedMp4 
        ? `${outputDir}/init.mp4` 
        : `${outputDir}/segment_%03d.ts`,
      
      // fMP4를 사용하지 않는 경우에만 세그먼트 파일명 설정
      ...(config.hls.useFragmentedMp4 ? [] : ['-hls_segment_filename', `${outputDir}/segment_%03d.ts`]),
      
      // 저지연 HLS를 위한 추가 옵션
      '-hls_init_time', '0.5',
      '-hls_playlist_type', 'event',
      '-start_number', '0',
      '-hls_allow_cache', '0',
      // 인코딩 성능 향상 옵션
      '-max_muxing_queue_size', '1024',
      '-vsync', '1',
      // 오디오/비디오 동기화 최적화
      '-async', '1',
      
      // CMAF 호환성 (Apple 기기 최적화)
      ...(config.hls.useFragmentedMp4 ? ['-tag:v', 'hvc1'] : []),
      
      // 출력 파일
      `${outputDir}/playlist.m3u8`
    ];
    
    // FFmpeg 프로세스 시작 - 보안 향상을 위한 설정
    const ffmpegProcess = spawn(config.hls.ffmpegPath || 'ffmpeg', ffmpegArgs, {
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    
    // 로그 스트림 설정
    ffmpegProcess.stderr.setEncoding('utf-8');
    
    // 로그 출력 제한 (버퍼링)
    let logBuffer = '';
    let lastLogTime = Date.now();
    
    ffmpegProcess.stderr.on('data', (data) => {
      logBuffer += data;
      
      // 로그 출력 제한
      const now = Date.now();
      if (now - lastLogTime > 10000 || 
          logBuffer.includes('Error') || 
          logBuffer.includes('error') ||
          logBuffer.includes('warning')) {
        
        if (logBuffer.includes('Error') || logBuffer.includes('error')) {
          console.error(`FFmpeg 오류 (${producerId}): ${logBuffer.substring(0, 500)}${logBuffer.length > 500 ? '...' : ''}`);
        } else if (logBuffer.includes('warning')) {
          console.warn(`FFmpeg 경고 (${producerId}): ${logBuffer.substring(0, 200)}${logBuffer.length > 200 ? '...' : ''}`);
        } else if (logBuffer.includes('segment') && logBuffer.includes('.ts')) {
          console.log(`FFmpeg: 새 세그먼트 생성 (${producerId})`);
        }
        
        logBuffer = '';
        lastLogTime = now;
      }
    });
    
    // 프로세스 종료 처리
    ffmpegProcess.on('close', (code) => {
      if (code === 0 || code === null) {
        console.log(`FFmpeg 프로세스 (${producerId}) 정상 종료`);
      } else {
        console.error(`FFmpeg 프로세스 (${producerId}) 비정상 종료, 코드: ${code}`);
        
        // 비정상 종료 시 자동 재시작 로직 추가
        console.log(`FFmpeg 프로세스 (${producerId}) 재시작 시도...`);
        setTimeout(async () => {
          try {
            const newProcess = await startFFmpeg(rtpPort, outputDir, producerId);
            // 기존 맵에 새 프로세스 저장
            ffmpegProcesses.set(producerId, newProcess);
          } catch (error) {
            console.error(`FFmpeg 재시작 실패 (${producerId}):`, error);
          }
        }, 2000); // 2초 후 재시작
      }
      
      ffmpegProcesses.delete(producerId);
      
      // 사용한 RTP 포트 해제
      const producerData = producers.get(producerId);
      if (producerData && producerData.rtpInfo) {
        releaseRtpPort(producerData.rtpInfo.rtpPort);
      }
    });
    
    return ffmpegProcess;
  } catch (error) {
    console.error(`FFmpeg 시작 오류:`, error);
    throw error;
  }
}

/**
 * 프로듀서 제거 및 관련 리소스 정리
 * @param {string} producerId - 프로듀서 ID
 */
async function removeProducer(producerId) {
  try {
    // 프로듀서 정보 가져오기
    const producerData = producers.get(producerId);
    if (!producerData) {
      console.log(`존재하지 않는 프로듀서 ID: ${producerId}`);
      return;
    }
    
    // FFmpeg 프로세스 종료
    stopFFmpeg(producerId);
    
    // 파일 시스템 감시자 정리
    if (producerData.watcher) {
      producerData.watcher.close();
    }
    
    // 업로드 인터벌 정리
    if (producerData.uploadInterval) {
      clearInterval(producerData.uploadInterval);
    }
    
    // 출력 디렉토리 정리 (선택적)
    if (producerData.rtpInfo && producerData.rtpInfo.outputDir) {
      try {
        // 오래된 파일만 삭제 (설정된 기간 이상된 파일)
        await cleanupDirectory(producerData.rtpInfo.outputDir, securityOptions.fileCleanupAge);
      } catch (err) {
        console.error(`디렉토리 정리 오류 (${producerId}):`, err);
      }
    }
    
    // 사용한 포트 해제
    if (producerData.rtpInfo && producerData.rtpInfo.rtpPort) {
      releaseRtpPort(producerData.rtpInfo.rtpPort);
    }
    
    // 프로듀서 정보 삭제
    producers.delete(producerId);
    
    console.log(`프로듀서 ${producerId} 제거 완료`);
  } catch (error) {
    console.error(`프로듀서 제거 오류 (${producerId}):`, error);
  }
}

/**
 * FFmpeg 프로세스 종료
 * @param {string} producerId - 프로듀서 ID
 */
function stopFFmpeg(producerId) {
  try {
    const ffmpegProcess = ffmpegProcesses.get(producerId);
    if (ffmpegProcess) {
      // 안전하게 프로세스 종료
      ffmpegProcess.kill('SIGTERM');
      
      // 5초 후에도 종료되지 않으면 강제 종료
      setTimeout(() => {
        if (ffmpegProcesses.has(producerId)) {
          console.log(`FFmpeg 프로세스 ${producerId} 강제 종료 시도`);
          ffmpegProcess.kill('SIGKILL');
          ffmpegProcesses.delete(producerId);
        }
      }, 5000);
      
      console.log(`FFmpeg 프로세스 ${producerId} 종료 요청됨`);
    }
  } catch (error) {
    console.error(`FFmpeg 종료 오류 (${producerId}):`, error);
  }
}

/**
 * 디렉토리 정리 - 오래된 파일 삭제
 * @param {string} directory - 정리할 디렉토리
 * @param {number} age - 삭제할 파일 나이 (밀리초)
 */
async function cleanupDirectory(directory, age) {
  try {
    const now = Date.now();
    const files = await readdir(directory);
    
    for (const file of files) {
      if (file === 'playlist.m3u8') continue; // 플레이리스트는 유지
      
      const filePath = path.join(directory, file);
      const fileStat = await stat(filePath);
      
      // 파일 나이 계산
      const fileAge = now - fileStat.mtime.getTime();
      
      if (fileAge > age) {
        try {
          await unlink(filePath);
          console.log(`오래된 파일 삭제: ${file}`);
        } catch (err) {
          console.error(`파일 삭제 오류 (${file}):`, err);
        }
      }
    }
  } catch (error) {
    console.error(`디렉토리 정리 오류 (${directory}):`, error);
  }
}

/**
 * HLS 스트림 URL 가져오기
 * @param {string} producerId - 프로듀서 ID
 * @returns {string|null} HLS URL
 */
function getHlsUrl(producerId) {
  const producerData = producers.get(producerId);
  return producerData ? producerData.hlsUrl : null;
}

/**
 * 모든 활성 스트림 정보 가져오기
 * @returns {Array<Object>} 스트림 정보 배열
 */
function getActiveStreams() {
  const streams = [];
  
  for (const [id, data] of producers.entries()) {
    // 민감한 정보 제외
    streams.push({
      id,
      roomId: data.roomId,
      kind: data.kind,
      createdAt: data.createdAt,
      hlsUrl: data.hlsUrl
    });
  }
  
  return streams;
}

/**
 * 주기적 정리 작업 설정
 */
function setupPeriodicCleanup() {
  // 주기적으로 오래된 스트림 정리 (2시간 이상된 스트림)
  const cleanupInterval = setInterval(async () => {
    const now = Date.now();
    const maxAge = 2 * 60 * 60 * 1000; // 2시간
    
    for (const [id, data] of producers.entries()) {
      if (now - data.createdAt > maxAge) {
        console.log(`오래된 스트림 정리: ${id}`);
        await removeProducer(id);
      }
    }
    
    // S3에 오래된 파일 정리 (옵션)
    if (s3Client && config.aws.s3.enabled && config.aws.s3.expirationDays) {
      await cleanupS3HlsSegments();
    }
  }, 15 * 60 * 1000); // 15분마다 실행
  
  return cleanupInterval;
}

/**
 * S3 오래된 HLS 세그먼트 정리
 */
async function cleanupS3HlsSegments() {
  try {
    if (!s3Client) return;
    
    const expirationTime = Date.now() - (config.aws.s3.expirationDays * 86400 * 1000);
    
    // S3 객체 목록 조회
    const listResponse = await s3Client.send(new ListObjectsV2Command({
      Bucket: config.aws.s3.bucket,
      Prefix: 'hls/',
      MaxKeys: 1000
    }));
    
    if (!listResponse.Contents || listResponse.Contents.length === 0) {
      return;
    }
    
    // 만료된 객체 필터링
    const expiredObjects = listResponse.Contents.filter(obj => 
      obj.LastModified && obj.LastModified.getTime() < expirationTime
    );
    
    // 객체 삭제
    if (expiredObjects.length > 0) {
      console.log(`${expiredObjects.length}개의 만료된 S3 객체 삭제 시작`);
      
      // 한 번에 최대 1000개까지 삭제 가능하므로 배치 처리
      for (let i = 0; i < expiredObjects.length; i += 100) {
        const batch = expiredObjects.slice(i, i + 100);
        
        await Promise.all(batch.map(obj => 
          s3Client.send(new DeleteObjectCommand({
            Bucket: config.aws.s3.bucket,
            Key: obj.Key
          }))
        ));
      }
      
      console.log(`${expiredObjects.length}개의 만료된 S3 객체 삭제 완료`);
    }
  } catch (error) {
    console.error('S3 세그먼트 정리 오류:', error);
  }
}

// 정리 작업 시작
const cleanupInterval = setupPeriodicCleanup();

// 모듈 종료 시 정리
process.on('exit', () => {
  clearInterval(cleanupInterval);
  
  // 모든 FFmpeg 프로세스 종료
  for (const [producerId, ffmpegProcess] of ffmpegProcesses.entries()) {
    ffmpegProcess.kill('SIGKILL');
  }
  
  ffmpegProcesses.clear();
  usedPorts.clear();
});

module.exports = {
  addProducer,
  removeProducer,
  getHlsUrl,
  stopFFmpeg,
  getActiveStreams
}; 