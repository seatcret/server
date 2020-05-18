import json
import os
import random
import time
from datetime import datetime
from typing import Optional, List
from base64 import b64decode


import click
import requests
import segno
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from redis import Redis
import firebase_admin
from firebase_admin import messaging
from firebase_admin.credentials import Certificate
from firebase_admin.messaging import Message, Notification

from .constants import SUBWAY_ID_NAMES, SEAT_OCCUPIED, SEAT_UNKNOWN


SEOUL_REALTIME_LOCATION_API_URL = 'http://swopenAPI.seoul.go.kr/api/subway/{api_key}/{format}/realtimePosition/0/1000/{subway_name}'
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
    })
    return user_id, redis.hgetall(f"user:{user_id}")


@app.route('/')
def home():
    subways = {}
    for subway_id, subway_name in SUBWAY_ID_NAMES.items():
        train_ids = redis.smembers(f'trains:{subway_id}')
        trains = []
        for train_id in train_ids:
            train = redis.hgetall(f'train:{train_id}')
            trains.append(train)
        subways[subway_name] = trains
    return render_template('home.html', user=get_current_user(), subways=subways)


@app.route('/users/', methods=['POST'])
def register():
    register_user(request.json['platform'], request.json['token'])
    return ''


@app.route('/trains/<string:train_id>/')
def train(train_id: str):
    train = redis.hgetall(f"train:{train_id}")
    return render_template('train.html', train=train)


@app.route('/stations/<string:station_id>/')
def station(station_id: str):
    return ''


@app.route('/seats/<string:train_id>/<int:car_number>/<int:seat_number>/')
def seat(train_id: str, car_number: int, seat_number: int):
    url = url_for('seat', train_id=train_id,
                  car_number=car_number, seat_number=seat_number)
    qr = segno.make(f"https://seatcret.ji.hyeok.org{url}")
    seats = redis.hgetall(f'train:{train_id}:seats')

    train = get_train(train_id)
    stations = get_subway_stations(train['subway_id'])

    return render_template(
        'seat.html', user=get_current_user(), url=url, qrcode=qr.svg_data_uri(),
        train_id=train_id, car_number=car_number, seat_number=seat_number,
        stations=stations,
    )


@app.route('/profile/')
def profile():
    user = get_current_user()
    if not user:
        return redirect_unsupported()
    
    created_at=datetime.utcfromtimestamp(
        int(user['created_at'])
    ).strftime('%Y-%m-%d %H:%M:%S')

    itinerary = get_user_itinerary(user['id'])
    if itinerary:
        train = get_train(itinerary['train_id'])
    else:
        train = None

    return render_template('profile.html', user=user, created_at=created_at, itinerary=itinerary, train=train)


def get_user_itinerary(user_id: str):
    return redis.hgetall(f'itinerary:{user_id}')



def redirect_unsupported():
    flash('지원하지 않는 기기입니다.')
    return redirect(url_for('home'))


@app.route('/itineraries/', methods=['POST'])
def add_itinerary():
    user = get_current_user()
    if not user:
        return redirect_unsupported()

    
    train_id = request.form['train_id']
    destination_id = request.form['destination_id']

    train = get_train(train_id)
    stations = get_subway_stations(train['subway_id'])
    destination_name = stations[destination_id]

    redis.hset(f"itinerary:{user['id']}", mapping={
        'train_id': train_id,

        'origin_name': train['station_name'],
        'origin_id': train['station_id'],

        'destination_id': destination_id,
        'destination_name': destination_name,

        'seated': request.form['seated'],
        'car_number': request.form['car_number'],
        'seat_number': request.form['seat_number'],
    })

    flash(f"{train['station_name']}에서 {destination_name}까지의 여정이 추가되었습니다!")
    flash(f"목적지 역에 도착할 때 알림을 보내드려요.")
    return redirect(url_for('profile'))


@app.route('/itineraries/delete/')
def end_itinerary():
    user = get_current_user()
    if not user:
        abort(403)

    redis.delete(f"itinerary:{user['id']}")
    return redirect(url_for('profile'))


def get_train(train_id: str):
    train = redis.hgetall(f"train:{train_id}")
    return train


def get_realtime_location(subway_name: str) -> Optional[List]:
    r = requests.get(SEOUL_REALTIME_LOCATION_API_URL.format(
        api_key=SEOUL_API_KEY,
        format='json',
        subway_name=subway_name
    ))
    r.raise_for_status()
    decoded = r.json()
    return decoded.get('realtimePositionList', None)


def get_subway_stations(subway_id: str):
    return redis.hgetall(f"subway:{subway_id}:stations")


@app.cli.command()
def event_processor():
    update_subway_location()
    notify_getoff()


def update_subway_location():
    """Update realtime subway locations."""
    for subway_id, subway_name in SUBWAY_ID_NAMES.items():
        positions = get_realtime_location(subway_name)
        if not positions:
            continue

        subway_train_set_key = f'trains:{subway_id}'
        redis.delete(subway_train_set_key)
        click.echo(f"[{datetime.now()}] {subway_name}: 현재 {len(positions)} 개 차량 운행중")

        for p in positions:
            train_id = p['trainNo']
            station_id = p['statnId']
            station_name = p['statnNm']

            redis.sadd(subway_train_set_key, train_id)
            redis.hset(f"subway:{subway_id}:stations", station_id, station_name)
            redis.hset(f"train:{train_id}", mapping={
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


def notify_getoff():
    fcm_messages = []

    keys = redis.keys("itinerary:*")
    for key in keys:
        user_id = key.split(':')[-1]
        user = get_user(user_id)

        itinerary = redis.hgetall(key)
        train_id = itinerary['train_id']
        train = get_train(train_id)
        if train['station_id'] == itinerary['destination_id']:
            redis.delete(key)
            if user['platform'] == 'fcm':
                message = Message(
                    notification=Notification('여정이 끝났습니다!', '하차하세요~'),
                    token=user['token'],
                )
                fcm_messages.append(message)

    click.echo(f"[{datetime.now()}] {len(fcm_messages)} 개 FCM 알람 발송")