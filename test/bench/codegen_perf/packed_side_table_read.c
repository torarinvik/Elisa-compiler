#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { RECORD_COUNT = 65536, CHUNK_RECORDS = 256, CHUNK_COUNT = RECORD_COUNT / CHUNK_RECORDS, READ_PASSES = 256 };

typedef struct {
    uint32_t tag;
    uint32_t payload_low;
    uint32_t payload_high;
} Record;

typedef struct {
    Record *items;
} RecordChunk;

typedef struct {
    volatile uint64_t *words;
} SideChunk;

#if defined(__clang__) || defined(__GNUC__)
#define NOINLINE __attribute__((noinline))
#else
#define NOINLINE
#endif

static NOINLINE void store_side(
    SideChunk *chunks, const uint64_t *words, uint32_t index, size_t count, size_t side_words
) {
    if (chunks == NULL) abort();
    if (side_words == 0) return;
    const size_t index_usize = (size_t)index;
    if (index_usize >= count) abort();
    const size_t chunk_index = index_usize / CHUNK_RECORDS;
    const size_t offset = (index_usize - chunk_index * CHUNK_RECORDS) * side_words;
    for (size_t word = 0; word < side_words; ++word) {
        chunks[chunk_index].words[offset + word] = words[word];
    }
}

static NOINLINE uint64_t load_side(
    const SideChunk *chunks, uint32_t index, size_t count, size_t side_words, size_t word_offset
) {
    if (chunks == NULL) abort();
    const size_t index_usize = (size_t)index;
    if (index_usize >= count) abort();
    if (word_offset >= side_words) abort();
    const size_t chunk_index = index_usize / CHUNK_RECORDS;
    const size_t offset = (index_usize - chunk_index * CHUNK_RECORDS) * side_words;
    return chunks[chunk_index].words[offset + word_offset];
}

static NOINLINE uint64_t checksum_records(const RecordChunk *records, size_t count) {
    uint64_t total = 0;
    for (size_t i = 0; i < count; ++i) {
        const size_t chunk_index = i / CHUNK_RECORDS;
        const size_t offset = i - chunk_index * CHUNK_RECORDS;
        const Record *record = &records[chunk_index].items[offset];
        if (record->tag == 1) {
            const uint64_t payload = ((uint64_t)record->payload_high << 32) | record->payload_low;
            total += (uint64_t)record->tag + payload;
        }
    }
    return total;
}

int main(void) {
    RecordChunk *records = calloc(CHUNK_COUNT, sizeof(*records));
    SideChunk *side = calloc(CHUNK_COUNT, sizeof(*side));
    uint32_t *handles = malloc(RECORD_COUNT * sizeof(*handles));
    if (records == NULL || side == NULL || handles == NULL) return 1;

    for (size_t chunk = 0; chunk < CHUNK_COUNT; ++chunk) {
        records[chunk].items = malloc(CHUNK_RECORDS * sizeof(*records[chunk].items));
        side[chunk].words = malloc(CHUNK_RECORDS * sizeof(*side[chunk].words));
        if (records[chunk].items == NULL || side[chunk].words == NULL) return 1;
    }

    for (size_t i = 0; i < RECORD_COUNT; ++i) {
        const size_t chunk_index = i / CHUNK_RECORDS;
        const size_t offset = i - chunk_index * CHUNK_RECORDS;
        const uint64_t stamp = (uint64_t)i + 1;
        const uint64_t words[1] = {stamp};
        memset(&records[chunk_index].items[offset], 0, sizeof(Record));
        records[chunk_index].items[offset].tag = 1;
        records[chunk_index].items[offset].payload_low = (uint32_t)i;
        records[chunk_index].items[offset].payload_high = (uint32_t)((uint64_t)i >> 32);
        store_side(side, words, (uint32_t)i, i + 1, 1);
        handles[i] = (uint32_t)i;
    }

    uint64_t total = 0;
    for (size_t pass = 0; pass < READ_PASSES; ++pass) {
        for (size_t i = 0; i < RECORD_COUNT; ++i) {
            total += load_side(side, handles[i], RECORD_COUNT, 1, 0);
        }
    }
    total += checksum_records(records, RECORD_COUNT);

    printf("%llu\n", (unsigned long long)total);
    const int status = (int)(total % 251);
    for (size_t chunk = 0; chunk < CHUNK_COUNT; ++chunk) {
        free(records[chunk].items);
        free((void *)side[chunk].words);
    }
    free(records);
    free(side);
    free(handles);
    return status;
}
