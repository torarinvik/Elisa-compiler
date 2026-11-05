// Prove that a conditional +1 counter stays no larger than a synchronized
// loop induction variable, whose latch and dominating guard bound its values.
#include <llvm/ADT/PostOrderIterator.h>
#include <llvm/Analysis/CFG.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/IR/IRBuilder.h>
using namespace llvm;
namespace {
static bool counterUpdateShape(Value *V, PHINode *Count, IntrinsicInst *Call, Loop *L, unsigned Depth=0) {
 if (Depth>8) return false;
 if (V==Count) return true;
 if (auto *E=dyn_cast<ExtractValueInst>(V))
  return E->getAggregateOperand()==Call && E->getNumIndices()==1 && *E->idx_begin()==0;
 if (auto *P=dyn_cast<PHINode>(V)) {
  if (!L->contains(P->getParent())) return false;
  for (Value *Incoming:P->incoming_values()) if(!counterUpdateShape(Incoming,Count,Call,L,Depth+1)) return false;
  return true;
 }
 if (auto *S=dyn_cast<SelectInst>(V))
  return counterUpdateShape(S->getTrueValue(),Count,Call,L,Depth+1) && counterUpdateShape(S->getFalseValue(),Count,Call,L,Depth+1);
 return false;
}
static unsigned foldGuardedCounters(Module &M) {
 if(M.getNamedMetadata("llvm.dbg.cu")||!M.getTargetTriple().isAArch64())return 0;
 unsigned Changed=0;
 for(Function &F:M){
  if(F.isDeclaration()||F.hasOptNone()||F.hasOptSize()||F.hasMinSize()||F.getInstructionCount()>2000||F.size()>128||F.hasFnAttribute(Attribute::SanitizeAddress)||F.hasFnAttribute(Attribute::SanitizeMemory)||F.hasFnAttribute(Attribute::SanitizeThread)||F.hasFnAttribute(Attribute::SanitizeHWAddress))continue;
  SmallVector<IntrinsicInst*,8> Candidates;
  for(Instruction &I:instructions(F))if(auto *C=dyn_cast<IntrinsicInst>(&I);C&&C->getIntrinsicID()==Intrinsic::sadd_with_overflow&&!C->hasOperandBundles()&&!C->hasMetadataOtherThanDebugLoc())
   if(auto *One=dyn_cast<ConstantInt>(C->getArgOperand(1));One&&One->isOne()&&isa<PHINode>(C->getArgOperand(0)))Candidates.push_back(C);
  if(Candidates.empty()||Candidates.size()>32)continue;
  DominatorTree DT(F);LoopInfo LI(DT);ReversePostOrderTraversal<Function*> RPO(&F);
  if(containsIrreducibleCFG<BasicBlock*>(RPO,LI))continue;
  SmallVector<std::pair<IntrinsicInst*,ExtractValueInst*>,8> Proven;
  for(auto *Call:Candidates){
   auto *Count=cast<PHINode>(Call->getArgOperand(0));Loop *L=LI.getLoopFor(Count->getParent());
   if(!L||L->getHeader()!=Count->getParent()||!L->getSubLoops().empty()||LI.getLoopFor(Call->getParent())!=L)continue;
   BasicBlock *Pre=L->getLoopPredecessor(),*Latch=L->getLoopLatch();if(!Pre||!Latch||Count->getNumIncomingValues()!=2)continue;
   int In=Count->getBasicBlockIndex(Pre),Back=Count->getBasicBlockIndex(Latch);if(In<0||Back<0)continue;
   auto *Seed=dyn_cast<ConstantInt>(Count->getIncomingValue(In));if(!Seed||Seed->isNegative()||Seed->getValue().isMaxSignedValue())continue;
   if(!counterUpdateShape(Count->getIncomingValue(Back),Count,Call,L))continue;
   ExtractValueInst *Flag=nullptr;for(User *U:Call->users())if(auto *E=dyn_cast<ExtractValueInst>(U);E&&E->getNumIndices()==1&&*E->idx_begin()==1)Flag=E;
   if(!Flag||!Flag->hasOneUse())continue;auto *FlagBranch=dyn_cast<CondBrInst>(*Flag->user_begin());if(!FlagBranch||FlagBranch->getCondition()!=Flag)continue;
   auto *Guard=dyn_cast<CondBrInst>(Latch->getTerminator());auto *Cmp=Guard?dyn_cast<ICmpInst>(Guard->getCondition()):nullptr;if(!Cmp)continue;
   bool OnTrue=Guard->getSuccessor(0)==L->getHeader(),OnFalse=Guard->getSuccessor(1)==L->getHeader();
   if(OnTrue==OnFalse)continue;auto Pred=OnTrue?Cmp->getPredicate():Cmp->getInversePredicate();
   if(Pred!=ICmpInst::ICMP_SLE)continue;
   auto *Next=dyn_cast<BinaryOperator>(Cmp->getOperand(0));Value *Bound=Cmp->getOperand(1);
   if(!Next||Next->getOpcode()!=Instruction::Add||Next->getType()!=Count->getType()||!L->contains(Next->getParent()))continue;
   auto *One=dyn_cast<ConstantInt>(Next->getOperand(1));auto *Cursor=dyn_cast<PHINode>(Next->getOperand(0));
   if(!One||!One->isOne()||!Cursor||Cursor->getParent()!=L->getHeader()||Cursor->getNumIncomingValues()!=2||Cursor->getBasicBlockIndex(Pre)<0||Cursor->getBasicBlockIndex(Latch)<0||Cursor->getIncomingValueForBlock(Latch)!=Next)continue;
   if(Cursor->getIncomingValueForBlock(Pre)!=Seed||!boundBelowSignedMax(F,DT,Bound,L->getHeader()))continue;
   // The condition must be loop invariant, and the cursor increment must be
   // reached no more than once per iteration (irreducible/nested loops rejected).
   if(!L->isLoopInvariant(Bound)||!DT.dominates(Next,Guard))continue;
   Proven.push_back({Call,Flag});
  }
  for(auto [Call,Flag]:Proven){IRBuilder<> B(Call);Value *Sum=B.CreateNSWAdd(Call->getArgOperand(0),Call->getArgOperand(1),"guarded.counter");SmallVector<ExtractValueInst*,4> Values;for(User *U:Call->users())if(auto *E=dyn_cast<ExtractValueInst>(U);E&&E->getNumIndices()==1&&*E->idx_begin()==0)Values.push_back(E);for(auto *E:Values)E->replaceAllUsesWith(Sum);Flag->replaceAllUsesWith(ConstantInt::getFalse(M.getContext()));++Changed;}
 }
 return Changed;
}
}
