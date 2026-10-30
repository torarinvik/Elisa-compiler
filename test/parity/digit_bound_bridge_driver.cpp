#include <llvm-c/Core.h>
#include <llvm-c/IRReader.h>
#include <llvm-c/Analysis.h>
#include <cstdio>
extern "C" unsigned elisacoreElideBoundedDivisionSums(LLVMModuleRef);
int main(int argc,char **argv) {
 if(argc != 3)return 2;
 LLVMContextRef ctx=LLVMContextCreate(); LLVMMemoryBufferRef buf=nullptr; char *err=nullptr;
 if(LLVMCreateMemoryBufferWithContentsOfFile(argv[1],&buf,&err)) {std::fprintf(stderr,"%s",err);return 2;}
 LLVMModuleRef m=nullptr; if(LLVMParseIRInContext(ctx,buf,&m,&err)){std::fprintf(stderr,"%s",err);return 2;}
 unsigned count=elisacoreElideBoundedDivisionSums(m);
 if(LLVMVerifyModule(m,LLVMReturnStatusAction,&err)){std::fprintf(stderr,"%s",err);return 3;}
 if(LLVMPrintModuleToFile(m,argv[2],&err)){std::fprintf(stderr,"%s",err);return 3;}
 std::printf("candidate functions: %u\n",count); LLVMDisposeModule(m); LLVMContextDispose(ctx);
}
