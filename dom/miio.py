# Lokalny protokół Xiaomi (miIO, UDP 54321), MIoT get/set_properties.
import socket, struct, time, json
try:
    import cryptolib
except ImportError:
    import ucryptolib as cryptolib
import hashlib

def _md5(b):
    return hashlib.md5(b).digest()

def _pad(b):
    n = 16 - len(b) % 16
    return b + bytes([n]) * n

def _unpad(b):
    if not b:
        return b
    n = b[-1]
    return b[:-n] if 0 < n <= 16 else b


class Device:
    def __init__(self, ip, token_hex, name=''):
        self.ip = ip
        self.name = name
        self.token = bytes.fromhex(token_hex)
        self.key = _md5(self.token)
        self.iv = _md5(self.key + self.token)
        self.did = None
        self.stamp = 0
        self.stamp_at = 0
        self.mid = int(time.time()) % 10000
        self.fail = 0

    def _sock(self, timeout=3):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        return s

    def _hello(self):
        s = self._sock()
        try:
            s.sendto(b'\x21\x31\x00\x20' + b'\xff' * 28, (self.ip, 54321))
            d = s.recv(1024)
        finally:
            s.close()
        self.did = struct.unpack('>I', d[8:12])[0]
        self.stamp = struct.unpack('>I', d[12:16])[0]
        self.stamp_at = time.time()

    def send(self, method, params):
        if self.did is None or time.time() - self.stamp_at > 120:
            self._hello()
        self.mid = (self.mid + 1) % 9999 + 1
        body = json.dumps({'id': self.mid, 'method': method, 'params': params}).encode()
        enc = cryptolib.aes(self.key, 2, self.iv).encrypt(_pad(body))
        stamp = self.stamp + int(time.time() - self.stamp_at) + 1
        head = struct.pack('>HHIII', 0x2131, 32 + len(enc), 0, self.did, stamp)
        chk = _md5(head + self.token + enc)
        s = self._sock()
        try:
            s.sendto(head + chk + enc, (self.ip, 54321))
            d = s.recv(4096)
        finally:
            s.close()
        raw = cryptolib.aes(self.key, 2, self.iv).decrypt(d[32:])
        raw = _unpad(raw).rstrip(b'\x00')
        r = json.loads(raw)
        if 'error' in r:
            raise OSError('miio %s: %s' % (self.name, r['error']))
        return r.get('result')

    def call(self, method, params, tries=3):
        last = None
        for i in range(tries):
            try:
                r = self.send(method, params)
                self.fail = 0
                return r
            except Exception as e:
                last = e
                self.did = None
                time.sleep(0.5)
        self.fail += 1
        raise last

    def get(self, props):
        """props: lista (siid, piid). Zwraca listę wartości (None przy błędzie)."""
        did = str(self.did or 'x')
        res = self.call('get_properties', [{'did': did, 'siid': s, 'piid': p} for s, p in props])
        out = []
        for (s, p) in props:
            v = None
            for x in res or []:
                if x.get('siid') == s and x.get('piid') == p and x.get('code', 0) == 0:
                    v = x.get('value')
            out.append(v)
        return out

    def set(self, siid, piid, value):
        did = str(self.did or 'x')
        res = self.call('set_properties', [{'did': did, 'siid': siid, 'piid': piid, 'value': value}])
        ok = bool(res) and res[0].get('code', -1) == 0
        if not ok:
            raise OSError('set %s %d.%d: %s' % (self.name, siid, piid, res))
        return True
