#include <stdint.h>
#include <stdlib.h>
typedef struct { int64_t x,y,vx,vy; } P;
static int64_t energy(const P*p){ return p->vx*p->vx+p->vy*p->vy; }
int main(void){ size_t n=100000; P*ps=malloc(n*sizeof(P));
 for(size_t i=0;i<n;i++){ int64_t k=i; ps[i]=(P){k,k*3,(k%7)-3,(k%5)-2}; }
 int64_t e=0; for(int s=0;s<1000;s++) for(size_t i=0;i<n;i++){ ps[i].x=(ps[i].x+ps[i].vx)%1000000; ps[i].y=(ps[i].y+ps[i].vy)%1000000; e+=energy(&ps[i]); }
 int64_t t=e; for(size_t i=0;i<n;i++) t+=ps[i].x+ps[i].y; return (int)(((t%251)+251)%251); }
