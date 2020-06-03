from typing import List

from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from ..constants import OPENAPI_BASE_URL, SAMPLE_API_KEY


REALTIME_POSITION_API_URL = '/api/subway/{api_key}/{format}/realtimePosition/{start_index}/{end_index}/{subway_name}'


class Client:
    def __init__(self, api_key: str = SAMPLE_API_KEY):
        self.api_key = api_key

    def get_realtime_position(self, subway_name: str,
                              start_index: int = 0, end_index: int = 1000) -> List:
        if self.api_key == SAMPLE_API_KEY:
            start_index = 0
            end_index = 50

        s = Session()
        retries = Retry(status_forcelist=[503])
        s.mount(OPENAPI_BASE_URL, HTTPAdapter(max_retries=retries))
        url = OPENAPI_BASE_URL + REALTIME_POSITION_API_URL.format(
            api_key=self.api_key,
            format='json',
            subway_name=subway_name,
            start_index=start_index,
            end_index=end_index,
        )
        r = s.get(url)
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
