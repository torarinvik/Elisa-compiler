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
// The cursor starts at or above the counter and advances once per iteration.
// Equality latches also need a lower bound so they cannot skip the limit.
static bool boundedCounterCursor(Loop &L, CondBrInst &Latch, ICmpInst &Cmp,
                                 ICmpInst::Predicate ContinuePred,
                                 ConstantInt &CountSeed, DominatorTree &DT,
                                 Argument *&FreezeLimit) {
  BasicBlock *Pre = L.getLoopPredecessor(), *Back = L.getLoopLatch();
  for (unsigned Side : {0u, 1u}) {
    auto Pred = Side == 0 ? ContinuePred : ICmpInst::getSwappedPredicate(ContinuePred);
    bool Equality = Pred == ICmpInst::ICMP_NE;
    if (!Equality && Pred != ICmpInst::ICMP_SLE) continue;
    Value *Tested = Cmp.getOperand(Side), *Limit = Cmp.getOperand(1 - Side);
    if (Limit->getType() != CountSeed.getType() || !L.isLoopInvariant(Limit)) continue;
    for (PHINode &Cursor : L.getHeader()->phis()) {
      if (Cursor.getType() != CountSeed.getType() || Cursor.getNumIncomingValues() != 2 ||
          Cursor.getBasicBlockIndex(Pre) < 0 || Cursor.getBasicBlockIndex(Back) < 0)
        continue;
      auto *Start = dyn_cast<ConstantInt>(Cursor.getIncomingValueForBlock(Pre));
      auto *Next = dyn_cast<BinaryOperator>(Cursor.getIncomingValueForBlock(Back));
      if (!Start || Start->getValue().slt(CountSeed.getValue()) ||
          Start->getValue().isMaxSignedValue() ||
          !Next || Next->getOpcode() != Instruction::Add || Next->getOperand(0) != &Cursor ||
          !L.contains(Next) || !DT.dominates(Next, &Latch) ||
          (Tested != Next && (!Equality || Tested != &Cursor))) continue;
      // The existing ordered-latch path handles equal seeds.
      if (!Equality && Side == 0 && Start == &CountSeed) continue;
      auto *One = dyn_cast<ConstantInt>(Next->getOperand(1));
      if (!One || !One->isOne()) continue;

      auto Range = ConstantRange::getFull(Start->getBitWidth());
      if (auto *C = dyn_cast<ConstantInt>(Limit)) Range = ConstantRange(C->getValue());
      for (auto *Node = DT.getNode(L.getHeader())->getIDom(); Node; Node = Node->getIDom()) {
        auto *Guard = dyn_cast<CondBrInst>(Node->getBlock()->getTerminator());
        auto *Compare = Guard ? dyn_cast<ICmpInst>(Guard->getCondition()) : nullptr;
        auto *K = Compare ? dyn_cast<ConstantInt>(Compare->getOperand(1)) : nullptr;
        if (!K || Compare->getOperand(0) != Limit) continue;
        for (unsigned Edge : {0u, 1u}) {
          if (!guardEdge(DT, Guard, Edge, L.getHeader())) continue;
          auto Pred = Edge == 0 ? Compare->getPredicate() : Compare->getInversePredicate();
          Range = Range.intersectWith(ConstantRange::makeExactICmpRegion(Pred, K->getValue()));
        }
      }
      if (Range.isEmptySet() || Range.getSignedMax().isMaxSignedValue()) continue;
      APInt First = Start->getValue() + (Tested == Next ? 1 : 0);
      if (Equality && Range.getSignedMin().slt(First)) continue;
      if (isGuaranteedNotToBeUndefOrPoison(Limit, nullptr, &Latch, &DT)) return true;
      // Make all guard and latch reads agree even for an undef argument.
      if (auto *A = dyn_cast<Argument>(Limit)) {
        FreezeLimit = A;
        return true;
      }
    }
  }
  return false;
}
static unsigned foldGuardedCounters(Module &M, SmallVectorImpl<Function *> &VectorizableFunctions) {
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
  SmallPtrSet<Argument *, 4> FreezeLimits;
  bool HasNewlyBoundedLoop = false;
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
   Argument *Limit = nullptr;
   if (!L->contains(Guard->getSuccessor(OnTrue ? 1 : 0)) &&
       boundedCounterCursor(*L, *Guard, *Cmp, Pred, *Seed, DT, Limit)) {
     if (Limit) FreezeLimits.insert(Limit);
     HasNewlyBoundedLoop = true;
     Proven.push_back({Call, Flag});
     continue;
   }
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
  for (Argument *Limit : FreezeLimits) {
    IRBuilder<> B(&*F.getEntryBlock().getFirstInsertionPt());
    Value *Stable = B.CreateFreeze(Limit, "guarded.counter.limit");
    Limit->replaceUsesWithIf(Stable, [Stable](Use &U) { return U.getUser() != Stable; });
  }
  if (HasNewlyBoundedLoop) VectorizableFunctions.push_back(&F);
  for(auto [Call,Flag]:Proven){IRBuilder<> B(Call);Value *Sum=B.CreateNSWAdd(Call->getArgOperand(0),Call->getArgOperand(1),"guarded.counter");SmallVector<ExtractValueInst*,4> Values;for(User *U:Call->users())if(auto *E=dyn_cast<ExtractValueInst>(U);E&&E->getNumIndices()==1&&*E->idx_begin()==0)Values.push_back(E);for(auto *E:Values)E->replaceAllUsesWith(Sum);Flag->replaceAllUsesWith(ConstantInt::getFalse(M.getContext()));++Changed;}
 }
 return Changed;
}
}
