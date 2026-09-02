#include <stdio.h>
#include "abi_shapes.h"
int main(void) {
    int ok = 1;
    I12 i = {1, 2, 3}; F16 f = {1, 2, 3, 4}; D16 d = {1.5, 2.5}; M8 m = {1.5f, 2}; L24 l = {10, 20, 30};
    ok &= take_i12(i) == 6;
    ok &= take_f16(f) == 5.0f;
    ok &= take_d16(d) == 4.0;
    ok &= take_m8(m) == 3.5f;
    ok &= take_l24(l) == 40;
    I12 ri = ret_i12(); ok &= ri.a == 1 && ri.b == 2 && ri.c == 3;
    F16 rf = ret_f16(); ok &= rf.x == 1 && rf.h == 4;
    D16 rd = ret_d16(); ok &= rd.x == 1.5 && rd.y == 2.5;
    L24 rl = ret_l24(); ok &= rl.a == 1 && rl.b == 2 && rl.c == 3;
    F32 r32 = ret_f32(); ok &= r32.x == 1 && r32.e3 == 8;
    printf("%s\n", ok ? "ALL OK" : "FAILED");
    return ok ? 0 : 1;
}
