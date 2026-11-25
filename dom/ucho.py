# Płytka-ucho w łazience (zapasowe ESP32, nie S3). Tylko słucha Bluetootha z bliska i od razu przekazuje
# do głównej płytki (192.168.100.35, UDP 8090) wiadomości czujnika ruchu w łazience i wagi.
# Niczym nie steruje i niczego nie decyduje: wszystkie reguły zostają w głównej płytce.
import time, socket, machine, network, gc, bluetooth

VERSION = 'ucho-1'
MAIN = ('192.168.100.35', 8090)
MOT_MAC = bytes.fromhex('740b12945338')  # Shelly BLU Motion „Czujnik Ruchu Łazienka”
Q = []
LAST = {}


def irq(event, data):
    if event != 5:  # tylko wyniki skanowania
        return
    try:
        addr = bytes(data[1])
        adv = bytes(data[4])
        if addr != MOT_MAC and b'\x16\x1d\x18' not in adv:  # czujnik ruchu albo waga (0x181D)
            return
        t = time.ticks_ms()
        prev = LAST.get(addr)
        if prev and prev[0] == adv and time.ticks_diff(t, prev[1]) < 1500:
            return  # ta sama wiadomość powtórzona przez czujnik
        LAST[addr] = (adv, t)
        if len(Q) < 20:
            Q.append(b'U1' + addr + adv)
    except Exception:
        pass


def run():
    wd = machine.WDT(timeout=120000)
    w = network.WLAN(network.STA_IF)
    b = bluetooth.BLE()
    b.active(True)
    b.irq(irq)
    b.gap_scan(0, 100000, 90000, True)  # prawie ciągłe słuchanie, bez przerw na arkusz
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    hb = 0
    boot = time.time()
    print('ucho start', VERSION)
    while True:
        wd.feed()
        while Q:
            p = Q.pop(0)
            try:
                s.sendto(p, MAIN)
            except Exception as e:
                print('send', e)
        if time.time() - hb > 60:
            hb = time.time()
            try:
                s.sendto(b'UH' + VERSION.encode() + b' ' + str(w.status('rssi')).encode(), MAIN)
            except Exception:
                pass
            gc.collect()
        if not w.isconnected() or time.time() - boot > 6 * 3600:
            machine.reset()  # zgubione Wi-Fi albo co 6 h: restart (przy starcie sprawdza nową wersję)
        time.sleep_ms(20)
