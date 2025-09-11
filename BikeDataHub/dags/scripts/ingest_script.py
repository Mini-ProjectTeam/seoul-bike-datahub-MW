import requests
import json
import os
import boto3
from dotenv import load_dotenv
from botocore.exceptions import ClientError
from datetime import datetime

from BikeDataHub.dags.scripts.test import response


def ingest_ttareungi_data_to_minio():
    # 서울시 따릉이 API에서 데이터를 가져와 MinIO(S3)에 원시 Json으로 저장
    load_dotenv()
    API_KEY = os.environ.get("SEOUL_API_KEY")
    BASE_URL = f"http://openapi.seoul.go.kr:8088/{API_KEY}/json/bikeList"

    MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT")
    MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY")
    MINIO_BUCKET = "bronze"

    all_bike_data = []
    start_index = 1
    step = 1000

    while True:
        end_index = start_index + step - 1
        url = f"{BASE_URL}/{start_index}/{end_index}/"
        print(f"Fetching data from: {url}")
        # 진행상황 모니터링용 로드 구문
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        # 혹시 에러가 난다면 여기서 멈춰라.
        data = response.json()

        bike_list_data = data.get('rentBikeStatus', {}).get('row')
