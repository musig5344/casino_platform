/**
 * AWS MediaLive 연동 모듈
 * AI 딜러 영상 스트림을 위한 AWS MediaLive 서비스 연동
 */

const AWS = require('aws-sdk');
const config = require('../mediasoup/config');

// AWS SDK 설정
AWS.config.update({
  region: config.aws.region,
  credentials: {
    accessKeyId: config.aws.credentials.accessKeyId,
    secretAccessKey: config.aws.credentials.secretAccessKey
  }
});

// MediaLive 및 MediaPackage 클라이언트 생성
const mediaLive = new AWS.MediaLive();
const mediaPackage = new AWS.MediaPackage();

// AI 딜러 테이블 정보
const AI_DEALER_TABLES = {
  'blackjack': {
    id: 'BLACKJACK',
    channelId: 'blackjack-channel',
    inputId: 'blackjack-input',
    hlsEndpoint: 'blackjack-endpoint'
  },
  'roulette': {
    id: 'ROULETTE',
    channelId: 'roulette-channel',
    inputId: 'roulette-input',
    hlsEndpoint: 'roulette-endpoint'
  },
  'baccarat': {
    id: 'BACCARAT',
    channelId: 'baccarat-channel',
    inputId: 'baccarat-input',
    hlsEndpoint: 'baccarat-endpoint'
  }
};

/**
 * MediaLive 스트림 시작
 * @param {string} tableId - 테이블 ID
 * @returns {Promise<Object>} - 스트림 정보
 */
async function startStream(tableId) {
  try {
    // 테이블 정보 확인
    const tableInfo = AI_DEALER_TABLES[tableId.toLowerCase()];
    if (!tableInfo) {
      throw new Error(`테이블 ID가 잘못되었습니다: ${tableId}`);
    }
    
    // 채널 상태 확인
    const channelInfo = await mediaLive.describeChannel({
      ChannelId: tableInfo.channelId
    }).promise();
    
    // 채널이 실행 중이 아니면 시작
    if (channelInfo.State !== 'RUNNING') {
      console.log(`채널 ${tableInfo.channelId} 시작 중...`);
      await mediaLive.startChannel({
        ChannelId: tableInfo.channelId
      }).promise();
      
      // 채널이 시작될 때까지 대기
      await waitForChannelState(tableInfo.channelId, 'RUNNING');
    }
    
    // HLS 엔드포인트 정보 가져오기
    const endpointInfo = await mediaPackage.describeOriginEndpoint({
      Id: tableInfo.hlsEndpoint
    }).promise();
    
    // 스트림 URL 반환
    const hlsUrl = endpointInfo.Url;
    
    console.log(`${tableId} 테이블 스트림 시작 완료: ${hlsUrl}`);
    
    // WebRTC 스트림 파라미터 생성 (실제 프로젝트에서는 MediaLive와 WebRTC 통합 필요)
    const webRtcParams = {
      rtpCapabilities: {
        codecs: [
          {
            kind: 'video',
            mimeType: 'video/h264',
            clockRate: 90000,
            parameters: {
              'packetization-mode': 1,
              'profile-level-id': '42e01f',
              'level-asymmetry-allowed': 1
            }
          },
          {
            kind: 'audio',
            mimeType: 'audio/opus',
            clockRate: 48000,
            channels: 2
          }
        ]
      }
    };
    
    return {
      tableId: tableId,
      hlsUrl: hlsUrl,
      status: 'running',
      webRtcParams: webRtcParams
    };
  } catch (error) {
    console.error('AWS MediaLive 스트림 시작 오류:', error);
    throw error;
  }
}

/**
 * MediaLive 스트림 중지
 * @param {string} tableId - 테이블 ID
 * @returns {Promise<Object>} - 스트림 상태
 */
async function stopStream(tableId) {
  try {
    // 테이블 정보 확인
    const tableInfo = AI_DEALER_TABLES[tableId.toLowerCase()];
    if (!tableInfo) {
      throw new Error(`테이블 ID가 잘못되었습니다: ${tableId}`);
    }
    
    // 채널 상태 확인
    const channelInfo = await mediaLive.describeChannel({
      ChannelId: tableInfo.channelId
    }).promise();
    
    // 채널이 실행 중이면 중지
    if (channelInfo.State === 'RUNNING') {
      console.log(`채널 ${tableInfo.channelId} 중지 중...`);
      await mediaLive.stopChannel({
        ChannelId: tableInfo.channelId
      }).promise();
      
      // 채널이 중지될 때까지 대기
      await waitForChannelState(tableInfo.channelId, 'IDLE');
    }
    
    console.log(`${tableId} 테이블 스트림 중지 완료`);
    
    return {
      tableId: tableId,
      status: 'stopped'
    };
  } catch (error) {
    console.error('AWS MediaLive 스트림 중지 오류:', error);
    throw error;
  }
}

/**
 * 채널 상태가 변경될 때까지 대기
 * @param {string} channelId - 채널 ID
 * @param {string} targetState - 대기할 상태
 * @returns {Promise<void>}
 */
async function waitForChannelState(channelId, targetState) {
  const maxAttempts = 60;
  const delay = 2000; // 2초
  
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const channelInfo = await mediaLive.describeChannel({
      ChannelId: channelId
    }).promise();
    
    if (channelInfo.State === targetState) {
      return;
    }
    
    console.log(`채널 ${channelId} 상태 대기 중: ${channelInfo.State} (목표: ${targetState})`);
    
    // 다음 확인까지 대기
    await new Promise(resolve => setTimeout(resolve, delay));
  }
  
  throw new Error(`채널 ${channelId}이(가) ${targetState} 상태가 되지 않음`);
}

/**
 * MediaLive 채널 생성 (관리 목적)
 * @param {string} tableId - 테이블 ID
 * @param {Object} options - 채널 옵션
 * @returns {Promise<Object>} - 채널 정보
 */
async function createChannel(tableId, options) {
  try {
    // 테이블 정보 확인
    const tableInfo = AI_DEALER_TABLES[tableId.toLowerCase()];
    if (!tableInfo) {
      throw new Error(`테이블 ID가 잘못되었습니다: ${tableId}`);
    }
    
    // 입력 생성
    const inputParams = {
      Name: `${tableId}-input`,
      Type: 'RTMP_PUSH',
      Destinations: [
        {
          StreamName: `${tableId}/stream1`
        },
        {
          StreamName: `${tableId}/stream2`
        }
      ]
    };
    
    const inputResult = await mediaLive.createInput(inputParams).promise();
    
    // MediaPackage 채널 생성
    const packageChannelParams = {
      Id: `${tableId}-package`,
      Description: `MediaPackage channel for ${tableId}`
    };
    
    const packageChannelResult = await mediaPackage.createChannel(packageChannelParams).promise();
    
    // MediaPackage HLS 엔드포인트 생성
    const endpointParams = {
      ChannelId: packageChannelResult.Id,
      Id: `${tableId}-endpoint`,
      Description: `HLS endpoint for ${tableId}`,
      HlsPackage: {
        SegmentDurationSeconds: 2,
        PlaylistWindowSeconds: 60,
        StreamSelection: {
          StreamOrder: 'ORIGINAL'
        }
      }
    };
    
    const endpointResult = await mediaPackage.createOriginEndpoint(endpointParams).promise();
    
    // MediaLive 채널 생성
    const channelParams = {
      Name: `${tableId}-channel`,
      RoleArn: options.roleArn,
      InputSpecification: {
        Codec: 'AVC',
        Resolution: 'HD',
        MaximumBitrate: 'MAX_20_MBPS'
      },
      InputAttachments: [
        {
          InputId: inputResult.Input.Id,
          InputSettings: {
            SourceEndBehavior: 'CONTINUE',
            InputFilter: 'AUTO',
            FilterStrength: 1,
            DeblockFilter: 'DISABLED',
            DenoiseFilter: 'DISABLED'
          }
        }
      ],
      Destinations: [
        {
          Id: 'destination1',
          Settings: [
            {
              PasswordParam: '/medialive/destination/password',
              Url: packageChannelResult.HlsIngest.IngestEndpoints[0].Url,
              Username: packageChannelResult.HlsIngest.IngestEndpoints[0].Username
            }
          ]
        }
      ],
      EncoderSettings: {
        // 인코더 설정 (실제 구현 시 확장 필요)
      }
    };
    
    const channelResult = await mediaLive.createChannel(channelParams).promise();
    
    // 새 채널 정보로 테이블 정보 업데이트
    AI_DEALER_TABLES[tableId.toLowerCase()] = {
      id: tableId.toUpperCase(),
      channelId: channelResult.Channel.Id,
      inputId: inputResult.Input.Id,
      hlsEndpoint: endpointResult.Id
    };
    
    return {
      tableId: tableId,
      channelId: channelResult.Channel.Id,
      inputId: inputResult.Input.Id,
      hlsEndpoint: endpointResult.Id,
      hlsUrl: endpointResult.Url
    };
  } catch (error) {
    console.error('AWS MediaLive 채널 생성 오류:', error);
    throw error;
  }
}

module.exports = {
  startStream,
  stopStream,
  createChannel
}; 