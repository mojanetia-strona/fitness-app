# Start płytki: Wi-Fi, czas, aktualizacja programu z GitHuba, uruchomienie app.py.
import time, json, machine, network, gc

RAW = 'https://raw.githubusercontent.com/mojanetia-strona/fitness-app/main/dom/'
FILES = ('miio.mpy', 'app.mpy', 'main.py')  # .mpy = skompilowane, mniej pamięci


def wifi(cfg):
    w = network.WLAN(network.STA_IF)
    w.active(True)
    if not w.isconnected():
        w.connect(cfg['wifi_ssid'], cfg['wifi_pass'])
        for i in range(40):
            if w.isconnected():
                break
            time.sleep(0.5)
    if w.isconnected():
        try:
            network.ipconfig(dns='8.8.8.8')  # DNS routera bywa zawodny dla Google
        except Exception:
            try:
                ip, mask, gw, dns = w.ifconfig()
                w.ifconfig((ip, mask, gw, '8.8.8.8'))
            except Exception:
                pass
    print('wifi', w.isconnected(), w.ifconfig()[0] if w.isconnected() else '')
    return w.isconnected()


def set_time():
    import ntptime
    for i in range(5):
        try:
            ntptime.settime()
            return True
        except Exception:
            time.sleep(2)
    return False


def update():
    try:
        import requests
    except ImportError:
        import urequests as requests
    try:
        local = open('version.txt').read().strip()
    except OSError:
        local = ''
    try:
        gc.collect()
        r = requests.get(RAW + 'version.txt')
        remote = r.text.strip() if r.status_code == 200 else ''
        r.close()
        def ver(s):
            try:
                return tuple(int(x) for x in s.split('.'))
            except Exception:
                return (0,)
        if not remote or ver(remote) <= ver(local):
            return  # tylko nowsza wersja (raw GitHub bywa chwilę opóźniony)
        print('aktualizacja', local, '->', remote)
        for f in FILES:
            gc.collect()
            r = requests.get(RAW + f)
            if r.status_code != 200:
                r.close()
                return
            with open(f + '.new', 'wb') as o:
                while True:
                    b = r.raw.read(1024)  # po kawałku: cały plik naraz nie mieści się w pamięci
                    if not b:
                        break
                    o.write(b)
            r.close()
        import os
        for f in FILES:
            os.rename(f + '.new', f)
        for f in ('app.py', 'miio.py'):
            try:
                os.remove(f)  # stare źródła miałyby pierwszeństwo przed .mpy
            except OSError:
                pass
        with open('version.txt', 'w') as o:
            o.write(remote)
        machine.reset()
    except Exception as e:
        print('update err', e)


def main():
    try:
        with open('config.json') as f:
            cfg = json.load(f)
    except Exception as e:
        print('brak config.json', e)
        return
    if not cfg.get('wifi_pass'):
        print('uzupelnij config.json')
        return
    # Bluetooth MUSI wystartować przed Wi-Fi i HTTPS, inaczej brakuje mu pamięci
    try:
        import bluetooth
        bluetooth.BLE().active(True)
    except Exception as e:
        print('ble init', e)
    if not wifi(cfg):
        time.sleep(30)
        machine.reset()
    set_time()
    if cfg.get('auto_update', True):
        update()
    import app
    app.run()


try:
    main()
except KeyboardInterrupt:
    print('zatrzymane')
except Exception as e:
    print('blad startu', e)
    time.sleep(60)
    machine.reset()
