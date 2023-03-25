#!/usr/bin/python3

# Kotodoski

# Данный сервер предназначен для хостинга на бесплатном Deta Spaces.
# Написан криво, и для серьёзных игр НЕ годится.
# Просто фигачим всё из config.py сюда
from config import *

from flask import Flask, request, Response
from datetime import datetime, timezone, timedelta
import hashlib
import os
import requests
from threading import Lock
import json

app = Flask(__name__)
lock = Lock()
data: dict = None
data_serialized = ''

def get_current_datetime() -> float:
    return datetime.now(timezone.utc).timestamp()

def get_current_date() -> float:
    # Нам пофиг на *время* т.к. сервер мог быть запущен
    # хоть в полдень, хоть в полночи, и нам нужно как-то нормально оперировать.
    # По этому здесь время игнорируется, и уже нужные часы/минуты/недели добавляются
    dtnow = datetime.now(timezone.utc)
    return datetime(dtnow.year, dtnow.month, dtnow.day).timestamp()


def get_next_reset_date(reset_type: str) -> float:
    dtnow = datetime.now(timezone.utc)

    if not reset_type:
        return 0
    elif reset_type == 'day':
        return (dtnow + timedelta(days=1)).timestamp()
    elif reset_type == 'week':
        return (dtnow + timedelta(weeks=1)).timestamp()
    elif reset_type == 'hour':
        return (dtnow + timedelta(hours=1)).timestamp()
    return 0


def backup_data():
    global data_serialized
    data_serialized = json.dumps(data)

    if not CONFIG_BACKUP_PATH:
        return
    
    try:
        os.makedirs(name=CONFIG_BACKUP_PATH, exist_ok=True)
        txt_path = os.path.join(CONFIG_BACKUP_PATH, 'leaderboards.json')
        with open(txt_path, 'w') as txt:
            txt.write(data_serialized)
        app.logger.info('Backed up leaderboards info to ' + txt_path)
    except:
        app.logger.info('Failed to back up leaderboards :(')


def load_backup_data_if_present():
    global data
    global data_serialized

    if not CONFIG_BACKUP_PATH:
        return False

    try:
        txt_path = os.path.join(CONFIG_BACKUP_PATH, 'leaderboards.json')
        with open(txt_path, 'r') as txt:
            data = json.load(txt)
        data_serialized = json.dumps(data)
        return True
    except:
        return False


def init_if_not_already():
    global data
    global data_serialized

    if data is not None:
        # уже...
        return
    
    if load_backup_data_if_present():
        return

    data = {}

    for key, value in CONFIG_LEADERBOARD_INFO.items():
        data[key] = {
            'reset_every': value['reset_every'],
            'reset_date': get_next_reset_date(value['reset_every']),
            'sort_in_reverse': value['reverse_sort'],
            'allow_overwrite': value['allow_overwrite'],
            'max_entries': value['max_entries'],
            'array': []
        }
        app.logger.info('Adding leaderboard with id of ', key, ' to the party...')
    
    data_serialized = json.dumps(data)
    app.logger.info('Initialized the leaderboard data')


def reset_leaderboards_if_necessary():
    global data

    dtnow = get_current_date()

    for key in data:
        dtreset = data[key]['reset_date']
        if not dtreset:
            continue

        if dtnow >= dtreset:
            app.logger.info('!!! Resetting leaderboard with id of ', key)
            data[key]['array'].clear()
            data[key]['reset_date'] = get_next_reset_date(data[key]['reset_every'])
            app.logger.info('!!! Resetted ', key)


def pre_request():
    init_if_not_already()
    reset_leaderboards_if_necessary()


def entry_sort_function(item) -> int:
    return item['score']


def impl_post_leaderboard(user_id: str, user_name: str, leaderboard_id: str, metadata: str, score: int) -> tuple[bool, str]:
    global data
    pre_request()

    # нет смысла иметь отрицательные или нулевые очки в таблице рекордов...
    if score is None or score <= 0:
        return (False, json.dumps({'status':-1,'error':'param score is invalid'}))

    if not user_id:
        return (False, json.dumps({'status':-2,'error':'param user_id is invalid'}))
    
    if not user_name:
        return (False, json.dumps({'status':-3,'error':'param user_name is invalid'}))
    
    if not leaderboard_id:
        return (False, json.dumps({'status':-4,'error':'param leaderboard_id is invalid'}))
    
    if not (leaderboard_id in data):
        return (False, json.dumps({'status':-5,'error':'leaderboard with given leaderboard_id does not exist'}))

    board_array: list = data[leaderboard_id]['array']
    for idx in range(len(board_array)):
        # ищем есть ли мы уже в табличке
        if board_array[idx]['user_id'] == user_id:
            if data[leaderboard_id]['allow_overwrite']:
                # если включена перезапись, то убираем старую запись
                board_array.pop(idx)
                break
            else:
                # если не включена, то возвращаем ошибку
                return (False, json.dumps({'status':0,'error':'an entry for given user_id already exists'}))

    # добавляем запись о пользователе в конец таблицы
    metadatastr = None
    if metadata is not None:
        metadatastr = str(metadata)
    board_array.append({
        'user_id': user_id,
        'user_name': user_name,
        'score': score,
        'timestamp': get_current_datetime(),
        'metadata': metadatastr,
    })
    # делаем пересортировку согласно параметрам таблицы
    board_array.sort(
        key = entry_sort_function,
        # :) потому что доски почёта обычно сортируются от БкМ
        reverse = not data[leaderboard_id]['sort_in_reverse']
    )
    # если назначен max_entries и есть лишние записи, убираем
    max_entries = data[leaderboard_id]['max_entries']
    if (max_entries is not None) and (max_entries > 0) and (len(board_array) > max_entries):
        how_many = len(board_array) - max_entries
        # обрубаем лишнее, здесь len всегда больше max_entries, и не равно ему.
        for _ in range(how_many):
            board_array.pop()
    # перенаходим наш индекс
    our_index = -1
    for idx in range(len(board_array)):
        if board_array[idx]['user_id'] == user_id:
            our_index = idx
            break
    if our_index == -1:
        # такого надеюсь не будет
        app.logger.error('!!! FATAL ERROR in leaderboard data for ', leaderboard_id, ' please inspect!')
        return (False, json.dumps({'status':-6,'error':'unable to find new entry index after sorting, WTF?!'}))
    backup_data()
    # йиппи!!!!1
    return (True, json.dumps({'status':1,'error':'','new_entry_index':our_index}))


def impl_get_leaderboard(user_id: str, leaderboard_id: str, index_start: int, amount: int) -> tuple[bool, str]:
    pre_request()

    if not user_id:
        return (False, json.dumps({'status':-1,'error':'param user_id is invalid'}))

    if not leaderboard_id:
        return (False, json.dumps({'status':-2,'error':'param leaderboard_id is invalid'}))
    
    if (index_start is None) or (index_start < -1):
        return (False, json.dumps({'status':-3,'error':'param index_start is invalid'}))
    
    # index_start == -1 значит вывести относительно нашего пользователя
    
    if not (leaderboard_id in data):
        return (False, json.dumps({'status':-4,'error':'leaderboard with given leaderboard_id does not exist'}))
    
    # amount <= 0 значит вывести до конца списка, если возможно.
    if amount < 0:
        return (False, json.dumps({'status':-5,'error':'param amount is invalid'}))

    board_array: list = data[leaderboard_id]['array']
    entries = len(board_array)
    
    # index_start == -1 значит искать относительно нас
    if index_start == -1:
        # собственно пытаемся найти "нас"
        for idx in range(len(board_array)):
            if board_array[idx]['user_id'] == user_id:
                index_start = idx
                break
    
    if index_start == -1:
        # был дан индекс -1 (искать относительно нас), но мы "нас" так и не нашли!
        return (False, json.dumps({'status':0,'error':'index_start is -1 but player with specified user_id is not present'}))

    if amount == 0:
        amount = entries - index_start
    
    tmplist = []
    for idx in range(index_start, index_start + amount):
        if idx >= entries:
            break

        entry = board_array[idx]
        tmplist.append(entry)

    return (True, json.dumps({'status':1,'error':'','entries':tmplist,'amount':len(tmplist),'total':entries}))


gas_session_cache = {}
gas_lock = Lock()


def do_gas_sign_sort_function(item) -> str:
    return item['key']


def do_gas_sign(contents: dict[str, str], secret: str) -> str:
    # сортировка по ключам
    templist = []
    for key, value in contents.items():
        templist.append({'key': key, 'value': value})
    templist.sort(key=do_gas_sign_sort_function)
    # создание строки для подписи
    tempstr = ''
    for item in templist:
        tempstr += item['key'] + '=' + item['value']
    tempstr += secret
    # переводим в utf-8 байтики
    tempstru8 = tempstr.encode('utf-8')
    # создание хэша строки
    sign = hashlib.md5(tempstru8).hexdigest()
    return sign


def do_gas_request(gas_uid: str, gas_hash: str, gas_ip: str) -> tuple[bool, str]:
    # -> bool - True / str это имя пользователя, False / это json с ошибкой.

    with gas_lock:
        if not gas_uid:
            return (False, json.dumps({'status':-10,'error':'param gas_uid is invalid'}))
        
        if not gas_hash:
            return (False, json.dumps({'status':-11,'error':'param gas_hash is invalid'}))
        
        if not gas_ip:
            return (False, json.dumps({'status':-12,'error':'param gas_ip is invalid'}))
        
        gas_gmr_id = str(CONFIG_GAS_GMR_ID)
        if not gas_gmr_id:
            return (False, json.dumps({'status':-13,'error':'param gas_gmr_id is invalid'}))
        
        gas_secret = CONFIG_GAS_SECRET
        if not gas_secret:
            return (False, json.dumps({'status':-14,'error':'param gas_secret is invalid'}))
        
        # чистим кэш если он забит
        if len(gas_session_cache) > CONFIG_GAS_MAX_CACHE_ENTRIES:
            app.logger.info('Clearing GAS session cache...')
            gas_session_cache.clear()
            app.logger.info('GAS session cache has been emptied')
        
        # если мы уже авторизованы то получаем имя пользователя
        cache_key = gas_gmr_id + gas_secret + gas_uid + gas_hash + gas_ip
        if cache_key in gas_session_cache:
            # нашли в кэше
            return (True, gas_session_cache[cache_key])
        
        gas_sign = do_gas_sign({
            'uid': gas_uid,
            'hash': gas_hash,
            'ip': gas_ip,
            'appid': gas_gmr_id
        }, gas_secret)
        if not gas_sign:
            return (False, json.dumps({'status':-15,'error':'failed to calculate gas_sign'}))
        
        gas_url = f'https://vkplay.ru/app/{gas_gmr_id}/gas?uid={gas_uid}&hash={gas_hash}&ip={gas_ip}&sign={gas_sign}'

        try:
            ok = requests.get(gas_url, headers={'User-Agent': CONFIG_SERVER_USER_AGENT})
            if ok.status_code >= 400:
                return (False, json.dumps({'status':-16,'error':'gas api request forbidden'}))
            ok_json = ok.json()
            ok_json_status = ok_json['status']
            if ok_json_status != 'ok':
                return (False, json.dumps({'status':-17,'error':'gas api status failed'}))
            
            # TODO: пихать что-то полезнее чем 'ok'?
            gas_session_cache[cache_key] = ok_json_status
            return (True, cache_key)
        except:
            return (False, json.dumps({'status':-18,'error':'gas api request failed'}))


vksteam_ticket_cache = {}
vksteam_lock = Lock()


def do_vksteam_verify_ticket(ticket: str, user_id: str) -> tuple[bool, str]:
    with vksteam_lock:
        if not user_id:
            return (False, json.dumps({'status':-20,'error':'param user_id is invalid'}))
        
        if not ticket:
            return (False, json.dumps({'status':-21,'error':'param vksteam_ticket is invalid'}))
        
        if len(vksteam_ticket_cache) > CONFIG_VKSTEAM_MAX_CACHE_ENTRIES:
            app.logger.info('Clearing VKSteam ticket cache...')
            vksteam_ticket_cache.clear()
            app.logger.info('VKSteam ticket cache cleared')

        if ticket in vksteam_ticket_cache:
            return (True, vksteam_ticket_cache[ticket])

        url = f'https://api.vkplay.ru/steam/ISteamUserAuth/AuthenticateUserTicket/v1/?key={CONFIG_VKSTEAM_KEY}&ticket={ticket}&appid={CONFIG_VKSTEAM_APP_ID}'

        try:
            ok = requests.get(url, headers={'User-Agent': CONFIG_SERVER_USER_AGENT})
            if ok.status_code >= 400:
                return (False, json.dumps({'status':-22,'error':'vksteam api request forbidden'}))
            ok_json = ok.json()
            if ok_json['response']['params']['result'] != 'OK':
                return (False, json.dumps({'status':-23,'error':'vksteam api result is not OK'}))
            # ЭТО ЧИСЛА А НЕ СТРОКИ, МЫЛО, БЛЯТЬ!
            steamid = str(ok_json['response']['params']['steamid'])
            ownersteamid = str(ok_json['response']['params']['ownersteamid'])
            if steamid != user_id and ownersteamid != user_id:
                # кто-то подделал тикет? ух ты!
                return (False, json.dumps({'status':-24,'error':'vksteam api user id mismatch'}))
            # ticket -> user_id lookup словарик :3
            vksteam_ticket_cache[ticket] = user_id
            return (True, user_id)
        except:
            return (False, json.dumps({'status':-25,'error':'vksteam api request failed'}))


def do_user_id_validation(is_post: str) -> tuple[bool, Response]:
    if is_post:
        rargs = request.form
    else:
        rargs = request.args
    
    user_id = rargs.get('user_id', type=str)
    if CONFIG_USE_GAS:
        gas_uid = rargs.get('gas_uid', type=str)
        gas_hash = rargs.get('gas_hash', type=str)
        gas_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        gas_result = do_gas_request(gas_uid, gas_hash, gas_ip)
        if not gas_result[0]:
            return (False, Response(response=gas_result[1], status=401, content_type='application/json; charset=utf-8'))
        if not user_id:
            # разрешить не указывать user_id если он уже известен из GAS
            user_id = gas_uid
    elif CONFIG_USE_VKSTEAM:
        vksteam_ticket = rargs.get('vksteam_ticket', type=str)
        vksteam_result = do_vksteam_verify_ticket(vksteam_ticket, user_id)
        if not vksteam_result[0]:
            return (False, Response(response=vksteam_result[1], status=401, content_type='application/json; charset=utf-8'))
    return (True, user_id)


@app.route('/v1/api/post', methods=['POST'])
def post_leaderboard():
    leaderboard_id = request.form.get('leaderboard_id', type=str)
    metadata = request.form.get('metadata', type=str)
    score = request.form.get('score', type=int)
    user_name = request.form.get('user_name', type=str)

    user_id_auth = do_user_id_validation(True)
    if not user_id_auth[0]:
        return user_id_auth[1]
    user_id = user_id_auth[1]
    
    with lock:
        rv = impl_post_leaderboard(
            user_id,
            user_name,
            leaderboard_id,
            metadata,
            score
        )

    if rv[0]:
        httpstatus = 200
    else:
        httpstatus = 400
    
    return Response(response=rv[1], status=httpstatus, content_type='application/json; charset=utf-8')


@app.route('/v1/api/get', methods=['GET'])
def get_leaderboard():
    leaderboard_id = request.args.get('leaderboard_id', type=str)
    index_start = request.args.get('index_start', type=int)
    amount = request.args.get('amount', type=int)

    user_id_auth = do_user_id_validation(False)
    if not user_id_auth[0]:
        return user_id_auth[1]
    user_id = user_id_auth[1]

    with lock:
        rv = impl_get_leaderboard(
            user_id,
            leaderboard_id,
            index_start,
            amount
        )

    if rv[0]:
        httpstatus = 200
    else:
        httpstatus = 400
    
    return Response(response=rv[1], status=httpstatus, content_type='application/json; charset=utf-8')


cloud_save_storage: dict = None
cloud_save_lock = Lock()
cloud_save_serialized = ''


def backup_cloud_save():
    global cloud_save_serialized
    
    cloud_save_serialized = json.dumps(cloud_save_storage)
    if not CONFIG_BACKUP_PATH:
        return

    try:
        os.makedirs(name=CONFIG_BACKUP_PATH, exist_ok=True)
        txt_path = os.path.join(CONFIG_BACKUP_PATH, 'cloud_save.json')
        with open(txt_path, 'w') as txt:
            txt.write(cloud_save_serialized)
        app.logger.info('Backed up cloud save info to ' + txt_path)
    except:
        app.logger.info('Failed to back up :(')


def read_cloud_save():
    global cloud_save_storage
    global cloud_save_serialized

    cloud_save_storage = {}
    cloud_save_serialized = json.dumps(cloud_save_storage)

    if not CONFIG_BACKUP_PATH:
        return

    try:
        txt_path = os.path.join(CONFIG_BACKUP_PATH, 'cloud_save.json')
        with open(txt_path) as txt:
            cloud_save_storage = json.load(txt)
        cloud_save_serialized = json.dumps(cloud_save_storage)
        app.logger.info('Parsed txt ok')
    except:
        app.logger.info('Failed to read the txt :(')


def pre_cloud_save_request():
    if cloud_save_storage is None:
        read_cloud_save()


@app.route('/v1/api/cloud_post', methods=['POST'])
def post_cloud_save():
    data_string = request.form.get('data', type=str)

    user_id_auth = do_user_id_validation(True)
    if not user_id_auth[0]:
        return user_id_auth[1]
    user_id = user_id_auth[1]
    
    rv = ''
    httpstatus = 200
    with cloud_save_lock:
        pre_cloud_save_request()

        if not data_string:
            dtnow = 0
            cloud_save_storage.pop(user_id)
        else:
            dtnow = get_current_datetime()
            cloud_save_storage[user_id] = { 'data': data_string, 'timestamp': dtnow }
        
        backup_cloud_save()
        rv = json.dumps({'status':1,'error':'','timestamp':dtnow})
    
    return Response(response=rv, status=httpstatus, content_type='application/json; charset=utf-8')


@app.route('/v1/api/cloud_get', methods=['GET'])
def get_cloud_save():

    user_id_auth = do_user_id_validation(False)
    if not user_id_auth[0]:
        return user_id_auth[1]
    user_id = user_id_auth[1]
    
    rv = ''
    httpstatus = 200
    with cloud_save_lock:
        pre_cloud_save_request()

        if not (user_id in cloud_save_storage):
            httpstatus = 404
            rv = json.dumps({'status':0,'error':'no data is present for given user_id','timestamp':0,'data':''})
        else:
            rv = json.dumps({'status':1,'error':'','timestamp': cloud_save_storage[user_id]['timestamp'], \
                             'data': cloud_save_storage[user_id]['data']})
    
    return Response(response=rv, status=httpstatus, content_type='application/json; charset=utf-8')


@app.route('/v1/api/admin_action', methods=['GET'])
def get_admin_action():
    global data

    ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    app.logger.info('admin request from ip address ' + ip)

    if not CONFIG_ADMIN_SECRET:
        return 'admin methods are disabled, izvinite!'

    secret = request.args.get('secret', type=str)
    if secret is None or secret != CONFIG_ADMIN_SECRET:
        return 'ne-a, izvinite'
    
    req = request.args.get('action', type=str)
    if not req:
        return 'admin: secret is correct, but no action was given'
    elif req == 'reset':
        with lock:
            data = None
            app.logger.info('Admin leaderboards reset!')
        return 'reset: successful'
    elif req == 'reset_cloud':
        with cloud_save_lock:
            cloud_save_storage.clear()
            app.logger.info('Cloud save data reset!!')
        return 'cloud save reset successful'
    elif req == 'get_cloud_save':
        return cloud_save_serialized
    elif req == 'get_leaderboards':
        return data_serialized
    else:
        return 'unknown admin api action o_O?'


def run_app():
    app.logger.info('!!! Starting a Flask application for local debugging...')
    app.logger.info('Kotodoski debug')
    app.run(port=8080, debug=True)


if __name__ == '__main__':
    run_app()

