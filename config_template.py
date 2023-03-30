
#
# Скопируй меня как config.py и запусти сервак!
#

# -- КОНФИГУРАЦИЯ       -- #
# bool, использовать GAS для проверки запросов, или же не проверять авторизацию?
CONFIG_USE_GAS = False
# int, Игра -> Системные свойства -> Состояние -> ID Игры (GMRID)
CONFIG_GAS_GMR_ID = 0
# str, GAS секрет из системных свойств??
CONFIG_GAS_SECRET = ''
# bool, использовать VKSteam для авторизации или нет?
CONFIG_USE_VKSTEAM = True
# int, Игра -> Системные свойства -> Режим эмуляции Steam -> ID для эмуляции Steam
CONFIG_VKSTEAM_APP_ID = 2000000
# str, Игра -> Системные свойства -> Режим эмуляции Steam -> Секрет для эмуляции Steam API
CONFIG_VKSTEAM_KEY = 'abcdef'
# str, каким User-Agentом представляться системе GAS или VKSteam?
CONFIG_SERVER_USER_AGENT = 'AverageGASEnjoyer/1.0 (WeLoveCats; Cat-like)'
# str, секрет для admin_ методов
CONFIG_ADMIN_SECRET = 'yaga.yaga.yaguar.moi.volshebniy.nektar'
# dict, конфигурация досок почёта, key - идентификатор доски.
CONFIG_LEADERBOARD_INFO = {
    # daily runs
    'board_daily': {
        # str, 'day' - сброс каждый день, 'week' - каждую неделю, 'hour' - час, None - не сбрасывать
        'reset_every': 'day',
        # bool, True - сортировать от меньшего к большему
        'reverse_sort': False,
        # bool, разрешать ли публиковать запись если данный игрок УЖЕ публиковал?
        'allow_overwrite': False,
        # int, макс. кол-во записей, None - не ограничено (опасно!)
        'max_entries': 1000
    },
    # weekly runs
    'board_weekly': {
        # str, 'day' - сброс каждый день, 'week' - каждую неделю, 'hour' - час, None - не сбрасывать
        'reset_every': 'week',
        # bool, True - сортировать от меньшего к большему
        'reverse_sort': False,
        # bool, разрешать ли публиковать запись если данный игрок УЖЕ публиковал?
        'allow_overwrite': False,
        # int, макс. кол-во записей, None - не ограничено (опасно!)
        'max_entries': 1000
    }
}
# str, чем приветствовать любопытных
CONFIG_GREETING_MESSAGE = 'Kotodoski Development Server'
# -- КОНЕЦ КОНФИГУРАЦИИ -- #
