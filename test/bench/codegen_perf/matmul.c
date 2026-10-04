#include <stdint.h>
#include <stdlib.h>
int main(void){ size_t n=300; int64_t*a=malloc(n*n*8),*b=malloc(n*n*8),*c=calloc(n*n,8);
 for(size_t i=0;i<n*n;i++){a[i]=i%17; b[i]=(int64_t)(i%13)-6;}
 for(int rep=0;rep<30;rep++) for(size_t i=0;i<n;i++) for(size_t k=0;k<n;k++){ int64_t aik=a[i*n+k]; for(size_t j=0;j<n;j++) c[i*n+j]+=aik*b[k*n+j]; }
 int64_t t=0; for(size_t i=0;i<n*n;i++) t+=c[i]; return (int)(((t%251)+251)%251); }
