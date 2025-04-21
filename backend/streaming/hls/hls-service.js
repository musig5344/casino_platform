/**
 * HLS 스트리밍 서비스
 * mediasoup WebRTC 스트림을 HLS로 변환
 */

const fs = require('fs');
const path = require('path');
const { promisify } = require('util');
const { spawn } = require('child_process');
const config = require('../mediasoup/config');

const mkdir = promisify(fs.mkdir);
const rmdir = promisify(fs.rmdir);
const unlink = promisify(fs.unlink);
const readdir = promisify(fs.readdir);
const stat = promisify(fs.stat);

class HlsService {
  /**
   * HLS 서비스 초기화
   * @param {Object} router - mediasoup 라우터
   * @param {string} roomId - 방 ID
   */
  constructor(router, roomId) {
    this.router = router;
    this.roomId = roomId;
    this.videoTransport = null;
    this.audioTransport = null;
    this.videoConsumer = null;
    this.audioConsumer = null;
    this.ffmpegProcess = null;
    this.isRunning = false;
    this.outputPath = path.join(config.hls.outputPath, roomId);
    this.baseUrl = `${config.hls.baseUrl}/${roomId}`;
  }

  /**
   * HLS 스트리밍 시작
   * @param {Object} videoProducer - 비디오 프로듀서
   * @param {Object} audioProducer - 오디오 프로듀서 (선택 사항)
   */
  async start(videoProducer, audioProducer = null) {
    if (this.isRunning) {
      console.log('HLS 스트리밍이 이미 실행 중입니다');
      return;
    }

    try {
      console.log(`HLS 스트리밍 시작: ${this.roomId}`);
      
      // HLS 출력 디렉토리 생성
      await this.createOutputDir();
      
      // RTP 트랜스포트 생성 (비디오)
      this.videoTransport = await this.createPlainTransport();
      
      // 비디오 컨슈머 생성
      this.videoConsumer = await this.createConsumer(
        this.videoTransport, 
        videoProducer
      );
      
      const videoRtpParameters = this.videoConsumer.rtpParameters;
      
      // 오디오가 있는 경우 오디오 컨슈머 생성
      let audioRtpParameters = null;
      if (audioProducer) {
        this.audioTransport = await this.createPlainTransport();
        this.audioConsumer = await this.createConsumer(
          this.audioTransport, 
          audioProducer
        );
        audioRtpParameters = this.audioConsumer.rtpParameters;
      }
      
      // FFmpeg 명령어 생성
      const ffmpegCommand = this.generateFfmpegCommand(
        videoRtpParameters,
        audioRtpParameters
      );
      
      // FFmpeg 프로세스 시작
      this.startFfmpeg(ffmpegCommand);
      
      this.isRunning = true;
      
    } catch (error) {
      console.error('HLS 스트리밍 시작 실패:', error);
      await this.stop();
      throw error;
    }
  }

  /**
   * HLS 스트리밍 중지
   */
  async stop() {
    if (!this.isRunning) {
      return;
    }

    console.log(`HLS 스트리밍 중지: ${this.roomId}`);
    
    // FFmpeg 프로세스 종료
    if (this.ffmpegProcess) {
      this.ffmpegProcess.kill('SIGINT');
      this.ffmpegProcess = null;
    }
    
    // 미디어 컨슈머 닫기
    if (this.videoConsumer) {
      this.videoConsumer.close();
      this.videoConsumer = null;
    }
    
    if (this.audioConsumer) {
      this.audioConsumer.close();
      this.audioConsumer = null;
    }
    
    // 트랜스포트 닫기
    if (this.videoTransport) {
      this.videoTransport.close();
      this.videoTransport = null;
    }
    
    if (this.audioTransport) {
      this.audioTransport.close();
      this.audioTransport = null;
    }
    
    this.isRunning = false;
  }

  /**
   * HLS URL 조회
   * @returns {string} HLS 스트림 URL
   */
  getHlsUrl() {
    return `${this.baseUrl}/index.m3u8`;
  }

  /**
   * 스트리밍 디렉토리 생성
   */
  async createOutputDir() {
    try {
      // HLS 출력 기본 디렉토리가 없는 경우 생성
      if (!fs.existsSync(config.hls.outputPath)) {
        await mkdir(config.hls.outputPath, { recursive: true });
      }
      
      // 해당 방 디렉토리가 없는 경우 생성
      if (!fs.existsSync(this.outputPath)) {
        await mkdir(this.outputPath, { recursive: true });
      }
    } catch (error) {
      console.error('HLS 출력 디렉토리 생성 실패:', error);
      throw error;
    }
  }

  /**
   * HLS 파일 정리
   */
  async cleanupFiles() {
    try {
      if (fs.existsSync(this.outputPath)) {
        const files = await readdir(this.outputPath);
        
        for (const file of files) {
          const filePath = path.join(this.outputPath, file);
          await unlink(filePath);
        }
        
        await rmdir(this.outputPath);
        console.log(`HLS 파일 정리 완료: ${this.outputPath}`);
      }
    } catch (error) {
      console.error('HLS 파일 정리 실패:', error);
    }
  }

  /**
   * Plain RTP 트랜스포트 생성
   * @returns {Object} RTP 트랜스포트
   */
  async createPlainTransport() {
    try {
      const transport = await this.router.createPlainTransport(
        config.mediasoup.plainTransportOptions
      );
      
      transport.on('close', () => {
        console.log(`플레인 트랜스포트 종료: ${transport.id}`);
      });
      
      return transport;
    } catch (error) {
      console.error('플레인 트랜스포트 생성 실패:', error);
      throw error;
    }
  }

  /**
   * RTP 컨슈머 생성
   * @param {Object} transport - RTP 트랜스포트
   * @param {Object} producer - 미디어 프로듀서
   * @returns {Object} RTP 컨슈머
   */
  async createConsumer(transport, producer) {
    try {
      const consumer = await transport.consume({
        producerId: producer.id,
        rtpCapabilities: this.router.rtpCapabilities,
        paused: false
      });
      
      return consumer;
    } catch (error) {
      console.error('컨슈머 생성 실패:', error);
      throw error;
    }
  }

  /**
   * FFmpeg 명령어 생성
   * @param {Object} videoRtpParameters - 비디오 RTP 파라미터
   * @param {Object} audioRtpParameters - 오디오 RTP 파라미터 (선택 사항)
   * @returns {Array<string>} FFmpeg 명령어 배열
   */
  generateFfmpegCommand(videoRtpParameters, audioRtpParameters) {
    const { segmentDuration, playlistLength } = config.hls;
    
    let command = [
      '-loglevel', 'debug',
      '-protocol_whitelist', 'pipe,udp,rtp,file,crypto'
    ];
    
    // SDP 파일 생성
    const sdpContent = this.generateSdpFile(videoRtpParameters, audioRtpParameters);
    const sdpFilePath = path.join(this.outputPath, 'stream.sdp');
    fs.writeFileSync(sdpFilePath, sdpContent);
    
    // 입력 추가
    command = command.concat([
      '-i', sdpFilePath
    ]);
    
    // HLS 출력 설정
    command = command.concat([
      // 비디오 인코딩 옵션
      '-map', '0:v:0',
      '-c:v', 'libx264',
      '-preset', 'veryfast',
      '-tune', 'zerolatency',
      '-profile:v', 'main',
      '-level', '4.1',
      '-b:v', '2000k',
      '-bufsize', '4000k',
      '-maxrate', '2500k',
      '-g', '60', // 2초마다 키프레임 (30fps 기준)
      '-keyint_min', '60',
      '-sc_threshold', '0',
      '-r', '30',
      
      // 오디오 인코딩 옵션 (오디오가 있는 경우)
      ...(audioRtpParameters ? [
        '-map', '0:a:0',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '48000',
        '-ac', '2'
      ] : []),
      
      // HLS 설정
      '-f', 'hls',
      '-hls_time', segmentDuration.toString(),
      '-hls_list_size', playlistLength.toString(),
      '-hls_flags', 'delete_segments+append_list',
      '-hls_delete_threshold', '4',
      '-hls_segment_type', 'mpegts',
      '-hls_segment_filename', path.join(this.outputPath, 'segment_%03d.ts'),
      '-method', 'PUT',
      path.join(this.outputPath, 'index.m3u8')
    ]);
    
    return command;
  }

  /**
   * SDP 파일 생성
   * @param {Object} videoRtpParameters - 비디오 RTP 파라미터
   * @param {Object} audioRtpParameters - 오디오 RTP 파라미터 (선택 사항)
   * @returns {string} SDP 파일 내용
   */
  generateSdpFile(videoRtpParameters, audioRtpParameters) {
    const videoTransportIp = this.videoTransport.tuple.localIp;
    const videoTransportPort = this.videoTransport.tuple.localPort;
    
    let sdp = `v=0
o=- 0 0 IN IP4 127.0.0.1
s=FFmpeg
c=IN IP4 ${videoTransportIp}
t=0 0
`;

    // 비디오 미디어 섹션
    const { codecs: videoCodecs, encodings: videoEncodings } = videoRtpParameters;
    const videoCodec = videoCodecs[0];
    const videoPayloadType = videoCodec.payloadType;
    const videoCodecName = videoCodec.mimeType.replace('video/', '');
    const videoClock = videoCodec.clockRate;
    
    sdp += `m=video ${videoTransportPort} RTP/AVP ${videoPayloadType}\n`;
    sdp += `a=rtpmap:${videoPayloadType} ${videoCodecName}/${videoClock}\n`;
    
    // 비디오 포맷 파라미터 추가
    if (videoCodec.parameters) {
      const fmtp = [];
      for (const [key, value] of Object.entries(videoCodec.parameters)) {
        fmtp.push(`${key}=${value}`);
      }
      if (fmtp.length > 0) {
        sdp += `a=fmtp:${videoPayloadType} ${fmtp.join(';')}\n`;
      }
    }
    
    sdp += `a=recvonly\n`;
    
    // 오디오 미디어 섹션 (오디오가 있는 경우)
    if (audioRtpParameters) {
      const audioTransportIp = this.audioTransport.tuple.localIp;
      const audioTransportPort = this.audioTransport.tuple.localPort;
      
      const { codecs: audioCodecs } = audioRtpParameters;
      const audioCodec = audioCodecs[0];
      const audioPayloadType = audioCodec.payloadType;
      const audioCodecName = audioCodec.mimeType.replace('audio/', '');
      const audioClock = audioCodec.clockRate;
      const audioChannels = audioCodec.channels || 2;
      
      sdp += `m=audio ${audioTransportPort} RTP/AVP ${audioPayloadType}\n`;
      sdp += `c=IN IP4 ${audioTransportIp}\n`;
      sdp += `a=rtpmap:${audioPayloadType} ${audioCodecName}/${audioClock}/${audioChannels}\n`;
      
      // 오디오 포맷 파라미터 추가
      if (audioCodec.parameters) {
        const fmtp = [];
        for (const [key, value] of Object.entries(audioCodec.parameters)) {
          fmtp.push(`${key}=${value}`);
        }
        if (fmtp.length > 0) {
          sdp += `a=fmtp:${audioPayloadType} ${fmtp.join(';')}\n`;
        }
      }
      
      sdp += `a=recvonly\n`;
    }
    
    return sdp;
  }

  /**
   * FFmpeg 프로세스 시작
   * @param {Array<string>} command - FFmpeg 명령어 배열
   */
  startFfmpeg(command) {
    console.log('FFmpeg 명령어 실행:', ['ffmpeg', ...command].join(' '));
    
    this.ffmpegProcess = spawn('ffmpeg', command, {
      detached: false,
      shell: false
    });
    
    this.ffmpegProcess.stdout.on('data', (data) => {
      console.log(`FFmpeg stdout: ${data}`);
    });
    
    this.ffmpegProcess.stderr.on('data', (data) => {
      console.log(`FFmpeg stderr: ${data}`);
    });
    
    this.ffmpegProcess.on('close', (code) => {
      console.log(`FFmpeg 프로세스 종료됨 (코드: ${code})`);
      this.ffmpegProcess = null;
      this.isRunning = false;
    });
    
    this.ffmpegProcess.on('error', (error) => {
      console.error('FFmpeg 프로세스 오류:', error);
      this.ffmpegProcess = null;
      this.isRunning = false;
    });
  }
}

module.exports = HlsService; 