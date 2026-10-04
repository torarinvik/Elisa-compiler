#include <stdint.h>
#include <stdlib.h>
typedef struct { int tag; int64_t v; } Op;
static int64_t step(int64_t acc, Op op){ switch(op.tag){ case 0: return (acc+op.v)%1000003; case 1: return (acc*op.v)%1000003; case 2: return acc^op.v; case 3: return 1000003-acc; default: return acc; } }
int main(void){ Op*ops=malloc(1000*sizeof(Op)); uint64_t s=99;
 for(int i=0;i<1000;i++){ s=s*6364136223846793005ULL+1442695040888963407ULL; uint64_t k=(s>>33)%5; ops[i].tag=(int)k; ops[i].v=(int64_t)((s>>20)%1000);} 
 int64_t acc=1; for(int r=0;r<300000;r++) for(int i=0;i<1000;i++) acc=step(acc,ops[i]); return (int)(acc%251); }
