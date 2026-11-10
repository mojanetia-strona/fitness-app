# Start płytki: Wi-Fi, czas, aktualizacja programu z GitHuba, uruchomienie app.py.
import time, json, machine, network, gc

RAW = 'https://raw.githubusercontent.com/mojanetia-strona/fitness-app/main/dom/'
FILES = ('miio.py', 'app.py', 'main.py')


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
        if not remote or remote == local:
            return
        print('aktualizacja', local, '->', remote)
        for f in FILES:
            gc.collect()
            r = requests.get(RAW + f)
            if r.status_code != 200:
                r.close()
                return
            with open(f + '.new', 'w') as o:
                o.write(r.text)
            r.close()
        import os
        for f in FILES:
            os.rename(f + '.new', f)
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
