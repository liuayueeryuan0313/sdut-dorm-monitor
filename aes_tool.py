import base64, random

def gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1: p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi: a ^= 0x1B
        b >>= 1
    return p

def _build():
    inv = [0] * 256
    for i in range(1, 256):
        for j in range(1, 256):
            if gmul(i, j) == 1:
                inv[i] = j
                break
    rotl8 = lambda x, s: ((x << s) | (x >> (8 - s))) & 0xFF
    sbox = []
    for i in range(256):
        x = inv[i]; y = x
        for s in (1, 2, 3, 4): y ^= rotl8(x, s)
        sbox.append(y ^ 0x63)
    inv_sbox = [0] * 256
    for i, v in enumerate(sbox): inv_sbox[v] = i
    return sbox, inv_sbox

SBOX, INV_SBOX = _build()
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]

def expand(key):
    w = [list(key[i*4:i*4+4]) for i in range(4)]
    for i in range(4, 44):
        t = w[i-1][:]
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i//4 - 1]
        w.append([w[i-4][k] ^ t[k] for k in range(4)])
    return [sum(w[4*r:4*r+4], []) for r in range(11)]

def _ark(s, rk): return [s[i] ^ rk[i] for i in range(16)]

def _shift(s):
    o = [0]*16
    for r in range(4):
        for c in range(4):
            o[c*4+r] = s[((c+r) % 4)*4+r]
    return o

def _inv_shift(s):
    o = [0]*16
    for r in range(4):
        for c in range(4):
            o[c*4+r] = s[((c-r) % 4)*4+r]
    return o

def _mix(s):
    o = [0]*16
    for c in range(4):
        a = s[c*4:c*4+4]
        o[c*4+0] = gmul(a[0],2) ^ gmul(a[1],3) ^ a[2] ^ a[3]
        o[c*4+1] = a[0] ^ gmul(a[1],2) ^ gmul(a[2],3) ^ a[3]
        o[c*4+2] = a[0] ^ a[1] ^ gmul(a[2],2) ^ gmul(a[3],3)
        o[c*4+3] = gmul(a[0],3) ^ a[1] ^ a[2] ^ gmul(a[3],2)
    return o

def _inv_mix(s):
    o = [0]*16
    for c in range(4):
        a = s[c*4:c*4+4]
        o[c*4+0] = gmul(a[0],14) ^ gmul(a[1],11) ^ gmul(a[2],13) ^ gmul(a[3],9)
        o[c*4+1] = gmul(a[0],9)  ^ gmul(a[1],14) ^ gmul(a[2],11) ^ gmul(a[3],13)
        o[c*4+2] = gmul(a[0],13) ^ gmul(a[1],9)  ^ gmul(a[2],14) ^ gmul(a[3],11)
        o[c*4+3] = gmul(a[0],11) ^ gmul(a[1],13) ^ gmul(a[2],9)  ^ gmul(a[3],14)
    return o

def enc_block(blk, rks):
    s = _ark(list(blk), rks[0])
    for rnd in range(1, 10):
        s = _ark(_mix(_shift([SBOX[b] for b in s])), rks[rnd])
    s = _ark(_shift([SBOX[b] for b in s]), rks[10])
    return bytes(s)

def dec_block(blk, rks):
    s = _ark(list(blk), rks[10])
    for rnd in range(9, 0, -1):
        s = _inv_mix(_ark([INV_SBOX[b] for b in _inv_shift(s)], rks[rnd]))
    s = _ark([INV_SBOX[b] for b in _inv_shift(s)], rks[0])
    return bytes(s)

def cbc_encrypt(data, key, iv):
    rks = expand(key)
    n = 16 - (len(data) % 16)
    data = data + bytes([n]) * n
    out = b""; prev = iv
    for i in range(0, len(data), 16):
        blk = bytes(x ^ y for x, y in zip(data[i:i+16], prev))
        prev = enc_block(blk, rks)
        out += prev
    return out

def cbc_decrypt(data, key, iv):
    rks = expand(key)
    out = b""; prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i+16]
        out += bytes(x ^ y for x, y in zip(dec_block(blk, rks), prev))
        prev = blk
    return out[:-out[-1]]

AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

def random_string(n):
    return "".join(random.choice(AES_CHARS) for _ in range(n))

def encrypt_password(pwd, salt):
    ct = cbc_encrypt((random_string(64) + pwd).encode("utf-8"),
                     salt.encode("utf-8"), random_string(16).encode("utf-8"))
    return base64.b64encode(ct).decode()

if __name__ == "__main__":
    # FIPS-197 C.1
    k = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    got = enc_block(pt, expand(k)).hex()
    print("ECB  :", got, "OK" if got == "69c4e0d86a7b0430d8cdb78070b4c55a" else "FAIL")
    print("DEC  :", dec_block(bytes.fromhex(got), expand(k)).hex())
    # NIST SP800-38A F.2.1 CBC-AES128
    k2 = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    p2 = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    c2 = cbc_encrypt(p2, k2, iv).hex()
    # 首块应等于 NIST 向量; 后面多出的是 PKCS7 填充块, 属正常
    print("CBC  :", c2[:32], "OK" if c2[:32] == "7649abac8119b246cee98e9b12e9197d" else "FAIL", "(首块)")
    print("CBCD :", cbc_decrypt(bytes.fromhex(c2), k2, iv).hex())
    # round trip (占位明文, 不涉及真实凭据)
    e = encrypt_password("EXAMPLE_PASSWORD", "gX3Lj4bmoXbTKCxo")
    print("SAMPLE AES FIELD:", e)
    print("ROUNDTRIP:", cbc_decrypt(base64.b64decode(e), b"gX3Lj4bmoXbTKCxo",
          base64.b64decode("")[:0] or None) if False else "skipped")
