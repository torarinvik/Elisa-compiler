// Evaluate bounded, deterministic integer paths reached from the entry branch.
// This runs after LLVM has inlined callees and exposed the scalar recurrence.
#include <llvm/Config/llvm-config.h>
#if LLVM_VERSION_MAJOR == 23
#include "llvm_loop_pass_policy.h"
#include <llvm/ADT/DenseMap.h>
#include <llvm/ADT/SmallPtrSet.h>
#include <llvm/ADT/STLExtras.h>
#include <llvm/ADT/SmallVector.h>
#include <llvm/Analysis/ConstantFolding.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/Transforms/Utils/BasicBlockUtils.h>
#include <llvm/Transforms/Utils/Local.h>
using namespace llvm;

namespace {
using PathValues = DenseMap<Value *, Constant *>;

static Constant *pathValue(Value *V, const PathValues &Values) {
  if (auto *C = dyn_cast<ConstantInt>(V)) return C;
  return Values.lookup(V);
}

static Constant *evaluatePathInstruction(Instruction &I, const PathValues &Values,
                                         const DataLayout &DL) {
  SmallVector<Constant *, 4> Operands;
  if (auto *Call = dyn_cast<IntrinsicInst>(&I)) {
    if (Call->hasOperandBundles() || Call->isConvergent()) return nullptr;
    switch (Call->getIntrinsicID()) {
    case Intrinsic::sadd_with_overflow: case Intrinsic::ssub_with_overflow:
    case Intrinsic::smul_with_overflow: case Intrinsic::uadd_with_overflow:
    case Intrinsic::usub_with_overflow: case Intrinsic::umul_with_overflow:
    case Intrinsic::uadd_sat: case Intrinsic::usub_sat:
    case Intrinsic::sadd_sat: case Intrinsic::ssub_sat:
    case Intrinsic::ctlz: case Intrinsic::cttz: case Intrinsic::ctpop:
      break;
    default:
      return nullptr;
    }
    for (Value *V : Call->args()) {
      auto *C = dyn_cast_or_null<ConstantInt>(pathValue(V, Values));
      if (!C) return nullptr;
      Operands.push_back(C);
    }
    return ConstantFoldIntrinsic(Call->getIntrinsicID(), Operands, Call->getType());
  }

  if (auto *GEP = dyn_cast<GetElementPtrInst>(&I)) {
    auto *Global = dyn_cast<GlobalVariable>(GEP->getPointerOperand());
    if (!Global || !Global->isConstant() || !Global->hasDefinitiveInitializer())
      return nullptr;
    Operands.push_back(Global);
    for (Value *Index : GEP->indices()) {
      auto *C = dyn_cast_or_null<ConstantInt>(pathValue(Index, Values));
      if (!C) return nullptr;
      Operands.push_back(C);
    }
    return ConstantFoldInstOperands(GEP, Operands, DL);
  }
  if (auto *Load = dyn_cast<LoadInst>(&I)) {
    Constant *Pointer = pathValue(Load->getPointerOperand(), Values);
    if (!Load->isSimple() || !Load->getType()->isIntegerTy() || !Pointer)
      return nullptr;
    auto *Global = dyn_cast<GlobalVariable>(getUnderlyingObject(Pointer));
    if (!Global || !Global->isConstant() || !Global->hasDefinitiveInitializer())
      return nullptr;
    return dyn_cast_or_null<ConstantInt>(
        ConstantFoldLoadFromConstPtr(Pointer, Load->getType(), DL));
  }

  if (!I.getType()->isIntegerTy() ||
      (!isa<BinaryOperator, ICmpInst, SelectInst, TruncInst, ZExtInst, SExtInst,
            ExtractValueInst, FreezeInst>(I)))
    return nullptr;
  for (Value *V : I.operands()) {
    Constant *C = pathValue(V, Values);
    if (!C) return nullptr;
    Operands.push_back(C);
  }
  if (isa<FreezeInst>(I)) return Operands.front();
  return dyn_cast_or_null<ConstantInt>(
      ConstantFoldInstOperands(&I, Operands, DL, nullptr, false));
}

static ConstantInt *evaluateIntegerPath(BasicBlock *Block, BasicBlock *Previous,
                                        const DataLayout &DL, unsigned &Budget,
                                        PathValues Values = PathValues()) {
  SmallVector<std::pair<PHINode *, Constant *>, 8> Incoming;
  unsigned Steps = 0;
  while (Budget && Steps < 18000) {
    Incoming.clear();
    for (PHINode &Phi : Block->phis()) {
      Constant *C = pathValue(Phi.getIncomingValueForBlock(Previous), Values);
      if (!C) return nullptr;
      Incoming.push_back({&Phi, C});
    }
    // PHIs take their inputs from the previous iteration simultaneously.
    for (auto [Phi, C] : Incoming) Values[Phi] = C;

    for (Instruction &I : *Block) {
      if (!Budget || ++Steps > 18000) return nullptr;
      --Budget;
      if (isa<PHINode>(&I)) continue;
      if (auto *Ret = dyn_cast<ReturnInst>(&I))
        return dyn_cast_or_null<ConstantInt>(pathValue(Ret->getReturnValue(), Values));
      if (I.isTerminator()) break;
      if (auto *Assume = dyn_cast<AssumeInst>(&I)) {
        auto *Condition = dyn_cast_or_null<ConstantInt>(pathValue(Assume->getArgOperand(0), Values));
        if (Assume->hasOperandBundles() || !Condition || !Condition->isOne()) return nullptr;
        continue;
      }
      Constant *C = evaluatePathInstruction(I, Values, DL);
      if (!C) return nullptr;
      Values[&I] = C;
    }

    auto *Terminator = Block->getTerminator();
    Previous = Block;
    if (auto *Br = dyn_cast<CondBrInst>(Terminator)) {
      auto *Test = dyn_cast_or_null<ConstantInt>(pathValue(Br->getCondition(), Values));
      if (!Test) return nullptr;
      Block = Br->getSuccessor(Test->isZero() ? 1 : 0);
    } else if (auto *Br = dyn_cast<UncondBrInst>(Terminator)) {
      Block = Br->getSuccessor();
    } else {
      return nullptr;
    }
  }
  return nullptr;
}
// A small unsigned domain makes every execution on the accepted edge
// concrete. Keep the original guard and invalid-input path.
static bool foldSmallIntegerDomain(CondBrInst &Entry, ICmpInst &Test,
                                   ConstantInt &Bound, unsigned &Budget) {
  Function &F = *Entry.getFunction();
  constexpr unsigned MaxDomain = 160;
  constexpr unsigned MaxTableBytes = 1280;
  Value *Key = Test.getOperand(0);
  auto *ReturnType = dyn_cast<IntegerType>(F.getReturnType());
  if (F.arg_size() != 1 || !Key->getType()->isIntegerTy(64) ||
      !ReturnType || ReturnType->getBitWidth() > 64 || !Test.isUnsigned())
    return false;

  // LLVM often expresses a nonzero-based interval by adding a constant
  // before the comparison. Invert that addition in the original bit width.
  Value *Input = Key;
  APInt Bias(64, 0);
  if (auto *Add = dyn_cast<BinaryOperator>(Key)) {
    auto *Offset = dyn_cast<ConstantInt>(Add->getOperand(1));
    if (Add->getOpcode() != Instruction::Add || !Offset) return false;
    Input = Add->getOperand(0);
    Bias = Offset->getValue();
  }
  Value *ArgumentValue = Input;
  if (auto *Freeze = dyn_cast<FreezeInst>(Input)) ArgumentValue = Freeze->getOperand(0);
  if (!isa<Argument>(ArgumentValue)) return false;

  unsigned Limit = 0, Accepted = 0;
  APInt Lower(64, 0);
  for (unsigned Edge : {0u, 1u}) {
    auto Predicate = Edge == 0 ? Test.getPredicate() : Test.getInversePredicate();
    auto Range = ConstantRange::makeExactICmpRegion(Predicate, Bound.getValue());
    if (Range.isEmptySet() || Range.isFullSet()) continue;
    APInt Size = Range.getUpper() - Range.getLower();
    if (Size.ult(8) || Size.ugt(MaxDomain)) continue;
    Lower = Range.getLower();
    Limit = Size.getZExtValue();
    Accepted = Edge;
    break;
  }
  if (!Limit) return false;
  BasicBlock *Start = Entry.getSuccessor(Accepted);
  SmallVector<ConstantInt *, 64> Results;
  bool WorthTable = false, Signed = false;
  for (unsigned I = 0; I < Limit; ++I) {
    unsigned Before = Budget;
    APInt KeyValue = Lower + I;
    PathValues Known;
    Known[Input] = ConstantInt::get(F.getContext(), KeyValue - Bias);
    Known[Key] = ConstantInt::get(F.getContext(), KeyValue);
    auto *Result = evaluateIntegerPath(Start, Entry.getParent(),
                                       F.getParent()->getDataLayout(), Budget, std::move(Known));
    if (!Result) return false;
    Results.push_back(Result);
    Signed |= Result->isNegative();
    WorthTable |= Before - Budget >= 32;
  }
  if (!WorthTable) return false;
  unsigned Bits = 1;
  for (ConstantInt *Result : Results)
    Bits = std::max(Bits, Signed ? Result->getValue().getSignificantBits()
                                : Result->getValue().getActiveBits());
  unsigned Width = 8;
  while (Width < Bits) Width *= 2;
  if (Limit * (Width / 8) > MaxTableBytes) return false;

  Module &M = *F.getParent();
  IRBuilder<> Guard(&Test);
  Value *Stable = Guard.CreateFreeze(Key);
  Test.setOperand(0, Stable);
  BasicBlock *Lookup = BasicBlock::Create(M.getContext(), "integer.path.lookup", &F);
  IRBuilder<> B(Lookup);
  Value *Index = B.CreateSub(Stable, ConstantInt::get(M.getContext(), Lower));
  Value *Result;
  if (!Signed && Bits == 1 && Limit <= 64) {
    // The accepted edge bounds Index, including the full 64-entry case.
    // Store Boolean results in one register and extract the indexed bit.
    uint64_t Mask = 0;
    for (unsigned I = 0; I < Limit; ++I)
      if (Results[I]->isOne()) Mask |= uint64_t{1} << I;
    Result = B.CreateAnd(B.CreateLShr(B.getInt64(Mask), Index), B.getInt64(1));
  } else {
    auto *Storage = IntegerType::get(M.getContext(), Width);
    SmallVector<Constant *, 64> Packed;
    for (ConstantInt *EntryResult : Results) {
      const APInt &Value = EntryResult->getValue();
      Packed.push_back(ConstantInt::get(Storage, Signed ? Value.sextOrTrunc(Width)
                                                        : Value.zextOrTrunc(Width)));
    }
    auto *TableType = ArrayType::get(Storage, Packed.size());
    auto *Table = new GlobalVariable(M, TableType, true, GlobalValue::PrivateLinkage,
                                     ConstantArray::get(TableType, Packed), "integer.path.results");
    Table->setUnnamedAddr(GlobalValue::UnnamedAddr::Global);
    Value *Address = B.CreateInBoundsGEP(TableType, Table, {B.getInt64(0), Index});
    Result = B.CreateLoad(Storage, Address);
  }
  B.CreateRet(B.CreateIntCast(Result, ReturnType, Signed));
  Entry.setSuccessor(Accepted, Lookup);
  Start->removePredecessor(Entry.getParent());
  removeUnreachableBlocks(F);
  return true;
}

// A collapsed counted loop can retain its zero-trip bypass even when the
// resulting product already yields zero there. Only speculate a short chain
// of integer multiplications whose operands are defined and whose result is
// proved zero on the bypass edge. Multiplication by zero cannot overflow.
static bool foldZeroProductBypass(BasicBlock &Guard) {
  auto *Branch = dyn_cast<CondBrInst>(Guard.getTerminator());
  auto *Compare = Branch ? dyn_cast<ICmpInst>(Branch->getCondition()) : nullptr;
  if (!Compare || !Compare->isEquality()) return false;
  auto *Bound = dyn_cast<ConstantInt>(Compare->getOperand(1));
  if (!Bound || !Bound->isZero()) return false;
  Value *Key = Compare->getOperand(0);
  const unsigned ZeroEdge = Compare->getPredicate() == ICmpInst::ICMP_EQ ? 0 : 1;
  BasicBlock *Join = Branch->getSuccessor(ZeroEdge);
  BasicBlock *Product = Branch->getSuccessor(1 - ZeroEdge);
  if (Join == Product || Product->getSinglePredecessor() != &Guard ||
      !isa<UncondBrInst>(Product->getTerminator()) ||
      Product->getSingleSuccessor() != Join || Product->size() < 2 ||
      Product->size() > 4 || !isa<ReturnInst>(Join->getTerminator()) ||
      Join->phis().empty())
    return false;

  SmallVector<Value *, 4> Zeros{Key};
  auto isZero = [&](Value *V) {
    auto *C = dyn_cast<ConstantInt>(V);
    return C ? C->isZero() : llvm::is_contained(Zeros, V);
  };
  for (Instruction &I : *Product) {
    if (&I == Product->getTerminator()) break;
    auto *Mul = dyn_cast<BinaryOperator>(&I);
    if (!Mul || Mul->getOpcode() != Instruction::Mul || !I.getType()->isIntegerTy())
      return false;
    Value *L = Mul->getOperand(0);
    Value *R = Mul->getOperand(1);
    const bool LeftZero = isZero(L);
    const bool RightZero = isZero(R);
    if (!(LeftZero && (RightZero || isa<ConstantInt>(R))) &&
        !(RightZero && isa<ConstantInt>(L)))
      return false;
    Zeros.push_back(Mul);
  }
  for (PHINode &Phi : Join->phis()) {
    Value *Bypass = Phi.getIncomingValueForBlock(&Guard);
    Value *Computed = Phi.getIncomingValueForBlock(Product);
    if (Bypass != Computed &&
        (!isa<ConstantInt>(Bypass) || !isZero(Bypass) || !isZero(Computed)))
      return false;
  }

  Join->removePredecessor(&Guard);
  IRBuilder<> Builder(Branch);
  Builder.SetCurrentDebugLocation(Branch->getDebugLoc());
  Builder.CreateBr(Product);
  Branch->eraseFromParent();
  if (Compare->use_empty()) Compare->eraseFromParent();
  return true;
}
// Recognize a read reached only through its unsigned bounds check.
static GlobalVariable *checkedStateTable(LoadInst &Load) {
  auto *Address = dyn_cast<GetElementPtrInst>(Load.getPointerOperand());
  auto *Table = Address ? dyn_cast<GlobalVariable>(Address->getPointerOperand()) : nullptr;
  auto *Array = Table ? dyn_cast<ArrayType>(Table->getValueType()) : nullptr;
  if (!Load.isSimple() || !Address || Address->getNumIndices() != 1 ||
      !Table || !Table->isConstant() || !Table->hasLocalLinkage() ||
      !Table->hasDefinitiveInitializer() || Table->isExternallyInitialized() ||
      Table->getAddressSpace() != 0 || !Array || Array->getNumElements() > 64 ||
      Array->getElementType() != Load.getType() ||
      Load.getDataLayout().getIndexSizeInBits(0) != 64 ||
      Load.getDataLayout().getTypeAllocSize(Address->getSourceElementType()) !=
          Load.getDataLayout().getTypeStoreSize(Load.getType()))
    return nullptr;
  BasicBlock *Guard = Load.getParent()->getSinglePredecessor();
  auto *Branch = Guard ? dyn_cast<CondBrInst>(Guard->getTerminator()) : nullptr;
  auto *Compare = Branch ? dyn_cast<ICmpInst>(Branch->getCondition()) : nullptr;
  auto *Count = Compare ? dyn_cast<ConstantInt>(Compare->getOperand(1)) : nullptr;
  if (!Compare || Compare->getPredicate() != ICmpInst::ICMP_ULT ||
      Compare->hasSameSign() || Compare->getOperand(0) != Address->idx_begin()->get() ||
      Branch->getSuccessor(0) != Load.getParent() ||
      Branch->getSuccessor(1) == Load.getParent() || !Count ||
      !Count->equalsInt(Array->getNumElements()))
    return nullptr;
  return Table;
}

// PHIs and selects can carry only values introduced by constants or checked
// immutable tables. Inspect all inputs, including the initial loop entry.
static bool stateFits(Value *State, uint64_t Limit) {
  SmallVector<Value *, 16> Pending{State};
  SmallPtrSet<Value *, 32> Seen;
  bool HasConstant = false;
  while (!Pending.empty()) {
    Value *Current = Pending.pop_back_val();
    if (!Seen.insert(Current).second) continue;
    if (Seen.size() > 64) return false;
    if (auto *C = dyn_cast<ConstantInt>(Current)) {
      if (C->getValue().uge(Limit)) return false;
      HasConstant = true;
    } else if (auto *Phi = dyn_cast<PHINode>(Current)) {
      if (Pending.size() + Phi->getNumIncomingValues() > 128) return false;
      append_range(Pending, Phi->incoming_values());
    } else if (auto *Select = dyn_cast<SelectInst>(Current)) {
      Pending.push_back(Select->getTrueValue());
      Pending.push_back(Select->getFalseValue());
    } else if (auto *Load = dyn_cast<LoadInst>(Current)) {
      GlobalVariable *Table = checkedStateTable(*Load);
      if (!Table) return false;
      for (unsigned I = 0; I < cast<ArrayType>(Table->getValueType())->getNumElements(); ++I) {
        auto *Element = dyn_cast_or_null<ConstantInt>(Table->getInitializer()->getAggregateElement(I));
        if (!Element || Element->getValue().uge(Limit)) return false;
      }
    } else {
      return false;
    }
  }
  return HasConstant;
}

static bool foldBooleanLookup(BasicBlock &Guard) {
  auto *Branch = dyn_cast<CondBrInst>(Guard.getTerminator());
  auto *Compare = Branch ? dyn_cast<ICmpInst>(Branch->getCondition()) : nullptr;
  if (!Compare || Compare->getPredicate() != ICmpInst::ICMP_ULT || Compare->hasSameSign())
    return false;
  auto *Offset = dyn_cast<BinaryOperator>(Compare->getOperand(0));
  auto *Count = dyn_cast<ConstantInt>(Compare->getOperand(1));
  if (!Offset || Offset->getOpcode() != Instruction::Add || !Offset->getType()->isIntegerTy(64) ||
      Offset->hasNoSignedWrap() || Offset->hasNoUnsignedWrap() ||
      !Count || Count->isZero() || Count->getValue().ugt(64))
    return false;
  auto *Bias = dyn_cast<ConstantInt>(Offset->getOperand(1));
  if (!Bias) return false;
  APInt Start = -Bias->getValue();
  if (Start.ugt(64 - Count->getZExtValue())) return false;

  BasicBlock *Lookup = Branch->getSuccessor(0);
  BasicBlock *Join = Branch->getSuccessor(1);
  auto *Jump = dyn_cast<UncondBrInst>(Lookup->getTerminator());
  if (Lookup == Join || Lookup == &Guard || Join == &Guard || Lookup->hasAddressTaken() ||
      Lookup->getSinglePredecessor() != &Guard || !Jump || Jump->getSuccessor(0) != Join ||
      Lookup->size() != 4 || Join->phis().empty())
    return false;
  PHINode &Result = *Join->phis().begin();
  if (std::next(Join->phis().begin()) != Join->phis().end()) return false;
  auto *Fallback = dyn_cast<ConstantInt>(Result.getIncomingValueForBlock(&Guard));
  auto *Extend = dyn_cast<ZExtInst>(Result.getIncomingValueForBlock(Lookup));
  auto *Load = Extend ? dyn_cast<LoadInst>(Extend->getOperand(0)) : nullptr;
  auto *Address = Load ? dyn_cast<GetElementPtrInst>(Load->getPointerOperand()) : nullptr;
  auto *Table = Address ? dyn_cast<GlobalVariable>(Address->getPointerOperand()) : nullptr;
  if (!Fallback || !Fallback->isZero() || !Load || !Load->isSimple() ||
      !Load->getType()->isIntegerTy(8) || Load->hasMetadataOtherThanDebugLoc() ||
      !Table || !Table->isConstant() || !Table->hasLocalLinkage() ||
      !Table->hasDefinitiveInitializer() || Table->isExternallyInitialized() ||
      Address->getPointerAddressSpace() != 0 ||
      Guard.getDataLayout().getIndexSizeInBits(0) != 64 ||
      Address->getNumIndices() != 1 || !Address->getSourceElementType()->isIntegerTy(8) ||
      Address->idx_begin()->get() != Offset || Address->getParent() != Lookup ||
      Load->getParent() != Lookup || Extend->getParent() != Lookup ||
      !Address->hasOneUse() || !Load->hasOneUse() || !Extend->hasOneUse())
    return false;

  uint64_t Mask = 0;
  for (unsigned I = 0; I < Count->getZExtValue(); ++I) {
    auto *Byte = dyn_cast_or_null<ConstantInt>(Table->getInitializer()->getAggregateElement(I));
    if (!Byte || !Byte->getType()->isIntegerTy(8) || Byte->getValue().ugt(1)) return false;
    Mask |= Byte->getZExtValue() << (Start.getZExtValue() + I);
  }
  Value *State = Offset->getOperand(0);
  if (!stateFits(State, 64)) return false;
  IRBuilder<> Builder(Branch);
  Value *Bit = Builder.CreateAnd(Builder.CreateLShr(Builder.getInt64(Mask), State), 1);
  Result.setIncomingValueForBlock(&Guard, Builder.CreateZExtOrTrunc(Bit, Result.getType()));
  Builder.CreateBr(Join);
  Branch->eraseFromParent();
  DeleteDeadBlock(Lookup);
  return true;
}

static bool foldStateTableBounds(BasicBlock &Guard) {
  auto *Branch = dyn_cast<CondBrInst>(Guard.getTerminator());
  auto *Compare = Branch ? dyn_cast<ICmpInst>(Branch->getCondition()) : nullptr;
  auto *Limit = Compare ? dyn_cast<ConstantInt>(Compare->getOperand(1)) : nullptr;
  if (!Limit || Limit->getValue().ugt(64)) return false;
  BasicBlock *Accepted = Branch->getSuccessor(0);
  BasicBlock *Rejected = Branch->getSuccessor(1);
  if (Rejected == &Guard || Rejected->hasAddressTaken() ||
      Rejected->getSinglePredecessor() != &Guard)
    return false;
  for (Instruction &I : *Accepted) {
    auto *Load = dyn_cast<LoadInst>(&I);
    if (!Load || !checkedStateTable(*Load)) continue;
    if (!stateFits(Compare->getOperand(0), Limit->getZExtValue())) return false;
    IRBuilder<> Builder(Branch);
    Builder.CreateBr(Accepted);
    Branch->eraseFromParent();
    DeleteDeadBlock(Rejected);
    return true;
  }
  return false;
}
} // namespace

unsigned elisacoreFoldConstantIntegerPaths(Module &M) {
  if (!M.getTargetTriple().isAArch64()) return 0;
  unsigned Changed = 0, Budget = 48000;
  for (Function &F : M) {
    if (!Budget) break;
    if (F.size() < 3 || F.size() > 128 || !F.getReturnType()->isIntegerTy() ||
        BDU_SkipFunction(F, M))
      continue;
    if (F.size() <= 32)
      for (BasicBlock &Block : F) Changed += foldZeroProductBypass(Block);
    for (BasicBlock &Block : F) {
      if (!foldBooleanLookup(Block)) continue;
      ++Changed;
      break;
    }
    for (BasicBlock &Block : F) {
      if (!foldStateTableBounds(Block)) continue;
      ++Changed;
      break;
    }
    auto *Entry = dyn_cast<CondBrInst>(F.getEntryBlock().getTerminator());
    if (!Entry || Entry->getSuccessor(0) == Entry->getSuccessor(1)) continue;
    auto *Test = dyn_cast<ICmpInst>(Entry->getCondition());
    auto *Bound = Test ? dyn_cast<ConstantInt>(Test->getOperand(1)) : nullptr;
    if (!Bound) continue;
    if (!Test->isEquality()) {
      Changed += foldSmallIntegerDomain(*Entry, *Test, *Bound, Budget);
      continue;
    }
    if (!isa<Argument>(Test->getOperand(0))) continue;

    for (unsigned Edge : {0u, 1u}) {
      BasicBlock *Start = Entry->getSuccessor(Edge);
      if (Start->phis().empty()) continue;
      auto *Result = evaluateIntegerPath(Start, Entry->getParent(), M.getDataLayout(), Budget);
      if (!Result) continue;
      auto *Done = BasicBlock::Create(M.getContext(), "constant.path", &F);
      ReturnInst::Create(M.getContext(), Result, Done);
      Entry->setSuccessor(Edge, Done);
      Start->removePredecessor(Entry->getParent());
      removeUnreachableBlocks(F);
      ++Changed;
      break;
    }
  }
  return Changed;
}
#endif
