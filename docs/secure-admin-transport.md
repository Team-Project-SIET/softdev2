# OpenTTD 15.3 secure Admin transport

`CONTEXT.md` remains the architecture authority. This controlled implementation
supports **X25519_AuthorizedKey only**. No real OpenTTD world or live AdminPort
was used. PAKE is not advertised or implemented; Admin excludes key-exchange-only.
Existing 13.4 observer/proof behavior remains historical regression support.

## Connection and state

`SecureAdminSession.connect_secure(..., key=AuthorizedKey.generate())` is the
explicit future production connection entry point. `authenticate(name, version)`
then performs the handshake under a maximum **10-second** deadline:

CONNECTED → AUTH_JOIN_SENT → AUTH_REQUEST_RECEIVED → AUTH_RESPONSE_SENT →
ENCRYPTION_ENABLED → PROTOCOL_RECEIVED → WELCOME_RECEIVED → ACTIVE → CLOSED.

Application writes and receives require ACTIVE. Unexpected packets, unsupported
methods, malformed framing/nonces, invalid public keys, and failed MACs close the
stream. AuthTimeout, AuthDisconnected, AuthRejected, and AdminProtocolError
separate deadline, I/O/EOF, server rejection, and protocol/crypto failure.
No reconnect, retry, method fallback, or insecure downgrade occurs.
`GameScriptSession` accepts supplied controlled streams but cannot open TCP;
its `connect` directs callers to the secure entry point.

| Packet | ID | Body |
| --- | --- | --- |
| ADMIN_JOIN_SECURE | 9 | NUL-terminated name, version, uint16 LE supported-method mask 4 |
| SERVER_AUTH_REQUEST | 128 | uint8 method 2, server public key 32 bytes, exchange nonce 24 bytes |
| ADMIN_AUTH_RESPONSE | 10 | client public key 32 bytes, MAC 16 bytes, encrypted random message 8 bytes |
| SERVER_ENABLE_ENCRYPTION | 129 | stream nonce 24 bytes |
| SERVER_PROTOCOL | 103 | Encrypted; existing parser, required Admin protocol version 3 |
| SERVER_WELCOME | 104 | Encrypted; existing Welcome parser |

Client name/version limits are 24/32 UTF-8 bytes excluding their NUL terminators.
Encryption becomes active only after the correctly ordered, validated enable
packet. Coalesced and fragmented reads preserve this exact boundary. Protocol and
Welcome are never processed as plaintext after enable.

## Cryptography and framing

The pinned `pymonocypher==4.0.3.2` native binding exposes the exact Monocypher
interfaces used by OpenTTD. Compatibility was checked against OpenTTD 15.3's
bundled **Monocypher 4.0.2**, rather than assumed from algorithm names.

X25519 uses 32-byte secret/public keys and rejects an all-zero shared secret.
BLAKE2b with a 64-byte output hashes, in order, shared secret, server public key,
client public key, and empty extra payload. First 32 bytes are client→server;
second 32 are server→client.

Authentication uses `crypto_aead_lock`: exchange nonce 24 bytes, client→server
key, **client public key as the 32-byte additional authenticated data**, and a
cryptographically random 8-byte message. Production uses `secrets.token_bytes`;
controlled tests may inject public deterministic test randomness.

Packet encryption uses two persistent `crypto_aead_init_x` contexts and
`crypto_aead_write/read` with **empty additional authenticated data**. Monocypher
rekeys after each successful packet. Contexts are not reinitialized per packet.
The readable uint16 LE total length includes the 16-byte MAC. Wire layout is:

`length[2] | MAC[16] | encrypted(packet_type[1] + payload)`

The length is neither encrypted nor passed as AEAD data. The existing 32767-byte
frame bound includes the MAC. Authentication failure invalidates the context and
session. Quit is encrypted when closing an active session.

`AdminFrameDecoder.feed_wire_frames` is the shared bounded length framer;
`PacketCipher` transforms those complete frames. `AdminStream` keeps ownership,
write policy, drain, and cleanup. `SecureAdminSession.receive` exposes decrypted
Admin frames to the existing `GameScriptTransport`. The raw reader belongs only
to the secure session. P04's AdminSession allowlist remains unchanged: it still
forbids GameScript and gameplay packets. No planner/executor is migrated.

## Credentials and isolated config

Generate/inject a proof-only AuthorizedKey in memory. Its repr excludes private
bytes. Public evidence may use `public_hex` and `public_sha256`; never serialize
internal key fields or retain private keys in receipts, logs, or JSON artifacts.
No private-key file is created by this implementation. Keys and cipher references
are dropped on close. Python/native bindings may retain memory copies; this is
not a locked-memory or guaranteed-erasure facility.

`AdminSettings(..., authorized_public_key_hex=key.public_hex)` writes only that lowercase
64-character public key to `[admin_authorized_keys]` in the isolated `private.cfg`.
The owned file is exclusively created with mode 0600. No normal OpenTTD profile
is modified. `allow_insecure_admin_login = false` remains in the generated config.
Only mask 4 is advertised, so the stored Admin password is not used by this client.

## Controlled reference evidence

`tests/reference/openttd_15_3_crypto_vectors.c` mirrors 15.3 key exchange,
authentication AEAD and packet encryption calls. It was compiled against the
unmodified tagged Monocypher source, producing the checked-in public test fixture
`tests/fixtures/openttd_15_3_crypto_vectors.json`. Ordinary tests need no compiler,
network, engine process, or live server. All seed values in the generator/tests
are public fixtures and must never be used for a real proof.

Reference source SHA-256:

- monocypher.cpp: `0f93173bc6ea75b37b812f1c15976775d32918f3a3eacc2626bac08c2b64968d`
- monocypher.h: `f78bb31255cfb7beba66afd2137f5194c8a025cf40488b6cc1e295234d43f374`

To reproduce, place those tagged files in a source directory and compile:

```sh
cc -x c -I SOURCE tests/reference/openttd_15_3_crypto_vectors.c SOURCE/monocypher.cpp -o vectors
./vectors
```

Tests compare public-key derivation, shared agreement, 64-byte derivation order,
authentication MAC/ciphertext and three sequential packets in **each** direction
with that native reference. They also exercise a server-side authorization model,
fragmented/coalesced secure handshake, encrypted Protocol/Welcome, encrypted
GameScript subscription, three correlated ACKs, damaged MAC/ciphertext, opposite
keys, plaintext after enable, invalid transitions, timeout, disconnect and cleanup.
This is controlled compatibility evidence; a native server ACK is not yet proved.

## Base graphics and next proof

Read-only inspection of the external installation found original DOS/Windows
`.obg` descriptors, `openttd.grf`, `orig_extra.grf`, fonts/title data and NoSound /
NoMusic descriptors. It contains no complete usable graphics set: the five
original graphics GRFs for each original set are absent. No OpenGFX archive/set
was found. A complete verified graphics set must be staged into the isolated
workspace later; nothing was downloaded or staged here.

The next harness must generate its ephemeral key, authorize the matching public
key, stage complete base graphics and the no-mutation API-15 bridge, reserve local
endpoints, perform the secure login, capture the correlated receipt, and own
shutdown/reaping. The [one-launch harness preparation](openttd-15.3-real-ack-proof.md)
now supplies these controlled interfaces and stages official OpenGFX 8.0.
Real launch/live connection remains separately authorized.

## Exact 15.3 authority

- [Admin handshake, 10-second deadline and encryption installation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_admin.cpp)
- [Admin packet layouts](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/core/tcp_admin.h)
- [Authentication methods](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_crypto.h)
- [Cryptographic field sizes](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_crypto_internal.h)
- [Key derivation, AEAD calls and authorization](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_crypto.cpp)
- [Packet encryption boundary](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/core/packet.cpp)
- [Reference authentication and encryption tests](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/tests/test_network_crypto.cpp)
- [Admin network documentation](https://github.com/OpenTTD/OpenTTD/blob/15.3/docs/admin_network.md)
- [Bundled Monocypher implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/3rdparty/monocypher/monocypher.cpp)
- [Private config authorized-key list](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/settings.cpp)
- [Python binding's one-shot and incremental AEAD calls](https://github.com/jetperch/pymonocypher/blob/v4.0.3.2/c_monocypher.pyx)
