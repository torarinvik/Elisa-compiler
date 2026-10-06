#include <stdint.h>
#include <stdlib.h>
#include <string.h>
int main(void){ size_t n=8000000; uint8_t*buf=malloc(n); uint64_t s=777;
 for(size_t i=0;i<n;i++){ s=s*6364136223846793005ULL+1442695040888963407ULL; uint64_t r=(s>>40)%8; buf[i]= r==0?32:(uint8_t)(97+(s>>50)%4);} 
 int64_t words=0,abs=0; uint64_t hash=1469598103934665603ULL;
 for(int rep=0;rep<40;rep++){ size_t start=0; for(size_t i=0;i<n;i++){ uint8_t ch=buf[i]; hash=(hash^ch)*1099511628211ULL;
   if(ch==32){ if(i>start){ words++; if(i-start==2 && memcmp(buf+start,"ab",2)==0) abs++; } start=i+1; } } }
 return (int)((words+abs+(int64_t)(hash%251))%251); }
