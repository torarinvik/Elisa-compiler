#include <stdio.h>
#include "abi_small.h"
int main(void){ int ok=1;
  { C1 v = {7}; ok &= t_c1(v) == 7; C1 r = r_c1(); ok &= r.a == 7; }
  { C2 v = {7, 7}; ok &= t_c2(v) == 7; C2 r = r_c2(); ok &= r.a == 7; }
  { C3 v = {7, 7, 7}; ok &= t_c3(v) == 7; C3 r = r_c3(); ok &= r.a == 7; }
  { I4 v = {7}; ok &= t_i4(v) == 7; I4 r = r_i4(); ok &= r.a == 7; }
  { I5 v = {7, 7}; ok &= t_i5(v) == 7; I5 r = r_i5(); ok &= r.a == 7; }
  { S6 v = {7, 7, 7}; ok &= t_s6(v) == 7; S6 r = r_s6(); ok &= r.a == 7; }
  { F4 v = {1.5}; ok &= t_f4(v) == 1.5; F4 r = r_f4(); ok &= r.f == 1.5; }
  { DF v = {1.5, 1.5}; ok &= t_df(v) == 1.5; DF r = r_df(); ok &= r.d == 1.5; }
  { FD v = {1.5, 1.5}; ok &= t_fd(v) == 1.5; FD r = r_fd(); ok &= r.f == 1.5; }
  { F12 v = {1.5, 1.5, 1.5}; ok &= t_f12(v) == 1.5; F12 r = r_f12(); ok &= r.a == 1.5; }
  { IFF v = {7, 1.5, 1.5}; ok &= t_iff(v) == 7; IFF r = r_iff(); ok &= r.a == 7; }
  { LF v = {7, 1.5}; ok &= t_lf(v) == 7; LF r = r_lf(); ok &= r.a == 7; }
  printf("%s\n", ok ? "ALL OK" : "FAILED"); return ok?0:1; }
