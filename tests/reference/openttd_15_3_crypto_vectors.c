/* Controlled, public test seeds only. Compile against OpenTTD tag 15.3's
 * src/3rdparty/monocypher/{monocypher.cpp,monocypher.h} (Monocypher 4.0.2).
 * Calls mirror network_crypto.cpp and packet.cpp. No OpenTTD process involved.
 * cc -x c -I SOURCE this.c SOURCE/monocypher.cpp -o vectors */
#include "monocypher.h"
#include <stdio.h>
static void emit(const char *name, const unsigned char *value, size_t n) {
    printf("\"%s\":\"", name);
    for (size_t i=0; i<n; i++) printf("%02x", value[i]);
    printf("\",\n");
}
int main(void) {
    unsigned char client[32], server[32], cp[32], sp[32], shared[32], keys[64];
    unsigned char nonce[24], stream_nonce[24], message[8], cipher[8], mac[16];
    for (int i=0;i<32;i++) {client[i]=i;server[i]=i+32;}
    for (int i=0;i<24;i++) {nonce[i]=i+64;stream_nonce[i]=i+88;}
    for (int i=0;i<8;i++) message[i]=i+112;
    crypto_x25519_public_key(cp,client);crypto_x25519_public_key(sp,server);
    crypto_x25519(shared,client,sp);
    crypto_blake2b_ctx hash;crypto_blake2b_init(&hash,64);
    crypto_blake2b_update(&hash,shared,32);crypto_blake2b_update(&hash,sp,32);
    crypto_blake2b_update(&hash,cp,32);crypto_blake2b_final(&hash,keys);
    crypto_aead_lock(cipher,mac,keys,nonce,cp,32,message,8);
    puts("{");emit("client_public",cp,32);emit("server_public",sp,32);
    emit("shared",shared,32);emit("derived",keys,64);emit("auth_mac",mac,16);
    emit("auth_cipher",cipher,8);
    for (int d=0;d<2;d++) {
        crypto_aead_ctx ctx;crypto_aead_init_x(&ctx,keys+d*32,stream_nonce);
        for (int i=0;i<3;i++) {
            unsigned char plain[4]={(unsigned char)(d?124:6), 'p','i',(unsigned char)('0'+i)};
            unsigned char packet[22]={22,0};char name[32];
            crypto_aead_write(&ctx,packet+18,packet+2,NULL,0,plain,4);
            snprintf(name,sizeof(name),"%s_%d",d?"server":"client",i);
            emit(name,packet,22);
        }
    }
    puts("\"reference\":\"OpenTTD 15.3 Monocypher 4.0.2\"}");
    return 0;
}
