from typing import List

import requests


SAMPLE_API_KEY = 'sample'
SEOUL_REALTIME_LOCATION_API_URL = 'http://swopenAPI.seoul.go.kr/api/subway/{api_key}/{format}/realtimePosition/{start_index}/{end_index}/{subway_name}'

SUBWAY_ID_NAMES = {
    '1001': '1호선',
    '1002': '2호선',
    '1003': '3호선',
    '1004': '4호선',
    '1005': '5호선',
    '1006': '6호선',
    '1007': '7호선',
    '1008': '8호선',
    '1009': '9호선',
    '1063': '경의중앙선',
    '1065': '공항철도',
    '1067': '경춘선',
    '1071': '수인선',
    '1075': '분당선',
    '1077': '신분당선',
    '1092': '우이신설선',
}


class SeoulSubway:
    def __init__(self, api_key: str = SAMPLE_API_KEY):
        self.api_key = api_key

    def get_realtime_location(self, subway_name: str,
                              start_index: int = 0, end_index: int = 1000) -> List:
        if self.api_key == SAMPLE_API_KEY:
            start_index = 0
            end_index = 50

        url = SEOUL_REALTIME_LOCATION_API_URL.format(
            api_key=self.api_key,
            format='json',
            subway_name=subway_name,
            start_index=start_index,
            end_index=end_index,
        )
        r = requests.get(url)
        r.raise_for_status()

        d = r.json()
        if 'realtimePositionList' not in d:
            """
            code: INFO-200
            message: 해당하는 데이터가 없습니다.

            해당 지하철 노선 운행이 종료되었을 때 반환됨.
            """
            if d['status'] == 500 and d['code'] == 'INFO-200':
                return []

            raise Exception(f"{d['code']}: {d['message']}")
        else:
            return d['realtimePositionList']
