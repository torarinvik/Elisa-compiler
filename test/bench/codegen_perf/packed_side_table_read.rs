use std::process;
use std::mem::MaybeUninit;

const RECORD_COUNT: usize = 65_536;
const CHUNK_RECORDS: usize = 256;
const CHUNK_COUNT: usize = RECORD_COUNT / CHUNK_RECORDS;
const READ_PASSES: usize = 256;
type SideChunk = Box<[MaybeUninit<u64>; CHUNK_RECORDS]>;
type RecordChunk = Box<[MaybeUninit<Record>; CHUNK_RECORDS]>;

#[derive(Clone, Copy)]
#[repr(C)]
struct Record {
    tag: u32,
    payload_low: u32,
    payload_high: u32,
}

#[inline(never)]
fn store_side(
    chunks: Option<&mut [SideChunk]>,
    words: &[u64],
    index: u32,
    count: usize,
    side_words: usize,
) {
    let Some(chunks) = chunks else {
        process::abort();
    };
    if side_words == 0 {
        return;
    }
    let index_usize = index as usize;
    if index_usize >= count {
        process::abort();
    }
    let chunk_index = index_usize / CHUNK_RECORDS;
    let offset = (index_usize - chunk_index * CHUNK_RECORDS) * side_words;
    unsafe {
        let slots = chunks.get_unchecked_mut(chunk_index).as_mut_ptr().cast::<u64>();
        for word in 0..side_words {
            std::ptr::write_volatile(
                slots.add(offset + word),
                *words.get_unchecked(word),
            );
        }
    }
}

#[inline(never)]
fn load_side(
    chunks: Option<&[SideChunk]>,
    index: u32,
    count: usize,
    side_words: usize,
    word_offset: usize,
) -> u64 {
    let Some(chunks) = chunks else {
        process::abort();
    };
    let index_usize = index as usize;
    if index_usize >= count {
        process::abort();
    }
    if word_offset >= side_words {
        process::abort();
    }
    let chunk_index = index_usize / CHUNK_RECORDS;
    let offset = (index_usize - chunk_index * CHUNK_RECORDS) * side_words;
    unsafe {
        let slots = chunks.get_unchecked(chunk_index).as_ptr().cast::<u64>();
        std::ptr::read_volatile(slots.add(offset + word_offset))
    }
}

#[inline(never)]
fn checksum_records(records: &[RecordChunk], count: usize) -> u64 {
    let mut total = 0;
    for i in 0..count {
        let chunk_index = i / CHUNK_RECORDS;
        let offset = i - chunk_index * CHUNK_RECORDS;
        let record = unsafe {
            records
                .get_unchecked(chunk_index)
                .get_unchecked(offset)
                .assume_init_ref()
        };
        if record.tag == 1 {
            let payload = u64::from(record.payload_low) | (u64::from(record.payload_high) << 32);
            total += u64::from(record.tag) + payload;
        }
    }
    total
}

fn main() {
    let mut records: Vec<RecordChunk> = (0..CHUNK_COUNT)
        .map(|_| Box::new([MaybeUninit::<Record>::uninit(); CHUNK_RECORDS]))
        .collect();
    let mut side: Vec<SideChunk> = (0..CHUNK_COUNT)
        .map(|_| Box::new([MaybeUninit::<u64>::uninit(); CHUNK_RECORDS]))
        .collect();
    let mut handles: Vec<u32> = Vec::with_capacity(RECORD_COUNT);

    for i in 0..RECORD_COUNT {
        let chunk_index = i / CHUNK_RECORDS;
        let offset = i - chunk_index * CHUNK_RECORDS;
        let stamp = i as u64 + 1;
        let payload_bits = i as u64;
        // RECORD_COUNT is exactly CHUNK_COUNT * CHUNK_RECORDS, so this loop's
        // quotient and remainder are within the collected chunk and fixed row.
        let record = unsafe {
            let record_ptr = records
                .get_unchecked_mut(chunk_index)
                .get_unchecked_mut(offset)
                .as_mut_ptr();
            std::ptr::write(
                record_ptr,
                Record { tag: 0, payload_low: 0, payload_high: 0 },
            );
            &mut *record_ptr
        };
        record.tag = 1;
        record.payload_low = payload_bits as u32;
        record.payload_high = (payload_bits >> 32) as u32;
        let words = [stamp];
        store_side(Some(&mut side[..]), &words, i as u32, i + 1, 1);
        handles.push(i as u32);
    }

    let mut total: u64 = 0;
    for _pass in 0..READ_PASSES {
        for &handle in &handles {
            total += load_side(Some(&side[..]), handle, RECORD_COUNT, 1, 0);
        }
    }
    total += checksum_records(&records, RECORD_COUNT);

    println!("{total}");
    drop(records);
    drop(side);
    drop(handles);
    process::exit((total % 251) as i32);
}
