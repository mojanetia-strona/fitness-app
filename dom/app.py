# Automatyka domu Łukasza: ESP32 + MicroPython.
# Zasada: płytka reaguje na zdarzenia (odłożenie telefonu, pora, wietrzenie), a włączanie
# i wyłączanie według obecności robi Google Home. Płytka niczego nie wymusza w kółko.
import time, json, gc, machine
import network
from miio import Device

try:
    import requests
except ImportError:
    import urequests as requests

# Biblioteka requests przy przekierowaniu (Apps Script zawsze przekierowuje) woła sama siebie bez limitu czasu,
# przez co zapytanie potrafi zawisnąć na zawsze. Podmieniamy funkcję tak, by limit był zawsze ustawiony.
if hasattr(requests, 'request'):
    _req_orig = requests.request

    def _req_timeout(*a, **k):
        if len(a) < 8 and not k.get('timeout'):
            k['timeout'] = 20
        return _req_orig(*a, **k)

    requests.request = _req_timeout

VERSION = '1.0.159'

# ---------- ustawienia domyślne (nadpisywane przez config.json -> "plan") ----------
PLAN = {
    'salon_day': 23.0,      # salon w dzień (wg Qingpinga; od 22.11 23°C, bo zimno)
    'salon_night': 18.0,    # salon w nocy (po odłożeniu telefonu)
    'bed_day': 17.0,        # sypialnia w dzień (tylko ochrona przed wychłodzeniem)
    'bed_night': 17.0,      # sypialnia w nocy (do spania chłodniej)
    'away_temp': 17.0,      # oba pokoje po wyjściu z domu (od 1.0.77 robi to płytka, nie Google Home)
    'bed_home': 23.0,       # sypialnia, gdy w niej jestem (Pon-Pt od 18:00, weekend po wstaniu); od 22.11 23°C jak w Google Home
    'bed_morning': 25.0,    # sypialnia przed pobudką, w trybie boost aż do wstania
    'salon_morning': 25.0,  # salon przed pobudką, w trybie boost aż do wstania
    'wake_boost': True,     # przed pobudką głowice w trybie boost (zawór 100%), odnawiany co 20 min do wstania
    'bed_pre_min': 60,      # (zapas) od 1.0.81 start grzania liczony z tempa nagrzewania pokoju
    'heat_rate': 2.0,       # startowe tempo nagrzewania (°C/h), potem płytka uczy się go sama każdego ranka
    'pre_min': 30, 'pre_max': 150, 'pre_margin': 10,  # start grzania: min/max minut przed pobudką + zapas
    'bed_after_min': 0,     # (nieużywane od 1.0.76) sypialnia zmienia się od razu po wstaniu
    'salon_pre_min': 60,    # (nieużywane) nawilżacz i oczyszczacz włączają się dopiero po zdjęciu telefonu
    'salon_heat_pre_min': 60,  # ile minut przed pobudką grzać salon
    'wake_wd': 420,         # domyślna pobudka w tygodniu (min od północy), gdy brak danych z telefonu
    'wake_we': 540,         # domyślna pobudka w weekend
    'night_from': 1260,     # odłożenie telefonu po 21:00 = noc
    'night_late': 1350,     # telefon odłożony wcześniej, ale nadal leży o 22:30 = też noc
    'rh_low': 48,           # salon: poniżej tej wilgotności (Qingping) nawilżacz na mocno
    'rh_ok': 53,            # salon: od tej wilgotności (Qingping) nawilżacz wraca do stałej wilgotności (26.11: było 50, przeskakiwał co 15 min)
    'pm_hi': 20,            # salon: PM2.5 z Qingpinga powyżej -> oczyszczacz bieg 3
    'pm_mid': 8,            # ... powyżej -> bieg 2, do tej wartości bieg 1 (cicho)
    'rh_target': 50,        # cel stałej wilgotności w salonie
    'bed_rh_hi': 55,        # sypialnia: przy tylu % nawilżacz pauza
    'bed_rh_lo': 47,        # sypialnia: przy tylu % nawilżacz wraca
    'air_max_min': 90,      # wietrzenie: po tylu minutach bez wiadomości z czujnika wracamy do normy (bezpiecznik)
    'ext_temp': True,       # salon: temperatura z Qingpinga do głowicy
    'scale_min': 45.0, 'scale_max': 150.0,
    'pc_plug': '192.168.100.40',  # gniazdko Shelly głośników Edifier: prąd tylko przy włączonym komputerze (Komputer ON → Muzyka Poranna OFF)
    'lamp_salon': '192.168.100.36',  # gniazdko Shelly „Lampa Salon”: włącza Google Home przy powrocie, płytka gasi na noc
    'desk_light': '192.168.100.41',  # moduł Shelly 1PM Mini nad biurkiem (świeci, gdy chodzi komputer)
    'kitchen_led': '192.168.100.39',  # moduł Shelly 1PM Mini „LED pod szafkami” w kuchni: włącza Google Home, płytka gasi na noc
    # --- budzenie światłem: żarówka WiZ „Lampka Sypialnia” (lokalnie, UDP 38899) ---
    'wiz_bed': '192.168.100.37',
    'night_lamp': True,     # lampka nocna (2× Osram SMART+ WiFi G9 na czarnym klawiszu): zgaszona 21:00-4:00 = noc
    'nl_ids': ['bf295d5589d3b6f19d1lqn', 'bfe41dd92e344b2ac8jpuh'],
    'nl_off_s': 2,          # tyle sekund obie żarówki muszą milczeć, żeby uznać lampkę za zgaszoną
    # --- klawisz jak zwykły włącznik: żarówka WiZ ma WiZclick z trybem 1 = „Wył.”, więc po podaniu prądu zostaje zgaszona
    # (mignięcie prądu w nocy niczego nie zapala); poza nocą płytka zapala ją od razu po powrocie do sieci ---
    'wiz_switch': True,
    'wiz_lamps': ['192.168.100.37'],  # żarówki obsługiwane tak (kolejne dopisywać po dostawie)
    'bath_motion': '74:0B:12:94:53:38',  # Shelly BLU Motion ZB w łazience (czytany Bluetoothem płytki)
    'bath_off_day': 120,    # łazienka gaśnie po tylu s bez ruchu: dzień (rano 10 min, wieczór 5 min: bath_timeout)
    'bath_off_night': 60,   # ... w nocy
    'wake_light': True,
    'wake_light_min': 30,   # tyle trwa rozjaśnianie (od ciemnego pomarańczu do jasnej bieli)
    'wake_light_wd': 420,   # zapas, gdy nie znamy pory zaśnięcia: w tygodniu start nie wcześniej niż 7:00 ...
    'wake_light_we': 480,   # ... w weekend nie wcześniej niż 8:00
    'wake_light_sleep': 495,  # start nie wcześniej niż 8 h snu + 15 min na zaśnięcie od odłożenia telefonu
    # --- robot sprzątający Xiaomi H50 Pro: rusza, gdy oddalę się od domu (Skrót iOS: wyjście z promienia 1,5 km) ---
    'robot': True,
    'robot_from': 420,      # najwcześniej 7:00
    'robot_to': 1260,       # najpóźniej start do 21:00
    'robot_every': 1,       # co ile dni (1 = codziennie, 2 = co drugi dzień)
    'robot_after': 30,      # robot rusza tyle minut po wyjściu z domu, jeśli nie wróciłem (Żabka, paczkomat: nie)
    'robot_fresh': 150,     # wyjście ważne tyle minut (np. wyjście o 6:50 uruchomi robota o 7:00)
    'robot_dock': [2, 3],   # MIoT xiaomi.vacuum.ov42gl: stop-and-gocharge (przerywa sprzątanie i wraca na stację)
    'robot_start': [2, 1],  # MIoT: usługa vacuum, akcja start-sweep (tryb taki, jak ustawiony w Xiaomi Home)
    # --- zasłony w sypialni: 2× SwitchBot Curtain 3 Rod (Bluetooth, bez huba) ---
    'curtains': True,
    'cur_left': 'C5:C5:0C:F4:59:35',
    'cur_right': 'C8:58:63:F2:4C:79',
    'cur_left_open': 82,    # % otwarcia lewej zasłony (100 = całkiem odsunięta, 0 = zasunięta)
    'cur_right_open': 65,   # % otwarcia prawej
    'cur_quiet': 1,         # prędkość cicha (budzenie, zasuwanie na noc)
    'cur_fast': 255,        # prędkość zwykła (po wstaniu)
}

cfg = {}
log_buf = []
state = {}


def mk(y, mo, d, h=0, mi=0, s=0):
    try:
        return time.mktime((y, mo, d, h, mi, s, 0, 0))
    except Exception:
        return time.mktime((y, mo, d, h, mi, s, 0, 0, 0))  # CPython (testy)


def now_local():
    """Czas lokalny (Polska) z uwzględnieniem czasu letniego."""
    t = time.time()
    y = time.gmtime(t)[0]

    def last_sunday(month):
        # ostatnia niedziela miesiąca, 01:00 UTC
        for d in range(31, 24, -1):
            try:
                ts = mk(y, month, d, 1)
            except Exception:
                continue
            if time.gmtime(ts)[1] == month and time.gmtime(ts)[6] == 6:
                return ts
        return 0
    off = 7200 if last_sunday(3) <= t < last_sunday(10) else 3600
    return time.gmtime(t + off)


def mins(tm=None):
    tm = tm or now_local()
    return tm[3] * 60 + tm[4]


def is_weekend(tm=None):
    tm = tm or now_local()
    return tm[6] >= 5


def stamp():
    tm = now_local()
    return '%02d:%02d' % (tm[3], tm[4])


def log(msg):
    line = stamp() + ' ' + msg
    print(line)
    log_buf.append(line)
    if len(log_buf) > 20:
        del log_buf[0]


# ---------- Apps Script ----------
def gas(params, want=True, action='esp'):
    url = cfg['gas_url'] + '?action=' + action + '&token=' + cfg['gas_token']
    for k in params:
        v = str(params[k])
        enc = ''
        for ch in v:
            if ch.isalpha() or ch.isdigit() or ch in '-_.~':
                enc += ch
            else:
                for b in ch.encode():
                    enc += '%%%02X' % b
        url += '&' + k + '=' + enc
    gc.collect()
    ble_pause()
    try:
        r = requests.get(url, timeout=25)
        try:
            if not want:
                # log: wystarczy, że arkusz przyjął zapytanie (bez czytania całej odpowiedzi, oszczędza pamięć)
                if r.status_code >= 400:
                    raise OSError('http %d' % r.status_code)
                return True
            return r.json()
        finally:
            r.close()
    finally:
        ble_resume()


def flush_log(extra=''):
    if not log_buf and not extra:
        return None
    txt = ' | '.join(log_buf)
    if extra:
        txt = (extra + ' | ' + txt) if txt else extra
    # bufor czyścimy od razu: arkusz zwykle przyjmuje wpis nawet wtedy, gdy odpowiedź się nie doczyta,
    # a ponawianie zapisywało te same linie co 2 min (śmieci w logu i zjadana pamięć)
    del log_buf[:]
    try:
        return gas({'log': txt[:480]}, False)
    except Exception as e:
        print('gas log err', e)
        return None


def parse_iso(s):
    # 'YYYY-MM-DDTHH:MM:SS' (czas lokalny) -> (y,m,d,h,mi)
    return (int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]))


def local_minutes_since(iso):
    """Ile minut minęło od podanego czasu lokalnego (przybliżenie przez porównanie z now_local)."""
    y, mo, d, h, mi = parse_iso(iso)
    a = mk(y, mo, d, h, mi)
    tm = now_local()
    b = mk(tm[0], tm[1], tm[2], tm[3], tm[4])
    return (b - a) // 60


# ---------- Shelly (centralka BLU Gateway Gen3, lokalnie) ----------
def trv_call(trv_id, method, params):
    gw = cfg.get('shelly_gw')
    if not gw or trv_id is None:
        return None
    body = json.dumps({'id': 1, 'method': 'BluTrv.Call',
                       'params': {'id': trv_id, 'method': method, 'params': params}})
    last = None
    for i in range(3):
        try:
            gc.collect()
            r = requests.post('http://%s/rpc' % gw, data=body, headers={'Content-Type': 'application/json'}, timeout=10)
            try:
                j = r.json()
            finally:
                r.close()
            if 'error' in j:
                raise OSError(str(j['error']))
            return j.get('result')
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def plug_set(ip, on, label):
    # gniazdko Shelly Gen3 w sieci domowej (lokalne RPC)
    for i in range(2):  # 25.11: było 3 × 8 s (do ok. 30 s blokady), teraz najwyżej ok. 7 s
        try:
            gc.collect()
            r = requests.get('http://%s/rpc/Switch.Set?id=0&on=%s' % (ip, 'true' if on else 'false'), timeout=3)
            r.close()
            LSW[ip] = (bool(on), time.time())
            log(label)
            return True
        except Exception as e:
            last = e
            fast_tick()
            time.sleep_ms(500)
    log('%s blad %s' % (label, last))
    return False


def wiz(params, method='setPilot', ip=None):
    """Żarówka WiZ w sieci domowej: JSON po UDP na port 38899. Zwraca odpowiedź (dict) albo None."""
    ip = ip or PLAN.get('wiz_bed')
    if not ip:
        return None
    import socket
    msg = json.dumps({'method': method, 'params': params}).encode()
    for i in range(3):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.5)
            s.sendto(msg, socket.getaddrinfo(ip, 38899)[0][-1])
            data = s.recv(2048)
            r = json.loads(data)
            if isinstance(r, dict) and r.get('error'):
                # żarówka odpowiedziała, ale odrzuciła polecenie
                state['wiz_err'] = 'odrzucila: %s' % str(r['error'])[:80]
                return None
            return r
        except Exception as e:
            last = e
            time.sleep(0.5)
        finally:
            if s:
                s.close()
    state['wiz_err'] = str(last)
    return None


def wake_pilot(p):
    """Wygląd światła w chwili p (0..1) rozjaśniania: bardzo długo ciemno i ciepło, jasno dopiero na końcu.
    Poziom zgodności (state['wiz_lvl']): 0 kolor + 2200 K, 1 sama biel od 2700 K (żarówka bez koloru), 2 sama jasność."""
    dim = int(10 + 90 * p ** 2.5 + 0.5)  # WiZ: 10% to najciemniej
    lvl = state.get('wiz_lvl') or 0
    if lvl >= 2:
        return {'state': True, 'dimming': dim}
    if lvl == 1:
        return {'state': True, 'dimming': dim, 'temp': (2700 + int(800 * p ** 1.5)) // 100 * 100}
    if p < 0.4:
        # najpierw ciemny pomarańcz (jak świt), pierwsze ~12 min na minimum jasności
        return {'state': True, 'dimming': dim, 'r': 255, 'g': int(25 + 75 * p / 0.4), 'b': 0}
    temp = 2200 + int(1300 * ((p - 0.4) / 0.6) ** 1.5)  # potem ciepła biel, na końcu 3500 K
    return {'state': True, 'dimming': dim, 'temp': temp // 100 * 100}


def wake_alarm_min(sync):
    """Najwcześniejszy dzisiejszy poranny budzik z kalendarza (minuty od północy) albo None."""
    tm = now_local()
    today = '%04d-%02d-%02d' % (tm[0], tm[1], tm[2])
    best = None
    for a in (sync or {}).get('alarms') or []:
        try:
            if a[:10] != today:
                continue
            m = int(a[11:13]) * 60 + int(a[14:16])
        except Exception:
            continue
        if m < 720 and (best is None or m < best):
            best = m
    return best


def wake_light_start(sync, weekend):
    """Kiedy dziś zacząć rozjaśnianie (minuty od północy)."""
    fade = PLAN['wake_light_min']
    sa = state.get('sleep_at')
    if sa is not None:
        floor = (sa + PLAN['wake_light_sleep']) % 1440  # np. telefon odłożony 22:00 -> najwcześniej 6:15
    else:
        floor = PLAN['wake_light_we' if weekend else 'wake_light_wd']
    start = max(wake_min(sync, weekend) - fade, floor)
    am = wake_alarm_min(sync)
    if am is not None and am - fade < start:
        start = am - fade  # budzik z kalendarza: o godzinie budzika ma być już jasno
    return max(start, 0)


# ---------- Panel dom.ldesk.pl (26.11) ----------
# Ręczne ustawienie z panelu (albo od Claude przez arkusz) ma pierwszeństwo do najbliższego zdarzenia automatyki
# (lampka nocna, noc, pobudka, wyjście, powrót), które przejmuje sterowanie jak wcześniej.
MAN = {}


def day_key_at(t):
    tm = time.gmtime(t + 3600 * (1 + (1 if now_local()[3] != time.gmtime(time.time() + 3600)[3] else 0)))
    return '%04d%02d%02d' % (tm[0], tm[1], tm[2])


def man_clear(why=''):
    if MAN:
        log('panel: reczne ustawienia koniec (%s)' % why)
    MAN.clear()


def no_wake_today():
    return state.get('no_wake') == day_key()


def panel_lights(room, on, k=None, dim=None):
    ips = room_ips(room)
    if not ips:
        return
    base = 'work' if room in SUB else room
    if on:
        tk, td = light_target(base)
        pr = {'state': True, 'temp': int(k or tk), 'dimming': int(dim or td)}
    else:
        pr = {'state': False}
    MAN[base] = {'pr': pr, 't': time.time()}  # salon albo kuchnia osobno = cały 'work' ręcznie do najbliższego zdarzenia
    cmd = {'room': room, 'on': on, 't0': time.time(), 'left': set(ips), 'n': len(ips), 'rs': 0, 'done': {}}
    want = WS.setdefault('want', {})
    for ip in ips:
        want[ip] = {'p': pr, 'until': time.time() + 300, 'at': time.time(), 'cmd': cmd}
    room_burst(ips, pr, cmd)
    log('panel: swiatla %s %s%s (%d/%d od razu)' % (room, 'on' if on else 'off',
        (' %dK %d%%' % (pr['temp'], pr['dimming'])) if on else '', cmd.get('burst', 0), len(ips)))


def panel_exec(c, a):
    if c == 'swiatla':
        rooms = ('work', 'bed', 'bath') if a.get('room') == 'all' else (a.get('room'),)
        for r in rooms:
            if r in ('work', 'bed', 'bath', 'salon', 'kitchen'):
                panel_lights(r, bool(a.get('on')), a.get('k'), a.get('dim'))
    elif c == 'lampa':
        key = a.get('key')
        if key in ('lamp_salon', 'kitchen_led', 'desk_light') and PLAN.get(key):
            MAN[key] = {'on': bool(a.get('on')), 't': time.time()}
            plug_set(PLAN[key], bool(a.get('on')), 'panel: %s %s' % (key, 'on' if a.get('on') else 'off'))
    elif c == 'wszystko_off':
        for r in ('work', 'bed', 'bath'):
            panel_lights(r, False)
        if PLAN.get('wiz_bed'):
            wiz({'state': False})
        for key in ('lamp_salon', 'kitchen_led', 'desk_light'):
            if PLAN.get(key):
                MAN[key] = {'on': False, 't': time.time()}
                plug_set(PLAN[key], False, 'panel: %s off' % key)
    elif c == 'czytanie':
        for r in ('work', 'bed'):
            panel_lights(r, False)
        if PLAN.get('lamp_salon'):
            MAN['lamp_salon'] = {'on': True, 't': time.time()}
            plug_set(PLAN['lamp_salon'], True, 'panel: tryb czytania, lampa salon on')
    elif c == 'temp':
        name = {'salon': 'salon', 'sypialnia': 'bed', 'bed': 'bed'}.get(a.get('room'))
        t = float(a.get('t', 0))
        if name and 10 <= t <= 28:
            trv_target(name, t)
            log('panel: grzejnik %s %.1f' % (name, t))
    elif c == 'budzenie':
        if a.get('on') is False or a.get('on') == 0 or str(a.get('on')).lower() in ('false', 'off', 'nie', '0'):
            # najbliższy poranek: dziś, jeśli jeszcze przed południem i przed pobudką, inaczej jutro
            key = day_key() if (mins() < 720 and state.get('asleep')) else day_key_at(time.time() + 86400)
            state['no_wake'] = key
            log('panel: bez budzenia %s (spie do oporu, dzien od wagi albo telefonu)' % key)
        else:
            state['no_wake'] = None
            log('panel: budzenie normalnie')
    elif c == 'robot':
        if dev.get('robot'):
            start = a.get('akcja') == 'start'
            s_, a_ = PLAN['robot_start' if start else 'robot_dock']
            dev['robot'].action(s_, a_)
            if start:
                state['robot_day'] = day_num()
            log('panel: robot %s' % ('start sprzatania' if start else 'na stacje'))
    else:
        log('panel: nieznane polecenie %s' % c)


def panel_cmds(sync):
    cs = (sync or {}).get('cmds') or []
    for c in cs:
        try:
            panel_exec(c.get('c'), c.get('a') or {})
        except Exception as e:
            log('panel blad %s: %s' % (c.get('c'), e))
    if cs:
        NOW[0] = True  # od razu kolejna synchronizacja: panel zobaczy nowy stan po kilku sekundach


def panel_state():
    """Zwięzły stan domu dla panelu (wysyłany przy synchronizacji, ok. 500 znaków)."""
    def room(r):
        if r in SUB:
            mine = [x for mac, x in WS['seen'].items() if mac[-4:].lower() in SUB[r]]
        else:
            mine = [x for mac, x in WS['seen'].items() if room_of(mac) == r]
        lit = [x for x in mine if x['t'] and x['p'].get('state')]  # ostatni znany stan (t=0: jeszcze nie odpowiedziała)
        p = lit[0]['p'] if lit else {}
        return [len(lit), len(mine), p.get('temp'), p.get('dimming'), 1 if (('work' if r in SUB else r) in MAN) else 0]
    q = state.get('q') or (None, None, None, None)
    st = {
        'v': VERSION, 'a': 1 if state.get('asleep') else 0, 'w': 1 if state.get('away') else 0,
        'mo': 1 if morning_on() else 0, 'nl': 1 if NL.get('on') else 0, 'wl': 1 if state.get('wl') else 0,
        'nw': state.get('no_wake'), 'tout': state.get('tout'),
        'r': {'work': room('work'), 'salon': room('salon'), 'kitchen': room('kitchen'), 'bed': room('bed'), 'bath': room('bath')},
        'tg': {'work': light_target('work'), 'bed': light_target('bed')},
        's': [q[2] if q[2] is not None else room_temp('s', None),  # salon: Qingping, a do jego pierwszego odczytu głowica
              state.get('trv_salon') or TTGT.get('salon') or (room_temp('s', None) and TTGT.get('salon'))],
        'b': [room_temp('b', None), state.get('trv_bed') or TTGT.get('bed')],  # sypialnia: odczyt z głowicy najwyżej co 5 min
        'rh': q[0], 'pm': q[1], 'co2': q[3], 'm': [k for k in MAN],
    }
    lamps = {}
    for key in ('lamp_salon', 'kitchen_led', 'desk_light'):
        ip = PLAN.get(key)
        if not ip:
            continue
        c = LSW.get(ip)
        if not c or time.time() - c[1] > 120:  # starszy niż 2 min: dopytaj (zmiana z Google Home albo ręczna)
            light_on(ip)
            c = LSW.get(ip)
        lamps[key] = (1 if c[0] else 0) if c else None
    st['l'] = lamps
    return json.dumps(st)


def remote_cmd(sync):
    # polecenie ze skryptu (jednorazowe), np. test budzenia światłem uruchomiony z edytora skryptu
    c = (sync or {}).get('cmd')
    if not c:
        return
    if c == 'wake_test':
        log('test budzenia swiatlem: 3 min zamiast 30')
        state['wl'] = {'t0': time.time(), 'min': 3}
        state['wl_at'] = 0
    elif c in ('cur_open', 'cur_close'):
        curtains('open' if c == 'cur_open' else 'close', 'test')
    elif c == 'cur_info':
        state['cur_chk'] = 0
    elif c == 'wiz_learn':
        WS['learn'] = time.time() + 3600
        WS['inv'] = False
        log('zarowki: nauka klawiszy przez 60 min')
    elif c == 'wiz_probe2':
        # te same ustawienia, różne formy wiadomości (nowsze żarówki WiZ bywają wybredne)
        import socket
        ip = PLAN.get('wiz_bed')
        msgs = ['{"method":"setPilot","params":{"state":true}}',
                '{"id":1,"method":"setPilot","params":{"state":true}}',
                '{"method":"setState","params":{"state":true}}',
                '{"id":1,"method":"setState","params":{"state":true}}',
                '{"method":"setPilot","params":{"dimming":50}}',
                '{"method":"setPilot","params":{"src":"udp","state":true}}',
                '{"method":"setState","params":{"state":false}}']
        out = []
        for i, mtxt in enumerate(msgs):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            try:
                s.sendto(mtxt.encode(), socket.getaddrinfo(ip, 38899)[0][-1])
                out.append('%d:%s' % (i, s.recv(2048).decode()[:70]))
            except Exception as e:
                out.append('%d:brak (%s)' % (i, e))
            finally:
                s.close()
            time.sleep(2)
        log('lampka test2: ' + ' | '.join(out))
    elif c == 'wiz_probe':
        # sprawdzenie, które ustawienia żarówka przyjmuje (każde osobno, wynik w logu)
        tests = [{'state': True}, {'dimming': 10}, {'state': True, 'dimming': 10},
                 {'r': 255, 'g': 25, 'b': 0}, {'r': 255, 'g': 25, 'b': 0, 'dimming': 10},
                 {'state': True, 'r': 255, 'g': 25, 'b': 0, 'dimming': 10},
                 {'temp': 2200}, {'temp': 2200, 'dimming': 10}, {'state': True, 'temp': 3500, 'dimming': 100}]
        out = []
        for t in tests:
            ok = wiz(t) is not None
            out.append('%s=%s' % (','.join(sorted(t.keys())), 'ok' if ok else str(state.get('wiz_err'))[:40]))
            time.sleep(2)
        wiz({'state': False})
        log('lampka test: ' + ' | '.join(out))
        mc = wiz({}, 'getModelConfig')
        log('lampka mozliwosci: %s' % (json.dumps((mc or {}).get('result') or state.get('wiz_err'))[:400]))
    else:
        log('nieznane polecenie: %s' % c)


WZ = {'sock': None, 'i': 0, 'on': {}, 'miss': {}, 'st': {}, 'pt': 0}


def wiz_quick(ip):
    """Jedno szybkie pytanie o stan żarówki (bez ponawiania, żeby nie blokować pętli). True/False = świeci/nie, None = brak odpowiedzi."""
    import socket
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.sendto(b'{"method":"getPilot","params":{}}', socket.getaddrinfo(ip, 38899)[0][-1])
        r = json.loads(s.recv(1024))
        return bool((r.get('result') or {}).get('state'))
    except Exception:
        return None
    finally:
        if s:
            s.close()


LSW = {}  # 26.11: ostatni znany stan gniazdek/modułów Shelly z lampami (ip -> (on, kiedy)) dla panelu


def light_on(ip):
    """Czy gniazdko / moduł Shelly z lampą jest włączone (lokalne RPC). Brak odpowiedzi = nie."""
    try:
        gc.collect()
        r = requests.get('http://%s/rpc/Switch.GetStatus?id=0' % ip, timeout=3)
        try:
            v = bool(r.json().get('output'))
            LSW[ip] = (v, time.time())
            return v
        finally:
            r.close()
    except Exception:
        return False


def wiz_away(ip):
    """Nie ma mnie w domu: ostatnie zdarzenie ze Skrótu to wyjście i nie pali się żadne inne światło.
    (Gdy jestem w domu, zwykle coś świeci, więc to łapie też powrót, którego Skrót nie zapisał.)"""
    aw = WZ.get('away')
    if not aw or aw.get('e') != 'out':
        return False
    for other, st in WZ['st'].items():
        if other != ip and st:
            return False
    for key in ('lamp_salon', 'kitchen_led', 'desk_light'):
        if PLAN.get(key) and light_on(PLAN[key]):
            return False
    return True


def wiz_power_on(ip, why):
    """Żarówka dostała prąd (klawisz albo mignięcie prądu). W nocy, przy budzeniu i gdy mnie nie ma: zostaje zgaszona."""
    if state.get('asleep') or state.get('wl'):
        log('klawisz: %s wrocila do sieci (%s), noc - zostaje zgaszona' % (ip[-3:], why))
        return
    if SNAP['boot_rc'] == 'zasilanie' and time.time() - BOOT_T[0] < 180:
        return  # brak prądu w całym mieszkaniu, nie klawisz: stan przywraca restore_tick
    if wiz_away(ip):
        log('klawisz: %s wrocila do sieci (%s), mnie nie ma - zostaje zgaszona' % (ip[-3:], why))
        return
    pr = {'state': True}
    mac = ([m for m, x in WS['seen'].items() if x['ip'] == ip] or [''])[0]
    if ip != PLAN.get('wiz_bed') and mac[-4:].lower() != BED_LAMP and PLAN.get('lt_auto', True):
        if room_of(mac) == 'bath':
            return  # łazienkę zapala tylko czujnik ruchu
        pr['temp'], pr['dimming'] = light_target(room_of(mac) or 'work')  # od razu barwa pomieszczenia
    ok = wiz(pr, 'setPilot', ip) is not None
    WZ['st'][ip] = True if ok else WZ['st'].get(ip)
    log('klawisz: %s zapalona (%s)' % (ip[-3:], why) if ok else 'klawisz: %s nie odpowiada (%s)' % (ip[-3:], state.get('wiz_err')))


def wiz_switch_tick(sync):
    """Klawisz przy żarówce WiZ działa jak zwykły włącznik.
    Sygnał 1: żarówka po starcie rozgłasza „firstBeat” na port 38900 (pewny znak, że dostała prąd).
    Sygnał 2 (zapas): żarówka znikła z sieci na min. 3 s i wróciła zgaszona."""
    lamps = list(PLAN.get('wiz_lamps') or [])
    for x in ws_present(60).values():  # żarówki znalezione w sieci też działają jak zwykły włącznik
        if x['ip'] not in lamps:
            lamps.append(x['ip'])
    if not PLAN.get('wiz_switch') or not lamps:
        return
    if sync is not None:
        WZ['away'] = sync.get('away')
    import socket
    if WZ['sock'] is None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            s.bind(('0.0.0.0', 38900))
            s.setblocking(False)
            WZ['sock'] = s
        except Exception as e:
            WZ['sock'] = False
            log('klawisz: nasluch 38900 niedostepny (%s)' % e)
    if WZ['sock']:
        for _ in range(5):
            try:
                data, addr = WZ['sock'].recvfrom(1024)
            except Exception:
                break
            ip = addr[0]
            if b'firstBeat' in data:  # rozgłasza to tylko żarówka WiZ, która właśnie dostała prąd
                fm = None
                try:
                    fm = (json.loads(data).get('params') or {}).get('mac')
                    if fm:  # od razu wiemy, która to żarówka (i w którym pomieszczeniu)
                        WS['seen'][fm] = {'ip': ip, 't': time.time(), 'p': {'state': False}}
                except Exception:
                    pass
                if time.time() - WZ.setdefault('fb', {}).get(ip, 0) < 30:
                    continue  # żarówka rozgłasza firstBeat kilka razy pod rząd
                WZ['fb'][ip] = time.time()
                WZ['on'][ip] = True
                WZ['miss'][ip] = 0
                # nie od razu: czekamy 4 s, czy to klawisz (żarówki jednego pomieszczenia), czy sieć/prąd (wszystkie naraz)
                WZ.setdefault('pend', {})[ip] = (time.time(), fm)
    fb_process()
    # zapas „zniknęła i wróciła zgaszona” wyłączony od 1.0.97: przy 28 żarówkach Wi-Fi gubi odpowiedzi
    # i zapalał żarówki bez klawisza; wystarcza firstBeat
    if not PLAN.get('wiz_backup', False):
        return
    if time.time() - WZ['pt'] < 1:
        return
    WZ['pt'] = time.time()
    WZ['i'] = (WZ['i'] + 1) % len(lamps)
    ip = lamps[WZ['i']]
    st = wiz_quick(ip)
    if st is None:
        WZ['miss'][ip] = WZ['miss'].get(ip, 0) + 1
        if WZ['miss'][ip] >= 3 and WZ['on'].get(ip):
            WZ['on'][ip] = False  # brak prądu (klawisz wyłączony) albo chwilowo poza Wi-Fi
        return
    WZ['miss'][ip] = 0
    if WZ['on'].get(ip) is False:
        WZ['on'][ip] = True
        if not st:  # wróciła zgaszona = dostała prąd z klawisza (WiZclick „Wył.”); świecąca po utracie Wi-Fi nic nie zmienia
            wiz_power_on(ip, 'powrot do sieci')
            return
    WZ['on'][ip] = True
    WZ['st'][ip] = st


# ---------- wszystkie żarówki WiZ: wyszukiwanie w sieci i barwa wg pory dnia ----------
# Co 4 s płytka pyta całą sieć (broadcast getPilot na port 38899). Każda żarówka odpowiada swoim MAC, IP i stanem,
# więc nie trzeba stałych IP w routerze. Przez 60 min po starcie (albo po poleceniu wiz_learn) każda zmiana
# (żarówka znikła = klawisz wyłączony, wróciła = włączony) trafia do logu: tak przypisujemy żarówki do klawiszy.
WS = {'sock': None, 'seen': {}, 'scan': 0, 'bc': 0, 'bc_ok': False, 'learn': 0, 'pres': None, 'inv': False, 'col': 0}


# żarówki wg pomieszczeń (końcówka MAC, nauka klawiszy 23.11); salon i kuchnia to jedna strefa „praca”
ROOMS = {
    'bed': ('ed20', '983c', '67ea', '6032', '4754', 'e994', '9554', '6906'),
    'bath': ('ecc6', 'eb7e', 'f22c'),
    'work': ('6534', '5f96', '9544', 'e7ee', '6682', '68fa', '48b0', '677e',   # kuchnia pionowo / poziomo
             '6368', '62e4', '49b4', '64b2', '6410', '5e8c', '66ec', '623a'),  # salon pionowo / poziomo
}
# 26.11: tylko dla panelu (ręcznie): salon i kuchnia osobno. Automatyka zawsze steruje całym 'work'.
SUB = {'kitchen': ROOMS['work'][:8], 'salon': ROOMS['work'][8:]}
BED_LAMP = 'd3e2'  # lampka za łóżkiem: własne budzenie, barwy nie ruszamy


def room_of(mac):
    sfx = mac[-4:].lower()
    for r, ms in ROOMS.items():
        if sfx in ms:
            return r
    return None


def room_ips(room):
    if room in SUB:
        return [x['ip'] for mac, x in WS['seen'].items() if mac[-4:].lower() in SUB[room]]
    return [x['ip'] for mac, x in WS['seen'].items() if room_of(mac) == room]


def morning_on():
    """Tryb poranny: od wstania; w tygodniu do włączenia komputera (najdłużej 3 h), w weekend 1 h."""
    mo = state.get('morn')
    if not mo or mins() >= 1080 or mins() < 240:  # wieczorem i w nocy nigdy tryb poranny
        return False
    age = time.time() - mo['t0']
    if mo.get('we'):
        return age < 5400 and not mo.get('shower')  # weekend: do końca prysznica, najdłużej 1,5 h
    return age < 3 * 3600 and not mo.get('pc')


def eve_dim(m, ef, start):
    """26.11: wieczór. Barwa stała (2700 K), jasność płynnie spada od początku wieczoru (zimą 19:00) do 21:00 na minimum
    WiZ (10%) i tak zostaje do nocy, zgaszenia albo trybu czytania. start = jasność na początku (pokoje 40%, łazienka 45%)."""
    lo = PLAN.get('eve_dim_min', 10)
    end = max(PLAN.get('eve_dim_end', 1260), ef + 60)
    if m < 240 or m >= end:
        return lo
    if m <= ef:
        return start
    return int(start - (start - lo) * (m - ef) / float(end - ef) + 0.5)


def light_target(room='work', m=None):
    """Barwa (K) i jasność (%) dla pomieszczenia teraz. Ustalone z Łukaszem 23.11."""
    m = mins() if m is None else m
    ss = sun_min(False)
    dark = m >= ss or m < 240  # po zachodzie słońca (zmierzch) do 4:00
    ef = max(PLAN.get('eve_from', 1140), ss + 120) if ss + 120 < 1440 else PLAN.get('eve_from', 1140)
    if room == 'bath':
        if state.get('asleep') or nl_eve_on():
            return 2700, 10        # noc: jedna żarówka, minimum WiZ (10%), ciepło
        if morning_on():
            # 26.11: pierwsze 10 min po wstaniu łagodnie jak salon (rozbudzam się, np. na wadze), potem białe 6000 K 100%
            if time.time() - state['morn']['t0'] < PLAN.get('bath_soft_s', 600):
                return PLAN.get('morn_k', 2800), PLAN.get('morn_dim', 50)
            return 6000, 100       # rano: białe, jasne, rozbudza
        if not dark:
            return 5000, 100
        # po zmierzchu ciepło i przygaszone (45%); od wieczoru dokładnie jak pokoje: 40% -> 10% do 21:00
        if m >= ef or m < 240:
            return 2700, eve_dim(m, ef, PLAN.get('eve_dim', 40))  # wieczór: dokładnie jak pokoje (40% -> 10% do 21:00)
        if m >= ef - 60:  # 18:00-19:00: równo z pokojami (100% -> 40%), ale nigdy jaśniej niż 45%
            p_ = (m - (ef - 60)) / 60.0
            return 2700, min(45, int(100 - (100 - PLAN.get('eve_dim', 40)) * p_ + 0.5))
        return 2700, 45
    # 26.11: barwa wieczoru od 19:00, ale nie wcześniej niż 2 h po zachodzie (latem zachód ok. 21:00), żeby nie było skoku;
    # ostatnia godzina przed tym momentem: płynne przejście do 2700 K 40%
    eve = dark and (state.get('eve_ret') == day_key() or m >= ef or m < 240)
    pre = max(0.0, min(1.0, (m - (ef - 60)) / 60.0)) if dark and ef - 60 <= m < ef else 0.0
    if room == 'bed':
        if eve:
            return PLAN.get('eve_k', 2700), eve_dim(m, ef, PLAN.get('eve_dim', 40))  # tryb wieczór: jak salon i kuchnia
        if dark:  # 26.11: płynnie, bez skoków: po zmierzchu przez 2 h 100% -> 60%, 18:00-19:00 dalej do 40%
            d = 100 - 40 * min(1.0, ((m - ss) % 1440) / 120.0)
            d = d - (d - PLAN.get('eve_dim', 40)) * pre
            return 2700, int(d + 0.5)
        return 2700, 100  # zawsze ciepło
    # salon + kuchnia
    if state.get('asleep'):
        return 2700, 50
    if morning_on():
        return PLAN.get('morn_k', 2800), PLAN.get('morn_dim', 50)  # rano (25.11): ciepło, przygaszone
    if dark and (state.get('eve_ret') == day_key() or m >= PLAN.get('eve_from', 1140) or m < 240):
        # tryb wieczór: po zmierzchu i od 19:00 (albo po powrocie po zmroku): klimatycznie, delikatnie
        return PLAN.get('eve_k', 2700), eve_dim(m, ef, PLAN.get('eve_dim', 40))
    if dark:
        k = 5000 - 2000 * min(1.0, ((m - ss) % 1440) / 120.0)  # od zmierzchu przez 2 h do 3000 K, jasność 100%
        d = 100.0
        if pre:  # 26.11: 18:00-19:00 płynnie do trybu wieczór (2700 K 40%), zamiast skoku o 19:00
            k = k - (k - PLAN.get('eve_k', 2700)) * pre
            d = 100 - (100 - PLAN.get('eve_dim', 40)) * pre
        return int(k) // 100 * 100, int(d + 0.5)
    return 5000, 100


def ws_send(ip, params, method='setPilot'):
    """Polecenie bez czekania na odpowiedź (nie blokuje pętli)."""
    if not WS['sock']:
        return
    try:
        WS['sock'].sendto(json.dumps({'method': method, 'params': params}).encode(), (ip, 38899))
    except Exception as e:
        print('ws send err', e)


def ws_present(age=45):
    t = time.time()
    return {mac: x for mac, x in WS['seen'].items() if t - x['t'] <= age}


def wiz_scan_tick():
    import socket
    t = time.time()
    if WS['sock'] is None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.setsockopt(socket.SOL_SOCKET, getattr(socket, 'SO_BROADCAST', 0x20), 1)
            except Exception as e:
                print('so_broadcast', e)
            s.bind(('0.0.0.0', 0))
            s.setblocking(False)
            WS['sock'] = s
            WS['learn'] = 0  # nauka klawiszy zrobiona 23.11 (polecenie wiz_learn włącza ją ponownie)
            try:  # żarówki znane sprzed restartu: od razu wiadomo, która jest gdzie
                with open('wiz.json') as f:
                    for m, ip in json.load(f).items():
                        WS['seen'][m] = {'ip': ip, 't': 0, 'p': {}}
            except Exception:
                pass
        except Exception as e:
            WS['sock'] = False
            log('zarowki: wyszukiwanie niedostepne (%s)' % e)
    if not WS['sock']:
        return
    # odpowiedzi
    for _ in range(60):
        try:
            data, addr = WS['sock'].recvfrom(1024)
        except Exception:
            break
        try:
            r = json.loads(data)
        except Exception:
            continue
        x = r.get('result') if isinstance(r, dict) else None
        if not isinstance(x, dict) or not x.get('mac'):
            continue
        WS['seen'][x['mac']] = {'ip': addr[0], 't': t, 'p': {k: x[k] for k in ('state', 'temp', 'dimming', 'sceneId') if k in x}}
        # barwa wg pomieszczenia: poprawiamy tylko świeżo potwierdzoną świecącą żarówkę (sama odpowiedź sprzed ms).
        # Wcześniej płytka wysyłała barwę na podstawie starego stanu i ponownie zapalała żarówki zgaszone w aplikacji.
        p_ = WS['seen'][x['mac']]['p']
        if PLAN.get('lt_auto', True) and x.get('state') and not wake_hold() and room_of(x['mac']) not in MAN \
                and x['mac'][-4:].lower() != BED_LAMP \
                and addr[0] != PLAN.get('wiz_bed') and t - WS.setdefault('fix', {}).get(addr[0], 0) > 20:
            k, dim = light_target(room_of(x['mac']) or 'work')
            if p_.get('sceneId') or abs((p_.get('temp') or 0) - k) >= 100 or abs((p_.get('dimming') or 0) - dim) >= 5:
                WS['fix'][addr[0]] = t
                ws_send(addr[0], {'temp': k, 'dimming': dim})
        # strażnik: gdy mnie nie ma albo śpię, żadna żarówka nie ma prawa świecić (poza łazienką z czujnika w nocy).
        # Działa przy każdej odpowiedzi żarówki, więc zgubione polecenie „zgaś” nie zostawi światła na cały dzień.
        rm = room_of(x['mac'])
        if x.get('state') and rm not in MAN and (state.get('away') or (state.get('asleep') and rm != 'bath' and not wake_hold())) \
                and t - WS.setdefault('guard', {}).get(addr[0], 0) > 10:
            WS['guard'][addr[0]] = t
            ws_send(addr[0], {'state': False})
            if t - WS.get('guard_log', 0) > 600:
                WS['guard_log'] = t
                log('straznik: %s %s swiecila mimo %s, gasze' % (rm or '?', x['mac'][-4:], 'wyjscia' if state.get('away') else 'nocy'))
        w = WS.get('want', {}).get(addr[0])
        if w:
            c = w.get('cmd')
            if bool(x.get('state')) == w['p']['state']:
                WS['want'].pop(addr[0], None)  # potwierdzone
                if c and addr[0] in c['left']:
                    c['left'].discard(addr[0])
                    c['done'][addr[0]] = t - c['t0']
            elif t > w['until']:
                WS['want'].pop(addr[0], None)
            elif t - w['at'] > 1.5:
                w['at'] = t
                if c:
                    c['rs'] += 1
                ws_send(addr[0], w['p'])  # żarówka nie wykonała polecenia: ponawiamy
        st = WS.setdefault('st', {}).setdefault(addr[0], [0, 0, 0, 0])  # zapytania, odpowiedzi, suma rssi, liczba rssi
        st[1] += 1
        if x.get('rssi'):
            st[2] += x['rssi']
            st[3] += 1
        WS['bc_ok'] = True
    msg = b'{"method":"getPilot","params":{}}'
    # znane żarówki: po 4 na raz, bezpośrednio (płytka mieści w buforze tylko kilka odpowiedzi naraz,
    # przy 27 odpowiedziach jednocześnie większość ginęła i obecność migała)
    for ip in list(WS.get('want', {}).keys()):  # żarówki z niepotwierdzonym poleceniem: pytamy co sekundę
        w = WS['want'][ip]
        if t > w['until']:
            WS['want'].pop(ip, None)
            continue
        if t - w['at'] > 1.5:
            # brak potwierdzenia (zgubione polecenie albo zgubiona odpowiedź): ponawiamy samo polecenie, nie czekając
            w['at'] = t
            if w.get('cmd'):
                w['cmd']['rs'] += 1
            ws_send(ip, w['p'])
        try:
            WS['sock'].sendto(msg, (ip, 38899))
        except Exception:
            pass
    ips = sorted(set(x['ip'] for x in WS['seen'].values()))
    if ips:
        for _ in range(2):
            WS['ui'] = (WS.get('ui', 0) + 1) % len(ips)
            WS.setdefault('st', {}).setdefault(ips[WS['ui']], [0, 0, 0, 0])[0] += 1
            try:
                WS['sock'].sendto(msg, (ips[WS['ui']], 38899))
            except Exception:
                pass
    # nowe żarówki: pytanie do całej sieci co 60 s (pierwsze 30 s po starcie co 4 s)
    if t - WS['scan'] >= 60 or (t - BOOT_T[0] < 30 and t - WS['scan'] >= 4):
        WS['scan'] = t
        try:
            WS['sock'].sendto(msg, ('255.255.255.255', 38899))
        except Exception:
            pass
        WS['bc'] += 1
        # przegląd każdego adresu (254 paczki) tylko po starcie i co 15 min (25.11): żarówki mają stałe IP,
        # a nowe i tak zgłaszają się same (firstBeat) i odpowiadają na broadcast co minutę
        if t - WS.get('sw_at', 0) >= 900 or t - BOOT_T[0] < 30:
            WS['sw_at'] = t
            WS['sw'] = 2
    if WS.get('sw'):
        base = PLAN.get('wiz_net', '192.168.100.')
        a = WS['sw']
        for i in range(a, min(a + 16, 255)):
            try:
                WS['sock'].sendto(msg, (base + str(i), 38899))
            except Exception:
                pass
        WS['sw'] = 0 if a + 16 >= 255 else a + 16
    if t - BOOT_T[0] < 30:
        return
    if t - WS.get('saved', 0) > 300 and WS['seen']:
        WS['saved'] = t
        try:
            with open('wiz.json', 'w') as f:
                json.dump({m: x['ip'] for m, x in WS['seen'].items()}, f)
        except Exception as e:
            print('wiz save', e)
    # raz na godzinę: jakość Wi-Fi każdej żarówki (siła sygnału i ile odpowiedzi doszło)
    if 'rep' not in WS:
        WS['rep'] = t - 3000  # pierwszy raport ok. 10 min po starcie
    if t - WS['rep'] >= 3600 and WS.get('st'):
        WS['rep'] = t
        names = {'bed': 'syp', 'bath': 'laz', 'work': 'sal/kuch'}
        out = []
        for mac, x in sorted(WS['seen'].items(), key=lambda a: (room_of(a[0]) or 'z', a[1]['ip'])):
            q, r, rs, rn = WS['st'].get(x['ip'], [0, 0, 0, 0])
            if q:
                out.append('%s %s %s%% %s' % (names.get(room_of(mac), '?'), mac[-4:], min(100, r * 100 // q), ('%ddBm' % (rs // rn)) if rn else '?'))
        WS['st'] = {}
        log('wifi zarowek (odpowiedzi, sygnal): ' + ' | '.join(out))
    for c in list(WS.get('cmds', [])):  # statystyka poleceń: ile żarówek, w jakim czasie, ile ponowień
        if not c['left'] or t - c['t0'] > 300:
            WS['cmds'].remove(c)
            d = sorted(c['done'].values())
            st = WS.setdefault('cmd_stat', {'n': 0, 'bulbs': 0, 'ok': 0, 'rs': 0, 'slow': 0})
            st['n'] += 1
            st['bulbs'] += c['n']
            st['ok'] += len(d)
            st['rs'] += c['rs']
            st['slow'] += sum(1 for v in d if v > 3)
            log('polecenie %s %s: %d/%d potwierdzone (w serii do 4 s: %d), najwolniej %.1f s, ponowien %d%s' % (
                c['room'], 'on' if c['on'] else 'off', len(d), c['n'], c.get('burst', 0), d[-1] if d else 0, c['rs'],
                '' if not c['left'] else ', BRAK: ' + ' '.join('.' + i.split('.')[-1] for i in c['left'])))
    pres = ws_present()
    if not WS['inv']:
        WS['inv'] = True
        log('zarowki w sieci: %d (%s): %s' % (len(pres), 'broadcast' if WS['bc_ok'] else 'brak odpowiedzi', ' '.join(
            '%s=%s/%s/%s/%s' % (mac[-4:], x['ip'].split('.')[-1], 'wl' if x['p'].get('state') else 'wyl', x['p'].get('temp'), x['p'].get('dimming'))
            for mac, x in sorted(pres.items(), key=lambda a: a[1]['ip']))))
    # nauka klawiszy: zmiany obecności w logu
    keys = set(pres.keys())
    if WS['pres'] is not None and t < WS['learn']:
        gone = WS['pres'] - keys
        back = keys - WS['pres']
        if gone or back:
            def fmt(ms):
                return ' '.join('%s(.%s)' % (m[-4:], WS['seen'][m]['ip'].split('.')[-1]) for m in sorted(ms))
            log('zarowki: %s%s| w sieci %d' % ('zniknely %s ' % fmt(gone) if gone else '', 'wrocily %s ' % fmt(back) if back else '', len(keys)))
    WS['pres'] = keys
    # barwa wg pory dnia: tylko świecące żarówki (poza lampką za łóżkiem, która ma własne budzenie)
    if False:  # od 1.0.100 barwa poprawiana przy odpowiedzi żarówki (wyżej)
        WS['col'] = t
        tg = {}
        for mac, x in pres.items():
            p = x['p']
            room = room_of(mac)
            if mac[-4:].lower() == BED_LAMP or x['ip'] == PLAN.get('wiz_bed') or not p.get('state'):
                continue
            if room not in tg:
                tg[room] = light_target(room or 'work')
            k, dim = tg[room]
            if p.get('sceneId') or abs((p.get('temp') or 0) - k) >= 100 or abs((p.get('dimming') or 0) - dim) >= 5:
                ws_send(x['ip'], {'temp': k, 'dimming': dim})


MOT = {'t': 0, 'new': False, 'on': False}


def room_burst(ips, pr, cmd):
    """Szybka seria (25.11): żarówki WiZ co chwilę usypiają radio i gubią pojedyncze paczki UDP, a zwykłe ponawianie
    w pętli płytki szło z przerwami (inne zadania), stąd zapalanie „na raty” (do 72 s). Teraz przez najwyżej 4 s
    płytka zajmuje się tylko tymi żarówkami: wysyła polecenie co 0,25 s każdej niepotwierdzonej i od razu pyta o stan,
    aż wszystkie potwierdzą. Resztę (rzadkie maruderki) dokańcza zwykła pętla."""
    sock = WS.get('sock')
    if not sock:
        return
    msg = json.dumps({'method': 'setPilot', 'params': pr}).encode()
    ask = b'{"method":"getPilot","params":{}}'
    left = set(ips)
    t0 = time.ticks_ms()
    last = -1000
    while left and time.ticks_diff(time.ticks_ms(), t0) < PLAN.get('burst_ms', 4000):
        now = time.ticks_ms()
        if time.ticks_diff(now, last) >= 250:
            last = now
            for ip in left:
                try:
                    sock.sendto(msg, (ip, 38899))
                    sock.sendto(ask, (ip, 38899))
                except Exception:
                    pass
        for _ in range(40):
            try:
                data, addr = sock.recvfrom(1024)
            except Exception:
                break
            try:
                x = json.loads(data).get('result')
            except Exception:
                continue
            if not isinstance(x, dict) or not x.get('mac'):
                continue
            WS['seen'][x['mac']] = {'ip': addr[0], 't': time.time(),
                                    'p': {k: x[k] for k in ('state', 'temp', 'dimming', 'sceneId') if k in x}}
            ip = addr[0]
            ok_ = bool(x.get('state')) == pr['state']
            if ok_ and pr['state'] and 'temp' in pr:  # zmiana barwy: potwierdzone dopiero, gdy barwa i jasność się zgadzają
                ok_ = abs((x.get('temp') or 0) - pr['temp']) < 100 and abs((x.get('dimming') or 0) - pr.get('dimming', 0)) < 5
            if ip in left and ok_:
                left.discard(ip)
                WS.get('want', {}).pop(ip, None)
                if ip in cmd['left']:
                    cmd['left'].discard(ip)
                    cmd['done'][ip] = time.ticks_diff(time.ticks_ms(), t0) / 1000
        time.sleep_ms(20)
    cmd['burst'] = len(ips) - len(left)


def room_set(room, on, why=''):
    """Zapala (w barwie pomieszczenia) albo gasi wszystkie żarówki pomieszczenia, bez czekania na odpowiedź."""
    ips = room_ips(room)
    if not ips:
        return
    MAN.pop(room, None)  # automatyka przejmuje pokój ustawiony ręcznie z panelu
    want = WS.setdefault('want', {})
    if on:
        k, dim = light_target(room)
        pr = {'state': True, 'temp': k, 'dimming': dim}
    else:
        pr = {'state': False}
    cmd = {'room': room, 'on': on, 't0': time.time(), 'left': set(ips), 'n': len(ips), 'rs': 0, 'done': {}}
    WS.setdefault('cmds', []).append(cmd)
    for ip in ips:
        # zapamiętany cel na 5 min: dopóki żarówka nie potwierdzi stanu, płytka ponawia polecenie
        want[ip] = {'p': pr, 'until': time.time() + 300, 'at': time.time(), 'cmd': cmd}
    room_burst(ips, pr, cmd)
    if why:
        log('swiatla %s %s (%s, %d zarowek)' % (room, 'on' if on else 'off', why, len(ips)))


def bath_timeout(night):
    """Ile sekund bez ruchu, zanim łazienka zgaśnie (25.11): w nocy 1 min; pora prysznica 8 min
    (rano w trybie porannym, wieczorem od 20:00 albo po powrocie po 18:00); w dzień 2 min."""
    if night:
        return PLAN.get('bath_off_night', 60)
    m = mins()
    if morning_on() or m >= PLAN.get('bath_long_from', 1200) or m < 240 or state.get('ret18') == day_key():
        return PLAN.get('bath_off_shower', 480)
    return PLAN.get('bath_off_day', 120)


def bath_tick():
    """Łazienka tylko na czujnik: ruch -> światło w trybie pory, cisza 5 min (w nocy 2 min) -> zgaszone.
    W nocy świeci jedna żarówka, ciemno i ciepło."""
    if not PLAN.get('bath_motion'):
        return
    if GW_MOT['id'] is None and time.time() - MOT.get('diag', 0) > 300 and time.time() - BOOT_T[0] > 60:
        MOT['diag'] = time.time()  # diagnostyka co 5 min: czy czujnik ruchu dociera do płytki
        bm = BTH_SEEN.get(PLAN['bath_motion'])
        if bm:
            raw = ' '.join('%02x' % b for b in bm[1])
            if not MOT.get('diag_ok') or bm[1][0] & 0x01:
                MOT['diag_ok'] = True
                log('lazienka czujnik: odebrany %ds temu, dane %s%s' % (time.time() - bm[0], raw, ' (ZASZYFROWANY)' if bm[1][0] & 0x01 else ''))
        else:
            log('lazienka czujnik: brak sygnalu; czujniki BTHome w zasiegu: %s' % (', '.join(sorted(BTH_SEEN.keys())) or 'zaden'))
    ips = sorted(room_ips('bath'))
    if not ips:
        if MOT['new']:
            MOT['new'] = False
            log('lazienka ruch, ale plytka nie zna jeszcze zarowek lazienki')
        return
    night = bool(state.get('asleep'))
    if MOT.get('rs') and time.time() - MOT.get('rs_at', 0) >= 0.7:
        # polecenie po UDP bywa gubione: powtarzamy je jeszcze 3 razy co ~1 s
        MOT['rs'] -= 1
        MOT['rs_at'] = time.time() + 2
        MOT['new'] = True
        MOT['quiet'] = True
    if MOT['new']:
        MOT['new'] = False
        if not MOT.pop('quiet', False):
            MOT['rs'] = 1
            MOT['rs_at'] = time.time()
            MOT['rs_log'] = False
        k, dim = light_target('bath')
        mb = (MAN.get('bath') or {}).get('pr') or {}
        mw = (MAN.get('work') or {}).get('pr') or {}
        if mb.get('state') and any(x['p'].get('state') for mac, x in WS['seen'].items() if room_of(mac) == 'bath'):
            # 26.11: łazienka ustawiona ręcznie i wciąż świeci: ruch nie przywraca automatu (było: 15% z panelu -> 45%)
            k, dim = mb.get('temp', k), mb.get('dimming', dim)
        elif mw.get('state') and mw.get('dimming') and k <= 3000:
            # wieczorem łazienka nie jaśniejsza niż ręcznie przyciemniony salon
            dim = min(dim, mw['dimming'])
        use = ips[:1] if (night or nl_eve_on()) else ips
        # wszystkie naraz szybką serią z potwierdzeniem (25.11), zamiast po kolei z czekaniem na każdą
        pr = {'state': True, 'temp': k, 'dimming': dim}
        bc = {'room': 'bath', 'on': True, 't0': time.time(), 'left': set(use), 'n': len(use), 'rs': 0, 'done': {}}
        for ip in use:
            WS.setdefault('want', {})[ip] = {'p': pr, 'until': time.time() + 60, 'at': time.time(), 'cmd': bc}
        room_burst(use, pr, bc)
        bad = [ip.split('.')[-1] for ip in bc['left']]
        if not MOT.get('rs_log'):
            MOT['rs_log'] = True
            tm = now_local()
            log('lazienka TEST %02d:%02d:%02d: ruch z %s, zarowki %s, %s' % (
                tm[3], tm[4], tm[5], MOT.get('src', '?'), ' '.join('.' + i.split('.')[-1] for i in use),
                'wszystkie potwierdzily' if not bad else 'NIE potwierdzily: .' + ',.'.join(bad)))
        if night or nl_eve_on():
            for ip in ips[1:]:
                ws_send(ip, {'state': False})
        if not MOT['on']:
            MAN.pop('bath', None)  # nowe wejście: łazienka znów na czujniku
            MOT['on'] = True
            MOT['on_at'] = time.time()
            log('lazienka ruch: on %sK %s%%' % (k, dim))
            if night:
                state['night_walks'] = (state.get('night_walks') or 0) + 1  # nocne wyjścia do łazienki (jakość snu)
                log('lazienka w nocy (%d. raz tej nocy)' % state['night_walks'])
    elif 'bath' not in MAN and time.time() - MOT.get('lt', MOT['t']) > bath_timeout(night) and time.time() - MOT.get('chk', 0) > 20 \
            and (not GW_MOT['val'] or time.time() - MOT.get('lt', MOT['t']) > PLAN.get('bath_stuck', 1200)):
        # brak ruchu: gasimy, także gdy światło zapaliło się inaczej (klawisz, aplikacja).
        # Czujnik przy ciągłym ruchu nic nie nadaje (stan „ruch” trwa), a koniec ruchu zgłasza osobną wiadomością.
        # Dopóki stan to „ruch”, światło świeci. Zabezpieczenie na zgubioną wiadomość o końcu: 20 min bez żadnej
        # wiadomości (25.11: 4 min gasiły światło, gdy byłem w łazience).
        if GW_MOT['val']:
            GW_MOT['val'] = False
            log('lazienka: czujnik nie zglosil konca ruchu, gasze po czasie')
        MOT['chk'] = time.time()
        lit = [x['ip'] for mac, x in ws_present().items() if room_of(mac) == 'bath' and x['p'].get('state')]
        if MOT['on']:
            # weekendowy poranek kończy się po prysznicu: pobyt w łazience co najmniej 5 min, potem wyjście
            mo = state.get('morn')
            if mo and mo.get('we') and not mo.get('shower') and morning_on() \
                    and MOT.get('lt', 0) - MOT.get('on_at', time.time()) >= PLAN.get('shower_min', 300):
                mo['shower'] = True
                log('poranek: koniec prysznica, salon i kuchnia w tryb dzienny')
                if [1 for mac, x in ws_present().items() if room_of(mac) == 'work' and x['p'].get('state')]:
                    room_set('work', True, 'po prysznicu')
        if MOT['on'] or lit:
            if lit and not MOT['on'] and time.time() - MOT.get('lg', 0) > 600:
                MOT['lg'] = time.time()
                log('lazienka: brak ruchu, gasze (%d zarowek)' % len(lit))
            MOT['on'] = False
            for ip in ips:
                ws_send(ip, {'state': False})


def fb_process():
    """firstBeat = żarówka (ponownie) połączyła się z Wi-Fi: po włączeniu klawisza, ale też po restarcie routera,
    zmianie kanału czy mignięciu prądu. Klawisz zasila jedno pomieszczenie, więc zapalamy tylko wtedy, gdy w ciągu
    kilku sekund zgłosiły się żarówki z jednego pomieszczenia. Gdy naraz z kilku pomieszczeń: to sieć albo prąd,
    nic nie zapalamy (24.11 rano zmiana kanału w routerze zapaliła żarówki w sypialni)."""
    pend = WZ.get('pend')
    if not pend:
        return
    now = time.time()
    def room_ip(ip):
        if ip == PLAN.get('wiz_bed'):
            return 'lamp'
        for mac, x in WS['seen'].items():
            if x['ip'] == ip:
                return room_of(mac) or mac[-4:].lower()
        return ip
    # pokój właśnie zapalony klawiszem: kolejne żarówki tego pokoju (później złapały Wi-Fi) zapalamy od razu
    hot = WZ.get('hot')
    if hot and now < hot[1]:
        for ip in list(pend.keys()):
            if room_ip(ip) == hot[0]:
                pend.pop(ip)
                want = WS.setdefault('want', {})
                if hot[0] in ('bed', 'work') and not (state.get('asleep') or state.get('wl') or state.get('away')):
                    k, dim = light_target(hot[0])
                    pr = {'state': True, 'temp': k, 'dimming': dim}
                    cmd = {'room': hot[0], 'on': True, 't0': time.time(), 'left': {ip}, 'n': 1, 'rs': 0, 'done': {}}
                    want[ip] = {'p': pr, 'until': time.time() + 300, 'at': time.time(), 'cmd': cmd}
                    room_burst([ip], pr, cmd)
        if not pend:
            return
    if now - min(t for t, _ in pend.values()) < PLAN.get('fb_wait', 2.5):
        return
    rooms = set(room_ip(ip) for ip in pend)
    ips = list(pend.keys())
    WZ['pend'] = {}
    if now - BOOT_T[0] < 120:
        return  # tuż po starcie płytki to nie klawisz
    if len(rooms) > 1:
        log('zarowki: %d naraz z kilku pomieszczen (%s) - siec/prad, nic nie zapalam' % (len(ips), ','.join(sorted(str(r) for r in rooms))))
        return
    rm = list(rooms)[0]
    if rm in ('bed', 'work') and PLAN.get('lt_auto', True) and not (state.get('asleep') or state.get('wl')) \
            and not (SNAP['boot_rc'] == 'zasilanie' and now - BOOT_T[0] < 180) and not wiz_away(ips[0]):
        # klawisz zasila cały pokój: zapalamy od razu wszystkie jego żarówki jedną serią (25.11, koniec „na raty”)
        WZ['hot'] = (rm, now + 30)
        room_set(rm, True, 'klawisz')
        return
    for ip in ips:
        wiz_power_on(ip, 'firstBeat')


# ---------- lampka nocna (Osram SMART+ WiFi G9, Tuya) ----------
# Klawisz jest sygnałem: żarówki dostają prąd (lampka ON) albo znikają z sieci (OFF).
# Płytka słucha ich rozgłoszeń (UDP 6666/6667, w nich identyfikator i IP) i co 2 s puka na port 6668.
NL = {'socks': None, 'ips': {}, 'seen': {}, 'probe': {}, 'probe_at': 0, 'on': None, 'off_since': 0, 'learn_log': 0}
_NL_KEY = b'l\x1e\xc8\xe2\xbb\x9b\xb5\x9a\xb5\x0b\r\xafd\x9bA\n'  # md5("yGAdlopoPVldABfn"): stały klucz rozgłoszeń Tuya


def nl_eve_on():
    # lampka nocna zapalona po 21:00, jeszcze przed nocą: łazienka już w trybie nocnym
    t = state.get('nl_eve')
    return bool(t) and time.time() - t < 8 * 3600


def nl_mode():
    return bool(PLAN.get('night_lamp')) and time.time() - (state.get('nl_seen') or 0) < 3 * 86400


def _nl_packet(data, ip):
    ids = PLAN.get('nl_ids') or []
    gid = None
    try:
        import cryptolib
    except ImportError:
        import ucryptolib as cryptolib
    v35 = data[:4] == b'\x00\x00\x66\x99'
    if v35 and len(data) > 50:
        # Tuya 3.5 (prefiks 6699): AES-GCM; tag pomijamy, odszyfrowanie licznikiem (CTR) na zwykłym AES
        try:
            n = int.from_bytes(data[14:18], 'big')
            b = data[18:18 + n]
            iv, ct = b[:12], b[12:-16]
            aes = cryptolib.aes(_NL_KEY, 1)
            out = bytearray()
            for i in range(0, len(ct), 16):
                ks = aes.encrypt(iv + (i // 16 + 2).to_bytes(4, 'big'))
                out += bytes(x ^ y for x, y in zip(ct[i:i + 16], ks))
            gid = json.loads(out[out.find(b'{'):out.rfind(b'}') + 1]).get('gwId')
        except Exception as e:
            print('nl 3.5', e)
    elif len(data) > 28:
        for start in (20, 24):
            body = data[start:-8]
            if not body or len(body) % 16:
                continue
            try:
                raw = cryptolib.aes(_NL_KEY, 1).decrypt(body)
                raw = raw[:len(raw) - raw[-1]] if 0 < raw[-1] <= 16 else raw
                j = json.loads(raw)
                gid = j.get('gwId')
                break
            except Exception:
                pass
        if gid is None:
            try:  # stare żarówki rozgłaszają jawnym tekstem
                i = data.find(b'{')
                j = json.loads(data[i:data.rfind(b'}') + 1])
                gid = j.get('gwId')
            except Exception:
                pass
    if gid in ids:
        if NL['ips'].get(gid) != ip:
            NL['ips'][gid] = ip
            log('lampka nocna: zarowka %s pod %s' % (gid[-4:], ip))
            try:
                with open('nl.json', 'w') as f:
                    json.dump(NL['ips'], f)
            except Exception:
                pass
        NL['seen'][ip] = time.time()
    elif gid is None and v35 and ip not in NL['ips'].values() and len(set(NL['ips'].values())) < len(ids):
        # nie dało się odczytać, a w domu nie ma innych urządzeń Tuya: to żarówka z lampki
        NL['ips']['ip' + ip] = ip
        NL['seen'][ip] = time.time()
        log('lampka nocna: zarowka pod %s (bez odczytu identyfikatora)' % ip)
    elif gid is None and time.time() - NL['learn_log'] > 3600:
        NL['learn_log'] = time.time()
        log('lampka nocna: nieznane rozgloszenie z %s (%d B, %s)' % (ip, len(data), data[:4]))


def nl_tick():
    if not PLAN.get('night_lamp'):
        return
    if state.get('cozy') and (mins() >= 1320 or mins() < 240 or state.get('asleep')):
        state['cozy'] = None
        if PLAN.get('wiz_bed') and not state.get('asleep'):
            ok = wiz({'state': False}) is not None
            log('22:00: lampka za lozkiem off' + ('' if ok else ' (nie odpowiada)'))
    import socket
    now = time.time()
    if NL['socks'] is None:
        NL['socks'] = []
        for port in (6666, 6667):
            try:
                u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                u.bind(('0.0.0.0', port))
                u.setblocking(False)
                NL['socks'].append(u)
            except Exception as e:
                log('lampka nocna: port %d niedostepny (%s)' % (port, e))
        try:
            with open('nl.json') as f:
                NL['ips'].update(json.load(f))
        except Exception:
            pass
        for ip in (PLAN.get('nl_ips') or []):
            NL['ips'].setdefault('cfg' + ip, ip)
    for u in NL['socks']:
        for _ in range(6):
            try:
                data, addr = u.recvfrom(1024)
            except Exception:
                break
            _nl_packet(data, addr[0])
    # pukanie na port 6668 (bez blokowania pętli): połączenie przyjęte = żarówka ma prąd
    import select
    for ip in list(NL['probe']):
        c, t0 = NL['probe'][ip]
        ev = 0
        try:
            p = select.poll()
            p.register(c, select.POLLOUT | select.POLLERR | select.POLLHUP)
            r = p.poll(0)
            ev = r[0][1] if r else 0
        except Exception:
            ev = select.POLLERR
        if ev & (select.POLLERR | select.POLLHUP) or (not ev and now - t0 > 2):
            done = True
        elif ev & select.POLLOUT:
            NL['seen'][ip] = now
            done = True
        else:
            done = False
        if done:
            try:
                c.close()
            except Exception:
                pass
            del NL['probe'][ip]
    m_ = mins()
    # pukanie do lampki: wieczorem i w nocy co 2 s (szybka reakcja), w dzień co 10 s (lampka nic wtedy nie steruje)
    if now - NL['probe_at'] >= (2 if (m_ >= 1200 or m_ < 300 or NL['on']) else 10):
        NL['probe_at'] = now
        for ip in set(NL['ips'].values()):
            if ip in NL['probe']:
                continue
            try:
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                c.setblocking(False)
                try:
                    c.connect(socket.getaddrinfo(ip, 6668)[0][-1])
                except OSError:
                    pass  # EINPROGRESS: wynik sprawdzi poll w kolejnym obiegu
                NL['probe'][ip] = (c, now)
            except Exception as e:
                print('nl probe', e)
    if not NL['ips'] or now - BOOT_T[0] < 20:
        return
    alive = any(now - t < PLAN.get('nl_alive_s', 3.5) for t in NL['seen'].values())
    if alive:
        state['nl_seen'] = now
        NL['off_since'] = 0
        if NL['on'] is not True:
            prev = NL['on']
            NL['on'] = True
            if prev is not None:
                nl_event(True)
            else:
                print('lampka nocna: start, swieci')
    else:
        if not NL['off_since']:
            NL['off_since'] = now
        if NL['on'] is not False and now - NL['off_since'] >= PLAN.get('nl_off_s', 10):
            prev = NL['on']
            NL['on'] = False
            if prev is not None:
                nl_event(False)
            else:
                print('lampka nocna: start, zgaszona')


def nl_event(on):
    m = mins()
    if m >= PLAN['night_from'] or m < 240:
        man_clear('lampka nocna')
    night = m >= PLAN['night_from'] or m < 240
    if not night:
        log('lampka nocna %s (dzien, nic nie robie)' % ('on' if on else 'off'))
        return
    if state.get('away'):
        log('lampka nocna %s, ale mnie nie ma: nic' % ('on' if on else 'off'))
        return
    if state.get('asleep'):
        if on:
            log('lampka nocna on w nocy (noc trwa)')
            if PLAN.get('lamp_salon'):  # 26.11: lampka w nocy = coś mi się przypomniało, idę do salonu: lampa za kanapą
                plug_set(PLAN['lamp_salon'], True, 'lampa salon on (lampka w nocy)')
            return
        # ponowne zgaszenie w nocy: nowa pora zaśnięcia (statystyki snu i 8 h do budzenia światłem)
        state['ln_t'] = time.time()
        state['sleep_at'] = m
        log('lampka nocna off ponownie: nowa pora zasniecia')
        if PLAN.get('lamp_salon'):
            plug_set(PLAN['lamp_salon'], False, 'lampa salon off (lampka zgaszona)')
        try:
            gas({'e': 'down'}, False, 'phone')
        except Exception as e:
            log('lampka nocna: blad zapisu do arkusza %s' % e)
        return
    if on:
        # lampka po 21:00: wszystko gaśnie poza lampą za kanapą, łazienka nocna, zasłony zasuwane
        state['nl_eve'] = time.time()
        cozy = PLAN['night_from'] <= m < 1320
        log('lampka nocna on: gasze wszystko, zapalam lampe salon%s' % (', lampka za lozkiem przytulnie do 22:00' if cozy else ''))
        for r in ('work', 'bed'):
            room_set(r, False, 'lampka nocna')
        if PLAN.get('kitchen_led'):
            plug_set(PLAN['kitchen_led'], False, 'kuchnia led off')
        if PLAN.get('lamp_salon'):
            plug_set(PLAN['lamp_salon'], True, 'lampa salon on (czytanie)')  # jedyne światło w salonie przed nocą
        if PLAN.get('wiz_bed'):
            if cozy:
                state['cozy'] = day_key()
                wiz({'state': True, 'temp': 2200, 'dimming': 30})
            else:
                wiz({'state': False})
        if state.get('cur_state') != 'close':
            curtains('close', 'lampka nocna', quiet=False)
        # 26.11: w trybie czytania sypialnia zaczyna się powoli wychładzać
        trv_target('bed', PLAN.get('bed_read', 21.0))
        # salon cicho już w trybie czytania (jak w nocy)
        dev_set('salon_hum', 'sh_mode', 1, 'salon nawilzacz tryb nocny (czytanie)')
        dev_set('salon_pur', 'sp_mode', 3, 'salon oczyszczacz tryb nocny (czytanie)')
        # łazienka od razu nocna: jeśli świeci, zostaje jedna żarówka 2700 K 15%
        bips = sorted(room_ips('bath'))
        lit = [x['ip'] for mac, x in ws_present().items() if room_of(mac) == 'bath' and x['p'].get('state')]
        if bips and (lit or MOT.get('on')):
            ws_send(bips[0], {'state': True, 'temp': 2700, 'dimming': 10})
            for ip in bips[1:]:
                ws_send(ip, {'state': False})
            log('lazienka: tryb nocny (jedna zarowka)')
        return
    # zgaszona 21:00-4:00 = idę spać
    state['ln_t'] = time.time()
    log('lampka nocna off: noc')
    NOW[0] = True
    try:
        gas({'e': 'down'}, False, 'phone')  # wpis „odłożony” w Telefon: od niego liczy się sen
    except Exception as e:
        log('lampka nocna: blad zapisu do arkusza %s' % e)


def night_lamp_guard():
    # zapas dla żarówki bez WiZclick „Wył.”: w nocy przez 10 min po starcie płytki gasimy ją, gdy wróci do sieci włączona
    if not PLAN.get('wiz_bed') or not state.get('asleep') or state.get('wl'):
        return
    if time.time() - BOOT_T[0] > 600 or time.time() - state.get('nlg_at', 0) < 20:
        return
    state['nlg_at'] = time.time()
    r = wiz({}, 'getPilot')
    if r and (r.get('result') or {}).get('state'):
        if wiz({'state': False}) is not None:
            log('noc: lampka sypialnia zapalila sie po zaniku pradu, gasze')


def wake_hold():
    """Budzenie trwa albo dobiegło końca, a ja jeszcze nie wstałem: światła z budzenia zostają (bez strażnika i korekt)."""
    return bool(state.get('wl')) or (state.get('wl_done') == time.localtime()[2] and bool(state.get('asleep')) and mins() < 720)


def wake_ceiling(p):
    """Sufit w sypialni (żarówki bez koloru) razem z lampką: od ciemnej ciepłej bieli do jasnej 3500 K."""
    if not PLAN.get('wake_ceiling', True):
        return
    p = max(0.0, min(1.0, p))
    dim = int(10 + 90 * p ** 2.5 + 0.5)
    k = (2700 + int(800 * p ** 1.5)) // 100 * 100
    # 26.11: rozjaśnia się całe mieszkanie (sypialnia, salon, kuchnia), łazienka zostaje na czujniku
    for ip in list(room_ips('bed')) + list(room_ips('work')):
        ws_send(ip, {'state': True, 'temp': k, 'dimming': dim})


def wake_half():
    """27.11: połowa budzenia: cicho otwieramy zasłony. Ich start to w aplikacji treningowej godzina pobudki
    (budzi mnie ich dźwięk), więc arkusz dostaje znacznik przebudzenia."""
    if not state.get('asleep'):
        return
    curtains('open', 'budzenie, polowa')
    try:
        gas({}, action='przebudzenie')
    except Exception as e:
        log('przebudzenie: blad wysylki %s' % e)


def wake_light_tick():
    """Co 15 s podczas rozjaśniania: kolejny krok jasności."""
    wl = state.get('wl')
    if not wl or time.time() - state.get('wl_at', 0) < 15:
        return
    state['wl_at'] = time.time()
    p = (time.time() - wl['t0']) / (wl.get('min', PLAN['wake_light_min']) * 60.0)
    wake_ceiling(p)
    if not PLAN.get('wake_lamp', False):
        # lampka za łóżkiem nie bierze udziału w budzeniu (za blisko twarzy, 23.11): budzi tylko sufit
        if p >= 1:
            state['wl'] = None
            state['wl_done'] = time.localtime()[2]
            log('budzenie swiatlem: pelna jasnosc (sufit)')
        elif not wl.get('half') and p >= 0.5:
            wl = dict(wl)
            wl['half'] = 1
            state['wl'] = wl
            log('budzenie swiatlem: polowa (sypialnia, salon, kuchnia: %d zarowek)' % (len(room_ips('bed')) + len(room_ips('work'))))
            wake_half()
        return
    if p >= 1:
        if wiz(wake_pilot(1.0)) is None and 'Invalid params' in str(state.get('wiz_err')):
            state['wiz_lvl'] = 2
            wiz(wake_pilot(1.0))
        state['wl'] = None
        state['wl_done'] = time.localtime()[2]
        log('budzenie swiatlem: pelna jasnosc')
        return
    ok = wiz(wake_pilot(max(p, 0))) is not None
    while not ok and 'Invalid params' in str(state.get('wiz_err')) and (state.get('wiz_lvl') or 0) < 2:
        # żarówka nie zna któregoś ustawienia (np. kolorów): upraszczamy i próbujemy od razu jeszcze raz
        state['wiz_lvl'] = (state.get('wiz_lvl') or 0) + 1
        log('lampka: upraszczam ustawienia (poziom %d)' % state['wiz_lvl'])
        ok = wiz(wake_pilot(max(p, 0))) is not None
    if ok and not wl.get('half') and p >= 0.5:
        wl = dict(wl)
        wl['half'] = 1
        state['wl'] = wl
        log('budzenie swiatlem: polowa (lampka odpowiada)')
        wake_half()
    if not ok and not wl.get('err'):
        wl = dict(wl)
        wl['err'] = 1
        state['wl'] = wl
        log('lampka sypialnia nie odpowiada (%s)' % state.get('wiz_err'))


def trv_target(name, temp, force=False):
    tid = cfg.get('trv', {}).get(name)
    if tid is None:
        return
    temp = round(float(temp) * 2) / 2
    r = 's' if name == 'salon' else 'b'
    rec = air(r)
    if rec and not force:
        rec = dict(rec)
        rec['trv'] = temp
        air_put(r, rec)
        log('grzejnik %s: okno otwarte, %s po zamknieciu' % (name, temp))
        return
    try:
        if BOOST.get(name) and temp < PLAN['bed_morning' if name == 'bed' else 'salon_morning']:
            boost_off(name)
        trv_call(tid, 'TRV.SetTarget', {'id': 0, 'target_C': temp})
        state['trv_' + name] = temp
        state.pop('trv_retry_' + name, None)
        log('grzejnik %s -> %s' % (name, temp))
    except Exception as e:
        state['trv_retry_' + name] = temp  # ponowimy przy najbliższym sprawdzeniu głowic (co 30 min)
        log('grzejnik %s blad %s' % (name, e))


BOOST = {}  # głowica -> czas ostatniego włączenia boostu (tylko w RAM; po restarcie płytka odnawia go od razu)


def boost_on(name):
    tid = cfg.get('trv', {}).get(name)
    try:
        trv_call(tid, 'TRV.SetBoost', {'id': 0, 'duration': 1800})
        if not BOOST.get(name):
            log('grzejnik %s boost' % name)
        BOOST[name] = time.time()
    except Exception as e:
        log('grzejnik %s boost blad %s' % (name, e))


def boost_off(name):
    tid = cfg.get('trv', {}).get(name)
    BOOST.pop(name, None)
    try:
        trv_call(tid, 'TRV.ClearBoost', {'id': 0})
        log('grzejnik %s boost off' % name)
    except Exception as e:
        log('grzejnik %s boost off blad %s' % (name, e))


TCUR = {}  # pokój -> (czas, temperatura) z ostatniego odczytu
TTGT = {}  # głowica -> cel odczytany z głowicy


def room_temp(room, q_t):
    # salon: Qingping (głowica stoi przy oknie), sypialnia: głowica; odczyt głowicy najwyżej co 5 min
    if room == 's' and q_t is not None:
        return q_t
    name = ROOM_TRV[room]
    c = TCUR.get(name)
    if c and time.time() - c[0] < 300:
        return c[1]
    gw, tid = cfg.get('shelly_gw'), cfg.get('trv', {}).get(name)
    if not gw or tid is None:
        return None
    try:
        gc.collect()
        r = requests.get('http://%s/rpc/BluTrv.GetRemoteStatus?id=%s' % (gw, tid), timeout=10)
        try:
            tv = r.json()['status']['trv:0']
            v = tv['current_C']
            if tv.get('target_C') is not None:
                TTGT[name] = tv['target_C']  # 26.11: faktyczny cel z głowicy (dla panelu, także po restarcie płytki)
        finally:
            r.close()
        TCUR[name] = (time.time(), v)
        return v
    except Exception:
        return c[1] if c else None


def tout_band():
    """Pasmo temperatury na zewnątrz (z arkusza, Open-Meteo): mróz / zimno / łagodnie. None = brak danych."""
    t = state.get('tout')
    if t is None:
        return None
    return 'mroz' if t <= 0 else ('zimno' if t <= 6 else 'lagodnie')


def heat_lead(room, cur, target):
    # ile minut przed pobudką zacząć, żeby na pobudkę było ciepło (tempo nagrzewania uczone co rano;
    # od 26.11 osobno dla mrozu, zimna i łagodnej pogody, a gdy pasmo jeszcze nieznane: tempo ogólne)
    b = tout_band()
    rate = (state.get('rates_' + room) or {}).get(b) if b else None
    rate = rate or state.get('rate_' + room) or PLAN['heat_rate']
    if cur is None:
        return PLAN['salon_heat_pre_min']
    need = max(0.0, target - cur) / rate * 60 + PLAN['pre_margin']
    return int(max(PLAN['pre_min'], min(PLAN['pre_max'], need)))


def heat_learn(room, cur, done):
    # zapamiętuje tempo nagrzewania: po dojściu do celu albo przy wstaniu
    h = state.get('heat_' + room)
    if not h or cur is None:
        return
    hours = (time.time() - h['t0']) / 3600.0
    rise = cur - h['T0']
    if not done and cur < h['tgt'] - 0.3:
        return
    state['heat_' + room] = None
    if hours < 0.33 or rise < 0.5:
        return
    rate = max(0.5, min(6.0, rise / hours))
    old = state.get('rate_' + room) or PLAN['heat_rate']
    new = round(0.6 * old + 0.4 * rate, 2)
    state['rate_' + room] = new
    b = h.get('band')
    bn = None
    if b:
        rs = dict(state.get('rates_' + room) or {})
        ob = rs.get(b) or new
        bn = round(0.6 * ob + 0.4 * rate, 2)
        rs[b] = bn
        state['rates_' + room] = rs
    log('nagrzewanie %s: %.1f -> %.1f w %d min (%.1f C/h), tempo %.2f%s' % (ROOM_NAME[room], h['T0'], cur, hours * 60, rate, new,
        (', na zewnatrz %s (%s, tempo %.2f)' % (h.get('tout'), b, bn)) if b else ''))


def boost_tick(asleep, m):
    # boost trwa od startu grzania przed pobudką do wstania (telefon z ładowarki albo waga); odnawiany co 20 min
    if not state.get('boost_day') == day_key() or not PLAN['wake_boost']:
        return
    if not asleep or m >= 720:
        state['boost_day'] = None
        for n in list(BOOST):
            boost_off(n)
        return
    for name, room, key in (('salon', 's', 'salon_morning'), ('bed', 'b', 'bed_morning')):
        if air(room) or state.get('trv_' + name) != PLAN[key]:
            continue
        if time.time() - BOOST.get(name, 0) > 1200:
            boost_on(name)


def trv_brief():
    # skrót stanu głowic do logu: temperatura głowicy / cel / otwarcie zaworu
    gw = cfg.get('shelly_gw')
    out = []
    for name in ('salon', 'bed'):
        tid = cfg.get('trv', {}).get(name)
        if not gw or tid is None:
            continue
        try:
            gc.collect()
            r = requests.get('http://%s/rpc/BluTrv.GetRemoteStatus?id=%s' % (gw, tid), timeout=10)
            try:
                t = r.json()['status']['trv:0']
            finally:
                r.close()
            out.append('%s %.1f/%.1f %d%%' % (name, t['current_C'], t['target_C'], t['pos']))
            room = 's' if name == 'salon' else 'b'
            want = state.get('trv_retry_' + name)
            if want is not None and not air(room):
                log('grzejnik %s: ponawiam %s (poprzednio blad)' % (name, want))
                trv_target(name, want)
            elif t['target_C'] <= 5.5 and not air(room):
                log('grzejnik %s zostal na %.1f po wietrzeniu, przywracam' % (name, t['target_C']))
                trv_target(name, trv_plan(room))
        except Exception as e:
            out.append('%s ?' % name)
    return ' '.join(out)


def trv_ext(name, t):
    tid = cfg.get('trv', {}).get(name)
    if tid is None or t is None:
        return
    try:
        trv_call(tid, 'TRV.SetExternalTemperature', {'id': 0, 't_C': round(t, 1)})
    except Exception as e:
        print('ext temp err', e)


# ---------- urządzenia Xiaomi ----------
dev = {}

# (siid, piid)
P = {
    'q_rh': (3, 1), 'q_pm25': (3, 4), 'q_t': (3, 7), 'q_co2': (3, 8),
    'on': (2, 1),
    'sh_mode': (2, 3), 'sh_target': (2, 5),          # salon nawilżacz 600ek: 0 stała, 1 sen, 2 mocno
    'sp_mode': (2, 4),                               # salon oczyszczacz xiaomi.airp.mb5: 0 auto, 3 nocny, 5 ulubiony, 6 ręczny bieg
    'sp_fan': (2, 5),                                # bieg w trybie ręcznym: 0 = 1, 1 = 2, 2 = 3
    'bh_mode': (2, 5),                               # sypialnia deerma jsq2w: 1 poziom 1, 2 poziom 2, 3 poziom 3, 4 stała wilgotność
    'bh_rh': (3, 1),                                 # sypialnia: wilgotność z czujnika nawilżacza
}


def dev_get(name, keys):
    d = dev.get(name)
    if not d:
        return [None] * len(keys)
    try:
        return d.get([P[k] for k in keys])
    except Exception as e:
        if d.fail in (3, 30):
            log('%s nie odpowiada (%s)' % (name, e))
        return [None] * len(keys)


def dev_set(name, key, value, label=None):
    d = dev.get(name)
    if not d:
        return False
    if key == 'on' and not AIR_SELF[0]:
        r = dev_room(name)
        rec = air(r) if r else None
        if rec:
            rec = dict(rec)
            rec['on'] = dict(rec['on'])
            rec['on'][name] = bool(value)
            air_put(r, rec)
            if value:
                log('%s: okno otwarte, wlacze po zamknieciu' % name)
                return True
    try:
        s, p = P[key]
        d.set(s, p, value)
        if label:
            log(label)
        return True
    except Exception as e:
        log('%s blad %s' % (name, e))
        return False


# ---------- waga (Mi Smart Scale 2, BLE) ----------
scale = {'last_kg': None, 'last_sent': 0, 'pending': None, 'pending_at': 0, 'seen': 0, 'boost': False, 'logged': 0}


# ---------- czujniki okien (Shelly BLU Door/Window, BTHome v2, bez szyfrowania) ----------
win = {}  # mac -> {'open': 0/1, 'bat': %, 'pid': nr pakietu, 't': czas}
BTH_LEN = {0x00: 1, 0x01: 1, 0x05: 3, 0x2D: 1, 0x3A: 1, 0x3F: 2, 0x02: 2, 0x03: 2, 0x0C: 2, 0x21: 1}


BTH_SEEN = {}  # diagnostyka: MAC -> (czas, pierwsze bajty), czujniki BTHome w zasięgu


def bthome(addr, p):
    try:
        BTH_SEEN[':'.join('%02X' % b for b in addr)] = (time.time(), p[:6])
    except Exception:
        pass
    if not p or p[0] & 0x01:  # zaszyfrowane: pomijamy
        return
    d, j = {}, 1
    while j < len(p):
        oid = p[j]
        n = BTH_LEN.get(oid)
        if n is None or j + 1 + n > len(p):
            break
        d[oid] = p[j + 1]
        j += 1 + n
    mac = ':'.join('%02X' % b for b in addr)
    if 0x21 in d and mac == PLAN.get('bath_motion'):
        if MOT.get('ble') != d[0x21]:
            MOT['ble'] = d[0x21]
            MOT['blog'] = MOT.get('blog', 0) + 1  # licznik zmian z Bluetooth płytki (diagnostyka)
        if d[0x21] or GW_MOT['val']:
            MOT['lt'] = time.time()
        if d[0x21]:
            if not GW_MOT['val']:
                MOT['new'] = True
                MOT['src'] = 'bluetooth plytki'
            MOT['t'] = time.time()  # ruch w łazience (obsługa w pętli: bath_tick)
            GW_MOT['val'] = True
        elif GW_MOT['val']:
            GW_MOT['val'] = False
            MOT['t'] = time.time()
        return
    if 0x2D not in d:
        return
    w = win.get(mac) or {}
    w['open'] = d[0x2D]
    w['bat'] = d.get(0x01, w.get('bat'))
    w['t'] = time.time()
    win[mac] = w


win_seen = {}  # mac -> ostatnio zalogowany stan
WIN_ROOM = {'F4:01:CC:22:2E:77': 's', 'F4:01:CC:1B:C2:E8': 'b'}  # s = salon, b = sypialnia
ROOM_DEV = {'s': ('salon_hum', 'salon_pur'), 'b': ('bed_hum',)}
ROOM_TRV = {'s': 'salon', 'b': 'bed'}
ROOM_NAME = {'s': 'salon', 'b': 'sypialnia'}
ROOM_COLD = {'s': 5, 'b': 4}


AIR_SELF = [False]  # True: to samo wietrzenie włącza/wyłącza, bez zapamiętywania


def air(room):
    return (state.get('air') or {}).get(room)


def air_put(room, rec):
    a = dict(state.get('air') or {})
    a[room] = rec
    state['air'] = a


def dev_room(name):
    for r, ds in ROOM_DEV.items():
        if name in ds:
            return r


def air_start(room):
    rec = {'at': time.time(), 'on': {}, 'trv': state.get('trv_' + ROOM_TRV[room])}
    for d in ROOM_DEV[room]:
        on, = dev_get(d, ['on'])
        rec['on'][d] = bool(on)
    air_put(room, rec)
    log('okno otwarte: %s, wylaczam i skrecam grzejnik' % ROOM_NAME[room])
    AIR_SELF[0] = True
    for d in ROOM_DEV[room]:
        if rec['on'][d]:
            dev_set(d, 'on', False)
    AIR_SELF[0] = False
    trv_target(ROOM_TRV[room], ROOM_COLD[room], True)


def air_stop(room, why):
    rec = air(room) or {}
    air_put(room, None)
    log('okno %s: %s, przywracam' % (why, ROOM_NAME[room]))
    AIR_SELF[0] = True
    for d, on in (rec.get('on') or {}).items():
        if on:
            dev_set(d, 'on', True)
    AIR_SELF[0] = False
    t = rec.get('trv')
    if t is None:  # nie znamy celu sprzed otwarcia (np. po restarcie): bierzemy z planu na tę porę
        t = trv_plan(room)
    trv_target(ROOM_TRV[room], t)


def sun_min(rise):
    """Wschód/zachód słońca w Łodzi (min od północy, czas lokalny), przybliżenie ±5 min."""
    import math
    tm = now_local()
    n = tm[7] if len(tm) > 7 and tm[7] else 1
    lat, lon = 51.76, 19.46
    g = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = 0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
    la = math.radians(lat)
    c = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(dec)) - math.tan(la) * math.tan(dec)
    ha = math.degrees(math.acos(max(-1.0, min(1.0, c))))
    utc = 720 - 4 * (lon + (ha if rise else -ha)) - eqt
    lt = mk(tm[0], tm[1], tm[2], tm[3], tm[4])
    off = int(round((lt - time.time()) / 1800.0)) * 30  # 60 zimą, 120 latem
    return int(utc + off) % 1440


def is_evening(m=None):
    # tryb wieczorowy: od godziny po zachodzie słońca (wtedy jest już naprawdę ciemno) do rana
    m = mins() if m is None else m
    return m >= sun_min(False) + 60 or m < sun_min(True)


def hum_on(name, room, why):
    # włącza urządzenie, ale nie przy otwartym oknie w tym pokoju
    if air(room):
        return
    on, = dev_get(name, ['on'])
    if not on:
        dev_set(name, 'on', True, why)


def trv_plan(room):
    m, night = mins(), state.get('asleep')
    if state.get('away'):
        return PLAN['away_temp']
    if room == 's':
        return PLAN['salon_night'] if night else PLAN['salon_day']
    return PLAN['bed_night'] if night else (PLAN['bed_home'] if is_weekend() or m >= 1080 else PLAN['bed_day'])


GW_WIN = {}  # id czujnika okna w bramce Shelly -> mac
GW_STATE = {'map_at': 0, 'poll_at': 0, 'logged': False}


def gw_rpc(method, params=''):
    gw = cfg.get('shelly_gw')
    if not gw:
        return None
    gc.collect()
    r = requests.get('http://%s/rpc/%s%s' % (gw, method, params), timeout=8)
    try:
        return r.json()
    finally:
        r.close()


def gw_windows():
    # zabezpieczenie: bramka Shelly słucha Bluetooth bez przerwy, więc zna stan okien, nawet gdy płytka zgubi sygnał
    now = time.time()
    try:
        if not GW_WIN and now - GW_STATE['map_at'] > 600:
            GW_STATE['map_at'] = now
            off = 0
            while True:  # komponenty dodane w bramce (czujniki BTHome) są tylko tu, stronicowane
                res = gw_rpc('Shelly.GetComponents', '?dynamic_only=true&offset=%d' % off) or {}
                comps = res.get('components') or []
                for c in comps:
                    v = c.get('config') or {}
                    if c.get('key', '').startswith('bthomesensor:') and v.get('obj_id') == 0x2D:
                        mac = str(v.get('addr', '')).upper()
                        if mac in WIN_ROOM:
                            GW_WIN[v['id']] = mac
                off += len(comps)
                if not comps or off >= res.get('total', 0):
                    break
            if not GW_STATE['logged']:
                GW_STATE['logged'] = True
                log('bramka: czujniki okien %s' % (','.join(ROOM_NAME[WIN_ROOM[m]] for m in GW_WIN.values()) or 'brak (dodaj je do bramki w aplikacji Shelly)'))
        if not GW_WIN or now - GW_STATE['poll_at'] < 30:
            return
        GW_STATE['poll_at'] = now
        for sid, mac in GW_WIN.items():
            st = gw_rpc('BTHomeSensor.GetStatus', '?id=%d' % sid) or {}
            if st.get('value') is None:  # bramka jeszcze nic od czujnika nie dostała
                continue
            val = 1 if st['value'] else 0
            w = win.get(mac)
            # wiadomość z Bluetooth płytki ma pierwszeństwo; bramkę bierzemy, gdy płytka nic świeżego nie słyszała
            if w is None or (w['open'] != val and now - w['t'] > 60):
                if w is not None:
                    log('okno %s: stan z bramki (%s), plytka zgubila sygnal' % (ROOM_NAME[WIN_ROOM[mac]], 'otwarte' if val else 'zamkniete'))
                win[mac] = {'open': val, 'bat': (w or {}).get('bat'), 't': now}
    except Exception as e:
        print('gw okna', e)


GW_MOT = {'id': None, 'map_at': 0, 'at': 0, 'fail': 0, 'val': None, 'srv': None, 'inst': False}
MOT_PORT = 8089
MOT_SCRIPT = """// automatyka domu (plytka): ruch w lazience -> od razu wiadomosc do plytki (bez odpytywania)
let SID = "bthomesensor:%d";
Shelly.addStatusHandler(function (e) {
  if (e.component === SID && e.delta && typeof e.delta.value !== "undefined") {
    Shelly.call("HTTP.GET", {url: "http://%s:%d/ruch?v=" + (e.delta.value ? "1" : "0"), timeout: 3});
  }
});
"""


def gw_call(method, params):
    body = json.dumps({'id': 1, 'method': method, 'params': params})
    gc.collect()
    r = requests.post('http://%s/rpc' % cfg['shelly_gw'], data=body, headers={'Content-Type': 'application/json'}, timeout=8)
    try:
        j = r.json()
    finally:
        r.close()
    if 'error' in j:
        raise OSError(str(j['error']))
    return j.get('result')


def mot_install():
    """Wgrywa do bramki Shelly mały skrypt: przy zmianie czujnika ruchu bramka sama wysyła wiadomość do płytki."""
    my_ip = network.WLAN(network.STA_IF).ifconfig()[0]
    code = MOT_SCRIPT % (GW_MOT['id'], my_ip, MOT_PORT)
    sid = None
    for sc in (gw_call('Script.List', {}) or {}).get('scripts') or []:
        if sc.get('name') == 'lazienka_ruch':
            sid = sc.get('id')
    if sid is None:
        sid = gw_call('Script.Create', {'name': 'lazienka_ruch'})['id']
    try:
        gw_call('Script.Stop', {'id': sid})
    except Exception:
        pass
    gw_call('Script.PutCode', {'id': sid, 'code': code})
    gw_call('Script.SetConfig', {'id': sid, 'config': {'enable': True}})
    gw_call('Script.Start', {'id': sid})
    log('bramka: skrypt ruchu lazienki wgrany (id %s, wiadomosci na %s:%d)' % (sid, my_ip, MOT_PORT))


def mot_set(v, why):
    now = time.time()
    if v or GW_MOT['val']:
        MOT['lt'] = now  # ostatnia chwila z ruchem
    if v and not GW_MOT['val']:
        MOT['new'] = True
        MOT['src'] = why
    MOT['t'] = now  # ruch: od teraz; brak ruchu: od teraz liczy się czas do zgaszenia
    GW_MOT['val'] = v


TGT = {'t': 0, 'last': {}}


def target_tick():
    """Zmiana barwy/jasności z trybu (dzień, wieczór, rano, komputer, czytanie...) dla świecących żarówek:
    od razu cały pokój jedną serią z potwierdzeniem (26.11), a nie po kolei, gdy która się odezwie."""
    if time.time() - TGT['t'] < 1 or not PLAN.get('lt_auto', True):
        return
    TGT['t'] = time.time()
    if state.get('away') or wake_hold():
        return
    lit_all = [(mac, x) for mac, x in ws_present().items() if x['p'].get('state')]
    for room in ('work', 'bed', 'bath'):
        if room in MAN or (room != 'bath' and state.get('asleep')):
            continue
        k, dim = light_target(room)
        prev = TGT['last'].get(room)
        if prev is None:
            TGT['last'][room] = (k, dim)
            continue
        if abs(prev[0] - k) < 100 and abs(prev[1] - dim) < 5:
            continue  # drobne kroki (np. płynne przejście po zachodzie) dokańcza zwykła korekta
        TGT['last'][room] = (k, dim)
        ips = [x['ip'] for mac, x in lit_all if room_of(mac) == room and mac[-4:].lower() != BED_LAMP
               and x['ip'] != PLAN.get('wiz_bed')]
        if room == 'bath' and (state.get('asleep') or nl_eve_on()):
            continue  # łazienka nocna: jedna żarówka, tym steruje czujnik
        if not ips:
            continue
        pr = {'state': True, 'temp': k, 'dimming': dim}
        cmd = {'room': room, 'on': True, 't0': time.time(), 'left': set(ips), 'n': len(ips), 'rs': 0, 'done': {}}
        room_burst(ips, pr, cmd)
        for ip in ips:
            WS.setdefault('fix', {})[ip] = time.time()
        log('barwa %s -> %dK %d%%: %d/%d od razu' % (room, k, dim, cmd.get('burst', 0), len(ips)))


def fast_tick():
    """Lekkie, nieblokujące sprawdzenie (25.11): szturchnięcia, ucho z łazienki, ruch -> światło.
    Wołane między wolnymi rzeczami (arkusz, urządzenia), żeby światło w łazience nie czekało na nie."""
    try:
        http_tick()
        ucho_tick()
        bath_tick()
        target_tick()
    except Exception as e:
        print('fast', e)


def http_tick():
    """Mały serwer w domowej sieci (port 8089), bez blokowania pętli:
    /teraz      - Skrót z iPhone'a (ładowarka ON/OFF): od razu synchronizacja z arkuszem i reguły
    /ruch?v=1|0 - bramka Shelly: ruch w łazience"""
    if GW_MOT['srv'] is None:
        try:
            import socket
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(('0.0.0.0', MOT_PORT))
            srv.listen(2)
            srv.setblocking(False)
            GW_MOT['srv'] = srv
        except Exception as e:
            GW_MOT['srv'] = False
            log('nasluch 8089 niedostepny (%s)' % e)
    if not GW_MOT['srv']:
        return
    for _ in range(3):
        try:
            c, _a = GW_MOT['srv'].accept()
        except Exception:
            break
        try:
            c.settimeout(1)
            req = c.recv(256)
            src = _a[0] if isinstance(_a, tuple) else ''
            if not (src.startswith('192.168.100.') and src != '192.168.100.1'):
                # z internetu (przekierowanie portu na routerze): tylko /teraz z tokenem, najwyżej co 10 s
                tok = cfg.get('gas_token') or ''
                if (tok and b'/teraz' in req and ('k=' + tok).encode() in req
                        and time.time() - GW_MOT.get('ext_t', 0) > 10):
                    GW_MOT['ext_t'] = time.time()
                    c.send(b'HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok')
                    NOW[0] = True
                    print('teraz: synchronizacja na zadanie telefonu (z zewnatrz)')
                continue
            c.send(b'HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok')
            if b'/ruch?v=1' in req:
                mot_set(True, 'bramka')
            elif b'/ruch?v=0' in req:
                mot_set(False, 'bramka')
            elif b'/teraz' in req:
                NOW[0] = True  # telefon: zdarzenie już w arkuszu, płytka od razu je odczytuje
                print('teraz: synchronizacja na zadanie telefonu')
        except Exception as e:
            print('http req', e)
        finally:
            c.close()


def gw_motion():
    """Czujnik ruchu w łazience przez bramkę Shelly (płytka z salonu go nie słyszy, bramka tak).
    Bramka sama wysyła płytce wiadomość przy każdej zmianie (skrypt w bramce), płytka tylko nasłuchuje;
    raz na minutę sprawdzenie stanu w bramce na wypadek zgubionej wiadomości."""
    if not PLAN.get('bath_motion') or not cfg.get('shelly_gw'):
        return
    now = time.time()
    if GW_MOT['id'] is None:
        if now - GW_MOT['map_at'] < 300:
            return
        GW_MOT['map_at'] = now
        try:
            off = 0
            while True:
                res = gw_rpc('Shelly.GetComponents', '?dynamic_only=true&offset=%d' % off) or {}
                comps = res.get('components') or []
                for c in comps:
                    v = c.get('config') or {}
                    if c.get('key', '').startswith('bthomesensor:') and v.get('obj_id') == 0x21 and str(v.get('addr', '')).upper() == PLAN['bath_motion']:
                        GW_MOT['id'] = v['id']
                off += len(comps)
                if not comps or off >= res.get('total', 0):
                    break
            if GW_MOT['id'] is not None or not GW_MOT.get('nf_log'):
                GW_MOT['nf_log'] = True  # „nie znaleziony” tylko raz po starcie
                log('bramka: czujnik ruchu lazienka %s' % ('id %s' % GW_MOT['id'] if GW_MOT['id'] is not None else 'nie znaleziony'))
        except Exception as e:
            log('bramka: blad szukania czujnika ruchu (%s)' % e)
        return
    if not GW_MOT['inst'] and now - GW_MOT.get('inst_at', 0) > 600:
        GW_MOT['inst_at'] = now
        try:
            mot_install()
            GW_MOT['inst'] = True
        except Exception as e:
            log('bramka: nie udalo sie wgrac skryptu ruchu (%s), sprawdzam co minute' % e)
    # zapas: raz na minutę stan prosto z bramki
    if now - GW_MOT['at'] < 60 or now < GW_MOT['fail']:
        return
    GW_MOT['at'] = now
    try:
        gc.collect()
        r = requests.get('http://%s/rpc/BTHomeSensor.GetStatus?id=%d' % (cfg['shelly_gw'], GW_MOT['id']), timeout=2)
        try:
            v = bool(r.json().get('value'))
        finally:
            r.close()
    except Exception as e:
        GW_MOT['fail'] = now + 120
        log('bramka: brak odpowiedzi o czujnik ruchu (%s)' % e)
        return
    if v != bool(GW_MOT['val']):
        mot_set(v, 'sprawdzenie')


AIR_GUARD = [0]


def air_guard():
    # przy otwartym oknie sprzęt ma stać wyłączony, nawet gdy włączy go ktoś inny (Google Home, Mi Home, przycisk);
    # takie włączenie zapamiętujemy, więc po zamknięciu okna sprzęt wróci włączony
    if time.time() - AIR_GUARD[0] < 30:
        return
    AIR_GUARD[0] = time.time()
    for room in ('s', 'b'):
        rec = air(room)
        if not rec:
            continue
        for d in ROOM_DEV[room]:
            on, = dev_get(d, ['on'])
            if on:
                rec = dict(rec)
                rec['on'] = dict(rec.get('on') or {})
                rec['on'][d] = True
                air_put(room, rec)
                AIR_SELF[0] = True
                dev_set(d, 'on', False, '%s wlaczony przy otwartym oknie, wylaczam (wlacze po zamknieciu)' % d)
                AIR_SELF[0] = False
        # grzejnik też ma zostać skręcony (polecenie mogło nie dojść albo ktoś go podkręcił)
        gw, tid = cfg.get('shelly_gw'), cfg.get('trv', {}).get(ROOM_TRV[room])
        if gw and tid is not None:
            try:
                gc.collect()
                r = requests.get('http://%s/rpc/BluTrv.GetRemoteStatus?id=%s' % (gw, tid), timeout=10)
                try:
                    tgt = r.json()['status']['trv:0']['target_C']
                finally:
                    r.close()
                if tgt > ROOM_COLD[room] + 0.5:
                    log('grzejnik %s na %.1f przy otwartym oknie, skrecam ponownie' % (ROOM_TRV[room], tgt))
                    trv_target(ROOM_TRV[room], ROOM_COLD[room], True)
            except Exception as e:
                print('air_guard trv', e)


def win_tick():
    air_guard()
    for mac, w in list(win.items()):
        if win_seen.get(mac) != w['open']:
            first = mac not in win_seen
            win_seen[mac] = w['open']
            if not WIN_ROOM.get(mac):
                log('okno %s %s%s (bateria %s%%)' % (mac, 'OTWARTE' if w['open'] else 'zamkniete',
                                                     ' [nowy czujnik]' if first else '', w.get('bat')))
        room = WIN_ROOM.get(mac)
        if room:
            if w['open'] and not air(room):
                air_start(room)
            elif not w['open'] and air(room):
                air_stop(room, 'zamkniete')
    for room in ('s', 'b'):
        rec = air(room)
        if rec and time.time() - rec['at'] > PLAN['air_max_min'] * 60:
            fresh = [w for m, w in win.items() if WIN_ROOM.get(m) == room and w['open'] and time.time() - w['t'] < 600]
            if fresh:
                rec = dict(rec)
                rec['at'] = time.time()
                air_put(room, rec)
            else:
                air_stop(room, 'bez sygnalu z czujnika')


def ble_irq(event, data):
    if event != 5:  # _IRQ_SCAN_RESULT
        sb_irq(event, data)
        return
    try:
        adv = bytes(data[4])
        i = 0
        while i + 1 < len(adv):
            ln = adv[i]
            if ln == 0:
                break
            typ = adv[i + 1]
            if typ == 0x16 and ln >= 4 and adv[i + 2] == 0xD2 and adv[i + 3] == 0xFC:
                bthome(bytes(data[1]), adv[i + 4:i + 1 + ln])
            if typ == 0x16 and ln >= 13 and adv[i + 2] == 0x1D and adv[i + 3] == 0x18:
                p = adv[i + 4:i + 1 + ln]
                ctrl = p[0]
                scale['seen'] = time.time()
                scale['last_raw'] = (ctrl, p[1] | (p[2] << 8))
                stab = ctrl & 0x20
                removed = ctrl & 0x80
                if stab and not removed:
                    raw = p[1] | (p[2] << 8)
                    if ctrl & 0x01 or ctrl & 0x10:
                        kg = None  # funty / jin: pomijamy
                    else:
                        kg = raw / 200.0
                    if kg:
                        scale['pending'] = kg
                        scale['pending_at'] = time.time()
            i += ln + 1
    except Exception:
        pass


# ---------- ucho w łazience (zapasowe ESP32): przekazuje wiadomości Bluetooth czujnika ruchu i wagi ----------
UCHO = {'sock': None, 'seen': 0, 'info': '', 'n': 0, 'logged': 0}


def ucho_tick():
    if UCHO['sock'] is None:
        try:
            import socket
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.bind(('0.0.0.0', 8090))
            u.setblocking(False)
            UCHO['sock'] = u
        except Exception as e:
            print('ucho bind', e)
            UCHO['sock'] = False
            return
    if not UCHO['sock']:
        return
    for _ in range(20):
        try:
            p, addr = UCHO['sock'].recvfrom(300)
        except Exception:
            break
        if addr[0] != PLAN.get('ucho_ip', addr[0]):
            continue
        if p[:2] == b'UH':
            first = not UCHO['seen']
            UCHO['seen'] = time.time()
            UCHO['info'] = p[2:].decode()
            if first or time.time() - UCHO['logged'] > 6 * 3600:
                UCHO['logged'] = time.time()
                log('ucho lazienka: w sieci (%s, %s), odebranych wiadomosci %d' % (addr[0], UCHO['info'], UCHO['n']))
        elif p[:2] == b'U1' and len(p) > 8:
            UCHO['seen'] = time.time()
            UCHO['n'] += 1
            ble_irq(5, (0, p[2:8], 0, 0, p[8:]))  # jak własny Bluetooth: te same reguły, jedna decyzja


BLE = [None]


def ble_on():
    import bluetooth
    b = bluetooth.BLE()
    b.active(True)
    b.irq(ble_irq)
    # wycinek czasu radia (100 ms co 200 ms): czujniki okien nadają krótko, Wi-Fi ma drugą połowę czasu
    b.gap_scan(0, 200000, 100000, True)
    BLE[0] = b


def ble_pause():
    # na czas HTTPS wstrzymujemy skanowanie (Bluetooth zostaje włączony: ponowne włączenie bywa niemożliwe)
    if BLE[0]:
        try:
            BLE[0].gap_scan(None)
        except Exception:
            pass
    gc.collect()


def ble_resume():
    scale['boost'] = False  # scale_tick w razie potrzeby znowu włączy ciągły skan
    if BLE[0]:
        try:
            BLE[0].gap_scan(0, 200000, 100000, True)
        except Exception as e:
            print('ble resume err', e)


# ---------- zasłony SwitchBot Curtain 3 (połączenie Bluetooth na czas jednego polecenia) ----------
SB = {}
SB_WRITE = 'cba20002'  # charakterystyka poleceń
SB_NOTIFY = 'cba20003'  # odpowiedzi


def sb_irq(event, data):
    try:
        if event == 7:  # połączono
            SB['conn'] = data[0]
        elif event == 8:  # rozłączono
            SB['disc'] = True
        elif event == 11:  # znaleziona charakterystyka
            u = str(data[4]).lower()
            if SB_WRITE in u:
                SB['wh'] = data[2]
            elif SB_NOTIFY in u:
                SB['nh'] = data[2]
        elif event == 12:
            SB['cdone'] = True
        elif event == 17:  # zapis potwierdzony (status 0 = ok)
            SB['wdone'] = data[2]
        elif event == 18:  # odpowiedź zasłony
            SB['notify'] = bytes(data[2])
    except Exception:
        pass


def sb_wait(key, ms):
    t = time.ticks_ms()
    while key not in SB:
        if time.ticks_diff(time.ticks_ms(), t) > ms or (key != 'disc' and SB.get('disc')):
            return False
        time.sleep_ms(20)
    return True


def sb_send(mac, payload):
    """Jedno polecenie do zasłony: połącz, wyślij, odbierz odpowiedź, rozłącz. Zwraca odpowiedź (bytes) albo None."""
    b = BLE[0]
    if not b:
        state['sb_err'] = 'bluetooth wylaczony'
        return None
    addr = bytes([int(x, 16) for x in mac.split(':')])
    ble_pause()
    try:
        for attempt in range(3):
            SB.clear()
            try:
                b.gap_connect(0 if attempt == 2 else 1, addr, 8000)  # SwitchBot ma adres losowy statyczny (typ 1)
            except Exception as e:
                state['sb_err'] = 'laczenie %s' % e
                time.sleep_ms(500)
                continue
            if not sb_wait('conn', 9000):
                state['sb_err'] = 'brak polaczenia'
                try:
                    b.gap_connect(None)
                except Exception:
                    pass
                continue
            c = SB['conn']
            try:
                b.gattc_discover_characteristics(c, 1, 0xFFFF)
                if not sb_wait('cdone', 6000) or 'wh' not in SB:
                    state['sb_err'] = 'brak uslugi zaslony'
                    continue
                if 'nh' in SB:
                    SB.pop('wdone', None)
                    b.gattc_write(c, SB['nh'] + 1, b'\x01\x00', 1)  # włącz odpowiedzi
                    sb_wait('wdone', 2000)
                SB.pop('wdone', None)
                SB.pop('notify', None)
                b.gattc_write(c, SB['wh'], payload, 1)
                if not sb_wait('wdone', 3000) or SB.get('wdone'):
                    state['sb_err'] = 'zapis nieudany'
                    continue
                sb_wait('notify', 2000)
                return SB.get('notify') or b''
            finally:
                try:
                    b.gap_disconnect(c)
                except Exception:
                    pass
                sb_wait('disc', 2000)
        return None
    finally:
        ble_resume()


def cur_side(mac, open_pct, speed):
    # w protokole zasłony 0 = otwarta, 100 = zamknięta
    pos = 100 - max(0, min(100, int(open_pct)))
    r = sb_send(mac, bytes([0x57, 0x0F, 0x45, 0x01, 0x05, speed & 0xFF, pos]))
    if r is None:
        return 'blad (%s)' % state.get('sb_err')
    return 'ok' if (not r or r[0] == 1) else 'odp %s' % ''.join('%02x' % x for x in r)


def curtains(want, why, quiet=True):
    """want: 'open' / 'close'. Przy otwartym oknie w sypialni zasłony stoją; polecenie czeka na zamknięcie okna."""
    if not PLAN.get('curtains') or not PLAN.get('cur_left'):
        return
    if air('b'):
        if state.get('cur_want') != want:
            log('zaslony: okno w sypialni otwarte, %s po zamknieciu' % ('otworze' if want == 'open' else 'zasune'))
        state['cur_want'] = want
        state['cur_why'] = why
        return
    state['cur_want'] = None
    sp = PLAN['cur_quiet'] if quiet else PLAN['cur_fast']
    if want == 'open':
        l = cur_side(PLAN['cur_left'], PLAN['cur_left_open'], sp)
        p = cur_side(PLAN['cur_right'], PLAN['cur_right_open'], sp)
    else:
        l = cur_side(PLAN['cur_left'], 0, sp)
        p = cur_side(PLAN['cur_right'], 0, sp)
    state['cur_state'] = want
    state['cur_day'] = day_key()
    log('zaslony %s (%s%s): lewa %s, prawa %s' % ('otwieram' if want == 'open' else 'zasuwam', why, ', cicho' if quiet else '', l, p))


def curtains_tick():
    # odłożone polecenie (okno było otwarte) wykonujemy po zamknięciu okna
    w = state.get('cur_want')
    if w and not air('b'):
        curtains(w, (state.get('cur_why') or '') + ', okno zamkniete')
    # raz na dobę (i po starcie płytki) sprawdzamy baterie zasłon
    if PLAN.get('curtains') and PLAN.get('cur_left') and BLE[0] and time.time() - BOOT_T[0] > 60 \
            and time.time() - state.get('cur_chk', 0) > 86400:
        state['cur_chk'] = time.time()
        out = []
        for name, key in (('lewa', 'cur_left'), ('prawa', 'cur_right')):
            r = sb_send(PLAN[key], b'\x57\x02')
            if r and len(r) > 1 and r[0] == 1:
                out.append('%s bateria %d%%%s' % (name, r[1], ' pozycja %d' % r[6] if len(r) > 6 else ''))
            else:
                out.append('%s nie odpowiada (%s)' % (name, state.get('sb_err') if r is None else 'odp %s' % r))
        log('zaslony: ' + ', '.join(out))


def ble_start():
    state['ble_wanted'] = True
    try:
        ble_on()
        log('bluetooth ok')
    except Exception as e:
        log('bluetooth blad %s' % e)


def scale_tick():
    # waga się obudziła: skanuj ciągle przez minutę, żeby nie przegapić ustabilizowanego wyniku
    if BLE[0]:
        if scale['seen'] and time.time() - scale['seen'] < 60:
            if not scale['boost']:
                try:
                    BLE[0].gap_scan(0, 30000, 30000, True)
                    scale['boost'] = True
                    if time.time() - scale['logged'] > 300:
                        scale['logged'] = time.time()
                        log('waga nadaje %s' % (scale.get('last_raw'),))
                except Exception:
                    pass
        elif scale['boost']:
            scale['boost'] = False
            ble_resume()
    kg = scale['pending']
    if kg is None or time.time() - scale['pending_at'] < 3:
        return
    scale['pending'] = None
    lo, hi = PLAN['scale_min'], PLAN['scale_max']
    if scale['last_kg']:
        lo, hi = max(lo, scale['last_kg'] - 8), min(hi, scale['last_kg'] + 8)
    if not (lo <= kg <= hi):
        return
    if scale['last_kg'] and abs(kg - scale['last_kg']) < 0.05 and time.time() - scale['last_sent'] < 600:
        return
    early = False
    if state.get('asleep') and 240 <= mins() < 780:
        # 27.11: rano waga od razu daje poranne światło w łazience, bez czekania na odpowiedź arkusza (kilka sekund)
        early = True
        bath_wake_light()
    try:
        res = gas({'kg': '%.2f' % kg})
        if isinstance(res, dict) and res.get('pobudka_waga'):
            NOW[0] = True  # pobudka z wagi: od razu synchronizacja i reguły, bez czekania na kolejny cykl
            bips = [] if early else list(room_ips('bath'))
            if bips:  # 26.11: łazienka od razu pełne poranne światło, reszta poranka po synchronizacji
                pr = {'state': True, 'temp': PLAN.get('morn_k', 2800), 'dimming': PLAN.get('morn_dim', 50)}  # łagodnie (26.11)
                bc = {'room': 'bath', 'on': True, 't0': time.time(), 'left': set(bips), 'n': len(bips), 'rs': 0, 'done': {}}
                room_burst(bips, pr, bc)
                for ip in bips:  # do czasu synchronizacji (pobudka) nie poprawiamy barwy z powrotem na nocną
                    WS.setdefault('fix', {})[ip] = time.time() + 40
                log('waga: pobudka, lazienka od razu lagodne poranne swiatlo')
        scale['last_kg'] = kg
        scale['last_sent'] = time.time()
        log('waga %.2f kg zapisana' % kg)
    except Exception as e:
        log('waga blad %s' % e)
        scale['pending'] = kg
        scale['pending_at'] = time.time()


NOW = [False]  # wymuszenie natychmiastowej synchronizacji (np. pobudka z wagi)


def bath_wake_light():
    bips = list(room_ips('bath'))
    if not bips:
        return
    pr = {'state': True, 'temp': PLAN.get('morn_k', 2800), 'dimming': PLAN.get('morn_dim', 50)}
    bc = {'room': 'bath', 'on': True, 't0': time.time(), 'left': set(bips), 'n': len(bips), 'rs': 0, 'done': {}}
    room_burst(bips, pr, bc)
    for ip in bips:
        WS.setdefault('fix', {})[ip] = time.time() + 40
    log('waga: pobudka, lazienka od razu lagodne poranne swiatlo')

# ---------- Komputer ON → Muzyka Poranna OFF ----------
PC = {'on': None, 'evt': False, 't': 0}


DESK = {'t': 0}


def desk_quiet():
    """Wieczorne wyciszenie: od 18:00 do poranka lampa nad biurkiem się nie pali."""
    m = mins()
    return m >= 1080 or m < 240 or bool(state.get('asleep'))


def desk_tick():
    """O 18:00 gasi lampę nad biurkiem i LED-y w kuchni; potem do rana pilnuje, żeby lampa nad biurkiem nie świeciła."""
    if not desk_quiet() or time.time() - DESK['t'] < 20:
        return
    DESK['t'] = time.time()
    if mins() >= 1080 and once('quiet18'):
        if PLAN.get('kitchen_led') and light_on(PLAN['kitchen_led']):
            plug_set(PLAN['kitchen_led'], False, '18:00 wyciszenie: kuchnia led off')
    ip = PLAN.get('desk_light')
    if ip and not (MAN.get('desk_light') or {}).get('on') and light_on(ip):
        plug_set(ip, False, 'lampa biurko off (po 18:00 nie swieci do rana)')


def pc_tick():
    # co 15 s stan gniazdka przy komputerze; przejście OFF -> ON = komputer włączony, arkusz wyłącza poranną muzykę
    desk_tick()
    ip = PLAN.get('pc_plug')
    if not ip or time.time() - PC['t'] < 15:
        return
    PC['t'] = time.time()
    try:
        gc.collect()
        r = requests.get('http://%s/rpc/Switch.GetStatus?id=0' % ip, timeout=5)
        try:
            on = bool(r.json().get('output'))
        finally:
            r.close()
    except Exception:
        return
    if PC['on'] and on is False:
        if PLAN.get('kitchen_led'):  # komputer wyłączony: LED-y w kuchni off
            plug_set(PLAN['kitchen_led'], False, 'komputer wylaczony: kuchnia led off')
    if PC['on'] is False and on:
        PC['evt'] = True
        NOW[0] = True
        log('komputer wlaczony')
        m = mins()
        if desk_quiet():
            DESK['t'] = time.time() - 15  # lampa nad biurkiem zapala się z komputerem: sprawdzenie za ok. 5 s
        mo = state.get('morn')
        if mo and not mo.get('we') and not mo.get('pc'):
            mo = dict(mo)
            mo['pc'] = True
            state['morn'] = mo  # w tygodniu poranne ciepłe światło kończy się z włączeniem komputera
            WS['col'] = 0  # barwa dzienna od razu
            TGT['t'] = 0
            target_tick()  # najpierw żarówki (cały salon i kuchnia serią), dopiero potem LED-y (26.11)
        if PLAN.get('kitchen_led') and not state.get('asleep') and 240 <= m < sun_min(False):
            plug_set(PLAN['kitchen_led'], True, 'komputer wlaczony: kuchnia led on')  # tylko w dzień (do zmierzchu)
    PC['on'] = on


# ---------- logika ----------


def phone_asleep(ph):
    """Telefon odłożony na ładowarkę na noc (po 21:00 albo przed 4:00) i jeszcze nie zdjęty."""
    if not ph or ph.get('e') != 'down':
        return False
    y, mo, d, h, mi = parse_iso(ph['t'])
    m = h * 60 + mi
    since = local_minutes_since(ph['t'])
    if m >= PLAN['night_from'] or m < 240:
        return since < 14 * 60
    # odłożony wcześniej wieczorem (od 18:00) i nadal leży o 22:30
    now = mins()
    return m >= 1080 and (now >= PLAN['night_late'] or now < 240) and since < 14 * 60


def wake_min(sync, weekend):
    w = (sync or {}).get('wake') or {}
    # typowa pobudka dla dzisiejszego dnia tygodnia (mediana), potem dni robocze/weekend, potem domyślna
    v = (w.get('days') or {}).get(str(now_local()[6] + 1))
    if v is None:
        v = w.get('we' if weekend else 'wd')
    if v is None:
        v = PLAN['wake_we' if weekend else 'wake_wd']
    return v


def day_key():
    tm = now_local()
    return '%04d%02d%02d' % (tm[0], tm[1], tm[2])


SAVE_KEYS = ('eve_ret', 'ret18', 'morn', 'night_walks', 'asleep', 'bed_off_at', 'bed_eve', 'night_on', 'bed_pause', 'air', 'wl', 'sleep_at', 'robot_ev', 'robot_day', 'wiz_lvl',
             'cur_want', 'cur_why', 'cur_state', 'cur_day', 'boost_day', 'away_ev', 'away',
             'rate_s', 'rate_b', 'heat_s', 'heat_b', 'ln_t', 'nl_seen', 'nl_eve', 'cozy', 'rates_s', 'rates_b', 'tout')


def day_num():
    tm = now_local()
    return int(mk(tm[0], tm[1], tm[2], 12) // 86400)


def robot_tick(sync, m):
    """Robot rusza raz na `robot_every` dni, 30 min po wyjściu z domu, jeśli w tym czasie nie wróciłem. Po powrocie wraca na stację."""
    aw = (sync or {}).get('away')
    if not PLAN['robot'] or not aw or aw.get('e') != 'out' or not dev.get('robot'):
        return
    if state.get('robot_ev') == aw.get('t'):
        return  # to wyjście już obsłużone
    try:
        age = local_minutes_since(aw['t'])
    except Exception:
        return
    if age > PLAN['robot_fresh']:
        state['robot_ev'] = aw['t']
        return
    gym = False
    try:
        g = (sync or {}).get('gym')
        gym = bool(g) and local_minutes_since(g['t']) <= age  # wejście na siłownię po tym wyjściu: rusza od razu
    except Exception:
        pass
    if age < PLAN.get('robot_after', 30) and not gym:
        return  # jeszcze czekamy: krótkie wyjście (Żabka, paczkomat) robota nie uruchamia
    if not (PLAN['robot_from'] <= m < PLAN['robot_to']):
        return  # poczekamy do pory dziennej, dopóki zdarzenie jest świeże
    state['robot_ev'] = aw['t']
    last = state.get('robot_day')
    if last is not None and day_num() - last < PLAN['robot_every']:
        log('robot: wyjscie z domu, ale juz sprzatal (dzien %s)' % last)
        return
    s, a = PLAN['robot_start']
    try:
        dev['robot'].action(s, a)
        state['robot_day'] = day_num()
        log('robot: %s, start sprzatania' % ('silownia' if gym else 'nie ma mnie od %d min' % age))
    except Exception as e:
        log('robot: blad startu %s' % e)


def save_state():
    d = {k: state.get(k) for k in SAVE_KEYS}
    for k in state:
        if k.startswith('once_'):
            d[k] = state[k]
    js = json.dumps(d)
    if js == state.get('_saved'):
        return
    try:
        with open('state.json', 'w') as f:
            json.dump({'t': time.time(), 's': d}, f)
        state['_saved'] = js
    except Exception as e:
        print('state save err', e)


def load_state():
    try:
        with open('state.json') as f:
            j = json.load(f)
        if time.time() - j.get('t', 0) < 12 * 3600:
            state.update(j['s'])
            state['_saved'] = json.dumps(j['s'])
            return True
    except Exception:
        pass
    return False


def once(key):
    """True tylko za pierwszym razem danego dnia."""
    k = 'once_' + key
    if state.get(k) == day_key():
        return False
    state[k] = day_key()
    return True


def tick_rules(sync, q):
    rh, pm25, t, co2 = q
    m = mins()
    weekend = is_weekend()
    ph = (sync or {}).get('phone')
    if (sync or {}).get('tout') is not None:
        state['tout'] = sync['tout']  # temperatura na zewnątrz (Open-Meteo przez arkusz)
    was = state.get('asleep')
    # bez odpowiedzi z arkusza nie zgadujemy: zostaje poprzedni stan (inaczej po restarcie noc/pobudka odpalałyby się drugi raz)
    asleep = phone_asleep(ph) if sync else bool(was)
    if was and not asleep and not (240 <= m < 1080):
        asleep = True  # bezpiecznik: poranek/pobudka tylko między 4:00 a 18:00, cokolwiek by się wydarzyło
    if was and not asleep and ph and ph.get('e') == 'up':
        # pobudka liczy się tylko od zdjęcia telefonu po 4:00 (albo z wagi); zdjęcie sprzed 4:00 nie odpali poranka później.
        # Zdjęcie w ciągu 10 min od startu płytki to skok prądu (ładowarka gaśnie razem z płytką), nie pobudka.
        try:
            _, _, _, eh, emi = parse_iso(ph['t'])
            ago = local_minutes_since(ph['t'])
            blip = abs((time.time() - ago * 60) - BOOT_T[0]) < 600
            # zdjęcie telefonu wieczorem (od 18:00) po odłożeniu na noc to zerknięcie, nie poranek (23.11: o 21:20
            # odpalał się tryb poranny: białe światło, zasłony otwarte)
            if eh * 60 + emi < 240 or eh * 60 + emi >= 1080 or blip:
                asleep = True
                if blip and not state.get('blip_log'):
                    state['blip_log'] = 1
                    log('telefon zdjety tuz po starcie plytki: skok pradu, nie pobudka')
        except Exception as e:
            print('wake check', e)
    if was and not asleep and m < 240:
        asleep = True  # zerknięcie na telefon w nocy to jeszcze nie pobudka
    lt = state.get('ln_t')
    ln = bool(lt) and time.time() - lt < 12 * 3600
    if nl_mode():
        if not was:
            if ln:
                asleep = True  # lampka nocna zgaszona po 21:00
            elif asleep and not (60 <= m < 240):
                asleep = False  # sam telefon na ładowarce nie usypia domu; zapas: od 1:00
        elif ln and not asleep:
            # noc z lampki kończy dopiero zdjęcie telefonu (albo waga) po jej zgaszeniu
            try:
                up_after = ph and ph.get('e') == 'up' and local_minutes_since(ph['t']) * 60 < time.time() - lt - 30
            except Exception:
                up_after = False
            if not up_after:
                asleep = True
    state['asleep'] = asleep

    # --- po starcie płytki: nowe temperatury dzienne od razu (tylko gdy jestem w domu i nie śpię) ---
    if sync and not state.get('boot_temps'):
        state['boot_temps'] = 1
        aw = sync.get('away') or {}
        if not asleep and aw.get('e') != 'out':
            if not air('s'):
                trv_target('salon', trv_plan('s'))
            if not air('b') and trv_plan('b') == PLAN['bed_home']:
                trv_target('bed', PLAN['bed_home'])

    # --- wyjście / powrót (Skróty iOS): wyjście = rozłączenie z domowym Wi-Fi; powrót = lokalizacja albo połączenie z Wi-Fi ---
    aw = (sync or {}).get('away') or {}
    if aw.get('t') and aw.get('t') != state.get('away_ev'):
        first = state.get('away_ev') is None
        state['away_ev'] = aw['t']
        prev = bool(state.get('away'))
        new = aw.get('e') == 'out'
        if new and asleep and not first:
            new = prev
            log('wyjscie w nocy (telefon zgubil wifi?), ignoruje')
        state['away'] = new
        if not first and new == prev:
            pass  # drugi powrót (lokalizacja + Wi-Fi) albo powtórzone wyjście: nic nowego
        elif not first:
            man_clear('wyjscie' if new else 'powrot')
            for n in list(BOOST):
                boost_off(n)
            if state['away']:
                # dawna rutyna Google Home „Wyjście → Wszystko OFF” (+ lampa salon i lampka sypialnia, których tam brakowało)
                # kolejność (25.11): najpierw światło, bo je widać; urządzenia potem
                for r in ('work', 'bed', 'bath'):
                    room_set(r, False)
                if PLAN.get('wiz_bed'):
                    wiz({'state': False})
                for key in ('lamp_salon', 'kitchen_led', 'desk_light'):
                    if PLAN.get(key):
                        plug_set(PLAN[key], False, key + ' off')
                log('wyjscie z domu: zarowki off, potem wszystko off, grzejniki %s' % PLAN['away_temp'])
                for d in ('bed_hum', 'salon_hum', 'salon_pur'):
                    dev_set(d, 'on', False)
            elif not asleep:
                # dawne rutyny „Powrót do domu Pon-Pt”, „DOM Weekend ON” i „Światło Wieczór”, bez ich okienek godzinowych
                bed_ok = weekend or m >= 1080  # Pon-Pt sypialnia dopiero od 18:00
                if m >= 1080 or m < 240:
                    state['ret18'] = day_key()  # powrót po 18:00: łazienka gaśnie po 8 min (prysznic)
                eve = (m >= max(1080, sun_min(False))) or m < 240  # wieczór = po zmierzchu, ale nie wcześniej niż 18:00
                # kolejność (25.11): najpierw światło, bo je widać; nawilżacze i reszta potem
                if eve:  # wieczorem: salon, kuchnia i sypialnia klimatycznie (LED-y w kuchni za mocne: off; Lampa Salon tylko do czytania)
                    state['eve_ret'] = day_key()
                    room_set('work', True, 'powrot wieczorem, klimatycznie')
                    room_set('bed', True, 'powrot wieczorem')  # sypialnia ciepło, przygaszona
                else:
                    room_set('work', True, 'powrot w dzien')  # cały salon i kuchnia
                log('powrot do domu: salon on%s%s' % (', sypialnia on' if bed_ok else '', ', wieczor' if eve else ''))
                if eve and PLAN.get('kitchen_led'):
                    plug_set(PLAN['kitchen_led'], False, 'kitchen_led off (wieczor)')
                hum_on('salon_hum', 's', None)
                hum_on('salon_pur', 's', None)
                if bed_ok:
                    hum_on('bed_hum', 'b', None)
                    state['bed_eve'] = day_key()
            if not state['away'] and dev.get('robot') and PLAN.get('robot_dock'):
                # wracam: robot na stację, nawet jeśli nie skończył (dawne „Zadokuj Robota”)
                try:
                    s_, a_ = PLAN['robot_dock']
                    dev['robot'].action(s_, a_)
                    log('robot: wrocilem, na stacje')
                except Exception as e:
                    log('robot: blad dokowania %s' % e)
            for name, room in (('salon', 's'), ('bed', 'b')):
                trv_target(name, trv_plan(room))

    # --- robot: wyszedłem dalej niż 1,5 km od domu ---
    robot_tick(sync, m)

    # --- zasypianie: telefon odłożony na noc ---
    if asleep and not was:
        log('noc: telefon odlozony')
        state['morn'] = None
        state['night_walks'] = 0
        for r in ('work', 'bed', 'bath'):
            room_set(r, False)
        MOT['on'] = False
        try:
            if ln:
                state['sleep_at'] = mins()  # noc z lampki: od zgaszenia liczymy 8 h snu
                log('noc: lampka nocna zgaszona')
            else:
                _, _, _, h, mi = parse_iso(ph['t'])
                state['sleep_at'] = h * 60 + mi  # pora odłożenia telefonu: od niej liczymy 8 h snu
        except Exception:
            state['sleep_at'] = mins()
        if PLAN.get('lamp_salon'):  # najpierw światła (25.11), urządzenia potem
            plug_set(PLAN['lamp_salon'], False, 'lampa salon off')
        if PLAN.get('kitchen_led'):
            plug_set(PLAN['kitchen_led'], False, 'kuchnia led off')
        if PLAN.get('wiz_bed'):
            state['wl'] = None
            log('lampka sypialnia off' if wiz({'state': False}) is not None else 'lampka sypialnia nie odpowiada (%s)' % state.get('wiz_err'))
        dev_set('bed_hum', 'on', False, 'sypialnia nawilzacz off')
        # salon na noc: nawilżacz i oczyszczacz zostają włączone, ale w trybie nocnym (cicho)
        dev_set('salon_hum', 'on', True)
        dev_set('salon_hum', 'sh_mode', 1, 'salon nawilzacz tryb nocny')
        dev_set('salon_pur', 'on', True)
        dev_set('salon_pur', 'sp_mode', 3, 'salon oczyszczacz tryb nocny')
        trv_target('salon', PLAN['salon_night'])
        trv_target('bed', PLAN['bed_night'])
        state['night_on'] = True
        if state.get('cur_state') != 'close':
            curtains('close', 'noc')

    # --- rano, przed pobudką (tylko gdy telefon nadal leży = jestem w domu) ---
    if asleep and m < 720 and not no_wake_today():  # panel: „bez budzenia” = śpię do oporu, nic przed wstaniem
        wm = wake_min(sync, weekend)
        am = wake_alarm_min(sync)
        we = min(wm, am) if am is not None else wm  # wczesny termin z kalendarza: ciepło na budzik
        for room, name, key, ok in (('s', 'salon', 'salon_morning', 'salon_heat'), ('b', 'bed', 'bed_morning', 'bed_heat')):
            if state.get('once_' + ok) == day_key() or m < we - PLAN['pre_max']:
                continue
            cur = room_temp(room, t)
            # 26.11: salon grzeje na 25° (szybciej), ale start liczony pod komfort na pobudkę (23°), nie pod 25°
            lead = heat_lead(room, cur, PLAN['salon_day'] if room == 's' else PLAN[key])
            if m >= we - lead and once(ok):
                log('przed pobudka: %s %s boost, teraz %s, start %d min przed %d:%02d%s' % (
                    ROOM_NAME[room], PLAN[key], None if cur is None else round(cur, 1), lead, we // 60, we % 60, ' (budzik)' if we != wm else ''))
                trv_target(name, PLAN[key])
                state['boost_day'] = day_key()
                if cur is not None:
                    state['heat_' + room] = {'t0': time.time(), 'T0': cur, 'tgt': PLAN[key], 'tout': state.get('tout'), 'band': tout_band()}
        for room in ('s', 'b'):
            if state.get('heat_' + room):
                heat_learn(room, room_temp(room, t), False)
        # budzenie światłem: start nie wcześniej niż 8 h 15 min od odłożenia telefonu, wcześniej tylko pod budzik z kalendarza
        if PLAN['wake_light'] and PLAN.get('wiz_bed') and sync:
            ws = wake_light_start(sync, weekend)
            if ws <= m < ws + PLAN['wake_light_min'] and once('wake_light'):
                am = wake_alarm_min(sync)
                log('budzenie swiatlem start %02d:%02d (pobudka %d:%02d%s)' % (
                    ws // 60, ws % 60, wm // 60, wm % 60, ', budzik %d:%02d' % (am // 60, am % 60) if am is not None else ''))
                state['wl'] = {'t0': time.time() - (m - ws) * 60}
                state['wl_at'] = 0
                # 27.11: zasłony ruszają dopiero w połowie rozjaśniania (budził mnie ich dźwięk od razu na starcie)
                # 26.11: powietrze rusza już z budzeniem (zaraz wstaję), nie dopiero po wstaniu
                dev_set('salon_hum', 'on', True)
                if dev_set('salon_hum', 'sh_mode', 0, 'budzenie: salon nawilzacz tryb dzienny'):
                    dev_set('salon_hum', 'sh_target', PLAN['rh_target'])
                dev_set('salon_pur', 'on', True)
                dev_set('salon_pur', 'sp_mode', 0, 'budzenie: salon oczyszczacz tryb dzienny')
                if weekend:
                    hum_on('bed_hum', 'b', 'budzenie: sypialnia nawilzacz on (weekend)')

    if was and not asleep:
        for room in ('s', 'b'):
            if state.get('heat_' + room):
                heat_learn(room, room_temp(room, t), True)
    boost_tick(asleep, m)

    # --- wstałem: telefon zdjęty rano ---
    if was and not asleep and ph and ph.get('e') == 'up':
        log('rano: telefon zdjety')
        man_clear('pobudka')
        if state.get('no_wake') == day_key():
            state['no_wake'] = None
        state['ln_t'] = None
        state['nl_eve'] = None
        state['morn'] = {'t0': time.time(), 'we': is_weekend()}
        state['night_walks'] = 0
        if MOT.get('on') and room_ips('bath'):
            # pobudka zwykle z wagi w łazience (25.11): od razu pełne poranne światło na wszystkich żarówkach łazienki
            room_set('bath', True, 'pobudka, jestem w lazience')
        room_set('work', True, 'rano')  # najpierw salon i kuchnia (tam idę), potem sypialnia gaśnie (25.11)
        room_set('bed', False, 'wstalem')  # sufit w sypialni gaśnie (wychodzę z sypialni)
        # wstałem i wychodzę z sypialni: lampka off na każdym etapie rozjaśniania (a jeśli się nie zaczęło, już nie ruszy)
        if PLAN['wake_light'] and PLAN.get('wiz_bed'):
            was_on = state.get('wl') is not None or state.get('wl_done') == time.localtime()[2]
            state['wl'] = None
            ok = wiz({'state': False}) is not None  # wysyłamy zawsze (np. po restarcie płytki), lampka już wyłączona nic nie robi
            if was_on:
                log('budzenie swiatlem: wstalem, lampka off' if ok else 'lampka sypialnia nie odpowiada (%s)' % state.get('wiz_err'))
        # tryb dzienny: nawilżacz na stałą wilgotność (dalej moc ustawia reguła wg Qingpinga), oczyszczacz na auto
        dev_set('salon_hum', 'on', True)
        if dev_set('salon_hum', 'sh_mode', 0, 'rano: salon nawilzacz tryb dzienny'):
            dev_set('salon_hum', 'sh_target', PLAN['rh_target'])
        dev_set('salon_pur', 'on', True)
        dev_set('salon_pur', 'sp_mode', 0, 'rano: salon oczyszczacz tryb dzienny')  # bieg ustawi reguła wg Qingpinga
        if is_weekend():
            hum_on('bed_hum', 'b', 'rano: sypialnia nawilzacz on (weekend)')  # dawne „DOM Weekend ON”
        trv_target('salon', PLAN['salon_day'])
        # sypialnia od razu po wstaniu: w tygodniu 17°C (stoi pusta do 18:00), w weekend 23°C
        state['bed_off_at'] = None
        trv_target('bed', PLAN['bed_home'] if is_weekend() else PLAN['bed_day'])
        state['night_on'] = False
        # zasłony: jeśli nie otworzyły się już przy budzeniu, otwieramy teraz (zwykła prędkość)
        if not (state.get('cur_state') == 'open' and state.get('cur_day') == day_key()):
            curtains('open', 'wstalem', quiet=False)
    if state.get('bed_off_at') and time.time() >= state['bed_off_at']:
        state['bed_off_at'] = None
        # w tygodniu do 18:00 sypialnia stoi pusta; w weekend jestem w domu
        trv_target('bed', PLAN['bed_home'] if is_weekend() else PLAN['bed_day'])

    # --- Pon-Pt od 18:00: sypialnia ciepło, jeśli jestem w domu ---
    if not weekend and 1080 <= m < PLAN['night_from'] and not asleep and not state.get('away') and not state.get('bed_eve') == day_key():
        state['bed_eve'] = day_key()
        log('wieczor: jestem w domu, sypialnia %s i nawilzacz' % PLAN['bed_home'])
        trv_target('bed', PLAN['bed_home'])
        hum_on('bed_hum', 'b', None)

    # --- 21:00: zasłony w sypialni zasuwane (wieczorem dziwnie siedzieć przy odsłoniętych) ---
    if not nl_mode() and m >= PLAN['night_from'] and state.get('cur_state') != 'close' and once('cur_eve'):
        curtains('close', 'wieczor 21:00')

    # --- tryb wieczór (24.11): po zmierzchu i od 19:00, gdy jestem w domu: Lampa Salon ON, salon i kuchnia
    # przechodzą na 2700 K 40% (light_target; zapalone żarówki płytka przestawia sama), LED-y kuchni wieczorem nigdy ---
    if (m >= PLAN.get('eve_from', 1140) and m >= sun_min(False) and not asleep and not state.get('away')
            and not nl_eve_on() and once('eve19')):
        log('wieczor: po zmierzchu i po 19:00, tryb wieczor (salon, kuchnia i sypialnia 2700K 40%)')
        for r in ('work', 'bed'):
            ips = [x['ip'] for mac, x in ws_present().items() if room_of(mac) == r and x['p'].get('state')]
            if ips:
                room_set(r, True, 'wieczor')

    # --- salon: moc nawilżacza według Qingpinga ---
    if rh is not None and not air('s') and not asleep and not nl_eve_on():  # w nocy i w trybie czytania nie ruszamy trybu nocnego
        on, mode = dev_get('salon_hum', ['on', 'sh_mode'])
        if on:
            if rh < PLAN['rh_low'] and mode != 2:
                dev_set('salon_hum', 'sh_mode', 2, 'salon nawilzacz mocno (RH %d)' % rh)
            elif rh >= PLAN['rh_ok'] and mode == 2:
                if dev_set('salon_hum', 'sh_mode', 0, 'salon nawilzacz stala wilgotnosc (RH %d)' % rh):
                    dev_set('salon_hum', 'sh_target', PLAN['rh_target'])

    # --- salon: bieg oczyszczacza według PM2.5 z Qingpinga (jak nawilżacz według wilgotności) ---
    if not air('s') and not asleep and not nl_eve_on():
        p_on, p_mode, p_fan = dev_get('salon_pur', ['on', 'sp_mode', 'sp_fan'])
        if p_on and pm25 is None and p_mode == 6:
            dev_set('salon_pur', 'sp_mode', 0, 'qingping milczy: salon oczyszczacz na auto (wlasny czujnik)')
        elif p_on and pm25 is not None and p_mode in (0, 6):
            cur = (p_fan + 1) if (p_mode == 6 and p_fan is not None) else 0
            if pm25 > PLAN['pm_hi'] or (cur == 3 and pm25 > PLAN['pm_hi'] - 5):
                want = 3
            elif pm25 > PLAN['pm_mid'] or (cur >= 2 and pm25 > PLAN['pm_mid'] - 3):
                want = 2
            else:
                want = 1
            # w górę od razu, w dół najwyżej co 10 min (żeby nie skakał)
            if want != cur and (cur == 0 or want > cur or time.time() - state.get('pur_lvl_at', 0) > 600):
                ok = True
                if p_mode != 6:
                    ok = dev_set('salon_pur', 'sp_mode', 6)
                if ok and dev_set('salon_pur', 'sp_fan', want - 1, 'salon oczyszczacz bieg %d (PM2.5 %d)' % (want, pm25)):
                    state['pur_lvl_at'] = time.time()

    # --- sypialnia: nawilżacz sam przestrzeliwuje cel, więc pilnuje go płytka (jego własny czujnik) ---
    # włączony przeze mnie lub przez Google Home: przy >= 55% pauza (off), przy <= 47% z powrotem on (tylko gdy jestem w domu).
    # Wyłączony przeze mnie: nie ruszamy.
    if not asleep and not air('b') and time.time() - state.get('bed_chk', 0) > 120:
        state['bed_chk'] = time.time()
        b_on, b_rh = dev_get('bed_hum', ['on', 'bh_rh'])
        if b_rh is not None:
            state['bed_rh'] = b_rh
            if b_on and b_rh >= PLAN['bed_rh_hi']:
                if dev_set('bed_hum', 'on', False, 'sypialnia nawilzacz pauza (RH %d)' % b_rh):
                    state['bed_pause'] = True
            elif not b_on and state.get('bed_pause') and b_rh <= PLAN['bed_rh_lo']:
                # wznawiamy tylko, gdy jestem w domu (Google Home trzyma wtedy oczyszczacz w salonie włączony);
                # samo włączanie po powrocie robi Google Home, płytka tego nie dubluje
                home, = dev_get('salon_pur', ['on'])
                if home and dev_set('bed_hum', 'on', True, 'sypialnia nawilzacz wznowiony (RH %d)' % b_rh):
                    state['bed_pause'] = False
            elif b_on:
                state['bed_pause'] = False
                # moc według wilgotności: sucho = mocno, blisko celu = cicho (z zapasem, żeby nie przeskakiwał co chwilę)
                # odczyt nawilżacza skacze o kilka %, więc szeroki zapas i zmiana poziomu najwyżej co 15 min
                b_mode, = dev_get('bed_hum', ['bh_mode'])
                cur = b_mode if b_mode in (1, 2, 3) else 2
                if b_rh < 38 or (cur == 3 and b_rh < 43):
                    want = 3
                elif b_rh < 45 or (cur >= 2 and b_rh < 52):
                    want = 2
                else:
                    want = 1
                if want != b_mode and (b_mode not in (1, 2, 3) or time.time() - state.get('bed_lvl_at', 0) > 900):
                    if dev_set('bed_hum', 'bh_mode', want, 'sypialnia nawilzacz poziom %d (RH %d)' % (want, b_rh)):
                        state['bed_lvl_at'] = time.time()
    if asleep:
        state['bed_pause'] = False

    # --- temperatura z Qingpinga do głowicy w salonie (co 5 min) ---
    if PLAN['ext_temp'] and t is not None and time.time() - state.get('ext_at', 0) > 300:
        state['ext_at'] = time.time()
        state['ext_off'] = False
        trv_ext('salon', t)
    # Qingping milczy ponad 15 min: głowica nie może grzać według starej temperatury (sama nie wraca do swojego czujnika),
    # więc kasujemy temperaturę zewnętrzną; gdy Qingping wróci, wyżej znów ją wysyłamy
    if PLAN['ext_temp'] and t is None and not state.get('ext_off') and time.time() - state.get('ext_at', time.time()) > 900:
        tid = cfg.get('trv', {}).get('salon')
        try:
            trv_call(tid, 'TRV.SetExternalTemperature', {'id': 0})
            state['ext_off'] = True
            log('qingping milczy: grzejnik salon wraca do wlasnego czujnika')
        except Exception as e:
            print('ext off err', e)


def check_update():
    """Co 3 h: jeśli na GitHubie jest nowsza wersja, restart (main.py ją pobierze)."""
    try:
        ble_pause()
        r = requests.get('https://raw.githubusercontent.com/mojanetia-strona/fitness-app/main/dom/version.txt', timeout=20)
        remote = r.text.strip()
        r.close()
        ble_resume()
        if tuple(int(x) for x in remote.split('.')) > tuple(int(x) for x in VERSION.split('.')):
            flush_log('aktualizacja do ' + remote)
            machine.reset()
    except Exception as e:
        ble_resume()
        print('update check err', e)


# ---------- start ----------
def setup():
    global cfg
    with open('config.json') as f:
        cfg = json.load(f)
    PLAN.update(cfg.get('plan', {}))
    for name in ('qingping', 'salon_hum', 'salon_pur', 'bed_hum', 'robot'):
        d = cfg.get('devices', {}).get(name)
        if d and d.get('ip') and d.get('token') and len(d['token']) == 32:
            dev[name] = Device(d['ip'], d['token'], name)
    try:
        rc = {1: 'zasilanie', 2: 'reset', 3: 'straznik', 4: 'uspienie', 5: 'programowy'}.get(machine.reset_cause(), str(machine.reset_cause()))
    except Exception:
        rc = '?'
    log('start v%s (%s), urzadzenia: %s' % (VERSION, rc, ','.join(sorted(dev.keys()))))
    log('temperatury: salon dzien %s noc %s, sypialnia dom %s rano %s dzien %s noc %s' % (
        PLAN['salon_day'], PLAN['salon_night'], PLAN['bed_home'], PLAN['bed_morning'], PLAN['bed_day'], PLAN['bed_night']))
    SNAP['boot_rc'] = rc
    if rc == 'zasilanie':
        SNAP['restore_at'] = time.time() + 60  # urządzenia też dopiero wstają po braku prądu
    try:
        import os
        with open('lasterr.txt') as f:
            log('restart po braku polaczenia z arkuszem: ' + f.read()[:160])
        os.remove('lasterr.txt')
    except OSError:
        pass
    if load_state():
        log('stan przywrocony (noc: %s)' % state.get('asleep'))
    if PLAN.get('wiz_bed'):
        r = wiz({}, 'getPilot')
        if r and r.get('result'):
            x = r['result']
            sc = (wiz({}, 'getSystemConfig') or {}).get('result') or {}
            log('lampka sypialnia ok (%s, %s%%, model %s)' % ('wl' if x.get('state') else 'wyl', x.get('dimming'), sc.get('moduleName')))
            mc = wiz({}, 'getModelConfig')  # nowsze żarówki: zakres bieli (K) i rodzaj (kolor / biel)
            log('lampka mozliwosci: %s' % (json.dumps((mc or {}).get('result') or state.get('wiz_err'))[:300]))
        else:
            log('lampka sypialnia nie odpowiada (%s)' % state.get('wiz_err'))
    if dev.get('robot'):
        try:
            info = dev['robot'].call('miIO.info', [], 2) or {}
            log('robot ok (model %s, fw %s)' % (info.get('model'), info.get('fw_ver')))
        except Exception as e:
            log('robot nie odpowiada (%s)' % e)
    if not state.get('pur_model') and dev.get('salon_pur'):
        try:
            state['pur_model'] = (dev['salon_pur'].call('miIO.info', [], 1) or {}).get('model')
            log('oczyszczacz model %s' % state['pur_model'])
        except Exception as e:
            print('pur model err', e)


# ---------- powrót prądu: przywracanie stanu urządzeń ----------
# Co 2 min płytka zapisuje stan urządzeń zasilanych z gniazdka (snap.json). Gdy płytka wstaje po braku prądu
# (nie po aktualizacji ani restarcie), po 60 s przywraca ten stan: co było włączone, włącza w tym samym trybie,
# co było wyłączone, wyłącza. Głowice grzejników i robot mają baterie, więc ich to nie dotyczy.
SNAP_DEV = {'salon_hum': ('on', 'sh_mode', 'sh_target'), 'salon_pur': ('on', 'sp_mode', 'sp_fan'), 'bed_hum': ('on', 'bh_mode')}
SNAP = {'t': 0, 'boot_rc': None, 'restore_at': 0, 'js': None}


def snap_tick():
    if SNAP['restore_at'] or time.time() - SNAP['t'] < 120:
        return  # czekamy na przywrócenie po braku prądu (nie zapisujemy stanu „wszystko wyłączone”)
    SNAP['t'] = time.time()
    try:
        with open('snap.json') as f:
            d = json.load(f)
    except Exception:
        d = {}
    for name, keys in SNAP_DEV.items():
        if not dev.get(name):
            continue
        v = dev_get(name, keys)
        if None not in v:
            d[name] = dict(zip(keys, v))
    for key in ('lamp_salon', 'kitchen_led'):
        ip = PLAN.get(key)
        if not ip:
            continue
        try:
            gc.collect()
            r = requests.get('http://%s/rpc/Switch.GetStatus?id=0' % ip, timeout=3)
            try:
                d[key] = {'on': bool(r.json().get('output'))}
            finally:
                r.close()
        except Exception:
            pass
    for ip in PLAN.get('wiz_lamps') or []:
        r = wiz({}, 'getPilot', ip)
        x = (r or {}).get('result')
        if x:
            d['wiz_' + ip] = {k: x[k] for k in ('state', 'dimming', 'temp', 'sceneId', 'r', 'g', 'b') if k in x}
    for x in ws_present().values():  # pozostałe żarówki: stan z wyszukiwania (bez dodatkowych pytań)
        if x['ip'] not in (PLAN.get('wiz_lamps') or []):
            d['wiz_' + x['ip']] = dict(x['p'])
    for key in [k for k in d if k.startswith('wiz_') and k[4:] not in (PLAN.get('wiz_lamps') or [])]:
        if not any(x['ip'] == key[4:] for x in ws_present().values()):
            del d[key]  # żarówka bez prądu (klawisz wyłączony): nie przywracamy jej po braku prądu
    js = json.dumps(d)
    if js == SNAP['js']:
        return
    try:
        with open('snap.json', 'w') as f:
            f.write(js)
        SNAP['js'] = js
    except Exception as e:
        print('snap save err', e)


def restore_tick():
    if not SNAP['restore_at'] or time.time() < SNAP['restore_at']:
        return
    SNAP['restore_at'] = 0
    try:
        with open('snap.json') as f:
            d = json.load(f)
    except Exception:
        log('prad: brak zapisanego stanu urzadzen, nic nie przywracam')
        return
    done = []
    # zasada „światła pierwsze” (25.11): żarówki naraz serią, dopiero potem nawilżacze i oczyszczacz
    groups = {}
    for ip in [k[4:] for k in d if k.startswith('wiz_')]:
        st = d.get('wiz_' + ip)
        if st and st.get('state'):
            pr = {k: v for k, v in st.items() if k != 'state'}
            pr['state'] = True
            groups.setdefault(json.dumps(pr), []).append(ip)
    for pj, ips in groups.items():
        pr = json.loads(pj)
        cmd = {'room': 'prad', 'on': True, 't0': time.time(), 'left': set(ips), 'n': len(ips), 'rs': 0, 'done': {}}
        for ip in ips:
            WS.setdefault('want', {})[ip] = {'p': pr, 'until': time.time() + 300, 'at': time.time(), 'cmd': cmd}
            WZ['st'][ip] = True
        room_burst(ips, pr, cmd)
        done += ['%s wl' % ip[-3:] for ip in ips]
    for key in ('lamp_salon', 'kitchen_led'):
        st = d.get(key)
        if st and PLAN.get(key):
            plug_set(PLAN[key], bool(st.get('on')), 'prad: %s %s' % (key, 'wl' if st.get('on') else 'wyl'))
    for name, keys in SNAP_DEV.items():
        st = d.get(name)
        if not st or not dev.get(name):
            continue
        if st.get('on'):
            dev_set(name, 'on', True)
            time.sleep(2)
            for k in keys[1:]:
                if k == 'sp_fan' and st.get('sp_mode') != 6:
                    continue  # bieg tylko w trybie ręcznym (inaczej przełączyłby oczyszczacz z auto)
                if st.get(k) is not None:
                    dev_set(name, k, st[k])
            done.append('%s wl' % name)
        else:
            dev_set(name, 'on', False)
            done.append('%s wyl' % name)
    log('prad wrocil, przywracam stan: %s' % (', '.join(done) or 'nic'))


BOOT_T = [0]


def run():
    BOOT_T[0] = time.time()
    setup()
    ble_start()
    sync = None
    last_sync = 0
    last_rules = 0
    last_report = time.time()
    # strażnik: jeśli pętla stanie na dłużej niż 5 min (np. zawieszone połączenie), płytka sama się zrestartuje
    wdt = machine.WDT(timeout=300000)
    while True:
        wdt.feed()
        try:
            force = NOW[0]
            NOW[0] = False
            if not BOOT_T[1:] and time.time() - BOOT_T[0] > 45:  # 26.11: raz po starcie, gdy żarówki już się zgłosiły (stan dla panelu)
                BOOT_T.append(1)
                force = True
            # co 2 min; w oknie typowej pobudki (±1 h, np. 6:00-8:00 przy pobudce o 7:00),
            # dopóki śpię: co 20 s, żeby poranek ruszał od razu po zdjęciu telefonu
            every = 120
            if state.get('asleep'):
                try:
                    wm = wake_min(sync, is_weekend())
                    if wm - 60 <= mins() < wm + 60:
                        every = 20
                except Exception:
                    pass
            if force or time.time() - last_sync >= every:
                last_sync = time.time()
                fast_tick()  # ruch w łazience obsłużony przed kilkusekundową synchronizacją z arkuszem
                try:
                    prm = {'pc': 'on'} if PC['evt'] else {}
                    try:
                        prm['st'] = panel_state()
                    except Exception as e:
                        print('panel st', e)
                    sync = gas(prm)
                    PC['evt'] = False
                    state['sync_fail'] = 0
                    remote_cmd(sync)
                    panel_cmds(sync)
                except Exception as e:
                    print('sync err', e)
                    # brak łączności z arkuszem przez ok. 10 min: zapisz przyczynę i zrestartuj (płytka sama wraca do pracy)
                    state['sync_fail'] = state.get('sync_fail', 0) + 1
                    # brak pamięci sam nie minie (rozdrobniona pamięć): restart od razu, a nie po 10 min
                    if state['sync_fail'] >= 20 or isinstance(e, MemoryError):
                        try:
                            with open('lasterr.txt', 'w') as f:
                                f.write('%s %s (wolna pamiec %d)' % (stamp(), repr(e)[:120], gc.mem_free()))
                        except Exception:
                            pass
                        machine.reset()
            if force or time.time() - last_rules >= 30:
                last_rules = time.time()
                fast_tick()
                q = dev_get('qingping', ['q_rh', 'q_pm25', 'q_t', 'q_co2'])
                state['q'] = q
                fast_tick()
                tick_rules(sync, q)
                save_state()
            scale_tick()
            pc_tick()
            gw_windows()
            win_tick()
            curtains_tick()
            night_lamp_guard()
            nl_tick()
            wiz_scan_tick()
            http_tick()
            ucho_tick()
            gw_motion()
            bath_tick()
            wiz_switch_tick(sync)
            wake_light_tick()
            restore_tick()
            snap_tick()
            if log_buf and (time.time() - last_report > 120 or len(log_buf) > 8):
                last_report = time.time()
                fast_tick()
                flush_log()
            if time.time() - state.get('hb', 0) > 1800:
                state['hb'] = time.time()
                q = state.get('q') or [None] * 4
                flush_log('ok RH %s T %s CO2 %s PM %s | sypialnia RH %s | %s | mem %d' % (q[0], q[2], q[3], q[1], state.get('bed_rh'), trv_brief(), gc.mem_free()))
            if time.time() - state.setdefault('upd', time.time()) > 10800:  # setdefault: start liczy się od uruchomienia
                state['upd'] = time.time()
                check_update()
            if not network.WLAN(network.STA_IF).isconnected():
                machine.reset()
        except Exception as e:
            log('blad petli %s' % e)
        gc.collect()
        for _ in range(4):  # zamiast 1 s snu: co 0,25 s lekkie sprawdzenie łazienki (gniazda bez czekania)
            time.sleep_ms(250)
            fast_tick()
