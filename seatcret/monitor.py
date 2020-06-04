import os
import json
from base64 import b64decode
from datetime import datetime

import click
import firebase_admin
from firebase_admin.credentials import Certificate
from firebase_admin import messaging
from firebase_admin.messaging import Message, Notification

from .seoul.subway import Client
from .seoul.subway.constants import SUBWAY_ID_NAMES
from .db import redis, get_user, get_itinerary, get_train, delete_itinerary


def initialize_firebase():
    private_key = json.loads(b64decode(os.environ['FIREBASE_PRIVATE_KEY']))
    cred = Certificate(private_key)
    firebase_admin.initialize_app(cred)


def update_subway_location():
    """Update realtime subway locations."""
    client = Client(os.environ['SEOUL_API_KEY'])

    for subway_id, subway_name in SUBWAY_ID_NAMES.items():
        try:
            positions = client.get_realtime_position(subway_name)
        except:
            continue

        subway_train_set_key = f'subway:{subway_id}:trains'
        redis.delete(subway_train_set_key)
        click.echo(f"[{datetime.now()}] {subway_name}: 현재 {len(positions)} 개 차량 운행중")

        for p in positions:
            train_id = p['trainNo']
            station_id = p['statnId']
            station_name = p['statnNm']

            redis.sadd(subway_train_set_key, train_id)
            redis.hset(f"subway:{subway_id}:stations", station_id, station_name)
            redis.hset(f"train:{subway_id}:{train_id}", mapping={
                'id': train_id,

                'subway_id': subway_id,
                'subway_name': subway_name,

                'station_id': station_id,
                'station_name': station_name,

                'terminal_station_id': p['statnTid'],
                'terminal_station_name': p['statnTnm'],

                'direction': p['updnLine'],
                'status': p['trainSttus'],
                'is_express': p['directAt'],
                'is_last': p['lstcarAt'],

                'last_reception_date': p['lastRecptnDt'],
                'received_at': p['recptnDt'],
            })


def notify_getoff():
    fcm_messages = []
    standing_users = {}
    vacancies_created_car_ids = set()

    itinerary_keys = redis.keys("itinerary:*")
    for itinerary_key in itinerary_keys:
        user_id = itinerary_key.split(':')[-1]
        user = get_user(user_id)
        itinerary = get_itinerary(user_id)
        train = get_train(itinerary['subway_id'], itinerary['train_id'])
        car_id = f"{train['subway_id']}-{train['id']}-{itinerary['car_number']}"

        if train['station_id'] == itinerary['destination_id']:
            delete_itinerary(user_id)
            vacancies_created_car_ids.add(car_id)
            if user_id.startswith('dummy'):
                continue

            # send notification to users who need to get off the train
            if user.get('notification_itinerary_end', 'on') == 'on' and user['platform'] == 'fcm':
                message = Message(
                    notification=Notification('여정이 끝났습니다!', '하차하세요~'),
                    token=user['token'],
                )
                fcm_messages.append(message)
        else:
            # collect real users who are standing and whose itinerary is ongoing
            if user_id.startswith('dummy'):
                continue

            if itinerary['seated'] == "false":
                if car_id not in standing_users:
                    standing_users[car_id] = []
                standing_users[car_id].append(user)
    
    for car_id in vacancies_created_car_ids:
        if car_id in standing_users:
            for user in standing_users[car_id]:
                if user.get('notification_seat_vacancy', 'on') == 'on' and user['platform'] == 'fcm':
                    message = Message(
                        notification=Notification('자리가 생겼습니다!', '착석하세요~'),
                        token=user['token'],
                    )
                    fcm_messages.append(message)

    # bulk send FCM messages
    messaging.send_all(fcm_messages)
    for m in fcm_messages:
        click.echo(f"token: {m.token} title: {m.notification.title} body: {m.notification.body}")
    click.echo(f"[{datetime.now()}] {len(fcm_messages)} 개 FCM 알람 발송")