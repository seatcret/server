import json
import os
import random
import time
import uuid
from datetime import datetime

import click
import segno
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from seoul.subway import Direction, STATION_ID_NAMES, SUBWAY_ID_NAMES

from .util import find_path
from .db import redis, get_itinerary, get_train, get_seats, delete_itinerary, get_subway_stations, get_subway_trains, set_seat, set_itinerary


app = Flask(__name__)
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
    redis.hset(f"user:{user_id}", mapping={
        'platform': platform,
        'token': token,
        'created_at': int(time.time()),
        'notification_itinerary_end': 'on',
        'notification_seat_vacancy': 'on',
    })
    return user_id, redis.hgetall(f"user:{user_id}")


def get_train_directions_for_subway(subway_id: str):
    trains = get_subway_trains(subway_id)
    return {
        0: [train for train in trains if train.direction == Direction.UP],
        1: [train for train in trains if train.direction == Direction.DOWN],
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
        path = find_path(
            train.station_id, itinerary['destination_id'], train.direction)
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
    stations = get_subway_stations(train.subway_id)
    return render_template(
        'seat.html', user=get_current_user(), url=url, qrcode=qr.svg_data_uri(),
        train_id=train_id, car_number=car_number, seat_number=seat_number,
        stations=stations, subway_id=subway_id, data=data,
    )


@app.route('/profile/')
def profile():
    user = get_current_user()
    if not user:
        return redirect_unsupported()

    created_at = datetime.utcfromtimestamp(
        int(user['created_at'])
    ).strftime('%Y-%m-%d %H:%M:%S')

    itinerary = get_itinerary(user['id'])
    if itinerary:
        train = get_train(itinerary['subway_id'], itinerary['train_id'])
        remaining_path = find_path(
            train.station_id,
            itinerary['destination_id'],
            train.direction
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


def redirect_unsupported():
    flash('지원하지 않는 기기입니다.')
    return redirect(url_for('home'))


@app.route('/itineraries/', methods=['POST'])
def add_itinerary():
    user = get_current_user()
    if not user:
        return redirect_unsupported()
    itinerary = get_itinerary(user['id'])
    if itinerary:
        flash("이미 등록된 여정이 있습니다.")
        return redirect(url_for('profile'))

    f = request.form
    subway_id = f['subway_id']
    train_id = f['train_id']
    car_number = f['car_number']
    seat_number = f['seat_number']
    user_id = user['id']
    destination_id = f['destination_id']
    if f['seated'] == 'true':
        seated = 'true'
    else:
        seated = 'false'

    train = get_train(subway_id, train_id)
    origin_id = train.station_id

    origin_name = STATION_ID_NAMES[origin_id]
    destination_name = STATION_ID_NAMES[destination_id]

    path = find_path(origin_id, destination_id, train.direction)
    if not path:
        flash(
            f"해당 열차로는 {origin_name}역에서 {destination_name}역까지 갈 수 없습니다. 열차 운행 방향을 확인해 주세요.")
        return redirect(request.referrer)

    set_itinerary(user_id, subway_id, train_id, origin_id, destination_id, seated, car_number, seat_number)
    if seated:
        set_seat(subway_id, train_id, car_number, seat_number, user_id)

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
        for station_id in path:
            try:
                random_seat_number = available_seat_numbers.pop()
            except:
                break
            random_user_id = f"dummy-{uuid.uuid4()}"
            set_seat(subway_id, train_id, car_number,
                     random_seat_number, random_user_id)
            set_itinerary(random_user_id, subway_id, train_id, origin_id, station_id, 'true', car_number, random_seat_number)

    flash(f"{origin_name}에서 {destination_name}까지의 여정이 추가되었습니다!")
    return redirect(url_for('profile'))


@app.route('/itineraries/delete/')
def end_itinerary():
    user = get_current_user()
    if not user:
        abort(403)
    delete_itinerary(user['id'])
    return redirect(url_for('profile'))


@app.cli.command()
def event_processor():
    from .monitor import initialize_firebase, update_subway_location, notify_getoff

    initialize_firebase()
    while True:
        update_subway_location()
        notify_getoff()
        time.sleep(10)


@app.cli.command()
def flush_user_data():
    """Delete all user data."""
    for key in redis.scan_iter('itinerary:*'):
        click.echo(f"Deleting itinerary: {key}")
        redis.delete(key)

    for key in redis.scan_iter('train:*:seats'):
        click.echo(f"Deleting seat data: {key}")
        redis.delete(key)

    for key in redis.scan_iter('user:*'):
        redis.delete('key')
        click.echo(f"Deleting user data: {key}")

    redis.delete('next_user_id')
    redis.delete('users')
