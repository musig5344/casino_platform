/**
 * WebRTC 및 HLS 스트리밍 서비스 설정
 * AWS 인프라 최적화 버전
 */

const os = require('os');
const path = require('path');

// 환경별 기본값 설정
const environment = process.env.NODE_ENV || 'development';
const isProd = environment === 'production';

// 기본 CPU 설정
const numPhysicalCores = os.cpus().length;
// 프로덕션 환경에서는 물리 코어 수에 따라, 개발 환경에서는 1개 사용
const defaultNumWorkers = isProd ? Math.max(1, Math.min(numPhysicalCores, 4)) : 1;

const config = {
  // 환경 설정
  environment,
  
  // 웹 서버 설정
  listenIp: process.env.LISTEN_IP || '0.0.0.0',
  webServerPort: parseInt(process.env.PORT || '3000', 10),
  
  // CORS 설정
  corsOrigins: process.env.CORS_ORIGINS ? process.env.CORS_ORIGINS.split(',') : ['*'],
  
  // HTTPS 설정
  https: {
    enabled: process.env.HTTPS_ENABLED === 'true' || false,
    certFile: process.env.HTTPS_CERT_FILE || './ssl/cert.pem',
    keyFile: process.env.HTTPS_KEY_FILE || './ssl/key.pem'
  },
  
  // mediasoup 설정
  mediasoup: {
    // Worker 설정
    worker: {
      rtcMinPort: parseInt(process.env.MEDIASOUP_MIN_PORT || '10000', 10),
      rtcMaxPort: parseInt(process.env.MEDIASOUP_MAX_PORT || '10100', 10),
      logLevel: process.env.MEDIASOUP_LOG_LEVEL || (isProd ? 'warn' : 'info'),
      logTags: [
        'info',
        'ice',
        'dtls',
        'rtp',
        'srtp',
        'rtcp',
        'rtx',
        'bwe',
        'score',
        'simulcast',
        'svc'
      ],
      // AWS Spot 인스턴스에서는 성능 최적화를 위해 코어 수 조절 필요
      numWorkers: parseInt(process.env.MEDIASOUP_NUM_WORKERS || defaultNumWorkers.toString(), 10),
    },
    
    // Router 설정
    router: {
      mediaCodecs: [
        {
          kind: 'audio',
          mimeType: 'audio/opus',
          clockRate: 48000,
          channels: 2,
          parameters: {
            minptime: 10,
            useinbandfec: 1
          }
        },
        {
          kind: 'video',
          mimeType: 'video/VP8',
          clockRate: 90000,
          parameters: {
            'x-google-start-bitrate': 2000,
            'x-google-min-bitrate': 250,
            'x-google-max-bitrate': 5000
          }
        },
        {
          kind: 'video',
          mimeType: 'video/VP9',
          clockRate: 90000,
          parameters: {
            'profile-id': 2,
            'x-google-start-bitrate': 2000,
            'x-google-min-bitrate': 250,
            'x-google-max-bitrate': 5000
          }
        },
        {
          kind: 'video',
          mimeType: 'video/h264',
          clockRate: 90000,
          parameters: {
            'packetization-mode': 1,
            'profile-level-id': '4d0032',
            'level-asymmetry-allowed': 1,
            'x-google-start-bitrate': 2000,
            'x-google-min-bitrate': 250,
            'x-google-max-bitrate': 5000
          }
        },
        {
          kind: 'video',
          mimeType: 'video/h264',
          clockRate: 90000,
          parameters: {
            'packetization-mode': 1,
            'profile-level-id': '42e01f',
            'level-asymmetry-allowed': 1,
            'x-google-start-bitrate': 2000,
            'x-google-min-bitrate': 250,
            'x-google-max-bitrate': 5000
          }
        },
        // 실험적 AV1 코덱 지원 추가
        {
          kind: 'video',
          mimeType: 'video/AV1',
          clockRate: 90000,
          parameters: {
            'x-google-start-bitrate': 2000,
            'x-google-min-bitrate': 250,
            'x-google-max-bitrate': 5000
          }
        }
      ]
    },
    
    // WebRTC 트랜스포트 설정
    webRtcTransport: {
      listenIps: [
        {
          ip: process.env.MEDIASOUP_LISTEN_IP || '0.0.0.0',
          // EC2 인스턴스에서는 실제 퍼블릭 IP를 사용해야 함
          announcedIp: process.env.MEDIASOUP_ANNOUNCED_IP || getLocalIp()
        }
      ],
      // 초기 비트레이트 설정 (기본값 높게 설정)
      initialAvailableOutgoingBitrate: parseInt(process.env.MEDIASOUP_INITIAL_BITRATE || '2000000', 10),
      minimumAvailableOutgoingBitrate: parseInt(process.env.MEDIASOUP_MIN_BITRATE || '250000', 10),
      maximumAvailableOutgoingBitrate: parseInt(process.env.MEDIASOUP_MAX_BITRATE || '5000000', 10),
      // SCTP 최대 메시지 크기
      maxSctpMessageSize: 262144,
      // 최대 수신 비트레이트
      maxIncomingBitrate: parseInt(process.env.MEDIASOUP_MAX_INCOMING_BITRATE || '5000000', 10),
      factorIncomingBitrate: 0.9
    },
    
    // PlainRtpTransport 설정 (HLS 변환용)
    plainTransportOptions: {
      listenIp: {
        ip: process.env.MEDIASOUP_PLAIN_RTP_IP || '127.0.0.1',
        announcedIp: null
      },
      rtcpMux: true,
      comedia: false
    },

    // SVC(Scalable Video Coding) 설정
    svc: {
      enabled: true,
      numSpatialLayers: 4, // 공간적 계층 수 증가 (해상도 계층)
      numTemporalLayers: 3, // 시간적 계층 수 (프레임 레이트 계층)
      // 초저품질 프로파일 (매우 낮은 대역폭 시)
      ultraLowProfile: {
        spatialLayer: 0,
        temporalLayer: 0,
        maxBitrate: 250000 // 250kbps
      },
      // 저품질 프로파일 (낮은 대역폭 시)
      lowProfile: {
        spatialLayer: 1,
        temporalLayer: 1,
        maxBitrate: 800000 // 800kbps
      },
      // 중간 품질 프로파일 (중간 대역폭 시)
      mediumProfile: {
        spatialLayer: 2,
        temporalLayer: 2,
        maxBitrate: 2000000 // 2Mbps
      },
      // 최고 품질 프로파일 (높은 대역폭 시)
      highProfile: {
        spatialLayer: 3,
        temporalLayer: 2,
        maxBitrate: 5000000 // 5Mbps
      }
    },

    // 적응형 비트레이트 설정
    adaptiveBitrate: {
      enabled: true,
      // 비트레이트 변경 감지 간격 (밀리초)
      detectionInterval: 2000,
      // 최소 RTT (Round Trip Time) 임계값
      minRtt: 50,
      // 혼잡 감지 시 비트레이트 감소 비율
      decreaseFactor: 0.75,
      // 네트워크 상태 좋아질 때 비트레이트 증가 비율
      increaseFactor: 1.15,
      // 비트레이트 조정 제한 (밀리초) - 너무 잦은 변경 방지
      adjustmentThrottleMs: 5000,
      // 안정적인 네트워크 카운트 임계값
      stableNetworkThreshold: 5
    }
  },
  
  // HLS 설정
  hls: {
    enabled: process.env.HLS_ENABLED === 'true' || true,
    outputPath: process.env.HLS_OUTPUT_PATH || path.resolve(process.cwd(), 'public/hls'),
    baseUrl: process.env.HLS_BASE_URL || 'http://localhost:3000/hls',
    segmentDuration: parseInt(process.env.HLS_SEGMENT_DURATION || '0.5', 10), // 0.5초로 변경
    listSize: parseInt(process.env.HLS_LIST_SIZE || '4', 10), // 리스트 크기 감소
    // FFmpeg 경로 설정
    ffmpegPath: process.env.FFMPEG_PATH || 'ffmpeg',
    ffprobePath: process.env.FFPROBE_PATH || 'ffprobe',
    // 비디오 인코딩 프리셋 설정
    videoPreset: process.env.HLS_VIDEO_PRESET || 'veryfast',
    videoCrf: parseInt(process.env.HLS_VIDEO_CRF || '23', 10),
    // GOP 설정
    gopSize: parseInt(process.env.HLS_GOP_SIZE || '10', 10), // GOP 크기를 10으로 설정
    // fMP4 설정
    useFragmentedMp4: process.env.HLS_USE_FMP4 === 'true' || true
  },
  
  // AWS MediaLive 설정
  mediaLive: {
    region: process.env.AWS_REGION || 'ap-northeast-2',
    inputId: process.env.AWS_MEDIALIVE_INPUT_ID,
    channelId: process.env.AWS_MEDIALIVE_CHANNEL_ID,
    rtmpEndpoint: process.env.AWS_MEDIALIVE_RTMP_ENDPOINT,
    streamKey: process.env.AWS_MEDIALIVE_STREAM_KEY,
    cloudFrontDomain: process.env.CLOUDFRONT_DOMAIN,
    roleArn: process.env.MEDIALIVE_ROLE_ARN
  },
  
  // AWS 설정
  aws: {
    region: process.env.AWS_REGION || 'ap-northeast-2',
    credentials: {
      accessKeyId: process.env.AWS_ACCESS_KEY_ID,
      secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY
    },
    // Elastic Cache 설정
    elastiCache: {
      enabled: process.env.REDIS_ENABLED === 'true' || false,
      host: process.env.REDIS_HOST,
      port: parseInt(process.env.REDIS_PORT || '6379', 10),
      password: process.env.REDIS_PASSWORD || '',
      prefix: process.env.REDIS_PREFIX || `casino:${environment}:`
    },
    // Lambda 설정 (게임 로직 처리용)
    lambda: {
      enabled: process.env.LAMBDA_ENABLED === 'true' || false,
      functionName: process.env.LAMBDA_FUNCTION_NAME
    },
    // S3 설정
    s3: {
      enabled: process.env.AWS_S3_ENABLED === 'true' || false,
      bucket: process.env.AWS_S3_BUCKET || 'casino-platform-media',
      accessKeyId: process.env.AWS_ACCESS_KEY_ID,
      secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
      // 자동 만료 설정 (일 단위)
      expirationDays: parseInt(process.env.AWS_S3_EXPIRATION_DAYS || '7', 10)
    },
    // CloudFront 설정
    cloudFront: {
      enabled: process.env.AWS_CLOUDFRONT_ENABLED === 'true' || false,
      domain: process.env.AWS_CLOUDFRONT_DOMAIN,
      keyPairId: process.env.AWS_CLOUDFRONT_KEY_PAIR_ID,
      privateKey: process.env.AWS_CLOUDFRONT_PRIVATE_KEY,
      // 서명된 URL 만료 시간 (초)
      signedUrlExpireTime: parseInt(process.env.AWS_CLOUDFRONT_SIGNED_URL_EXPIRE_TIME || '3600', 10)
    },
    // MediaLive 설정
    mediaLive: {
      enabled: process.env.AWS_MEDIALIVE_ENABLED === 'true' || false,
      channelPrefix: process.env.AWS_MEDIALIVE_CHANNEL_PREFIX || 'casino-',
      inputSecurityGroup: process.env.AWS_MEDIALIVE_INPUT_SECURITY_GROUP,
      // 입력 유형 설정 (RTMP_PUSH, RTP_PUSH 등)
      inputType: process.env.AWS_MEDIALIVE_INPUT_TYPE || 'RTMP_PUSH',
      outputGroup: process.env.AWS_MEDIALIVE_OUTPUT_GROUP || 'HLS'
    },
    // MediaPackage 설정
    mediaPackage: {
      enabled: process.env.AWS_MEDIAPACKAGE_ENABLED === 'true' || false,
    }
  },
  
  // AI 딜러 스트림 설정
  aiDealerStream: {
    // AI 딜러 스트림 소스 URL
    sourceUrl: process.env.AI_DEALER_SOURCE_URL || '',
    // 스트림 캐시 TTL (초)
    cacheTtl: parseInt(process.env.AI_DEALER_CACHE_TTL || '60', 10),
    // 레디스 캐싱 키
    cacheKey: process.env.AI_DEALER_CACHE_KEY || 'ai:dealer:streams'
  },
  
  // 모니터링 설정
  monitoring: {
    enabled: process.env.MONITORING_ENABLED === 'true' || false,
    // CloudWatch 통합
    cloudWatch: {
      enabled: process.env.CLOUDWATCH_ENABLED === 'true' || false,
      region: process.env.AWS_REGION || 'ap-northeast-2',
      logGroup: process.env.CLOUDWATCH_LOG_GROUP || '/casino-platform/streaming',
      logRetentionDays: parseInt(process.env.CLOUDWATCH_LOG_RETENTION || '14', 10)
    }
  }
};

module.exports = config;

// 로컬 IP 주소 가져오기
function getLocalIp() {
  const ifaces = os.networkInterfaces();
  let ip = '127.0.0.1';
  
  Object.keys(ifaces).forEach((ifname) => {
    ifaces[ifname].forEach((iface) => {
      // IPv4 & 내부 네트워크 주소가 아닌 경우
      if (iface.family === 'IPv4' && !iface.internal) {
        ip = iface.address;
      }
    });
  });
  
  return ip;
} 