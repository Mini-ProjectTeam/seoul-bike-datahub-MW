# Docker Compose로 Spark 클러스터 구성 시 발생한 네트워크 연결 문제 해결기

데이터 파이프라인 구축 프로젝트에서 Docker Compose를 활용해 Airflow와 Spark를 통합한 데이터 플랫폼을 구성하는 과정에서 예상치 못한 네트워크 연결 문제에 직면했습니다. Spark Worker 컨테이너가 Spark Master에 연결하지 못해 지속적으로 종료되는 현상이 발생했고, 이를 해결하는 과정에서 Docker Compose 네트워킹의 중요한 개념을 다시 한번 깨닫게 되었습니다.

본 포스트에서는 문제 발생부터 해결까지의 전 과정을 상세히 기록하여, 비슷한 이슈를 겪고 있는 개발자분들께 도움이 되고자 합니다.

## 문제 상황 및 증상

Docker Compose를 통해 데이터 플랫폼을 구성하고 `docker-compose up -d` 명령어를 실행한 후, 대부분의 서비스는 정상적으로 실행되었으나 `spark-worker` 컨테이너만 몇 초 후 반복적으로 종료되는 현상이 관찰되었습니다.

컨테이너 로그를 확인한 결과, 다음과 같은 에러 메시지를 확인할 수 있었습니다:

```bash
$ docker logs spark_worker

ERROR Master: Failed to connect to master spark://spark_master:7077
org.apache.spark.SparkException: Exception thrown in awaitResult:
    at org.apache.spark.util.ThreadUtils$.awaitResult(ThreadUtils.scala:322)
    at org.apache.spark.rpc.RpcEnv.setupEndpointRefByURI(RpcEnv.scala:102)
    ...
Caused by: java.io.IOException: Failed to connect to spark_master/172.18.0.5:7077
    ...
Caused by: java.net.ConnectException: Connection refused
    ...
```

로그 분석 결과, Worker가 Master 서버에 연결을 시도하지만 연결이 거부되고 있음을 확인할 수 있었습니다.

## 초기 설정 및 문제가 있었던 구성

문제가 발생한 초기 `docker-compose.yml` 설정은 다음과 같았습니다:

```yaml
services:
  spark-master:
    image: bitnami/spark:3.5
    container_name: spark_master  # 컨테이너 이름을 명시적으로 지정
    environment:
      - SPARK_MODE=master
    ports:
      - "8081:8080"
      - "7077:7077"

  spark-worker:
    image: bitnami/spark:3.5
    container_name: spark_worker
    depends_on:
      - spark-master
    environment:
      - SPARK_MODE=worker
      - SPARK_MASTER_URL=spark://spark_master:7077  # 컨테이너 이름 사용
```

설정을 보면 `spark-master` 서비스에 `container_name: spark_master`를 명시적으로 지정했고, Worker에서는 이 컨테이너 이름을 통해 Master에 접근하도록 구성했습니다.

## 문제 해결을 위한 시도들

### 첫 번째 시도: localhost 주소 사용

동일한 Docker 환경 내에서 localhost를 통한 통신이 가능할 것으로 판단하여 `SPARK_MASTER_URL`을 `spark://localhost:7077`로 변경해보았습니다. 하지만 이 방법은 실패했습니다.

**실패 원인**: Docker 컨테이너는 각각 독립된 네트워크 네임스페이스를 가지므로, 컨테이너 내부의 localhost는 다른 컨테이너가 아닌 자기 자신을 가리킵니다.

### 두 번째 시도: 의존성 설정 재검토

Master 서비스가 완전히 초기화되기 전에 Worker가 연결을 시도하는 것일 가능성을 고려하여 `depends_on` 설정을 재검토했습니다. 하지만 해당 설정은 이미 올바르게 구성되어 있었고, `depends_on`은 컨테이너 시작 순서만 보장할 뿐 서비스의 완전한 준비 상태를 보장하지는 않는다는 점을 고려할 때 근본적인 해결책이 아님을 확인했습니다.

## 근본 원인 분석

문제의 핵심은 **Docker Compose 네트워킹에서 컨테이너 간 통신 시 사용해야 하는 호스트명의 차이**에 있었습니다.

Docker Compose 환경에서는 다음 두 가지 이름 개념이 존재합니다:

1. **Service Name**: `docker-compose.yml`에서 정의하는 최상위 키 (예: `spark-master`)
2. **Container Name**: `container_name` 속성으로 지정하는 컨테이너 식별명 (예: `spark_master`)

Docker Compose는 **Service Name**을 내부 DNS에 자동으로 등록하여 컨테이너 간 통신에 사용할 수 있도록 합니다. 반면 **Container Name**은 주로 호스트 시스템에서 특정 컨테이너를 관리하기 위한 용도로 사용되며, 컨테이너 간 네트워크 통신의 호스트명으로는 사용되지 않습니다.

따라서 Worker 컨테이너에서 `spark_master`(Container Name)로 연결을 시도했지만, Docker 내부 DNS에서는 이를 해석할 수 없어 연결이 실패한 것입니다.

## 해결 방법

문제를 해결하기 위해 Worker의 Master 연결 URL을 Container Name에서 Service Name으로 변경했습니다:

```yaml
services:
  spark-master:  # Service Name
    image: bitnami/spark:3.5
    container_name: spark_master  # Container Name (관리 목적)
    environment:
      - SPARK_MODE=master
    ports:
      - "8081:8080"
      - "7077:7077"

  spark-worker:
    image: bitnami/spark:3.5
    container_name: spark_worker
    depends_on:
      - spark-master
    environment:
      - SPARK_MODE=worker
      - SPARK_MASTER_URL=spark://spark-master:7077  # Service Name 사용
```

**핵심 변경사항**: `SPARK_MASTER_URL`의 호스트명을 `spark_master`에서 `spark-master`로 변경

이 수정 후 `docker-compose up -d --build` 명령어로 재실행한 결과, Spark Worker가 Master에 정상적으로 연결되었고, Spark Master UI(http://localhost:8081)에서도 활성 상태의 Worker를 확인할 수 있었습니다.

## 결론 및 Best Practice

이번 문제 해결 과정을 통해 Docker Compose 환경에서의 네트워크 통신 규칙을 명확히 이해할 수 있었습니다.

**핵심 원칙**:
- **컨테이너 간 통신**: Service Name 사용
- **호스트에서 컨테이너 관리**: Container Name 사용

Docker Compose를 활용한 멀티 컨테이너 환경 구성 시 이러한 네이밍 규칙을 정확히 이해하고 적용하는 것이 중요하며, 단순해 보이는 설정 실수가 예상치 못한 문제를 야기할 수 있다는 점을 다시 한번 확인할 수 있었습니다.

향후 유사한 프로젝트에서는 이러한 네트워킹 원칙을 처음부터 적용하여 불필요한 디버깅 시간을 줄일 수 있을 것으로 기대됩니다.