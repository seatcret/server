import json
import os
import random
import time
import uuid
from base64 import b64decode
from datetime import datetime
from typing import List

import click
import firebase_admin
import requests
import segno
from click import ClickException
from firebase_admin.credentials import Certificate
from firebase_admin import messaging
from firebase_admin.messaging import Message, Notification
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from redis import Redis

from .constants import SEAT_OCCUPIED, SEAT_UNKNOWN
from .seoul.subway.constants import STATION_ID_NAMES, SUBWAY_ID_NAMES
from .seoul.subway import Client
from .util import find_path


SEOUL_API_KEY= os.environ['SEOUL_API_KEY']
FIREBASE_PRIVATE_KEY = json.loads(b64decode(os.environ['FIREBASE_PRIVATE_KEY']))

cred = Certificate(FIREBASE_PRIVATE_KEY)
firebase_admin.initialize_app(cred)

app = Flask(__name__)
redis = Redis(decode_responses=True)

app.config['SECRET_KEY'] = os.environ['SECRET_KEY']


def get_current_user():
    token = request.cookies.get('token')
    if not token:
        return None

    platform, token = token.split(':', 1)
    user_id = redis.hget('users', f"{platform}:{token}")
    if user_id:
        user = redis.hgetall(f"user:{user_id}")
    else:
        user_id, user = register_user(platform, token)

    user['id'] = user_id
    return user


def register_user(platform: str, token: str):
    user_id = redis.incr('next_user_id')
    redis.hset('users', f"{platform}:{token}", user_id)
    redis.hset(f"user:{user_id}", mapping= {
        'platform': platform,
        'token': token,
        'created_at': int(time.time()),
        'notification_itinerary_end': 'on',
        'notification_seat_vacancy': 'on',
    })
    return user_id, redis.hgetall(f"user:{user_id}")


def get_subway_trains(subway_id: str):
    train_ids = redis.smembers(f'subway:{subway_id}:trains')
    trains = []
    for train_id in train_ids:
        train = redis.hgetall(f'train:{subway_id}:{train_id}')
        trains.append(train)
    return trains


def get_train_directions_for_subway(subway_id: str):
    trains = get_subway_trains(subway_id)
    return {
        0: [train for train in trains if train['direction'] == '0'],
        1: [train for train in trains if train['direction'] == '1'],
    }


@app.route('/')
def home():
    subways = {}
    for subway_id in SUBWAY_ID_NAMES:
        subways[subway_id] = get_train_directions_for_subway(subway_id)
    return render_template('home.html', user=get_current_user(),
                           subways=subways, SUBWAY_ID_NAMES=SUBWAY_ID_NAMES)


@app.route('/subways/<string:subway_id>/')
def subway(subway_id: str):
    train_directions = get_train_directions_for_subway(subway_id)
    return render_template('subway.html', user=get_current_user(), subway_id=subway_id,
                           train_directions=train_directions, SUBWAY_ID_NAMES=SUBWAY_ID_NAMES)


@app.route('/users/', methods=['POST'])
def register():
    register_user(request.json['platform'], request.json['token'])
    return ''


@app.route('/trains/<string:subway_id>/<string:train_id>/')
def train(subway_id: str, train_id: str):
    train = get_train(subway_id, train_id)
    seats = get_seats(subway_id, train_id)

    eta = {}
    for key, user_id in seats.items():
        used_car_number, used_seat_number = key.split('-')
        itinerary = get_itinerary(user_id)
        path = find_path(itinerary['origin_id'], itinerary['destination_id'], train['direction'])
        if path:
            eta[key] = len(path) - 1

    return render_template('train.html', train=train, seats=seats, eta=eta)


@app.route('/seats/<string:subway_id>/<string:train_id>/<int:car_number>/<int:seat_number>/')
def seat(subway_id: str, train_id: str, car_number: int, seat_number: int):
    url = url_for('seat', subway_id=subway_id, train_id=train_id,
                  car_number=car_number, seat_number=seat_number)
    data = f"https://seatcret.ji.hyeok.org{url}"
    qr = segno.make(data)
    seats = get_seats(subway_id, train_id)
    train = get_train(subway_id, train_id)
    stations = get_subway_stations(train['subway_id'])
    return render_template(
        'seat.html', user=get_current_user(), url=url, qrcode=qr.svg_data_uri(),
        train_id=train_id, car_number=car_number, seat_number=seat_number,
        stations=stations, subway_id=subway_id, data=data,
    )


def get_seats(subway_id: str, train_id: str) -> List:
    seats = redis.hgetall(f'train:{subway_id}:{train_id}:seats')
    return seats


@app.route('/profile/')
def profile():
    user = get_current_user()
    if not user:
        return redirect_unsupported()
    
    created_at=datetime.utcfromtimestamp(
        int(user['created_at'])
    ).strftime('%Y-%m-%d %H:%M:%S')

    itinerary = get_itinerary(user['id'])
    if itinerary:
        train = get_train(itinerary['subway_id'], itinerary['train_id'])
        remaining_path = find_path(
            train['station_id'],
            itinerary['destination_id'],
            int(train['direction'])
        )
    else:
        train = None
        remaining_path = None

    return render_template('profile.html', user=user, created_at=created_at, itinerary=itinerary, train=train,
                           STATION_ID_NAMES=STATION_ID_NAMES, remaining_path=remaining_path)


@app.route('/profile/', methods=['POST'])
def update_profile():
    user = get_current_user()
    redis.hset(f"user:{user['id']}", mapping={
        'notification_itinerary_end': 'on' if 'notification_itinerary_end' in request.form else 'off',
        'notification_seat_vacancy': 'on' if 'notification_seat_vacancy' in request.form else 'off',
    })
    flash('변경된 설정이 적용되었습니다.')
    return redirect(url_for('profile'))


def get_itinerary(user_id: str):
    return redis.hgetall(f'itinerary:{user_id}')


def redirect_unsupported():
    flash('지원하지 않는 기기입니다.')
    return redirect(url_for('home'))


def humanize_path(station_ids: List[str]):
    return ', '.join([STATION_ID_NAMES[station_id] for station_id in path])


@app.route('/itineraries/', methods=['POST'])
def add_itinerary():
    user = get_current_user()
    if not user:
        return redirect_unsupported()

    f = request.form
    subway_id = f['subway_id']
    train_id = f['train_id']
    car_number = f['car_number']
    seat_number = f['seat_number']
    user_id = user['id']
    destination_id = f['destination_id']
    seated = f['seated'] == 'true'

    train = get_train(subway_id, train_id)
    origin_id = train['station_id']

    origin_name = STATION_ID_NAMES[origin_id]
    destination_name = STATION_ID_NAMES[destination_id]

    path = find_path(origin_id, destination_id, int(train['direction']))
    if not path:
        flash(f"해당 열차로는 {origin_name}역에서 {destination_name}역까지 갈 수 없습니다. 열차 운행 방향을 확인해 주세요.")
        return redirect(request.referrer)

    redis.hset(f"itinerary:{user_id}", mapping={
        'subway_id': subway_id,
        'train_id': train_id,

        'origin_id': origin_id,
        'destination_id': destination_id,

        'seated': f['seated'],
        'car_number': car_number,
        'seat_number': seat_number,
    })
    if seated:
        set_seat(subway_id, train_id, car_number, seat_number, user_id)

    flash(f"{origin_name}에서 {destination_name}까지의 여정이 추가되었습니다!")
    flash(f"다음 역을 거쳐갑니다: {humanize_path(path)}")
    flash(f"목적지 역에 도착할 때 알림을 보내드려요.")

    # test harness for demonstration
    if 'add_test_users' in f and f['add_test_users'] == 'on':
        seats = get_seats(subway_id, train_id)
        used_seat_numbers = set()
        for key, user_id in seats.items():
            used_car_number, used_seat_number = key.split('-')
            if used_car_number == car_number:
                used_seat_numbers.add(int(used_seat_number))

        available_seat_numbers = list(set(range(1, 41)) - used_seat_numbers)
        random.shuffle(available_seat_numbers)
        path = find_path(train['station_id'], f['destination_id'], train['direction'])
        if path:
            for station_id in path:
                try:
                    random_seat_number = available_seat_numbers.pop()
                except:
                    break
                random_user_id = f"dummy-{uuid.uuid4()}"
                set_seat(subway_id, train_id, car_number, random_seat_number, random_user_id)
                redis.hset(f"itinerary:{random_user_id}", mapping={
                    'subway_id': subway_id,
                    'train_id': train_id,

                    'origin_id': train['station_id'],
                    'destination_id': station_id,

                    'seated': "true",
                    'car_number': car_number,
                    'seat_number': random_seat_number,
                })


    return redirect(url_for('profile'))


def set_seat(subway_id, train_id, car_number, seat_number, user_id):
    return redis.hset(f'train:{subway_id}:{train_id}:seats', f'{car_number}-{seat_number}', user_id)


def delete_seat(subway_id, train_id, car_number, seat_number):
    return redis.hdel(f'train:{subway_id}:{train_id}:seats', f'{car_number}-{seat_number}')


@app.route('/itineraries/delete/')
def end_itinerary():
    user = get_current_user()
    if not user:
        abort(403)

    _end_itinerary(user['id'])
    return redirect(url_for('profile'))


def get_train(subway_id: str, train_id: str):
    return redis.hgetall(f"train:{subway_id}:{train_id}")


def get_subway_stations(subway_id: str):
    return redis.hgetall(f"subway:{subway_id}:stations")


@app.cli.command()
def event_processor():
    while True:
        update_subway_location()
        notify_getoff()
        time.sleep(10)


def update_subway_location():
    """Update realtime subway locations."""
    client = Client(SEOUL_API_KEY)

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
    

def get_user(user_id: str):
    return redis.hgetall(f"user:{user_id}")


@app.cli.command()
def flush_user_data():
    """Delete all user data."""
    for key in redis.scan_iter('itinerary:*'):
        click.echo(f"Deleting itinerary: {key}")
        redis.delete(key)

    for key in redis.scan_iter('train:*:seats'):
        click.echo(f"Deleting seat data: {key}")
        redis.delete(key)


def _end_itinerary(user_id: str):
    itinerary = get_itinerary(user_id)
    redis.delete(f"itinerary:{user_id}")
    if itinerary['seated'] == 'true':
        delete_seat(itinerary['subway_id'], itinerary['train_id'], itinerary['car_number'], itinerary['seat_number'])


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
            _end_itinerary(user_id)
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
