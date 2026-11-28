# Płytka dyfuzora zapachowego (ESP32-C3 Super Mini przy dyfuzorze TurboTronic TT-LX1).
# Udaje pilota: nadajnik podczerwieni na GPIO4 wysyła kody NEC. Niczego nie decyduje:
# polecenia przychodzą z głównej płytki (UDP 8091), stan zgłasza co 60 s do głównej płytki (UDP 8090).
import time, socket, machine, network, gc, json

VERSION = 'aroma-4'
MAIN = ('192.168.100.35', 8090)
PORT = 8091
ROOMS = {'689dd27931e4': 's', '689dd2793214': 'b'}  # MAC płytki -> pokój (s = salon, b = sypialnia)
# kody pilota (NEC, adres 0x00), nagrane 28.11.2026
ONOFF, LIGHT, AROMA = 0x45, 0x46, 0x47
LEVELS = {1: 0x07, 2: 0x15, 3: 0x09, 4: 0x16, 5: 0x19, 6: 0x0D}
TIMERS = {1: 0x08, 4: 0x1C, 8: 0x5A}
ST = {'on': False, 'lvl': 1}
RMT = [None]


def tx(cmd, times=1):
    import esp32
    from machine import Pin
    if RMT[0] is None:
        RMT[0] = esp32.RMT(0, pin=Pin(4), clock_div=80, tx_carrier=(38000, 33, 1))
    v = (0xff << 8) | (cmd << 16) | ((~cmd & 0xff) << 24)  # adres 0x00, jego negacja 0xff
    d = [9000, 4500]
    for i in range(32):
        d += [562, 1687 if (v >> i) & 1 else 562]
    d.append(562)
    for k in range(times):
        RMT[0].write_pulses(d, 1)
        RMT[0].wait_done(timeout=200)
        time.sleep_ms(60)


def save():
    try:
        with open('aroma_state.json', 'w') as f:
            json.dump(ST, f)
    except Exception:
        pass


def load():
    try:
        with open('aroma_state.json') as f:
            ST.update(json.load(f))
    except Exception:
        pass
    try:
        if machine.reset_cause() == machine.PWRON_RESET:
            ST['on'] = False  # brak prądu: dyfuzor też się wyłączył
    except Exception:
        pass


def handle(c):
    """c: {'c': 'on'|'off'|'level'|'light'|'aroma'|'timer'|'raw', 'l': poziom, 'v': wartość}"""
    k = c.get('c')
    if k == 'on':
        if not ST['on']:
            tx(ONOFF)  # ON/OFF to przełącznik: wysyłamy tylko, gdy wg nas jest wyłączony
            ST['on'] = True
            time.sleep_ms(1500)
        lvl = c.get('l') or ST.get('lvl') or 1
        if lvl in LEVELS:
            tx(LEVELS[lvl], 2)  # poziom można powtórzyć bez szkody
            ST['lvl'] = lvl
    elif k == 'off':
        if ST['on']:
            tx(ONOFF)
            ST['on'] = False
    elif k == 'level' and c.get('l') in LEVELS:
        tx(LEVELS[c['l']], 2)
        ST['lvl'] = c['l']
    elif k == 'light':
        tx(LIGHT)
    elif k == 'aroma':
        tx(AROMA)
    elif k == 'timer' and c.get('v') in TIMERS:
        tx(TIMERS[c['v']])
    elif k == 'raw':
        tx(int(c.get('v', 0)))
    elif k == 'sync':
        ST['on'] = bool(c.get('v'))  # ręczna korekta stanu (np. po użyciu pilota)
    save()


def run(wd=None):
    if wd is None:
        try:
            wd = machine.WDT(timeout=120000)
        except Exception:
            wd = None
    w = network.WLAN(network.STA_IF)
    mac = ''.join('%02x' % b for b in w.config('mac'))
    room = ROOMS.get(mac, '?')
    load()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', PORT))
    s.setblocking(False)
    boot = time.time()
    hb = 0
    lost = [0]
    last = [None]
    print('aroma start', VERSION, room, mac)

    def report(tag, extra=None):
        d = {'r': room, 'v': VERSION, 'on': ST['on'], 'lvl': ST['lvl']}
        try:
            d['rssi'] = w.status('rssi')
        except Exception:
            pass
        if extra:
            d.update(extra)
        try:
            s.sendto(tag + json.dumps(d).encode(), MAIN)
        except Exception as e:
            print('send', e)

    while True:
        if wd:
            wd.feed()
        try:
            p, addr = s.recvfrom(300)
        except Exception:
            p = None
        if p and p[:2] == b'AC' and addr[0] == MAIN[0]:
            try:
                c = json.loads(p[2:])
                if c.get('id') is None or c.get('id') != last[0]:  # powtórka tego samego polecenia (słaby Wi-Fi): tylko potwierdź
                    last[0] = c.get('id')
                    handle(c)
                report(b'AA', {'id': c.get('id'), 'c': c.get('c')})
            except Exception as e:
                print('cmd', e)
        if time.time() - hb > 30:
            hb = time.time()
            report(b'AH')
            gc.collect()
        if not w.isconnected():
            # sypialnia ma słaby zasięg: krótkie zerwanie Wi-Fi nie restartuje płytki, tylko łączy ponownie
            if not lost[0]:
                lost[0] = time.time()
                print('wifi zerwane, lacze ponownie')
                try:
                    w.connect()
                except Exception:
                    pass
            elif time.time() - lost[0] > 90:
                machine.reset()
        elif lost[0]:
            lost[0] = 0
            hb = 0  # od razu zgłoś się głównej płytce
            print('wifi wrocilo')
        if time.time() - boot > 6 * 3600:
            machine.reset()  # co 6 h restart (przy starcie sprawdza nową wersję)
        time.sleep_ms(50)
