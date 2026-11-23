// Bound the values a local integer array can hold. When a non-escaping
// array is accessed only through element-aligned loads and stores, starts
// from a zero fill, and every store writes either a value of known range or
// a value loaded from the array itself, then every load returns a value in
// the union of those ranges: a fill or an outside store puts one there, and a
// copied element was already there. The loads get `!range` metadata, which
// lets later folding remove bounds checks on indices read from the array
// (permutation and order arrays indexing a second array are the common case)
// and overflow checks on arithmetic over its values. Vector stores contribute
// their lanes, and an element-aligned copy from another analyzed array
// contributes that array's range, so values moved between scratch arrays
// (a matrix and its squared copy) stay bounded. Ranges are signed, so
// remainders such as [-96, 96] survive.
#include <llvm/Analysis/LazyValueInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/GetElementPtrTypeIterator.h>
#include <llvm/IR/MDBuilder.h>
// Defined with the signed-check prover later in the same translation unit.
namespace ElisaCheckedSignedRanges {
using Facts = llvm::DenseMap<llvm::Value *, llvm::ConstantRange>;
static Facts dominatingBounds(llvm::Instruction &Call, llvm::DominatorTree &Tree,
                              llvm::AssumptionCache &Assumptions, const Facts &Incoming,
                              llvm::SmallPtrSetImpl<llvm::LoadInst *> *UnstableLoads,
                              llvm::SmallPtrSetImpl<llvm::Argument *> *FrozenArguments);
} // namespace ElisaCheckedSignedRanges
namespace ElisaArrayRanges {
using namespace llvm;

// Marks an array whose zero fill ElisaIndexedPrefix removed after proving
// that every load reads an element a store wrote first.
static constexpr const char *WrittenPrefix = "elisa.written.prefix";

struct Accesses {
  SmallVector<LoadInst *, 16> Loads;
  // Loads of several consecutive elements, as the vectorizer emits.
  SmallVector<LoadInst *, 4> VectorLoads;
  SmallVector<StoreInst *, 16> Stores;
  // Stores of several consecutive elements; only collected on request.
  SmallVector<StoreInst *, 4> VectorStores;
  SmallVector<MemTransferInst *, 2> Copies;
  // Copies and pattern fills into the array from its first element.
  SmallVector<MemIntrinsic *, 1> Writes;
  SmallVector<Instruction *, 1> Fills;
  // Views {data, length} of the array from its first element, each used
  // only as an argument of calls to defined functions.
  SmallVector<InsertValueInst *, 2> Views;
  // Byte offsets inside its element of an access to a field of a struct
  // element; absent for an access at the element's start.
  SmallDenseMap<Instruction *, uint64_t, 8> Residues;
  bool Filled = false;
};

// The byte offset inside an element that Address adds: every index steps
// by whole elements of ElementSize bytes (its stride is a multiple, or the
// index has enough known low zero bits to make the product one: a byte
// offset `i << 4` into i64s), except constant ones and struct fields, which
// a Composite element (a struct) may also step into.
static std::optional<uint64_t> elementResidue(GetElementPtrInst &Address, uint64_t ElementSize,
                                              const DataLayout &Layout, bool Composite) {
  uint64_t Residue = 0;
  for (gep_type_iterator Step = gep_type_begin(Address), End = gep_type_end(Address);
       Step != End; ++Step) {
    if (Step.isStruct()) {
      auto *Field = cast<ConstantInt>(Step.getOperand());
      Residue += Layout.getStructLayout(Step.getStructType())->getElementOffset(Field->getZExtValue());
      continue;
    }
    uint64_t Stride = Step.getSequentialElementStride(Layout).getFixedValue();
    if (Stride % ElementSize == 0) continue;
    if (auto *Constant = dyn_cast<ConstantInt>(Step.getOperand())) {
      int64_t Bytes = (Constant->getSExtValue() * int64_t(Stride)) % int64_t(ElementSize);
      Residue += uint64_t(Bytes < 0 ? Bytes + int64_t(ElementSize) : Bytes);
      continue;
    }
    unsigned Zeros = computeKnownBits(Step.getOperand(), Layout).countMinTrailingZeros();
    if (Zeros >= 64 || (Stride << Zeros) % ElementSize != 0) return std::nullopt;
  }
  Residue %= ElementSize;
  if (Residue && !Composite) return std::nullopt;
  return Residue;
}

// Collect the accesses of Pointer (Array or an element-aligned address in
// it, Residue bytes into its element); false when some use could read or
// write it in another way. A struct Element is Composite: its fields are
// loaded and stored separately, each access inside one element.
// The view `{Data, length}` that Data starts when Data points at the
// array's first element and the view only reaches defined functions'
// arguments, as `find(scratch[0:count], key)` passes a slice.
static InsertValueInst *viewFromStart(InsertValueInst &Data, Value &Pointer, const DataLayout &Layout) {
  auto *Shape = dyn_cast<StructType>(Data.getType());
  APInt Offset(Layout.getIndexTypeSizeInBits(Pointer.getType()), 0);
  if (!Shape || Shape->getNumElements() != 2 || Data.getNumIndices() != 1 || Data.getIndices()[0] != 0 ||
      Data.getInsertedValueOperand() != &Pointer || !isa<UndefValue>(Data.getAggregateOperand()) ||
      !isa<AllocaInst>(Pointer.stripAndAccumulateConstantOffsets(Layout, Offset, true)) || !Offset.isZero() ||
      !Data.hasOneUse())
    return nullptr;
  auto *View = dyn_cast<InsertValueInst>(Data.user_back());
  if (!View || View->getNumIndices() != 1 || View->getIndices()[0] != 1 || View->use_empty()) return nullptr;
  for (Use &Passed : View->uses()) {
    auto *Call = dyn_cast<CallBase>(Passed.getUser());
    Function *Callee = Call ? Call->getCalledFunction() : nullptr;
    if (!Callee || Callee->isDeclaration() || !Call->isArgOperand(&Passed)) return nullptr;
  }
  return View;
}

static bool collect(Value *Pointer, Type *Element, uint64_t ElementSize,
                    const DataLayout &Layout, Accesses &Out, unsigned Depth = 0,
                    bool AllowVectorStores = false, uint64_t Residue = 0) {
  if (Depth > 4) return false;
  bool Composite = isa<StructType>(Element);
  auto Inside = [&](Instruction &Access, Type *Accessed) {
    if (!Composite || Residue + Layout.getTypeStoreSize(Accessed).getFixedValue() > ElementSize)
      return false;
    if (Residue) Out.Residues[&Access] = Residue;
    return true;
  };
  for (User *Use : Pointer->users()) {
    if (auto *Load = dyn_cast<LoadInst>(Use)) {
      auto *Vector = dyn_cast<FixedVectorType>(Load->getType());
      if (!Load->isSimple()) return false;
      if (Load->getType() == Element || Inside(*Load, Load->getType())) Out.Loads.push_back(Load);
      else if (Vector && Vector->getElementType() == Element) Out.VectorLoads.push_back(Load);
      else return false;
    } else if (auto *Store = dyn_cast<StoreInst>(Use)) {
      if (!Store->isSimple() || Store->getPointerOperand() != Pointer) return false;
      Type *Stored = Store->getValueOperand()->getType();
      auto *Lanes = dyn_cast<FixedVectorType>(Stored);
      if (Stored == Element || Inside(*Store, Stored)) {
        Out.Stores.push_back(Store);
      } else if (AllowVectorStores && Lanes && Lanes->getElementType() == Element) {
        Out.VectorStores.push_back(Store);
      } else if (isa<ConstantAggregateZero>(Store->getValueOperand()) && Depth == 0) {
        Out.Filled = true;
        Out.Fills.push_back(Store);
      } else {
        return false;
      }
    } else if (auto *Address = dyn_cast<GetElementPtrInst>(Use)) {
      std::optional<uint64_t> Added = elementResidue(*Address, ElementSize, Layout, Composite);
      if (!Added || !collect(Address, Element, ElementSize, Layout, Out, Depth + 1, AllowVectorStores,
                             (Residue + *Added) % ElementSize))
        return false;
    } else if (Residue) {
      // Only loads and stores may address a field.
      if (!isa<LifetimeIntrinsic>(Use) && !isa<ICmpInst>(Use)) return false;
    } else if (auto *Fill = dyn_cast<MemSetInst>(Use)) {
      auto *Byte = dyn_cast<ConstantInt>(Fill->getValue());
      if (Fill->getRawDest() != Pointer || Fill->isVolatile()) return false;
      if (Byte && Byte->isZero()) {
        Out.Filled = true;
        Out.Fills.push_back(Fill);
      } else if (Depth == 0) {
        // A fill of another byte (`a[i] <- -1` over a prefix) writes it.
        Out.Writes.push_back(Fill);
      } else {
        return false;
      }
    } else if (auto *Copy = dyn_cast<MemTransferInst>(Use)) {
      if (Copy->isVolatile() || (Copy->getRawDest() == Pointer && (Depth > 0 || Copy->getRawSource() == Pointer)))
        return false;
      // Copies out of the array read it; they cannot change it.
      if (Copy->getRawDest() == Pointer) Out.Writes.push_back(Copy);
      else Out.Copies.push_back(Copy);
    } else if (auto *Data = dyn_cast<InsertValueInst>(Use)) {
      InsertValueInst *View = Residue ? nullptr : viewFromStart(*Data, *Pointer, Layout);
      if (!View) return false;
      Out.Views.push_back(View);
    } else if (!isa<LifetimeIntrinsic>(Use) && !isa<ICmpInst>(Use)) {
      // Comparing addresses (a vectorizer's overlap check) touches no element.
      return false;
    }
  }
  return true;
}

class Bounds {
public:
  Bounds(Accesses &Uses, ScalarEvolution &Evolution, LazyValueInfo &Values,
         DominatorTree &Tree, AssumptionCache &Assumptions)
      : uses(Uses), evolution(Evolution), values(Values), tree(Tree),
        assumptions(Assumptions) {
    for (LoadInst *Load : Uses.Loads) own.insert(Load);
    for (LoadInst *Load : Uses.VectorLoads) own.insert(Load);
  }

  // The union of the ranges of values the array can hold, or the full set.
  ConstantRange hull(unsigned Width) {
    ConstantRange Result(APInt(Width, 0));
    for (StoreInst *Store : uses.Stores) {
      Result = Result.unionWith(rangeOf(Store->getValueOperand(), Store),
                                ConstantRange::Signed);
      if (Result.isFullSet()) return Result;
    }
    for (StoreInst *Store : uses.VectorStores) {
      Result = Result.unionWith(laneRange(Store->getValueOperand(), Width),
                                ConstantRange::Signed);
      if (Result.isFullSet()) break;
    }
    return Result;
  }

private:
  Accesses &uses;
  ScalarEvolution &evolution;
  LazyValueInfo &values;
  DominatorTree &tree;
  AssumptionCache &assumptions;
  SmallPtrSet<Value *, 16> own, visiting;

  // A remainder is smaller in magnitude than its divisor, whose range the
  // guards dominating the store bound even where the store sits in a loop
  // that lazy value info cannot see through.
  ConstantRange remainderRange(BinaryOperator &Remainder, Instruction *At) {
    unsigned Width = Remainder.getType()->getIntegerBitWidth();
    Value *Divisor = Remainder.getOperand(1);
    ConstantRange DivisorRange = values.getConstantRange(Divisor, At, false);
    using ElisaCheckedSignedRanges::dominatingBounds;
    auto Facts = dominatingBounds(*At, tree, assumptions, ElisaCheckedSignedRanges::Facts(),
                                  nullptr, nullptr);
    if (auto Fact = Facts.find(Divisor); Fact != Facts.end())
      DivisorRange = DivisorRange.intersectWith(Fact->second, ConstantRange::Signed);
    ConstantRange Dividend = ConstantRange::getFull(Width);
    return Dividend.binaryOp(Remainder.getOpcode(), DivisorRange);
  }

  // Every lane of a stored vector: constant lanes, or a load whose
  // `!range` bounds each lane. Lanes of the array's own loads add nothing.
  ConstantRange laneRange(Value *Stored, unsigned Width) {
    if (own.count(Stored)) return ConstantRange::getEmpty(Width);
    if (auto *Lanes = dyn_cast<Constant>(Stored)) {
      auto *Type = cast<FixedVectorType>(Stored->getType());
      ConstantRange Result = ConstantRange::getEmpty(Width);
      for (unsigned Lane = 0; Lane < Type->getNumElements(); ++Lane) {
        auto *Value = dyn_cast_or_null<ConstantInt>(Lanes->getAggregateElement(Lane));
        if (!Value) return ConstantRange::getFull(Width);
        Result = Result.unionWith(ConstantRange(Value->getValue()), ConstantRange::Signed);
      }
      return Result;
    }
    if (auto *Load = dyn_cast<LoadInst>(Stored))
      if (MDNode *Range = Load->getMetadata(LLVMContext::MD_range))
        return getConstantRangeFromMetadata(*Range);
    return ConstantRange::getFull(Width);
  }

  // Values flowing from the array's own loads add nothing new.
  ConstantRange rangeOf(Value *Stored, Instruction *At, unsigned Depth = 0) {
    unsigned Width = Stored->getType()->getIntegerBitWidth();
    if (own.count(Stored) || visiting.count(Stored)) return ConstantRange::getEmpty(Width);
    if (Depth > 6) return ConstantRange::getFull(Width);
    // Each choice is judged where it is available: a phi input at the end of
    // its incoming block, a select operand at the select. Lazy value info
    // must not be asked about a value at a point it does not dominate.
    SmallVector<std::pair<Value *, Instruction *>, 4> Choices;
    if (auto *Merge = dyn_cast<PHINode>(Stored))
      for (unsigned Index = 0; Index < Merge->getNumIncomingValues(); ++Index)
        Choices.push_back({Merge->getIncomingValue(Index),
                           Merge->getIncomingBlock(Index)->getTerminator()});
    if (auto *Choice = dyn_cast<SelectInst>(Stored))
      Choices.append({{Choice->getTrueValue(), Choice}, {Choice->getFalseValue(), Choice}});
    if (!Choices.empty()) {
      visiting.insert(Stored);
      ConstantRange Result = ConstantRange::getEmpty(Width);
      for (auto [Choice, Context] : Choices)
        Result = Result.unionWith(rangeOf(Choice, Context, Depth + 1), ConstantRange::Signed);
      visiting.erase(Stored);
      return Result;
    }
    ConstantRange Known = values.getConstantRange(Stored, At, false);
    if (auto *Remainder = dyn_cast<BinaryOperator>(Stored);
        Remainder && (Remainder->getOpcode() == Instruction::SRem ||
                      Remainder->getOpcode() == Instruction::URem))
      Known = Known.intersectWith(remainderRange(*Remainder, At), ConstantRange::Signed);
    if (evolution.isSCEVable(Stored->getType()))
      Known = Known.intersectWith(evolution.getUnsignedRange(evolution.getSCEV(Stored)),
                                  ConstantRange::Unsigned);
    return Known;
  }
};

// A range that wraps as unsigned but not as signed (remainders such as
// [-96, 96]) is still a valid `!range` and bounds signed arithmetic.
static bool annotate(Accesses &Uses, const ConstantRange &Range) {
  if (Range.isFullSet() || Range.isEmptySet() ||
      (Range.isWrappedSet() && Range.isSignWrappedSet()))
    return false;
  bool Changed = false;
  SmallVector<LoadInst *, 20> Loads(Uses.Loads.begin(), Uses.Loads.end());
  Loads.append(Uses.VectorLoads.begin(), Uses.VectorLoads.end());
  for (LoadInst *Load : Loads) {
    if (Load->getMetadata(LLVMContext::MD_range)) continue;
    MDBuilder Builder(Load->getContext());
    Load->setMetadata(LLVMContext::MD_range,
                      Builder.createRange(Range.getLower(), Range.getUpper()));
    Changed = true;
  }
  return Changed;
}

struct Candidate {
  AllocaInst *Array;
  Accesses Uses;
};

// An element-aligned copy into the array from another analyzed array moves
// that array's values; the copied range is that array's hull.
static ConstantRange copiedRange(MemIntrinsic &Write, Type *Element, uint64_t ElementSize,
                                 const DenseMap<AllocaInst *, ConstantRange> &Hulls,
                                 const DataLayout &Layout) {
  unsigned Width = Element->getIntegerBitWidth();
  auto *Copy = dyn_cast<MemTransferInst>(&Write);
  if (!Copy) return ConstantRange::getFull(Width);
  auto *Source = dyn_cast<AllocaInst>(getUnderlyingObject(Copy->getRawSource()));
  auto Known = Source ? Hulls.find(Source) : Hulls.end();
  if (Known == Hulls.end() ||
      cast<ArrayType>(Source->getAllocatedType())->getElementType() != Element)
    return ConstantRange::getFull(Width);
  APInt Offset(Layout.getIndexTypeSizeInBits(Copy->getRawSource()->getType()), 0);
  Value *Base = Copy->getRawSource()->stripAndAccumulateConstantOffsets(Layout, Offset, true);
  unsigned Zeros = computeKnownBits(Copy->getLength(), Layout).countMinTrailingZeros();
  if (Base != Source || Offset.urem(ElementSize) != 0 ||
      (Zeros < 64 && (uint64_t(1) << Zeros) % ElementSize != 0))
    return ConstantRange::getFull(Width);
  return Known->second;
}

static unsigned annotateFunctionArrayRanges(Function &F, FunctionAnalysisManager &Analyses) {
  const DataLayout &Layout = F.getParent()->getDataLayout();
  SmallVector<Candidate, 8> Candidates;
  for (Instruction &Instruction : F.getEntryBlock()) {
    auto *Array = dyn_cast<AllocaInst>(&Instruction);
    auto *Type = Array ? dyn_cast<ArrayType>(Array->getAllocatedType()) : nullptr;
    if (!Type || !Type->getElementType()->isIntegerTy() || !Array->isStaticAlloca())
      continue;
    Candidate Next{Array, Accesses()};
    if (collect(Array, Type->getElementType(),
                Layout.getTypeAllocSize(Type->getElementType()).getFixedValue(), Layout,
                Next.Uses, 0, true) &&
        (Next.Uses.Filled || Array->getMetadata(WrittenPrefix)) && Next.Uses.Views.empty())
      Candidates.push_back(std::move(Next));
  }
  if (Candidates.empty()) return 0;
  auto &Evolution = Analyses.getResult<ScalarEvolutionAnalysis>(F);
  auto &Values = Analyses.getResult<LazyValueAnalysis>(F);
  auto &Tree = Analyses.getResult<DominatorTreeAnalysis>(F);
  auto &Assumptions = Analyses.getResult<AssumptionAnalysis>(F);
  // Arrays written only by stores first, so copies can read their hulls.
  DenseMap<AllocaInst *, ConstantRange> Hulls;
  for (bool Copied : {false, true})
    for (Candidate &Target : Candidates) {
      if (Target.Uses.Writes.empty() == Copied) continue;
      auto *Element = cast<ArrayType>(Target.Array->getAllocatedType())->getElementType();
      unsigned Width = Element->getIntegerBitWidth();
      uint64_t ElementSize = Layout.getTypeAllocSize(Element).getFixedValue();
      ConstantRange Range = Bounds(Target.Uses, Evolution, Values, Tree, Assumptions).hull(Width);
      for (MemIntrinsic *Write : Target.Uses.Writes)
        Range = Range.unionWith(copiedRange(*Write, Element, ElementSize, Hulls, Layout),
                                ConstantRange::Signed);
      Hulls.try_emplace(Target.Array, Range);
    }
  unsigned Changed = 0;
  for (Candidate &Target : Candidates)
    if (auto Hull = Hulls.find(Target.Array); Hull != Hulls.end())
      Changed += annotate(Target.Uses, Hull->second);
  return Changed;
}

// A second round lets an array filled by copying from another bounded array
// (`matrix <- squared`) see that array's freshly annotated loads.
static unsigned annotateArrayValueRanges(Module &Module) {
  PassBuilder Builder;
  FunctionAnalysisManager Analyses;
  Builder.registerFunctionAnalyses(Analyses);
  unsigned Changed = 0;
  for (Function &F : Module) {
    if (F.isDeclaration()) continue;
    for (unsigned Round = 0; Round < 2; ++Round) {
      unsigned Annotated = annotateFunctionArrayRanges(F, Analyses);
      Analyses.invalidate(F, PreservedAnalyses::none());
      Changed += Annotated;
      if (!Annotated) break;
    }
  }
  return Changed;
}
} // namespace ElisaArrayRanges
