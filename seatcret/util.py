from typing import List, Optional

from .seoul.subway.constants import STATION_ID_NAMES


def find_path(origin_id: str, destination_id: str, direction: int) -> Optional[List[str]]:
    if origin_id[:4] == '1002':  # 2호선 을지로순환선
        branch_id = origin_id[:8]
    else:
        branch_id = origin_id[:4]

    station_ids = [k for k in STATION_ID_NAMES if k.startswith(branch_id)]
    if branch_id == '10020002':  # 2호선 을지로순환선
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

    if path[-1] != destination_id:
        return None

    return path