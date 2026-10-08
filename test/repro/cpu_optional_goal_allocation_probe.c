/* Test-only ABI observation of a caller-owned live AST store. No allocation,
   mutation, retained pointers, replacement runtime, or policy suppression. */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef struct { void *data; uint64_t count, capacity; } Array;
typedef struct { Array chunks; uint64_t count, record_bytes, chunk_records; Array side_chunks; uint64_t side_words, data_cursor, data_end; } AoS;
typedef struct { void *arena; uint64_t row_bytes; AoS *state; } Store;
_Static_assert(sizeof(AoS)==96,"coherent PackedAoSStore ABI");
_Static_assert(sizeof(Store)==24,"packed store carrier ABI");
_Static_assert(offsetof(AoS,count)==24,"allocation counter ABI");
int64_t oracle_store_count(uintptr_t bits) { const Store *store=(const Store*)bits; return store && store->state ? (int64_t)store->state->count : -1; }
bool oracle_store_layout_ok(uintptr_t bits) { const Store *store=(const Store*)bits; return store && store->arena && store->state && store->state->chunk_records==256 && store->row_bytes==store->state->record_bytes; }
