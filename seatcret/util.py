from typing import List, Optional

from .seoul.subway.constants import STATION_ID_NAMES


def find_path(origin_id: str, destination_id: str, direction: int) -> Optional[List[str]]:
    branch_id = origin_id[:8]
    if branch_id != '10020002':  # 2호선 을지로순환선
        return None
    station_ids = [k for k in STATION_ID_NAMES if k.startswith(branch_id)]
    if direction == 1:
        cycle = reversed(station_ids * 2)
    else:
        cycle = station_ids * 2
    path = []
    origin_found = False
    for station_id in cycle:
        if station_id == origin_id:
            origin_found = True
        
        if origin_found:
            path.append(station_id)
            if station_id == destination_id:
                break
    return path

