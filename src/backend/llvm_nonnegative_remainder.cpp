// A signed remainder by a positive power of two equals unsigned remainder
// when its dividend is nonnegative. Prove nonnegativity through guarded
// values and non-wrapping monotone recurrences, including loop-header PHIs.
// Unknown expressions, unanchored cycles and undefined seeds decline.
#include <llvm/ADT/SmallPtrSet.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/IR/ConstantRange.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/Module.h>
using namespace llvm;
namespace {
class NonnegativeRecurrenceProof {
  Function &F; DominatorTree &DT; LoopInfo &LI; unsigned Work=0;
  bool guarded(Value *V, Instruction *At) {
    for(BasicBlock &B:F){
      auto *Br=dyn_cast<CondBrInst>(B.getTerminator()); auto *Cmp=Br?dyn_cast<ICmpInst>(Br->getCondition()):nullptr;
      if(!Cmp || Cmp->getOperand(0)!=V || Br->getSuccessor(0)==Br->getSuccessor(1))continue;
      auto *K=dyn_cast<ConstantInt>(Cmp->getOperand(1)); if(!K)continue;
      for(unsigned E=0;E<2;++E) if(DT.dominates(BasicBlockEdge(&B,Br->getSuccessor(E)),At->getParent())) {
        auto P=E==0?Cmp->getPredicate():Cmp->getInversePredicate();
        auto R=ConstantRange::makeAllowedICmpRegion(P,ConstantRange(K->getValue()));
        if(!R.isEmptySet() && !R.getSignedMin().isNegative())return true;
      }
    }
    return false;
  }
  bool prove(Value *V,Instruction *At,PHINode *Root,SmallPtrSetImpl<Value*> &Active,unsigned Depth){
    if(++Work>1024 || Depth>64 || !V->getType()->isIntegerTy())return false;
    if(auto *K=dyn_cast<ConstantInt>(V))return !K->isNegative();
    if(isa<UndefValue>(V) || isa<PoisonValue>(V))return false;
    if(V==Root && Active.count(V))return true;
    if(!Active.insert(V).second)return false;
    bool Result=false;
    if(auto *P=dyn_cast<PHINode>(V)){
      PHINode *NextRoot=Root;
      if(!Root){Loop *L=LI.getLoopFor(P->getParent());if(!L||L->getHeader()!=P->getParent()){Active.erase(V);return false;}
        bool HasOutside=false;for(unsigned I=0;I<P->getNumIncomingValues();++I)HasOutside|=!L->contains(P->getIncomingBlock(I));
        if(!HasOutside){Active.erase(V);return false;}NextRoot=P;
      }
      Result=true;
      SmallPtrSet<Value*,32> RootActive;
      if(!Root)RootActive.insert(P);
      SmallPtrSetImpl<Value*> &Path = Root ? Active : RootActive;
      for(unsigned I=0;I<P->getNumIncomingValues();++I)
        if(!prove(P->getIncomingValue(I),P->getIncomingBlock(I)->getTerminator(),NextRoot,Path,Depth+1)){Result=false;break;}
    }else if(auto *S=dyn_cast<SelectInst>(V)){
      Result=prove(S->getTrueValue(),S,Root,Active,Depth+1)&&prove(S->getFalseValue(),S,Root,Active,Depth+1);
    }else if(auto *O=dyn_cast<BinaryOperator>(V)){
      auto Code=O->getOpcode();
      if((Code==Instruction::Add||Code==Instruction::Mul)&&O->hasNoSignedWrap())
        Result=prove(O->getOperand(0),O,Root,Active,Depth+1)&&prove(O->getOperand(1),O,Root,Active,Depth+1);
      else if(Code==Instruction::And){for(Value *X:O->operands())if(auto *K=dyn_cast<ConstantInt>(X);K&&!K->isNegative())Result=true;}
      else if(Code==Instruction::SRem){auto *K=dyn_cast<ConstantInt>(O->getOperand(1));Result=K&&K->getValue().isStrictlyPositive()&&prove(O->getOperand(0),O,Root,Active,Depth+1);}
    }
    if(!Result)Result=guarded(V,At);
    Active.erase(V);return Result;
  }
public:
  NonnegativeRecurrenceProof(Function &Fn,DominatorTree &D,LoopInfo &L):F(Fn),DT(D),LI(L){}
  bool operator()(Value *V,Instruction *At){SmallPtrSet<Value*,32> Active;Work=0;return prove(V,At,nullptr,Active,0);}
};
static unsigned foldNonnegativeRemainders(Module &M){
 if(M.getNamedMetadata("llvm.dbg.cu")||!M.getTargetTriple().isAArch64())return 0;
 unsigned Count=0;
 for(Function &F:M){if(F.isDeclaration()||F.hasOptNone()||F.hasOptSize()||F.hasMinSize()||F.getInstructionCount()>2000||F.size()>128||F.hasFnAttribute(Attribute::SanitizeAddress)||F.hasFnAttribute(Attribute::SanitizeMemory)||F.hasFnAttribute(Attribute::SanitizeThread)||F.hasFnAttribute(Attribute::SanitizeHWAddress))continue;
  SmallVector<BinaryOperator*,8> Candidates;
  for(Instruction &I:instructions(F))if(auto *B=dyn_cast<BinaryOperator>(&I);B&&B->getOpcode()==Instruction::SRem&&!B->hasMetadataOtherThanDebugLoc())if(auto *K=dyn_cast<ConstantInt>(B->getOperand(1));K&&K->getValue().isStrictlyPositive()&&K->getValue().isPowerOf2())Candidates.push_back(B);
  if(Candidates.empty()||Candidates.size()>32)continue;
  DominatorTree DT(F);LoopInfo LI(DT);NonnegativeRecurrenceProof Proof(F,DT,LI);SmallVector<BinaryOperator*,8> Safe;
  for(auto *B:Candidates)if(Proof(B->getOperand(0),B))Safe.push_back(B);
  for(auto *B:Safe){IRBuilder<> Builder(B);Builder.SetCurrentDebugLocation(B->getDebugLoc());auto *V=Builder.CreateURem(B->getOperand(0),B->getOperand(1),"nonnegative.remainder");B->replaceAllUsesWith(V);B->eraseFromParent();++Count;}
 }
 return Count;
}
}
