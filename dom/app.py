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

VERSION = '1.0.64'

# ---------- ustawienia domyślne (nadpisywane przez config.json -> "plan") ----------
PLAN = {
    'salon_day': 22.0,      # salon w dzień
    'salon_night': 18.0,    # salon w nocy (po odłożeniu telefonu)
    'bed_day': 17.0,        # sypialnia w dzień (tylko ochrona przed wychłodzeniem)
    'bed_night': 17.0,      # sypialnia w nocy (do spania chłodniej)
    'bed_home': 20.0,       # sypialnia, gdy w niej jestem (Pon-Pt od 18:00, weekend po wstaniu); głowica przy grzejniku, korekta -2
    'bed_morning': 22.0,    # sypialnia przed pobudką (cieplej na wstanie)
    'bed_pre_min': 60,      # ile minut przed pobudką grzać sypialnię (tak samo jak salon)
    'bed_after_min': 30,    # ile minut po zdjęciu telefonu wyłączyć sypialnię
    'salon_pre_min': 60,    # (nieużywane) nawilżacz i oczyszczacz włączają się dopiero po zdjęciu telefonu
    'salon_heat_pre_min': 60,  # ile minut przed pobudką grzać salon na dzień
    'wake_wd': 420,         # domyślna pobudka w tygodniu (min od północy), gdy brak danych z telefonu
    'wake_we': 540,         # domyślna pobudka w weekend
    'night_from': 1260,     # odłożenie telefonu po 21:00 = noc
    'night_late': 1350,     # telefon odłożony wcześniej, ale nadal leży o 22:30 = też noc
    'rh_low': 48,           # salon: poniżej tej wilgotności (Qingping) nawilżacz na mocno
    'rh_ok': 50,            # salon: od tej wilgotności nawilżacz wraca do stałej wilgotności
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
    # --- budzenie światłem: żarówka WiZ „Lampka Sypialnia” (lokalnie, UDP 38899) ---
    'wiz_bed': '192.168.100.37',
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
    'robot_fresh': 45,      # zdarzenie „oddaliłem się” ważne tyle minut (np. wyjście o 6:50 uruchomi robota o 7:00)
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
def gas(params, want=True):
    url = cfg['gas_url'] + '?action=esp&token=' + cfg['gas_token']
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
    for i in range(3):
        try:
            gc.collect()
            r = requests.get('http://%s/rpc/Switch.Set?id=0&on=%s' % (ip, 'true' if on else 'false'), timeout=8)
            r.close()
            log(label)
            return True
        except Exception as e:
            last = e
            time.sleep(2)
    log('%s blad %s' % (label, last))
    return False


def wiz(params, method='setPilot'):
    """Żarówka WiZ w sieci domowej: JSON po UDP na port 38899. Zwraca odpowiedź (dict) albo None."""
    ip = PLAN.get('wiz_bed')
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


def night_lamp_guard():
    # po zaniku prądu żarówka WiZ sama się zapala (tak ma zostać, bo bywa zwykłą lampką);
    # w nocy przez 10 min po starcie płytki gasimy ją, gdy wróci do sieci włączona
    if not PLAN.get('wiz_bed') or not state.get('asleep') or state.get('wl'):
        return
    if time.time() - BOOT_T[0] > 600 or time.time() - state.get('nlg_at', 0) < 20:
        return
    state['nlg_at'] = time.time()
    r = wiz({}, 'getPilot')
    if r and (r.get('result') or {}).get('state'):
        if wiz({'state': False}) is not None:
            log('noc: lampka sypialnia zapalila sie po zaniku pradu, gasze')


def wake_light_tick():
    """Co 15 s podczas rozjaśniania: kolejny krok jasności."""
    wl = state.get('wl')
    if not wl or time.time() - state.get('wl_at', 0) < 15:
        return
    state['wl_at'] = time.time()
    p = (time.time() - wl['t0']) / (wl.get('min', PLAN['wake_light_min']) * 60.0)
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
        trv_call(tid, 'TRV.SetTarget', {'id': 0, 'target_C': temp})
        state['trv_' + name] = temp
        log('grzejnik %s -> %s' % (name, temp))
    except Exception as e:
        log('grzejnik %s blad %s' % (name, e))


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
            if t['target_C'] <= 5.5 and not air(room):
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


def bthome(addr, p):
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
    if 0x2D not in d:
        return
    mac = ':'.join('%02X' % b for b in addr)
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


def trv_plan(room):
    m, night = mins(), state.get('asleep')
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
    try:
        res = gas({'kg': '%.2f' % kg})
        if isinstance(res, dict) and res.get('pobudka_waga'):
            NOW[0] = True  # pobudka z wagi: od razu synchronizacja i reguły, bez czekania na kolejny cykl
        scale['last_kg'] = kg
        scale['last_sent'] = time.time()
        log('waga %.2f kg zapisana' % kg)
    except Exception as e:
        log('waga blad %s' % e)
        scale['pending'] = kg
        scale['pending_at'] = time.time()


NOW = [False]  # wymuszenie natychmiastowej synchronizacji (np. pobudka z wagi)

# ---------- Komputer ON → Muzyka Poranna OFF ----------
PC = {'on': None, 'evt': False, 't': 0}


def pc_tick():
    # co 15 s stan gniazdka przy komputerze; przejście OFF -> ON = komputer włączony, arkusz wyłącza poranną muzykę
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
    if PC['on'] is False and on:
        PC['evt'] = True
        NOW[0] = True
        log('komputer wlaczony')
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


SAVE_KEYS = ('asleep', 'bed_off_at', 'bed_eve', 'night_on', 'bed_pause', 'air', 'wl', 'sleep_at', 'robot_ev', 'robot_day', 'wiz_lvl',
             'cur_want', 'cur_why', 'cur_state', 'cur_day')


def day_num():
    tm = now_local()
    return int(mk(tm[0], tm[1], tm[2], 12) // 86400)


def robot_tick(sync, m):
    """Robot rusza raz na `robot_every` dni, gdy telefon zgłosi oddalenie od domu (> 1,5 km). Kończy sam, powrotu nie przerywamy."""
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
        log('robot: wyszedlem z domu, start sprzatania')
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
    was = state.get('asleep')
    # bez odpowiedzi z arkusza nie zgadujemy: zostaje poprzedni stan (inaczej po restarcie noc/pobudka odpalałyby się drugi raz)
    asleep = phone_asleep(ph) if sync else bool(was)
    if was and not asleep and ph and ph.get('e') == 'up':
        # pobudka liczy się tylko od zdjęcia telefonu po 4:00 (albo z wagi); zdjęcie sprzed 4:00 nie odpali poranka później.
        # Zdjęcie w ciągu 10 min od startu płytki to skok prądu (ładowarka gaśnie razem z płytką), nie pobudka.
        try:
            _, _, _, eh, emi = parse_iso(ph['t'])
            ago = local_minutes_since(ph['t'])
            blip = abs((time.time() - ago * 60) - BOOT_T[0]) < 600
            if eh * 60 + emi < 240 or blip:
                asleep = True
                if blip and not state.get('blip_log'):
                    state['blip_log'] = 1
                    log('telefon zdjety tuz po starcie plytki: skok pradu, nie pobudka')
        except Exception as e:
            print('wake check', e)
    if was and not asleep and m < 240:
        asleep = True  # zerknięcie na telefon w nocy to jeszcze nie pobudka
    state['asleep'] = asleep

    # --- robot: wyszedłem dalej niż 1,5 km od domu ---
    robot_tick(sync, m)

    # --- zasypianie: telefon odłożony na noc ---
    if asleep and not was:
        log('noc: telefon odlozony')
        try:
            _, _, _, h, mi = parse_iso(ph['t'])
            state['sleep_at'] = h * 60 + mi  # pora odłożenia telefonu: od niej liczymy 8 h snu
        except Exception:
            state['sleep_at'] = mins()
        dev_set('bed_hum', 'on', False, 'sypialnia nawilzacz off')
        if PLAN.get('lamp_salon'):
            plug_set(PLAN['lamp_salon'], False, 'lampa salon off')
        if PLAN.get('wiz_bed'):
            state['wl'] = None
            log('lampka sypialnia off' if wiz({'state': False}) is not None else 'lampka sypialnia nie odpowiada (%s)' % state.get('wiz_err'))
        # salon na noc: nawilżacz i oczyszczacz zostają włączone, ale w trybie nocnym (cicho)
        dev_set('salon_hum', 'on', True)
        dev_set('salon_hum', 'sh_mode', 1, 'salon nawilzacz tryb nocny')
        dev_set('salon_pur', 'on', True)
        dev_set('salon_pur', 'sp_mode', 3, 'salon oczyszczacz tryb nocny')
        trv_target('salon', PLAN['salon_night'])
        trv_target('bed', PLAN['bed_night'])
        state['night_on'] = True
        curtains('close', 'noc')

    # --- rano, przed pobudką (tylko gdy telefon nadal leży = jestem w domu) ---
    if asleep and m < 720:
        wm = wake_min(sync, weekend)
        if m >= wm - PLAN['salon_heat_pre_min'] and once('salon_heat'):
            trv_target('salon', PLAN['salon_day'])
        if m >= wm - PLAN['bed_pre_min'] and once('bed_heat'):
            trv_target('bed', PLAN['bed_morning'])
        # budzenie światłem: start nie wcześniej niż 8 h 15 min od odłożenia telefonu, wcześniej tylko pod budzik z kalendarza
        if PLAN['wake_light'] and PLAN.get('wiz_bed') and sync:
            ws = wake_light_start(sync, weekend)
            if ws <= m < ws + PLAN['wake_light_min'] and once('wake_light'):
                am = wake_alarm_min(sync)
                log('budzenie swiatlem start %02d:%02d (pobudka %d:%02d%s)' % (
                    ws // 60, ws % 60, wm // 60, wm % 60, ', budzik %d:%02d' % (am // 60, am % 60) if am is not None else ''))
                state['wl'] = {'t0': time.time() - (m - ws) * 60}
                state['wl_at'] = 0
                curtains('open', 'budzenie')  # cicho, razem z rozjaśnianiem lampki

    # --- wstałem: telefon zdjęty rano ---
    if was and not asleep and ph and ph.get('e') == 'up':
        log('rano: telefon zdjety')
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
        trv_target('salon', PLAN['salon_day'])
        state['bed_off_at'] = time.time() + PLAN['bed_after_min'] * 60
        state['night_on'] = False
        # zasłony: jeśli nie otworzyły się już przy budzeniu, otwieramy teraz (zwykła prędkość)
        if not (state.get('cur_state') == 'open' and state.get('cur_day') == day_key()):
            curtains('open', 'wstalem', quiet=False)
    if state.get('bed_off_at') and time.time() >= state['bed_off_at']:
        state['bed_off_at'] = None
        # w tygodniu do 18:00 sypialnia stoi pusta; w weekend jestem w domu
        trv_target('bed', PLAN['bed_home'] if is_weekend() else PLAN['bed_day'])

    # --- Pon-Pt od 18:00: sypialnia 22°C, jeśli jestem w domu (Google Home trzyma wtedy salon włączony) ---
    if not weekend and 1080 <= m < PLAN['night_from'] and not asleep and not state.get('bed_eve') == day_key():
        pur_on, = dev_get('salon_pur', ['on'])
        if pur_on:
            state['bed_eve'] = day_key()
            log('wieczor: jestem w domu, sypialnia %s' % PLAN['bed_home'])
            trv_target('bed', PLAN['bed_home'])

    # --- salon: moc nawilżacza według Qingpinga ---
    if rh is not None and not air('s') and not asleep:  # w nocy nie ruszamy trybu nocnego
        on, mode = dev_get('salon_hum', ['on', 'sh_mode'])
        if on:
            if rh < PLAN['rh_low'] and mode != 2:
                dev_set('salon_hum', 'sh_mode', 2, 'salon nawilzacz mocno (RH %d)' % rh)
            elif rh >= PLAN['rh_ok'] and mode == 2:
                if dev_set('salon_hum', 'sh_mode', 0, 'salon nawilzacz stala wilgotnosc (RH %d)' % rh):
                    dev_set('salon_hum', 'sh_target', PLAN['rh_target'])

    # --- salon: bieg oczyszczacza według PM2.5 z Qingpinga (jak nawilżacz według wilgotności) ---
    if not air('s') and not asleep:
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
            if force or time.time() - last_sync >= 120:  # co 2 min; pobudka z wagi i tak synchronizuje od razu (force)
                last_sync = time.time()
                try:
                    sync = gas({'pc': 'on'} if PC['evt'] else {})
                    PC['evt'] = False
                    state['sync_fail'] = 0
                    remote_cmd(sync)
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
                q = dev_get('qingping', ['q_rh', 'q_pm25', 'q_t', 'q_co2'])
                state['q'] = q
                tick_rules(sync, q)
                save_state()
            scale_tick()
            pc_tick()
            gw_windows()
            win_tick()
            curtains_tick()
            night_lamp_guard()
            wake_light_tick()
            if log_buf and (time.time() - last_report > 120 or len(log_buf) > 8):
                last_report = time.time()
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
        time.sleep(1)
