from typing import List, Optional

from .seoul.subway.constants import STATION_ID_NAMES


def get_branch_id(station_id: str):
    if station_id[:4] == '1002':  # 2호선 을지로순환선
        return station_id[:8]
    else:
        return station_id[:4]


def find_path(origin_id: str, destination_id: str, direction: int) -> Optional[List[str]]:
    # 환승은 지원하지 않음
    orig_branch_id = get_branch_id(origin_id)
    dest_branch_id = get_branch_id(destination_id)
    if orig_branch_id != dest_branch_id:
        return None

    station_ids = sorted(
        [k for k in STATION_ID_NAMES if k.startswith(orig_branch_id)])
    if orig_branch_id == '10020002':  # 2호선 을지로순환선
        station_ids *= 2
        if direction == 1:
            station_ids = reversed(station_ids)
    else:
        if direction == 0:
            station_ids = reversed(station_ids)

    path = []
    origin_found = False
    for station_id in station_ids:
        if station_id == origin_id:
            origin_found = True

        if origin_found:
            path.append(station_id)
            if station_id == destination_id:
                break

    if not path:
        return None
    if path[-1] != destination_id:
        return None
    return path
