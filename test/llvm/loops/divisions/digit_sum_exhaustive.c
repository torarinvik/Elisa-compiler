#include <stdio.h>
extern int sum2(int);
extern int sum3(int);
extern int sum4(int);
extern int sum5(int);
extern int sum6(int);
extern int sum7(int);
extern int sum8(int);
extern int sum9(int);
extern int sum10(int);
extern int sum11(int);
extern int sum12(int);
extern int sum13(int);
extern int sum14(int);
extern int sum15(int);
extern int sum16(int);
extern int sum17(int);
extern int sum18(int);
extern int sum19(int);
extern int sum20(int);
extern int bad_initial(signed char, signed char);
int main(void) {
for(int n=-128;n<=127;n++){
printf("%d ",sum2(n));
printf("%d ",sum3(n));
printf("%d ",sum4(n));
printf("%d ",sum5(n));
printf("%d ",sum6(n));
printf("%d ",sum7(n));
printf("%d ",sum8(n));
printf("%d ",sum9(n));
printf("%d ",sum10(n));
printf("%d ",sum11(n));
printf("%d ",sum12(n));
printf("%d ",sum13(n));
printf("%d ",sum14(n));
printf("%d ",sum15(n));
printf("%d ",sum16(n));
printf("%d ",sum17(n));
printf("%d ",sum18(n));
printf("%d ",sum19(n));
printf("%d ",sum20(n));
}
printf("%d\n",bad_initial(1,127));
return 0;
}
