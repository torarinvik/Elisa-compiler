#include <stdint.h>
#include <stdlib.h>
__attribute__((noinline)) static int64_t small(int64_t seed){ int64_t*xs=malloc(16*8); for(int i=0;i<16;i++) xs[i]=seed+i; int64_t t=0; for(int i=0;i<16;i++) t+=xs[i]; free(xs); return t; }
int main(void){ int64_t acc=0; for(int64_t i=0;i<20000000;i++) acc=(acc+small(i))%1000000007; return (int)(acc%251); }
