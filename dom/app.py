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

VERSION = '1.0.0'

# ---------- ustawienia domyślne (nadpisywane przez config.json -> "plan") ----------
PLAN = {
    'salon_day': 22.0,      # salon w dzień
    'salon_night': 18.0,    # salon w nocy (po odłożeniu telefonu)
    'bed_day': 4.0,         # sypialnia w dzień (4 = praktycznie wyłączona)
    'bed_night': 4.0,       # sypialnia w nocy
    'bed_morning': 20.0,    # sypialnia przed pobudką
    'bed_pre_min': 30,      # ile minut przed pobudką grzać sypialnię
    'bed_after_min': 30,    # ile minut po zdjęciu telefonu wyłączyć sypialnię
    'salon_pre_min': 90,    # ile minut przed pobudką włączyć salon (nawilżacz, oczyszczacz)
    'salon_heat_pre_min': 60,  # ile minut przed pobudką grzać salon na dzień
    'wake_wd': 420,         # domyślna pobudka w tygodniu (min od północy), gdy brak danych z telefonu
    'wake_we': 540,         # domyślna pobudka w weekend
    'night_from': 1260,     # odłożenie telefonu po 21:00 = noc
    'rh_low': 42,           # salon: poniżej tej wilgotności (Qingping) nawilżacz na mocno
    'rh_ok': 48,            # salon: od tej wilgotności nawilżacz wraca do stałej wilgotności
    'rh_target': 50,        # cel stałej wilgotności w salonie
    'air_co2_drop': 100,    # wietrzenie: spadek CO2 w 3 min (ppm)
    'air_t_drop': 0.6,      # wietrzenie: spadek temperatury w 3 min (°C)
    'air_max_min': 30,      # wietrzenie: najdłużej tyle minut pauzy
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
def gas(params):
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
    r = requests.get(url)
    try:
        return r.json()
    finally:
        r.close()


def flush_log(extra=''):
    if not log_buf and not extra:
        return None
    txt = ' | '.join(log_buf)
    if extra:
        txt = (extra + ' | ' + txt) if txt else extra
    try:
        res = gas({'log': txt[:480]})
        log_buf.clear()
        return res
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
            r = requests.post('http://%s/rpc' % gw, data=body, headers={'Content-Type': 'application/json'})
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
    'bh_mode': (2, 8),                               # sypialnia deerma jsq2w
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
scale = {'last_kg': None, 'last_sent': 0, 'pending': None, 'pending_at': 0}


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


def ble_start():
    try:
        import bluetooth
        b = bluetooth.BLE()
        b.active(True)
        b.irq(ble_irq)
        b.gap_scan(0, 60000, 30000, False)
        log('bluetooth ok')
        return b
    except Exception as e:
        log('bluetooth blad %s' % e)
        return None


def scale_tick():
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
        log('waga %.1f kg zapisana' % kg)
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
    if not (m >= PLAN['night_from'] or m < 240):
        return False
    return local_minutes_since(ph['t']) < 14 * 60


def wake_min(sync, weekend):
    w = (sync or {}).get('wake') or {}
    v = w.get('we' if weekend else 'wd')
    if v is None:
        v = PLAN['wake_we' if weekend else 'wake_wd']
    return v


def day_key():
    tm = now_local()
    return '%04d%02d%02d' % (tm[0], tm[1], tm[2])


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
    asleep = phone_asleep(ph)
    was = state.get('asleep')
    if was and not asleep and m < 240:
        asleep = True  # zerknięcie na telefon w nocy to jeszcze nie pobudka
    state['asleep'] = asleep

    # --- zasypianie: telefon odłożony na noc ---
    if asleep and not was:
        log('noc: telefon odlozony')
        dev_set('bed_hum', 'on', False, 'sypialnia nawilzacz off')
        dev_set('salon_hum', 'on', False, 'salon nawilzacz off')
        dev_set('salon_pur', 'on', False, 'salon oczyszczacz off')
        trv_target('salon', PLAN['salon_night'])
        trv_target('bed', PLAN['bed_night'])
        state['night_on'] = True

    # --- rano, przed pobudką (tylko gdy telefon nadal leży = jestem w domu) ---
    if asleep and m < 720:
        wm = wake_min(sync, weekend)
        if m >= wm - PLAN['salon_pre_min'] and once('salon_morning'):
            dev_set('salon_hum', 'on', True, 'rano: salon nawilzacz on')
            dev_set('salon_pur', 'on', True, 'rano: salon oczyszczacz on')
        if m >= wm - PLAN['salon_heat_pre_min'] and once('salon_heat'):
            trv_target('salon', PLAN['salon_day'])
        if m >= wm - PLAN['bed_pre_min'] and once('bed_heat'):
            trv_target('bed', PLAN['bed_morning'])

    # --- wstałem: telefon zdjęty rano ---
    if was and not asleep and ph and ph.get('e') == 'up':
        log('rano: telefon zdjety')
        trv_target('salon', PLAN['salon_day'])
        state['bed_off_at'] = time.time() + PLAN['bed_after_min'] * 60
        state['night_on'] = False
    if state.get('bed_off_at') and time.time() >= state['bed_off_at']:
        state['bed_off_at'] = None
        trv_target('bed', PLAN['bed_day'])

    # --- salon: moc nawilżacza według Qingpinga ---
    if rh is not None and not state.get('airing'):
        on, mode = dev_get('salon_hum', ['on', 'sh_mode'])
        if on:
            if rh < PLAN['rh_low'] and mode != 2:
                dev_set('salon_hum', 'sh_mode', 2, 'salon nawilzacz mocno (RH %d)' % rh)
            elif rh >= PLAN['rh_ok'] and mode == 2:
                if dev_set('salon_hum', 'sh_mode', 0, 'salon nawilzacz stala wilgotnosc (RH %d)' % rh):
                    dev_set('salon_hum', 'sh_target', PLAN['rh_target'])

    # --- bezpiecznik wietrzenia ---
    if co2 is not None and t is not None:
        hist.append((time.time(), co2, t))
        while hist and time.time() - hist[0][0] > 400:
            hist.pop(0)
        old = [h for h in hist if 150 <= time.time() - h[0] <= 260]
        if old:
            o = old[0]
            dco2 = co2 - o[1]
            dt = t - o[2]
            if not state.get('airing'):
                if dco2 <= -PLAN['air_co2_drop'] or dt <= -PLAN['air_t_drop']:
                    start_airing(dco2, dt)
            else:
                calm = dco2 > -30 and dt > -0.2
                long = time.time() - state['airing_at'] > PLAN['air_max_min'] * 60
                if (calm and time.time() - state['airing_at'] > 300) or long:
                    stop_airing('koniec' if calm else 'limit czasu')

    # --- temperatura z Qingpinga do głowicy w salonie (co 5 min) ---
    if PLAN['ext_temp'] and t is not None and time.time() - state.get('ext_at', 0) > 300:
        state['ext_at'] = time.time()
        trv_ext('salon', t)


def start_airing(dco2, dt):
    hum_on, = dev_get('salon_hum', ['on'])
    pur_on, = dev_get('salon_pur', ['on'])
    state['airing'] = {'hum': bool(hum_on), 'pur': bool(pur_on), 'trv': state.get('trv_salon')}
    state['airing_at'] = time.time()
    log('wietrzenie start (CO2 %+d, T %+.1f)' % (dco2, dt))
    if hum_on:
        dev_set('salon_hum', 'on', False)
    if pur_on:
        dev_set('salon_pur', 'on', False)
    trv_target('salon', 5)


def stop_airing(why):
    a = state.get('airing') or {}
    state['airing'] = None
    log('wietrzenie %s' % why)
    # przywróć tylko to, co chodziło, i tylko jeśli nikt w międzyczasie nie przestawił (np. wyjście z domu)
    if a.get('hum'):
        dev_set('salon_hum', 'on', True)
    if a.get('pur'):
        dev_set('salon_pur', 'on', True)
    trv_target('salon', a.get('trv') or PLAN['salon_day'])


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
    log('start v%s, urzadzenia: %s' % (VERSION, ','.join(sorted(dev.keys()))))


def run():
    setup()
    ble_start()
    sync = None
    last_sync = 0
    last_rules = 0
    last_report = time.time()
    while True:
        try:
            if time.time() - last_sync >= 60:
                last_sync = time.time()
                try:
                    sync = gas({})
                except Exception as e:
                    print('sync err', e)
            if time.time() - last_rules >= 60:
                last_rules = time.time()
                q = dev_get('qingping', ['q_rh', 'q_pm25', 'q_t', 'q_co2'])
                state['q'] = q
                tick_rules(sync, q)
            scale_tick()
            if log_buf and (time.time() - last_report > 120 or len(log_buf) > 8):
                last_report = time.time()
                flush_log()
            if time.time() - state.get('hb', 0) > 3600:
                state['hb'] = time.time()
                q = state.get('q') or [None] * 4
                flush_log('ok RH %s T %s CO2 %s PM %s mem %d' % (q[0], q[2], q[3], q[1], gc.mem_free()))
            if not network.WLAN(network.STA_IF).isconnected():
                machine.reset()
        except Exception as e:
            log('blad petli %s' % e)
        gc.collect()
        time.sleep(1)
