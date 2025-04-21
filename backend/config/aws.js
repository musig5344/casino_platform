/**
 * AWS 서비스 설정
 * 환경 변수에서 값을 가져오거나 기본값 사용
 */

// 현재 환경
const environment = process.env.NODE_ENV || 'development';

// AWS 리전
const region = process.env.AWS_REGION || 'ap-northeast-2';

// MediaLive 설정
const mediaLive = {
  region,
  inputId: process.env.MEDIALIVE_INPUT_ID,
  channelId: process.env.MEDIALIVE_CHANNEL_ID,
  streamKey: process.env.MEDIALIVE_STREAM_KEY,
  cloudFrontDomain: process.env.CLOUDFRONT_DOMAIN,
  roleArn: process.env.MEDIALIVE_ROLE_ARN,
  s3Bucket: process.env.MEDIALIVE_S3_BUCKET,
  defaultResolution: process.env.MEDIALIVE_DEFAULT_RESOLUTION || '1280x720',
  defaultFrameRate: parseInt(process.env.MEDIALIVE_DEFAULT_FRAMERATE || '30', 10)
};

// ElastiCache 설정
const elastiCache = {
  primaryEndpoint: process.env.ELASTICACHE_PRIMARY_ENDPOINT,
  port: parseInt(process.env.ELASTICACHE_PORT || '6379', 10),
  useTLS: process.env.ELASTICACHE_USE_TLS === 'true',
  ttl: {
    default: parseInt(process.env.ELASTICACHE_DEFAULT_TTL || '3600', 10), // 1시간
    gameState: parseInt(process.env.ELASTICACHE_GAME_STATE_TTL || '1800', 10), // 30분
    dealerInfo: parseInt(process.env.ELASTICACHE_DEALER_INFO_TTL || '86400', 10) // 24시간
  }
};

// Lambda 설정
const lambda = {
  region,
  streamingFunction: process.env.LAMBDA_STREAMING_FUNCTION,
  gameLogicFunction: process.env.LAMBDA_GAME_LOGIC_FUNCTION,
  timeout: parseInt(process.env.LAMBDA_TIMEOUT || '30000', 10) // 30초
};

// S3 설정
const s3 = {
  region,
  bucket: process.env.S3_BUCKET,
  dealerAssetPrefix: process.env.S3_DEALER_ASSET_PREFIX || 'dealers/',
  gameAssetPrefix: process.env.S3_GAME_ASSET_PREFIX || 'games/'
};

// MediaConnect 설정
const mediaConnect = {
  region,
  flowArn: process.env.MEDIACONNECT_FLOW_ARN
};

// SageMaker 설정
const sageMaker = {
  region,
  endpointName: process.env.SAGEMAKER_ENDPOINT_NAME
};

// CloudWatch 설정
const cloudWatch = {
  region,
  logGroup: process.env.CLOUDWATCH_LOG_GROUP,
  alarmPrefix: process.env.CLOUDWATCH_ALARM_PREFIX || 'CasinoPlatform'
};

// API Gateway 설정
const apiGateway = {
  baseUrl: process.env.API_GATEWAY_BASE_URL
};

// EC2 스팟 인스턴스 설정
const ec2Spot = {
  instanceType: process.env.EC2_SPOT_INSTANCE_TYPE || 'g4dn.xlarge',
  securityGroupId: process.env.EC2_SECURITY_GROUP_ID,
  subnetId: process.env.EC2_SUBNET_ID,
  iamRole: process.env.EC2_IAM_ROLE
};

module.exports = {
  environment,
  region,
  mediaLive,
  elastiCache,
  lambda,
  s3,
  mediaConnect,
  sageMaker,
  cloudWatch,
  apiGateway,
  ec2Spot
}; 