/**
 * AWS MediaLive 스트리밍 서비스
 * HLS/RTMP 스트림을 사용하여 AI 딜러 영상 송출
 */

const { 
  MediaLiveClient, 
  DescribeInputCommand, 
  DescribeChannelCommand,
  StartChannelCommand,
  StopChannelCommand,
  CreateChannelCommand,
  ListChannelsCommand
} = require('@aws-sdk/client-medialive');

const {
  MediaPackageClient,
  DescribeChannelCommand: DescribeMediaPackageChannelCommand,
  CreateChannelCommand: CreateMediaPackageChannelCommand
} = require('@aws-sdk/client-mediapackage');

const config = require('../../config/aws');

class MediaLiveService {
  constructor() {
    // 타임아웃 설정 (ms)
    const defaultTimeout = 10000;
    
    // AWS SDK v3 설정
    const sdkConfig = {
      region: config.mediaLive.region || 'ap-northeast-2',
      maxAttempts: 3, // 최대 재시도 횟수
      retryMode: 'standard', // 표준 재시도 모드
      requestTimeout: defaultTimeout // 요청 타임아웃
    };
    
    // 인증 정보 추가
    if (process.env.AWS_ACCESS_KEY_ID && process.env.AWS_SECRET_ACCESS_KEY) {
      sdkConfig.credentials = {
        accessKeyId: process.env.AWS_ACCESS_KEY_ID,
        secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY
      };
      
      if (process.env.AWS_SESSION_TOKEN) {
        sdkConfig.credentials.sessionToken = process.env.AWS_SESSION_TOKEN;
      }
    }
    
    // MediaLive 클라이언트 생성
    this.mediaLiveClient = new MediaLiveClient(sdkConfig);
    
    // MediaPackage 클라이언트 생성
    this.mediaPackageClient = new MediaPackageClient(sdkConfig);
    
    // 설정 불러오기
    this.config = {
      inputId: config.mediaLive.inputId,
      channelId: config.mediaLive.channelId,
      streamKey: config.mediaLive.streamKey,
      cloudFrontDomain: config.mediaLive.cloudFrontDomain,
      roleArn: config.mediaLive.roleArn || 'arn:aws:iam::123456789012:role/MediaLiveAccessRole',
      defaultResolution: config.mediaLive.defaultResolution || '1280x720',
      defaultFrameRate: config.mediaLive.defaultFrameRate || 30
    };
  }

  /**
   * 채널 정보 조회
   * @param {string} [channelId] - 채널 ID (없으면 기본값 사용)
   * @returns {Promise<Object>} 채널 정보
   */
  async getChannelInfo(channelId = null) {
    try {
      const command = new DescribeChannelCommand({
        ChannelId: channelId || this.config.channelId
      });
      
      const response = await this.mediaLiveClient.send(command);
      return response;
    } catch (error) {
      console.error('MediaLive 채널 정보 조회 실패:', error);
      throw new Error(`채널 정보 조회 실패: ${error.message}`);
    }
  }

  /**
   * 채널 상태 조회
   * @param {string} [channelId] - 채널 ID (없으면 기본값 사용)
   * @returns {Promise<string>} 채널 상태 (IDLE, RUNNING, STOPPING 등)
   */
  async getChannelState(channelId = null) {
    try {
      const channelInfo = await this.getChannelInfo(channelId || this.config.channelId);
      return channelInfo.State;
    } catch (error) {
      console.error('MediaLive 채널 상태 조회 실패:', error);
      throw new Error(`채널 상태 조회 실패: ${error.message}`);
    }
  }

  /**
   * 모든 채널 목록 조회
   * @returns {Promise<Array>} 채널 목록
   */
  async listChannels() {
    try {
      const command = new ListChannelsCommand({});
      const response = await this.mediaLiveClient.send(command);
      return response.Channels || [];
    } catch (error) {
      console.error('MediaLive 채널 목록 조회 실패:', error);
      throw new Error(`채널 목록 조회 실패: ${error.message}`);
    }
  }

  /**
   * 입력 정보 조회
   * @param {string} [inputId] - 입력 ID (없으면 기본값 사용)
   * @returns {Promise<Object>} 입력 정보
   */
  async getInputInfo(inputId = null) {
    try {
      const command = new DescribeInputCommand({
        InputId: inputId || this.config.inputId
      });
      
      const response = await this.mediaLiveClient.send(command);
      return response;
    } catch (error) {
      console.error('MediaLive 입력 정보 조회 실패:', error);
      throw new Error(`입력 정보 조회 실패: ${error.message}`);
    }
  }

  /**
   * RTMP 입력 URL 조회
   * @returns {Promise<string>} RTMP 입력 URL
   */
  async getRtmpUrl() {
    try {
      const inputInfo = await this.getInputInfo();
      
      if (!inputInfo.Destinations || inputInfo.Destinations.length === 0) {
        throw new Error('RTMP 입력 URL을 찾을 수 없습니다');
      }
      
      // 첫 번째 입력 주소 사용
      const destination = inputInfo.Destinations[0];
      
      // 스트림 키가 URL에 포함되었는지 확인
      const url = destination.Url || '';
      const streamKey = this.config.streamKey || '';
      
      // URL 형식에 따라 적절한 RTMP URL 생성
      let rtmpUrl;
      if (url.includes('rtmp://')) {
        rtmpUrl = streamKey ? `${url}/${streamKey}` : url;
      } else {
        rtmpUrl = streamKey ? `rtmp://${url}/${streamKey}` : `rtmp://${url}`;
      }
      
      return rtmpUrl;
    } catch (error) {
      console.error('RTMP URL 조회 실패:', error);
      throw new Error(`RTMP URL 조회 실패: ${error.message}`);
    }
  }

  /**
   * HLS 출력 URL 조회
   * @returns {string} HLS 출력 URL
   */
  getHlsUrl() {
    try {
      if (!this.config.cloudFrontDomain) {
        throw new Error('CloudFront 도메인이 설정되지 않았습니다');
      }
      
      // HLS URL 형식
      // CloudFront 배포를 통해 MediaPackage 출력에 접근하는 URL
      return `https://${this.config.cloudFrontDomain}/out/v1/index.m3u8`;
    } catch (error) {
      console.error('HLS URL 생성 실패:', error);
      throw new Error(`HLS URL 생성 실패: ${error.message}`);
    }
  }

  /**
   * 채널 시작
   * @param {string} [channelId] - 채널 ID (없으면 기본값 사용)
   * @returns {Promise<Object>} 채널 상태 정보
   */
  async startChannel(channelId = null) {
    try {
      const targetChannelId = channelId || this.config.channelId;
      
      // 현재 상태 확인
      const currentState = await this.getChannelState(targetChannelId);
      
      if (currentState === 'RUNNING') {
        console.log('채널이 이미 실행 중입니다');
        return { State: currentState, ChannelId: targetChannelId };
      }
      
      const command = new StartChannelCommand({
        ChannelId: targetChannelId
      });
      
      const response = await this.mediaLiveClient.send(command);
      console.log('MediaLive 채널 시작됨:', response);
      
      return response;
    } catch (error) {
      console.error('MediaLive 채널 시작 실패:', error);
      throw new Error(`채널 시작 실패: ${error.message}`);
    }
  }

  /**
   * 채널 중지
   * @param {string} [channelId] - 채널 ID (없으면 기본값 사용)
   * @returns {Promise<Object>} 채널 상태 정보
   */
  async stopChannel(channelId = null) {
    try {
      const targetChannelId = channelId || this.config.channelId;
      
      // 현재 상태 확인
      const currentState = await this.getChannelState(targetChannelId);
      
      if (currentState === 'IDLE') {
        console.log('채널이 이미 중지되었습니다');
        return { State: currentState, ChannelId: targetChannelId };
      }
      
      const command = new StopChannelCommand({
        ChannelId: targetChannelId
      });
      
      const response = await this.mediaLiveClient.send(command);
      console.log('MediaLive 채널 중지됨:', response);
      
      return response;
    } catch (error) {
      console.error('MediaLive 채널 중지 실패:', error);
      throw new Error(`채널 중지 실패: ${error.message}`);
    }
  }

  /**
   * 새 MediaLive 채널 생성
   * @param {Object} options - 채널 생성 옵션
   * @param {string} options.name - 채널 이름
   * @param {string} options.inputId - 입력 ID
   * @param {string} options.resolution - 해상도 (예: 1280x720)
   * @param {number} options.frameRate - 프레임 레이트
   * @param {string} options.mediaPackageChannelId - MediaPackage 채널 ID
   * @returns {Promise<Object>} 생성된 채널 정보
   */
  async createChannel(options) {
    try {
      const {
        name,
        inputId = this.config.inputId,
        resolution = this.config.defaultResolution,
        frameRate = this.config.defaultFrameRate,
        mediaPackageChannelId
      } = options;
      
      if (!name) {
        throw new Error('채널 이름이 필요합니다');
      }
      
      if (!inputId) {
        throw new Error('입력 ID가 필요합니다');
      }
      
      // 해상도 파싱
      const [width, height] = resolution.split('x').map(Number);
      
      if (!width || !height) {
        throw new Error('올바른 해상도 형식이 아닙니다 (예: 1280x720)');
      }
      
      // MediaPackage 채널 정보 가져오기 또는 생성
      let mediaPackageEndpoints;
      
      if (mediaPackageChannelId) {
        const mediaPackageInfo = await this.getMediaPackageChannel(mediaPackageChannelId);
        mediaPackageEndpoints = mediaPackageInfo.HlsIngest.ingestEndpoints;
      }
      
      // 채널 생성 명령 구성
      const createChannelParams = {
        Name: name,
        RoleArn: this.config.roleArn,
        InputAttachments: [
          {
            InputId: inputId,
            InputAttachmentName: 'input1'
          }
        ],
        EncoderSettings: {
          AudioDescriptions: [
            {
              AudioSelectorName: 'Default',
              CodecSettings: {
                AacSettings: {
                  InputType: 'NORMAL',
                  Profile: 'LC',
                  RateControlMode: 'CBR',
                  Bitrate: 192000,
                  SampleRate: 48000
                }
              },
              Name: 'audio_1'
            }
          ],
          VideoDescriptions: [
            {
              Height: height,
              Width: width,
              CodecSettings: {
                H264Settings: {
                  AfdSignaling: 'NONE',
                  ColorMetadata: 'INSERT',
                  AdaptiveQuantization: 'HIGH',
                  Bitrate: 2500000,
                  EntropyEncoding: 'CABAC',
                  FlickerAq: 'ENABLED',
                  FramerateDenominator: 1,
                  FramerateNumerator: frameRate,
                  GopClosedCadence: 1,
                  GopSize: frameRate * 2, // 2초 키프레임
                  GopSizeUnits: 'FRAMES',
                  Level: 'H264_LEVEL_AUTO',
                  LookAheadRateControl: 'HIGH',
                  Profile: 'HIGH',
                  RateControlMode: 'CBR',
                  SceneChangeDetect: 'ENABLED',
                  SpatialAq: 'ENABLED',
                  TemporalAq: 'ENABLED',
                  TimecodeInsertion: 'DISABLED'
                }
              },
              Name: 'video_1'
            }
          ],
          OutputGroups: []
        }
      };
      
      // 출력 그룹 설정 - HLS
      const hlsOutputGroup = {
        Name: 'HLS_Output',
        OutputGroupSettings: {
          HlsGroupSettings: {
            AdMarkers: [],
            CaptionLanguageSetting: 'OMIT',
            CaptionLanguageMappings: [],
            HlsCdnSettings: {
              HlsBasicPutSettings: {
                ConnectionRetryInterval: 30,
                FilecacheDuration: 300,
                NumRetries: 5,
                RestartDelay: 5
              }
            },
            InputLossAction: 'PAUSE_OUTPUT',
            IvInManifest: 'INCLUDE',
            IvSource: 'FOLLOWS_SEGMENT_NUMBER',
            ManifestCompression: 'NONE',
            ManifestDurationFormat: 'INTEGER',
            Mode: 'LIVE',
            OutputSelection: 'MANIFESTS_AND_SEGMENTS',
            ProgramDateTime: 'INCLUDE',
            ProgramDateTimePeriod: 30,
            SegmentLength: 4,
            SegmentationMode: 'USE_SEGMENT_DURATION',
            StreamInfResolution: 'INCLUDE',
            TimedMetadataId3Frame: 'PRIV',
            TimedMetadataId3Period: 10,
            TsFileMode: 'SEGMENTED_FILES'
          }
        },
        Outputs: [
          {
            AudioDescriptionNames: ['audio_1'],
            OutputName: 'hls_output_1',
            VideoDescriptionName: 'video_1',
            OutputSettings: {
              HlsOutputSettings: {
                H265PackagingType: 'HVC1',
                HlsSettings: {
                  StandardHlsSettings: {
                    M3u8Settings: {
                      PcrControl: 'PCR_EVERY_PES_PACKET',
                      TimedMetadataBehavior: 'NO_PASSTHROUGH',
                      PmtPid: '480',
                      VideoPid: '481',
                      AudioPids: '482-498',
                      AudioFramesPerPes: 4,
                      EcmPid: '8182',
                      ProgramNum: 1
                    },
                    AudioRenditionSets: 'PROGRAM_AUDIO'
                  }
                },
                NameModifier: '_1'
              }
            }
          }
        ]
      };
      
      // MediaPackage 엔드포인트가 있으면 HLS 출력 그룹 목적지 추가
      if (mediaPackageEndpoints && mediaPackageEndpoints.length > 0) {
        const destinations = mediaPackageEndpoints.map((endpoint, index) => ({
          Id: `destination_${index}`,
          Settings: [
            {
              PasswordParam: endpoint.Password,
              Url: endpoint.Url,
              Username: endpoint.Username
            }
          ]
        }));
        
        createChannelParams.Destinations = destinations;
        hlsOutputGroup.OutputGroupSettings.HlsGroupSettings.Destination = {
          DestinationRefId: 'destination_0'
        };
      } else {
        // S3 버킷이나 다른 목적지 사용
        hlsOutputGroup.OutputGroupSettings.HlsGroupSettings.Destination = {
          DestinationRefId: 'destination_1'
        };
        
        // 기본 출력 목적지 설정 (실제 상황에 맞게 수정 필요)
        createChannelParams.Destinations = [
          {
            Id: 'destination_1',
            Settings: [
              {
                Url: `s3://${config.mediaLive.s3Bucket || 'your-output-bucket'}/${name}/`
              }
            ]
          }
        ];
      }
      
      // 출력 그룹 추가
      createChannelParams.EncoderSettings.OutputGroups.push(hlsOutputGroup);
      
      // 채널 생성 요청
      const command = new CreateChannelCommand(createChannelParams);
      const response = await this.mediaLiveClient.send(command);
      
      console.log('새 MediaLive 채널 생성됨:', response.Channel.Id);
      
      return {
        channel_id: response.Channel.Id,
        name: response.Channel.Name,
        arn: response.Channel.Arn,
        state: response.Channel.State
      };
    } catch (error) {
      console.error('MediaLive 채널 생성 실패:', error);
      throw new Error(`채널 생성 실패: ${error.message}`);
    }
  }

  /**
   * MediaPackage 채널 정보 조회
   * @param {string} channelId - MediaPackage 채널 ID
   * @returns {Promise<Object>} 채널 정보
   */
  async getMediaPackageChannel(channelId) {
    try {
      const command = new DescribeMediaPackageChannelCommand({
        Id: channelId
      });
      
      const response = await this.mediaPackageClient.send(command);
      return response;
    } catch (error) {
      console.error('MediaPackage 채널 정보 조회 실패:', error);
      throw new Error(`MediaPackage 채널 정보 조회 실패: ${error.message}`);
    }
  }

  /**
   * FFmpeg 명령어 생성 (RTMP 스트리밍용)
   * @param {string} inputFile - 입력 파일 경로 (MP4)
   * @param {Object} options - 추가 옵션
   * @returns {Promise<string>} FFmpeg 명령어
   */
  async generateFfmpegCommand(inputFile, options = {}) {
    try {
      const rtmpUrl = await this.getRtmpUrl();
      
      // 기본 옵션
      const defaultOptions = {
        videoCodec: 'libx264',
        videoBitrate: '2500k',
        audioCodec: 'aac',
        audioBitrate: '128k',
        frameRate: 30,
        keyframe: 2, // 2초마다 키프레임
        preset: 'veryfast',
        profile: 'main',
        level: '4.0',
        size: '1280x720', // 720p
        loop: options.loop || false
      };
      
      // 옵션 병합
      const mergedOptions = { ...defaultOptions, ...options };
      
      // 명령어 구성
      let command = 'ffmpeg -y ';
      
      // 루프 옵션
      if (mergedOptions.loop) {
        command += '-stream_loop -1 ';
      }
      
      // 입력 파일
      command += `-i "${inputFile}" `;
      
      // 비디오 인코딩 옵션
      command += `-c:v ${mergedOptions.videoCodec} `;
      command += `-b:v ${mergedOptions.videoBitrate} `;
      command += `-r ${mergedOptions.frameRate} `;
      command += `-g ${mergedOptions.frameRate * mergedOptions.keyframe} `;
      command += `-preset ${mergedOptions.preset} `;
      command += `-profile:v ${mergedOptions.profile} `;
      command += `-level ${mergedOptions.level} `;
      command += `-s ${mergedOptions.size} `;
      
      // 오디오 인코딩 옵션
      command += `-c:a ${mergedOptions.audioCodec} `;
      command += `-b:a ${mergedOptions.audioBitrate} `;
      command += `-ar 48000 `;
      command += `-ac 2 `;
      
      // RTMP 출력
      command += `-f flv "${rtmpUrl}"`;
      
      return command;
    } catch (error) {
      console.error('FFmpeg 명령어 생성 실패:', error);
      throw new Error(`FFmpeg 명령어 생성 실패: ${error.message}`);
    }
  }
}

module.exports = MediaLiveService; 