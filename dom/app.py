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

VERSION = '1.0.29'

# ---------- ustawienia domyślne (nadpisywane przez config.json -> "plan") ----------
PLAN = {
    'salon_day': 22.0,      # salon w dzień
    'salon_night': 18.0,    # salon w nocy (po odłożeniu telefonu)
    'bed_day': 17.0,        # sypialnia w dzień (tylko ochrona przed wychłodzeniem)
    'bed_night': 17.0,      # sypialnia w nocy (do spania chłodniej)
    'bed_home': 20.0,       # sypialnia, gdy w niej jestem (Pon-Pt od 18:00, weekend po wstaniu); głowica przy grzejniku, korekta -2
    'bed_morning': 22.0,    # sypialnia przed pobudką (cieplej na wstanie)
    'bed_pre_min': 30,      # ile minut przed pobudką grzać sypialnię
    'bed_after_min': 30,    # ile minut po zdjęciu telefonu wyłączyć sypialnię
    'salon_pre_min': 60,    # (nieużywane) nawilżacz i oczyszczacz włączają się dopiero po zdjęciu telefonu
    'salon_heat_pre_min': 60,  # ile minut przed pobudką grzać salon na dzień
    'wake_wd': 420,         # domyślna pobudka w tygodniu (min od północy), gdy brak danych z telefonu
    'wake_we': 540,         # domyślna pobudka w weekend
    'night_from': 1260,     # odłożenie telefonu po 21:00 = noc
    'night_late': 1350,     # telefon odłożony wcześniej, ale nadal leży o 22:30 = też noc
    'rh_low': 48,           # salon: poniżej tej wilgotności (Qingping) nawilżacz na mocno
    'rh_ok': 50,            # salon: od tej wilgotności nawilżacz wraca do stałej wilgotności
    'rh_target': 50,        # cel stałej wilgotności w salonie
    'bed_rh_hi': 55,        # sypialnia: przy tylu % nawilżacz pauza
    'bed_rh_lo': 47,        # sypialnia: przy tylu % nawilżacz wraca
    'airing': False,        # tryb wietrzenia wyłączony (wróci z czujnikami okien)
    'air_co2_drop': 100,    # wietrzenie: spadek CO2 w 3 min (ppm)
    'air_t_drop': 0.6,      # wietrzenie: spadek temperatury w 3 min (°C)
    'air_max_min': 20,      # wietrzenie: najdłużej tyle minut pauzy
    'ext_temp': True,       # salon: temperatura z Qingpinga do głowicy
    'scale_min': 45.0, 'scale_max': 150.0,
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


def trv_target(name, temp):
    tid = cfg.get('trv', {}).get(name)
    if tid is None:
        return
    temp = round(float(temp) * 2) / 2
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
    'sp_mode': (2, 4),                               # salon oczyszczacz (MIoT): 0 auto, 1 nocny, 2 ulubiony
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


def ble_irq(event, data):
    if event != 5:  # _IRQ_SCAN_RESULT
        return
    try:
        adv = bytes(data[4])
        i = 0
        while i + 1 < len(adv):
            ln = adv[i]
            if ln == 0:
                break
            typ = adv[i + 1]
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
    # mały wycinek czasu radia (30 ms co 300 ms), żeby nie zagłuszać Wi-Fi
    b.gap_scan(0, 300000, 30000, True)
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
            BLE[0].gap_scan(0, 300000, 30000, True)
        except Exception as e:
            print('ble resume err', e)


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
        gas({'kg': '%.2f' % kg})
        scale['last_kg'] = kg
        scale['last_sent'] = time.time()
        log('waga %.2f kg zapisana' % kg)
    except Exception as e:
        log('waga blad %s' % e)
        scale['pending'] = kg
        scale['pending_at'] = time.time()


# ---------- logika ----------
hist = []  # (czas, co2, temp) z ostatnich minut


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


SAVE_KEYS = ('asleep', 'bed_off_at', 'bed_eve', 'night_on', 'bed_pause')


def save_state():
    d = {k: state.get(k) for k in SAVE_KEYS}
    for k in state:
        if k.startswith('once_'):
            d[k] = state[k]
    if d == state.get('_saved'):
        return
    try:
        with open('state.json', 'w') as f:
            json.dump({'t': time.time(), 's': d}, f)
        state['_saved'] = d
    except Exception as e:
        print('state save err', e)


def load_state():
    try:
        with open('state.json') as f:
            j = json.load(f)
        if time.time() - j.get('t', 0) < 12 * 3600:
            state.update(j['s'])
            state['_saved'] = j['s']
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
    if was and not asleep and m < 240:
        asleep = True  # zerknięcie na telefon w nocy to jeszcze nie pobudka
    state['asleep'] = asleep

    # --- zasypianie: telefon odłożony na noc ---
    if asleep and not was:
        log('noc: telefon odlozony')
        dev_set('bed_hum', 'on', False, 'sypialnia nawilzacz off')
        # salon na noc: nawilżacz i oczyszczacz zostają włączone, ale w trybie nocnym (cicho)
        dev_set('salon_hum', 'on', True)
        dev_set('salon_hum', 'sh_mode', 1, 'salon nawilzacz tryb nocny')
        dev_set('salon_pur', 'on', True)
        dev_set('salon_pur', 'sp_mode', 1, 'salon oczyszczacz tryb nocny')
        trv_target('salon', PLAN['salon_night'])
        trv_target('bed', PLAN['bed_night'])
        state['night_on'] = True

    # --- rano, przed pobudką (tylko gdy telefon nadal leży = jestem w domu) ---
    if asleep and m < 720:
        wm = wake_min(sync, weekend)
        if m >= wm - PLAN['salon_heat_pre_min'] and once('salon_heat'):
            trv_target('salon', PLAN['salon_day'])
        if m >= wm - PLAN['bed_pre_min'] and once('bed_heat'):
            trv_target('bed', PLAN['bed_morning'])

    # --- wstałem: telefon zdjęty rano ---
    if was and not asleep and ph and ph.get('e') == 'up':
        log('rano: telefon zdjety')
        # tryb dzienny: nawilżacz na stałą wilgotność (dalej moc ustawia reguła wg Qingpinga), oczyszczacz na auto
        dev_set('salon_hum', 'on', True)
        if dev_set('salon_hum', 'sh_mode', 0, 'rano: salon nawilzacz tryb dzienny'):
            dev_set('salon_hum', 'sh_target', PLAN['rh_target'])
        dev_set('salon_pur', 'on', True)
        dev_set('salon_pur', 'sp_mode', 0, 'rano: salon oczyszczacz tryb dzienny (auto)')
        trv_target('salon', PLAN['salon_day'])
        state['bed_off_at'] = time.time() + PLAN['bed_after_min'] * 60
        state['night_on'] = False
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
    if rh is not None and not state.get('airing') and not asleep:  # w nocy nie ruszamy trybu nocnego
        on, mode = dev_get('salon_hum', ['on', 'sh_mode'])
        if on:
            if rh < PLAN['rh_low'] and mode != 2:
                dev_set('salon_hum', 'sh_mode', 2, 'salon nawilzacz mocno (RH %d)' % rh)
            elif rh >= PLAN['rh_ok'] and mode == 2:
                if dev_set('salon_hum', 'sh_mode', 0, 'salon nawilzacz stala wilgotnosc (RH %d)' % rh):
                    dev_set('salon_hum', 'sh_target', PLAN['rh_target'])

    # --- sypialnia: nawilżacz sam przestrzeliwuje cel, więc pilnuje go płytka (jego własny czujnik) ---
    # włączony przeze mnie: przy >= 55% pauza (off), przy <= 47% z powrotem on. Wyłączony przeze mnie: nie ruszamy.
    if not asleep and not state.get('airing') and time.time() - state.get('bed_chk', 0) > 120:
        state['bed_chk'] = time.time()
        b_on, b_rh = dev_get('bed_hum', ['on', 'bh_rh'])
        if b_rh is not None:
            state['bed_rh'] = b_rh
            if b_on and b_rh >= PLAN['bed_rh_hi']:
                if dev_set('bed_hum', 'on', False, 'sypialnia nawilzacz pauza (RH %d)' % b_rh):
                    state['bed_pause'] = True
            elif not b_on and state.get('bed_pause') and b_rh <= PLAN['bed_rh_lo']:
                if dev_set('bed_hum', 'on', True, 'sypialnia nawilzacz wznowiony (RH %d)' % b_rh):
                    state['bed_pause'] = False
            elif b_on:
                state['bed_pause'] = False
                # moc według wilgotności: sucho = mocno, blisko celu = cicho (z zapasem, żeby nie przeskakiwał co chwilę)
                b_mode, = dev_get('bed_hum', ['bh_mode'])
                cur = b_mode if b_mode in (1, 2, 3) else 2
                want = cur
                if b_rh < 38 or (cur == 3 and b_rh < 42):
                    want = 3
                elif b_rh < 48 or (cur == 2 and b_rh < 51):
                    want = 2
                else:
                    want = 1
                if want != b_mode:
                    dev_set('bed_hum', 'bh_mode', want, 'sypialnia nawilzacz poziom %d (RH %d)' % (want, b_rh))
    if asleep:
        state['bed_pause'] = False

    # --- bezpiecznik wietrzenia ---
    if co2 is not None and t is not None:
        hist.append((time.time(), co2, t))
    while hist and time.time() - hist[0][0] > 400:
        hist.pop(0)
    if state.get('airing'):
        el = time.time() - state['airing_at']
        if el > PLAN['air_max_min'] * 60:
            stop_airing('limit czasu')  # działa też, gdy Qingping chwilowo nie odpowiada
        elif co2 is not None and t is not None and el > 180:
            ref = [h for h in hist if 100 <= time.time() - h[0] <= 260]
            if ref:
                d_co2 = co2 - ref[0][1]
                d_t = t - ref[0][2]
                # okno zamknięte: CO2 znowu rośnie albo temperatura wraca / przestała spadać
                if d_co2 >= 0 or d_t >= 0.1 or (d_co2 > -30 and d_t > -0.2):
                    stop_airing('koniec (CO2 %+d, T %+.1f)' % (d_co2, d_t))
    elif PLAN['airing'] and co2 is not None and t is not None:
        ref = [h for h in hist if 100 <= time.time() - h[0] <= 260]
        if ref:
            d_co2 = co2 - ref[0][1]
            d_t = t - ref[0][2]
            if d_co2 <= -PLAN['air_co2_drop'] or d_t <= -PLAN['air_t_drop']:
                start_airing(d_co2, d_t)

    # --- temperatura z Qingpinga do głowicy w salonie (co 5 min) ---
    if PLAN['ext_temp'] and t is not None and time.time() - state.get('ext_at', 0) > 300:
        state['ext_at'] = time.time()
        trv_ext('salon', t)


def start_airing(dco2, dt):
    hum_on, = dev_get('salon_hum', ['on'])
    pur_on, = dev_get('salon_pur', ['on'])
    bed_on, = dev_get('bed_hum', ['on'])
    state['airing'] = {'hum': bool(hum_on), 'pur': bool(pur_on), 'bed': bool(bed_on),
                       'trv': state.get('trv_salon'), 'trv_bed': state.get('trv_bed')}
    state['airing_at'] = time.time()
    try:
        with open('airing.json', 'w') as f:
            json.dump(state['airing'], f)
    except Exception:
        pass
    log('wietrzenie start (CO2 %+d, T %+.1f)' % (dco2, dt))
    if hum_on:
        dev_set('salon_hum', 'on', False)
    if pur_on:
        dev_set('salon_pur', 'on', False)
    if bed_on:
        dev_set('bed_hum', 'on', False)
    # grzejniki przykręcone, żeby nie grzały ulicy przy otwartym oknie
    trv_target('salon', 5)
    trv_target('bed', 4)


def stop_airing(why):
    a = state.get('airing') or {}
    state['airing'] = None
    try:
        import os
        os.remove('airing.json')
    except Exception:
        pass
    log('wietrzenie %s' % why)
    # przywróć tylko to, co chodziło przed wietrzeniem
    if a.get('hum'):
        dev_set('salon_hum', 'on', True)
    if a.get('pur'):
        dev_set('salon_pur', 'on', True)
    if a.get('bed'):
        dev_set('bed_hum', 'on', True)
    trv_target('salon', a.get('trv') or PLAN['salon_day'])
    if a.get('trv_bed'):
        trv_target('bed', a['trv_bed'])


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
    for name in ('qingping', 'salon_hum', 'salon_pur', 'bed_hum'):
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
    if not state.get('pur_model') and dev.get('salon_pur'):
        try:
            state['pur_model'] = (dev['salon_pur'].call('miIO.info', [], 1) or {}).get('model')
            log('oczyszczacz model %s' % state['pur_model'])
        except Exception as e:
            print('pur model err', e)
    try:
        with open('airing.json') as f:
            state['airing'] = json.load(f)
        stop_airing('przerwane restartem, przywracam')
    except OSError:
        pass


def run():
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
            if time.time() - last_sync >= 120:
                last_sync = time.time()
                try:
                    sync = gas({})
                    state['sync_fail'] = 0
                except Exception as e:
                    print('sync err', e)
                    # brak łączności z arkuszem przez ok. 10 min: zapisz przyczynę i zrestartuj (płytka sama wraca do pracy)
                    state['sync_fail'] = state.get('sync_fail', 0) + 1
                    # brak pamięci sam nie minie (rozdrobniona pamięć): restart od razu, a nie po 10 min
                    if state['sync_fail'] >= 5 or isinstance(e, MemoryError):
                        try:
                            with open('lasterr.txt', 'w') as f:
                                f.write('%s %s (wolna pamiec %d)' % (stamp(), repr(e)[:120], gc.mem_free()))
                        except Exception:
                            pass
                        machine.reset()
            if time.time() - last_rules >= 60:
                last_rules = time.time()
                q = dev_get('qingping', ['q_rh', 'q_pm25', 'q_t', 'q_co2'])
                state['q'] = q
                tick_rules(sync, q)
                save_state()
            scale_tick()
            if log_buf and (time.time() - last_report > 120 or len(log_buf) > 8):
                last_report = time.time()
                flush_log()
            if time.time() - state.get('hb', 0) > 1800:
                state['hb'] = time.time()
                q = state.get('q') or [None] * 4
                flush_log('ok RH %s T %s CO2 %s PM %s | sypialnia RH %s | %s | mem %d' % (q[0], q[2], q[3], q[1], state.get('bed_rh'), trv_brief(), gc.mem_free()))
            if time.time() - state.get('upd', time.time() - 600) > 10800:
                state['upd'] = time.time()
                check_update()
            if not network.WLAN(network.STA_IF).isconnected():
                machine.reset()
        except Exception as e:
            log('blad petli %s' % e)
        gc.collect()
        time.sleep(1)
