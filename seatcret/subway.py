from typing import List, Optional

import requests


SEOUL_REALTIME_LOCATION_API_URL = 'http://swopenAPI.seoul.go.kr/api/subway/{api_key}/{format}/realtimePosition/0/1000/{subway_name}'

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
    def __init__(self, api_key: str):
        self.api_key = api_key


    def get_realtime_location(self, subway_name: str) -> Optional[List]:
        r = requests.get(SEOUL_REALTIME_LOCATION_API_URL.format(
            api_key=self.api_key,
            format='json',
            subway_name=subway_name
        ))
        try:
            decoded = r.json()
        except ValueError:
            return None
        return decoded.get('realtimePositionList', None)
