// Fold checked signed increments only when dominating control flow proves
// x <= bound and bound < signed maximum. Offset comparisons are inverted with
// ConstantRange arithmetic in the original integer width, so wrapping guards
// remain conservative. The no-signed-wrap flag is valid only at that guarded
// increment; no assumptions are introduced elsewhere.
#include <llvm/IR/Module.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/ConstantRange.h>
using namespace llvm;
namespace {
static bool guardEdge(DominatorTree &DT,CondBrInst *Br,unsigned Edge,BasicBlock *Use){
 return Br->getSuccessor(0)!=Br->getSuccessor(1) && DT.dominates(BasicBlockEdge(Br->getParent(),Br->getSuccessor(Edge)),Use);
}
static bool boundBelowSignedMax(Function &F,DominatorTree &DT,Value *Bound,BasicBlock *Use){
 auto *Ty=dyn_cast<IntegerType>(Bound->getType());if(!Ty)return false;unsigned W=Ty->getBitWidth(); if(W<2||W>128)return false;
 if(auto *C=dyn_cast<ConstantInt>(Bound))return !C->getValue().isMaxSignedValue();
 for(BasicBlock &B:F){auto *Br=dyn_cast<CondBrInst>(B.getTerminator());auto *Cmp=Br?dyn_cast<ICmpInst>(Br->getCondition()):nullptr;if(!Cmp)continue;
  auto *K=dyn_cast<ConstantInt>(Cmp->getOperand(1));if(!K||K->getBitWidth()!=W)continue;
  Value *Expr=Cmp->getOperand(0);APInt Shift(W,0);
  if(Expr!=Bound){auto *Add=dyn_cast<BinaryOperator>(Expr);if(!Add||Add->getOpcode()!=Instruction::Add)continue;auto *Offset=dyn_cast<ConstantInt>(Add->getOperand(1));if(!Offset||Add->getOperand(0)!=Bound)continue;Shift=Offset->getValue();}
  for(unsigned E=0;E<2;++E){if(!guardEdge(DT,Br,E,Use))continue;auto Pred=E==0?Cmp->getPredicate():Cmp->getInversePredicate();
   ConstantRange R=ConstantRange::makeAllowedICmpRegion(Pred,ConstantRange(K->getValue())).sub(ConstantRange(Shift));
   if(!R.isEmptySet()&&R.getSignedMax().slt(APInt::getSignedMaxValue(W)))return true;
  }
 }
 return false;
}
static unsigned foldGuardedIncrements(Module &M){
 if(M.getNamedMetadata("llvm.dbg.cu")||!M.getTargetTriple().isAArch64())return 0;unsigned Changed=0;
 for(Function &F:M){if(F.isDeclaration()||F.hasOptNone()||F.hasOptSize()||F.hasMinSize()||F.getInstructionCount()>2000||F.size()>128||F.hasFnAttribute(Attribute::SanitizeAddress)||F.hasFnAttribute(Attribute::SanitizeMemory)||F.hasFnAttribute(Attribute::SanitizeThread)||F.hasFnAttribute(Attribute::SanitizeHWAddress))continue;
  // Most functions do not contain a checked increment. Avoid constructing a
  // dominator tree for them, especially when compiling the self-host.
  bool HasIncrement=false;
  for (Instruction &I:instructions(F)) if (auto *II=dyn_cast<IntrinsicInst>(&I))
   if (II->getIntrinsicID()==Intrinsic::sadd_with_overflow)
    if (auto *One=dyn_cast<ConstantInt>(II->getArgOperand(1))) HasIncrement|=One->isOne();
  if(!HasIncrement)continue;
  DominatorTree DT(F);SmallVector<ExtractValueInst*,8> Flags;
  for(Instruction &I:instructions(F))if(auto *II=dyn_cast<IntrinsicInst>(&I);II&&II->getIntrinsicID()==Intrinsic::sadd_with_overflow){
   auto *One=dyn_cast<ConstantInt>(II->getArgOperand(1));if(!One||!One->isOne()||II->hasOperandBundles()||II->hasMetadataOtherThanDebugLoc())continue;
   auto *V=II->getArgOperand(0);ExtractValueInst *Flag=nullptr;
   for(User *U:II->users())if(auto *E=dyn_cast<ExtractValueInst>(U);E&&E->getNumIndices()==1&&*E->idx_begin()==1)Flag=E;
   if(!Flag||!Flag->hasOneUse()||!isa<CondBrInst>(*Flag->user_begin()))continue;
   bool Proved=false;
   for(BasicBlock &B:F){auto *Br=dyn_cast<CondBrInst>(B.getTerminator());auto *Cmp=Br?dyn_cast<ICmpInst>(Br->getCondition()):nullptr;if(!Cmp||Cmp->getOperand(0)!=V)continue;
    auto P=Cmp->getPredicate();unsigned E=P==ICmpInst::ICMP_SLE?0:P==ICmpInst::ICMP_SGT?1:2;if(E==2||!guardEdge(DT,Br,E,II->getParent()))continue;
    if(boundBelowSignedMax(F,DT,Cmp->getOperand(1),II->getParent())){Proved=true;break;}
   }
   if(Proved)Flags.push_back(Flag);
  }
  for(auto *Flag:Flags){
   auto *Call=cast<IntrinsicInst>(Flag->getAggregateOperand());
   IRBuilder<> Builder(Call);
   Value *Sum=Builder.CreateNSWAdd(Call->getArgOperand(0), Call->getArgOperand(1), "guarded.increment");
   SmallVector<ExtractValueInst*,4> Values;
   for(User *U:Call->users()) if(auto *E=dyn_cast<ExtractValueInst>(U))
    if(E->getNumIndices()==1 && *E->idx_begin()==0) Values.push_back(E);
   for(auto *E:Values) E->replaceAllUsesWith(Sum);
   Flag->replaceAllUsesWith(ConstantInt::getFalse(M.getContext()));++Changed;
  }
 }
 return Changed;
}
}
