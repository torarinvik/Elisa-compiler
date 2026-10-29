// Attach a debug record to an LLVM instruction for the split-half rejection test.
#include <llvm/Config/llvm-config.h>
#include <llvm/IR/BasicBlock.h>
#include <llvm/IR/DebugProgramInstruction.h>
#include <llvm/IR/Instruction.h>
#include <llvm/IR/Metadata.h>

extern "C" void split_test_attach_debug_record(void *value) {
  auto *instruction = static_cast<llvm::Instruction *>(value);
  auto *node = llvm::MDNode::get(instruction->getContext(), {});
#if LLVM_VERSION_MAJOR >= 23
  auto *record = llvm::DbgLabelRecord::createUnresolvedDbgLabelRecord(node);
#else
  auto *record = llvm::DbgLabelRecord::createUnresolvedDbgLabelRecord(node, node);
#endif
  instruction->getParent()->insertDbgRecordBefore(record, instruction->getIterator());
}
