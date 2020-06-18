import json
from typing import List

from redis import Redis
from seoul.subway import Train


redis = Redis(decode_responses=True)


def get_subway_trains(subway_id: str) -> List[dict]:
    train_ids = redis.smembers(f'subway:{subway_id}:trains')
    trains = []
    for train_id in train_ids:
        train = get_train(subway_id, train_id)
        trains.append(train)
    return trains


def get_subway_stations(subway_id: str) -> dict:
    return redis.hgetall(f"subway:{subway_id}:stations")


def get_train(subway_id: str, train_id: str) -> dict:
    return Train(**json.loads(redis.get(f"train:{subway_id}:{train_id}")))


def get_itinerary(user_id: str) -> dict:
    return redis.hgetall(f'itinerary:{user_id}')


def set_itinerary(user_id, subway_id, train_id, origin_id, destination_id, seated, car_number, seat_number) -> int:
    return redis.hset(f"itinerary:{user_id}", mapping={
        'subway_id': subway_id,
        'train_id': train_id,

        'origin_id': origin_id,
        'destination_id': destination_id,

        'seated': seated,
        'car_number': car_number,
        'seat_number': seat_number,
    })


def get_seats(subway_id: str, train_id: str) -> dict:
    seats = redis.hgetall(f'train:{subway_id}:{train_id}:seats')
    return seats


def set_seat(subway_id, train_id, car_number, seat_number, user_id) -> int:
    return redis.hset(f'train:{subway_id}:{train_id}:seats', f'{car_number}-{seat_number}', user_id)


def delete_seat(subway_id, train_id, car_number, seat_number) -> int:
    return redis.hdel(f'train:{subway_id}:{train_id}:seats', f'{car_number}-{seat_number}')


def delete_itinerary(user_id: str):
    itinerary = get_itinerary(user_id)
    if itinerary:
        if itinerary['seated'] == 'true':
            delete_seat(itinerary['subway_id'], itinerary['train_id'],
                        itinerary['car_number'], itinerary['seat_number'])
        redis.delete(f"itinerary:{user_id}")


def get_user(user_id: str) -> dict:
    return redis.hgetall(f"user:{user_id}")
