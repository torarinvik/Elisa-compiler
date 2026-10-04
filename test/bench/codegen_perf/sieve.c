#include <stdint.h>
#include <stdlib.h>
static int64_t sieve(size_t n){ uint8_t*f=malloc(n); for(size_t i=0;i<n;i++) f[i]=1; f[0]=f[1]=0;
 for(size_t p=2;p*p<n;p++) if(f[p]) for(size_t m=p*p;m<n;m+=p) f[m]=0;
 int64_t c=0; for(size_t i=0;i<n;i++) c+=f[i]; free(f); return c; }
int main(void){ int64_t t=0; for(int r=0;r<30;r++) t+=sieve(10000000); return (int)(t%251); }
