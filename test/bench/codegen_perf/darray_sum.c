#include <stdint.h>
#include <stdlib.h>
int main(void){ size_t n=4000000; int64_t *xs=malloc(n*8); uint64_t s=12345;
 for(size_t i=0;i<n;i++){ s=s*6364136223846793005ULL+1442695040888963407ULL; xs[i]=(int64_t)(s>>33);} 
 int64_t total=0; for(int64_t r=0;r<200;r++){ for(size_t i=0;i<n;i++) total+=xs[i]^r; for(size_t i=0;i<n;i++) total-=xs[i]>>3; }
 return (int)(total%251); }
