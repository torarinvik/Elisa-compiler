#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef struct { const uint8_t *p; int64_t n; } SV;
int main(void){ size_t n=4000; uint8_t*buf=malloc(n*8); uint64_t s=4242;
 for(size_t i=0;i<n*8;i++){ s=s*6364136223846793005ULL+1442695040888963407ULL; buf[i]=(uint8_t)(97+(s>>59)); }
 SV*words=malloc(n*sizeof(SV)); for(size_t w=0;w<n;w++){ words[w].p=buf+w*8; words[w].n=6; }
 int64_t found=0; for(size_t q=0;q<100000;q++){ SV t=words[(q*7919)%n];
   for(size_t j=0;j<n;j++){ if(words[j].n==t.n && (words[j].p==t.p || memcmp(words[j].p,t.p,t.n)==0)){ found+=j; break; } } }
 return (int)(found%251); }
