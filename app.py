#!/usr/bin/python3

# Kotodoski

# Данный сервер предназначен для хостинга на бесплатном Deta Spaces.
# Написан криво, и для серьёзных игр НЕ годится.
# Просто фигачим всё из config.py сюда
from config import *

from flask import Flask, request, Response
from datetime import datetime, timezone, timedelta
import hashlib
import requests

from deta import Deta


app = Flask(__name__)

deta = Deta()

db_leaderboards = deta.Base('db_leaderboards')
data = None


def get_json(the_value) -> str:
    return app.json.dumps(the_value, separators=(',', ':'))


def get_current_datetime() -> float:
    return datetime.now(timezone.utc).timestamp()


def get_next_reset_date(reset_type: str) -> float:
    dtnow = datetime.now(timezone.utc)

    if not reset_type:
        # не сбрасывать вообще
        return 0
    elif reset_type == 'day':
        # следующий день, без учёта часов, минут или секунд
        return (datetime(dtnow.year, dtnow.month, dtnow.day, tzinfo=dtnow.tzinfo, fold=dtnow.fold) + timedelta(days=1)).timestamp()
    elif reset_type == 'week':
        # следующая неделя относительно текущей, без учёта дней, часов, минут или секунд
        # недели очень странный предмет, здесь нужно из текущей даты
        # вычесть сколько дней в текущей неделе, и добавить +1 неделю к этой дате.
        # то есть мы откатываем текущую дату в начало недели, и добавляем неделю.
        return ((datetime(dtnow.year, dtnow.month, dtnow.day, tzinfo=dtnow.tzinfo, fold=dtnow.fold) - timedelta(days=dtnow.weekday())) + timedelta(weeks=1)).timestamp()
    elif reset_type == 'hour':
        # следующий час, без учёта минут или секунд
        return (datetime(dtnow.year, dtnow.month, dtnow.day, dtnow.hour, tzinfo=dtnow.tzinfo, fold=dtnow.fold) + timedelta(hours=1)).timestamp()
    elif reset_type == 'minute':
        # следующая минута, без учёта секунд
        # только для тестирования сброса, не использовать в проде!!
        return (datetime(dtnow.year, dtnow.month, dtnow.day, dtnow.hour, dtnow.minute, tzinfo=dtnow.tzinfo, fold=dtnow.fold) + timedelta(minutes=1)).timestamp()
    # ?????
    app.logger.error('!!! Unknown board reset date type ' + reset_type)
    return 0


def init_if_not_already(lbid: str):
    global data
    
    do_commit = False
    data = db_leaderboards.get(lbid)

    # app.logger.warn('@@ data lb = ' + str(data))

    if data is None:
        if not (lbid in CONFIG_LEADERBOARD_INFO):
            # такой нет в конфиге? ух ты...
            return False
        
        value = CONFIG_LEADERBOARD_INFO[lbid]
        # deta base не может хранить None как значение
        if value['reset_every'] is None:
            value['reset_every'] = ''
        if value['max_entries'] is None:
            value['max_entries'] = 0
        data = {
            'reset_every': value['reset_every'],
            'reset_date': get_next_reset_date(value['reset_every']),
            'sort_in_reverse': value['reverse_sort'],
            'allow_overwrite': value['allow_overwrite'],
            'max_entries': value['max_entries'],
            'array': []
        }
        do_commit = True
    
    if do_commit:
        app.logger.info('Initialized the leaderboard data for ' + lbid)
        db_leaderboards.put(data, lbid)
    
    return True


def reset_leaderboards_if_necessary(lbid: str):
    dtnow = get_current_datetime()

    do_reset = False

    dtreset = data['reset_date']
    if not dtreset:
        # не сбрасываемая досочка
        return

    if dtnow >= dtreset:
        app.logger.warn('!!! Resetting leaderboard with id of ' + lbid)
        data['array'].clear()
        data['reset_date'] = get_next_reset_date(data['reset_every'])
        app.logger.warn('!!! Resetted ' + lbid)
        do_reset = True
    
    if do_reset:
        app.logger.info('!!! Comitting changes to the db')
        db_leaderboards.put(data, lbid)


def pre_request(lbid: str):
    if not init_if_not_already(lbid):
        return False
    reset_leaderboards_if_necessary(lbid)
    return True


def entry_sort_function(item) -> int:
    return item['score']


def impl_post_leaderboard(user_id: str, user_name: str, leaderboard_id: str, metadata: str, score: int) -> tuple[bool, str]:
    # нет смысла иметь отрицательные или нулевые очки в таблице рекордов...
    if score is None or score <= 0:
        return (False, get_json({'status':-1,'error':'param score is invalid'}))

    if not user_id:
        return (False, get_json({'status':-2,'error':'param user_id is invalid'}))
    
    if not user_name:
        return (False, get_json({'status':-3,'error':'param user_name is invalid'}))
    
    if not leaderboard_id:
        return (False, get_json({'status':-4,'error':'param leaderboard_id is invalid'}))

    if not pre_request(leaderboard_id):
        return (False, get_json({'status':-5,'error':'leaderboard with given leaderboard_id does not exist'}))

    board_array: list = data['array']
    for idx in range(len(board_array)):
        # ищем есть ли мы уже в табличке
        if board_array[idx]['user_id'] == user_id:
            if data['allow_overwrite']:
                # если включена перезапись, то убираем старую запись
                board_array.pop(idx)
                break
            else:
                # если не включена, то возвращаем ошибку
                return (False, get_json({'status':0,'error':'an entry for given user_id already exists'}))

    # добавляем запись о пользователе в конец таблицы
    metadatastr = ''
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
        reverse = not data['sort_in_reverse']
    )
    # если назначен max_entries и есть лишние записи, убираем
    max_entries = data['max_entries']
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
        return (False, get_json({'status':-6,'error':'unable to find new entry index after sorting, WTF?!'}))
    db_leaderboards.put(data, leaderboard_id)
    # йиппи!!!!1
    return (True, get_json({'status':1,'error':'','new_entry_index':our_index}))


def impl_get_leaderboard(user_id: str, leaderboard_id: str, index_start: int, amount: int) -> tuple[bool, str]:
    if not user_id:
        return (False, get_json({'status':-1,'error':'param user_id is invalid'}))

    if not leaderboard_id:
        return (False, get_json({'status':-2,'error':'param leaderboard_id is invalid'}))

    if index_start is None:
        index_start = 0
        
    if index_start < -1:
        return (False, get_json({'status':-3,'error':'param index_start is invalid'}))
    
    # index_start == -1 значит вывести относительно нашего пользователя
    
    if amount is None:
        amount = 0

    if amount < 0:
        return (False, get_json({'status':-5,'error':'param amount is invalid'}))

    if not pre_request(leaderboard_id):
        return (False, get_json({'status':-4,'error':'leaderboard with given leaderboard_id does not exist'}))

    board_array: list = data['array']
    entries = len(board_array)
    
    # index_start == -1 значит искать относительно нас
    if index_start == -1:
        # собственно пытаемся найти "нас"
        for idx in range(entries):
            if board_array[idx]['user_id'] == user_id:
                index_start = idx
                break
    
    if index_start == -1:
        # был дан индекс -1 (искать относительно нас), но мы "нас" так и не нашли!
        return (False, get_json({'status':0,'error':'index_start is -1 but player with specified user_id is not present'}))

    if amount == 0:
        # amount <= 0 значит вывести до конца списка, если возможно.
        amount = entries - index_start
    
    tmplist = []
    for idx in range(index_start, index_start + amount):
        if idx >= entries:
            break

        entry = dict(board_array[idx])
        # докинуть индекс из цикла для подсчёта места
        entry['index'] = idx
        tmplist.append(entry)

    return (True, get_json({'status':1,'error':'','entries':tmplist,'amount':len(tmplist),'total':entries}))


def get_client_ip():
    return request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)


gas_session_cache = deta.Base('gas_session_cache')


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

    if not gas_uid:
        return (False, get_json({'status':-10,'error':'param gas_uid is invalid'}))
    
    if not gas_hash:
        return (False, get_json({'status':-11,'error':'param gas_hash is invalid'}))
    
    if not gas_ip:
        return (False, get_json({'status':-12,'error':'param gas_ip is invalid'}))
    
    gas_gmr_id = str(CONFIG_GAS_GMR_ID)
    if not gas_gmr_id:
        return (False, get_json({'status':-13,'error':'param gas_gmr_id is invalid'}))
    
    gas_secret = CONFIG_GAS_SECRET
    if not gas_secret:
        return (False, get_json({'status':-14,'error':'param gas_secret is invalid'}))
    
    # если мы уже авторизованы то получаем имя пользователя
    cache_key = gas_gmr_id + gas_secret + gas_uid + gas_hash + gas_ip
    cache_value = gas_session_cache.get(cache_key)
    if (cache_value is not None) and (cache_value['key'] == cache_key) and (cache_value['value'] == gas_uid):
        # нашли в кэше
        gas_session_cache.update(None, cache_key, expire_in=86400)
        return (True, gas_uid)
    
    gas_sign = do_gas_sign({
        'uid': gas_uid,
        'hash': gas_hash,
        'ip': gas_ip,
        'appid': gas_gmr_id
    }, gas_secret)
    if not gas_sign:
        return (False, get_json({'status':-15,'error':'failed to calculate gas_sign'}))
    
    gas_url = f'https://vkplay.ru/app/{gas_gmr_id}/gas?uid={gas_uid}&hash={gas_hash}&ip={gas_ip}&sign={gas_sign}'

    try:
        ok = requests.get(gas_url, headers={'User-Agent': CONFIG_SERVER_USER_AGENT})
        if ok.status_code >= 400:
            return (False, get_json({'status':-16,'error':'gas api request forbidden'}))
        ok_json = ok.json()
        ok_json_status = ok_json['status']
        if ok_json_status != 'ok':
            return (False, get_json({'status':-17,'error':'gas api status failed'}))
        
        # TODO: пихать что-то полезнее чем 'ok'?
        gas_session_cache.put(gas_uid, cache_key, expire_in=86400)
        return (True, cache_key)
    except:
        return (False, get_json({'status':-18,'error':'gas api request failed'}))


vksteam_ticket_cache = deta.Base('vksteam_ticket_cache')


def do_vksteam_verify_ticket(ticket: str, user_id: str) -> tuple[bool, str]:
    if not user_id:
        return (False, get_json({'status':-20,'error':'param user_id is invalid'}))
    
    if not ticket:
        return (False, get_json({'status':-21,'error':'param vksteam_ticket is invalid'}))

    cache_key = user_id + '_' + ticket
    cache_value = vksteam_ticket_cache.get(cache_key)
    if (cache_value is not None) and (cache_value['key'] == cache_key) and (cache_value['value'] == user_id):
        # продляем жизнь тикета в кэше
        vksteam_ticket_cache.update(None, cache_key, expire_in=86400)
        return (True, user_id)

    url = f'https://api.vkplay.ru/steam/ISteamUserAuth/AuthenticateUserTicket/v1/?key={CONFIG_VKSTEAM_KEY}&ticket={ticket}&appid={CONFIG_VKSTEAM_APP_ID}'

    try:
        ok = requests.get(url, headers={'User-Agent': CONFIG_SERVER_USER_AGENT})
        if ok.status_code >= 400:
            app.logger.error('@@ api request forbidden ' + str(user_id) + ';' + str(ticket) + ';' + str(ok.status_code) + ';' + str(ok.text))
            return (False, get_json({'status':-22,'error':'vksteam api request forbidden'}))
        ok_json = ok.json()
        if ok_json['response']['params']['result'] != 'OK':
            app.logger.error('@@ api result is not OK ' + str(user_id) + ';' + str(ticket) + ';' + str(ok.status_code) + ';' + str(ok.text))
            return (False, get_json({'status':-23,'error':'vksteam api result is not OK'}))
        # ЭТО ЧИСЛА А НЕ СТРОКИ, БЛЯТЬ!
        steamid = str(ok_json['response']['params']['steamid'])
        ownersteamid = str(ok_json['response']['params']['ownersteamid'])
        if steamid != user_id and ownersteamid != user_id:
            # кто-то подделал тикет? ух ты!
            app.logger.error('@@ api ticket forged ' + str(user_id) + ';' + str(ticket) + ';' + str(ok.status_code) + ';' + str(ok.text))
            return (False, get_json({'status':-24,'error':'vksteam api user id mismatch'}))
        # ticket -> user_id lookup словарик :3
        vksteam_ticket_cache.put(user_id, cache_key, expire_in=86400)
        return (True, user_id)
    except:
        # у vk play сдох сервер?
        app.logger.error('@@ vksteam is asleep ' + str(user_id) + ';' + str(ticket) + ';')
        return (False, get_json({'status':-25,'error':'vksteam api request failed'}))


def do_user_id_validation(is_post: str) -> tuple[bool, Response]:
    if is_post:
        rargs = request.form
    else:
        rargs = request.args
    
    user_id = rargs.get('user_id', type=str)
    if CONFIG_USE_GAS:
        gas_uid = rargs.get('gas_uid', type=str)
        gas_hash = rargs.get('gas_hash', type=str)
        gas_ip = get_client_ip()
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


cloud_save_storage = deta.Base('cloud_saves')


@app.route('/v1/api/cloud_post', methods=['POST'])
def post_cloud_save():
    data_string = request.form.get('data', type=str)
    slot_id = request.form.get('slot_id', type=str)

    user_id_auth = do_user_id_validation(True)
    if not user_id_auth[0]:
        return user_id_auth[1]
    user_id = user_id_auth[1]
    
    rv = ''
    httpstatus = 200
    if not user_id:
        httpstatus = 400
        rv = get_json({'status':-1,'error':'param user_id is invalid'})
    elif not slot_id:
        httpstatus = 400
        rv = get_json({'status':-2,'error':'param slot_id is invalid'})
    else:
        if not data_string:
            dtnow = 0
            cloud_save_storage.delete(user_id + '_' + slot_id)
        else:
            dtnow = get_current_datetime()
            data_to_put = { 'data': data_string, 'timestamp': dtnow }
            cloud_save_storage.put(data_to_put, user_id + '_' + slot_id)
        # 0 если сейв был удалён, или временная метка сервера если всё ОК.
        rv = get_json({'status':1,'error':'','timestamp':dtnow})
    
    return Response(response=rv, status=httpstatus, content_type='application/json; charset=utf-8')


@app.route('/v1/api/cloud_get', methods=['GET'])
def get_cloud_save():
    slot_id = request.args.get('slot_id', type=str)

    user_id_auth = do_user_id_validation(False)
    if not user_id_auth[0]:
        return user_id_auth[1]
    user_id = user_id_auth[1]
    
    rv = ''
    httpstatus = 200
    if not user_id:
        httpstatus = 400
        rv = get_json({'status':-1,'error':'param user_id is invalid'})
    elif not slot_id:
        httpstatus = 400
        rv = get_json({'status':-2,'error':'param slot_id is invalid'})
    else:
        user_data = cloud_save_storage.get(user_id + '_' + slot_id)
        # app.logger.warn('@@ cloud data = ' + str(user_data))
        if (user_data is None):
            httpstatus = 404
            rv = get_json({'status':0,
                             'error':'no data is present for given user_id or slot_id',
                             'timestamp':0,
                             'data':''
                            })
        else:
            rv = get_json({'status':1,
                             'error':'',
                             'timestamp': user_data['timestamp'],
                             'data': user_data['data']
                            })
    
    return Response(response=rv, status=httpstatus, content_type='application/json; charset=utf-8')


@app.route('/v1/api/admin_action', methods=['GET'])
def get_admin_action():
    global data

    ip = get_client_ip()
    app.logger.info('admin request from ip address ' + ip)

    if not CONFIG_ADMIN_SECRET:
        return 'admin methods are disabled, izvinite!'

    secret = request.args.get('secret', type=str)
    if secret is None or secret != CONFIG_ADMIN_SECRET:
        return 'ne-a, izvinite'
    
    # TODO: починить эти методы наконец.
    req = request.args.get('action', type=str)
    if not req:
        return 'admin: secret is correct, but no action was given'
    elif req == 'reset':
        return 'reset: successful'
    elif req == 'reset_cloud':
        return 'cloud save reset successful'
    elif req == 'get_cloud_save':
        return ''
    elif req == 'get_leaderboards':
        return ''
    else:
        return 'unknown admin api action o_O?'


@app.route('/v1/api/server_time', methods=['GET'])
def get_server_time():
    # этот метод можно использовать без авторизации
    # для проверки доступности сервера
    ip = get_client_ip()
    rv = get_json({'status':1,'error':'','timestamp':get_current_datetime(),'ip':ip})
    return Response(response=rv, status=200, content_type='application/json; charset=utf-8')


@app.route("/")
def print_greeting():
    # что выводить если ваш сервер попытались открыть
    # как ссылку в браузере?
    if not CONFIG_GREETING_MESSAGE:
        return 'Kotodoski Staging Server'
    else:
        return CONFIG_GREETING_MESSAGE


def run_app():
    app.logger.info('!!! Starting a Flask application for local debugging...')
    app.logger.info('Kotodoski debug')
    app.run(port=8080, debug=True)


if __name__ == '__main__':
    run_app()

