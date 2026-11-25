"""IR shapes for the view fills, shared by their test.

`view-fills` shrinks the zero fill of a local integer array used only through one view
`{ptr, i64}` of its first `length` elements to those elements, when the length fits the
array and every access through the view, here or in a helper the view is passed to,
stays below the length. The fixture fills a 64 x i32 buffer, views its first
`min(n, 64)` elements and hands the view to a helper that stores 1 into each of them;
each case varies one part, and its numbers are what the C++ pass did with the same
shape (see EXPECTED).
"""
TRIPLE = 'arm64-apple-darwin'
HEADER = f'target triple = "{TRIPLE}"\n@sink = global ptr null\ndeclare void @opaque({{ ptr, i64 }})\n'

HELPER = '''define void @helper({ ptr, i64 } %view) {
entry:
  %data = extractvalue { ptr, i64 } %view, 0
  %length = extractvalue { ptr, i64 } %view, 1
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %slot = getelementptr i32, ptr %data, i64 %i
  BODY
  %next = add nuw i64 %i, 1
  %more = icmp ult i64 %next, %length
  br i1 %more, label %loop, label %done
done:
  ret void
}
'''
STORE = 'store i32 1, ptr %slot'

CALLER = '''define void @caller(i64 %n) {
entry:
  %buffer = alloca [64 x i32]
  FILL
  %length = call i64 @llvm.umin.i64(i64 %n, i64 64)
  %data = insertvalue { ptr, i64 } undef, ptr %buffer, 0
  %view = insertvalue { ptr, i64 } %data, i64 %length, 1
  USE
  ret void
}
'''
FILL = 'call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 256, i1 false)'
USE = 'call void @helper({ ptr, i64 } %view)'


def module(helper=STORE, fill=FILL, use=USE, caller=None, extra=''):
    """The fixture with the helper's loop BODY, the caller's FILL and USE replaced."""
    text = caller if caller is not None else CALLER.replace('FILL', fill).replace('USE', use)
    return HEADER + HELPER.replace('BODY', helper) + text + extra


def varied(text, *replacements):
    """TEXT with each (old, new) replacement made everywhere."""
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text


COUNT_BESIDE = '''define void @counted({ ptr, i64 } %view, i64 %count) {
entry:
  %data = extractvalue { ptr, i64 } %view, 0
  %empty = icmp eq i64 %count, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %slot = getelementptr i32, ptr %data, i64 %i
  store i32 1, ptr %slot
  %next = add nuw i64 %i, 1
  %more = icmp ult i64 %next, %count
  br i1 %more, label %loop, label %done
done:
  ret void
}
'''
RECURSIVE = '''define void @halves({ ptr, i64 } %view) {
entry:
  %data = extractvalue { ptr, i64 } %view, 0
  %length = extractvalue { ptr, i64 } %view, 1
  %small = icmp ult i64 %length, 2
  br i1 %small, label %done, label %split
split:
  store i32 1, ptr %data
  %half = lshr i64 %length, 1
  %shorter = insertvalue { ptr, i64 } %view, i64 %half, 1
  call void @halves({ ptr, i64 } %shorter)
  br label %done
done:
  ret void
}
'''
FIELDS = '''define void @fields({ ptr, i64 } %view) {
entry:
  %data = extractvalue { ptr, i64 } %view, 0
  %length = extractvalue { ptr, i64 } %view, 1
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %done, label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %loop]
  %element = getelementptr i64, ptr %data, i64 %i
  %high = getelementptr i8, ptr %element, i64 4
  store i32 7, ptr %high
  %next = add nuw i64 %i, 1
  %more = icmp ult i64 %next, %length
  br i1 %more, label %loop, label %done
done:
  ret void
}
'''
COPY = '''define void @copied({ ptr, i64 } %view, ptr %source) {
entry:
  %data = extractvalue { ptr, i64 } %view, 0
  %length = extractvalue { ptr, i64 } %view, 1
  %bytes = shl nuw i64 %length, 2
  call void @llvm.memcpy.p0.p0.i64(ptr %data, ptr %source, i64 %bytes, i1 false)
  ret void
}
'''
AGAIN = '''define void @again({ ptr, i64 } %view, i64 %depth) {
entry:
  %data = extractvalue { ptr, i64 } %view, 0
  %length = extractvalue { ptr, i64 } %view, 1
  %empty = icmp eq i64 %length, 0
  br i1 %empty, label %done, label %write
write:
  store i32 1, ptr %data
  %deeper = icmp ugt i64 %depth, 0
  br i1 %deeper, label %recurse, label %done
recurse:
  %less = sub i64 %depth, 1
  call void @again({ ptr, i64 } %view, i64 %less)
  br label %done
done:
  ret void
}
'''
NESTED = '''define void @outer({ ptr, i64 } %view) {
entry:
  call void @helper({ ptr, i64 } %view)
  ret void
}
'''

CASES = {
    'shrunk': module(),
    'off-by-one': module(helper='%after = getelementptr i32, ptr %slot, i64 1\n  store i32 1, ptr %after'),
    'unbounded-length': varied(module(), ('%length = call i64 @llvm.umin.i64(i64 %n, i64 64)', '%length = add i64 %n, 0')),
    'constant-length': varied(module(), ('%length = call i64 @llvm.umin.i64(i64 %n, i64 64)\n', ''), ('i64 %length, 1', 'i64 16, 1')),
    'fill-in-loop': module(caller='''define void @caller(i64 %n) {
entry:
  %buffer = alloca [64 x i32]
  br label %again
again:
  %round = phi i64 [0, %entry], [%later, %again]
  call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 256, i1 false)
  %later = add i64 %round, 1
  %repeat = icmp ult i64 %later, 3
  br i1 %repeat, label %again, label %view
view:
  %length = call i64 @llvm.umin.i64(i64 %n, i64 64)
  %data = insertvalue { ptr, i64 } undef, ptr %buffer, 0
  %built = insertvalue { ptr, i64 } %data, i64 %length, 1
  call void @helper({ ptr, i64 } %built)
  ret void
}
'''),
    'direct-read': module(use='call void @helper({ ptr, i64 } %view)\n  %first = load i32, ptr %buffer\n  store i32 %first, ptr @sink'),
    'partial-fill': module(fill='call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 128, i1 false)'),
    'nonzero-fill': module(fill='call void @llvm.memset.p0.i64(ptr %buffer, i8 1, i64 256, i1 false)'),
    'volatile-fill': module(fill='call void @llvm.memset.p0.i64(ptr %buffer, i8 0, i64 256, i1 true)'),
    'aligned-fill': module(fill='call void @llvm.memset.p0.i64(ptr align 16 %buffer, i8 0, i64 256, i1 false)'),
    'lifetime-markers': module(fill='call void @llvm.lifetime.start.p0(ptr %buffer)\n  ' + FILL, use=USE + '\n  call void @llvm.lifetime.end.p0(ptr %buffer)'),
    'first-element-data': varied(module(), ('%data = insertvalue { ptr, i64 } undef, ptr %buffer, 0', '%first = getelementptr [64 x i32], ptr %buffer, i64 0, i64 0\n  %data = insertvalue { ptr, i64 } undef, ptr %first, 0')),
    'count-beside-view': module(use='%count = call i64 @llvm.umin.i64(i64 %n, i64 32)\n  call void @counted({ ptr, i64 } %view, i64 %count)', extra=COUNT_BESIDE),
    'count-too-large': module(use='call void @counted({ ptr, i64 } %view, i64 %n)', extra=COUNT_BESIDE),
    'count-is-length': module(use='call void @counted({ ptr, i64 } %view, i64 %length)', extra=COUNT_BESIDE),
    'recursive-same-view': module(use='call void @again({ ptr, i64 } %view, i64 %n)', extra=AGAIN),
    'recursive-helper': module(use='call void @halves({ ptr, i64 } %view)', extra=RECURSIVE),
    'field-access': varied(module(use='call void @fields({ ptr, i64 } %view)', extra=FIELDS),
                           ('%buffer = alloca [64 x i32]', '%buffer = alloca [64 x i64]'), ('i64 256, i1 false', 'i64 512, i1 false')),
    'copied-in': module(use='call void @copied({ ptr, i64 } %view, ptr @sink)', extra=COPY),
    'nested-helper': module(use='call void @outer({ ptr, i64 } %view)', extra=NESTED),
    'escaping-pointer': module(helper='store ptr %slot, ptr @sink'),
    'address-compare': module(helper='%address = ptrtoint ptr %slot to i64\n  %low = icmp ult i64 %address, 4096\n  %bit = zext i1 %low to i32\n  store i32 %bit, ptr %slot'),
    'address-escape': module(helper='%address = ptrtoint ptr %slot to i64\n  %back = inttoptr i64 %address to ptr\n  store i32 1, ptr %back'),
    'volatile-store': module(helper='store volatile i32 1, ptr %slot'),
    'declared-helper': module(use='call void @opaque({ ptr, i64 } %view)'),
    'slice-from-zero': varied(module(), ('%length = call i64 @llvm.umin.i64(i64 %n, i64 64)', '%high = call i64 @llvm.umin.i64(i64 %n, i64 64)\n  %positive = icmp uge i64 %high, 0\n  %chosen = select i1 %positive, i64 %high, i64 0\n  %length = sub i64 %chosen, 0')),
    'byte-buffer': varied(module(helper='store i8 1, ptr %slot'), ('%buffer = alloca [64 x i32]', '%buffer = alloca [64 x i8]'), ('i64 256, i1 false', 'i64 64, i1 false'),
                          ('getelementptr i32, ptr %data', 'getelementptr i8, ptr %data')),
    'two-buffers': module(caller='''define void @caller(i64 %n) {
entry:
  %first = alloca [64 x i32]
  %second = alloca [64 x i32]
  call void @llvm.memset.p0.i64(ptr %first, i8 0, i64 256, i1 false)
  call void @llvm.memset.p0.i64(ptr %second, i8 0, i64 256, i1 false)
  %length = call i64 @llvm.umin.i64(i64 %n, i64 64)
  %first.data = insertvalue { ptr, i64 } undef, ptr %first, 0
  %first.view = insertvalue { ptr, i64 } %first.data, i64 %length, 1
  call void @helper({ ptr, i64 } %first.view)
  %second.data = insertvalue { ptr, i64 } undef, ptr %second, 0
  %second.view = insertvalue { ptr, i64 } %second.data, i64 %length, 1
  call void @helper({ ptr, i64 } %second.view)
  ret void
}
'''),
    'optnone': varied(module(), ('define void @caller(i64 %n) {', 'define void @caller(i64 %n) noinline optnone {'), ('define void @helper({ ptr, i64 } %view) {', 'define void @helper({ ptr, i64 } %view) noinline optnone {')),
}

# Per case: the count of fills shrunk, the length operands of the module's memsets
# (sorted; a constant's value, else the instruction's name), and a second run's count.
EXPECTED = {
    'shrunk': (1, ['%view.fill.bytes'], 0),
    'off-by-one': (0, ['256'], 0),
    'unbounded-length': (0, ['256'], 0),
    'constant-length': (1, ['64'], 0),
    'fill-in-loop': (0, ['256'], 0),
    'direct-read': (0, ['256'], 0),
    'partial-fill': (0, ['128'], 0),
    'nonzero-fill': (0, ['256'], 0),
    'volatile-fill': (0, ['256'], 0),
    'aligned-fill': (1, ['%view.fill.bytes'], 0),
    'lifetime-markers': (1, ['%view.fill.bytes'], 0),
    'first-element-data': (1, ['%view.fill.bytes'], 0),
    'count-beside-view': (0, ['256'], 0),
    'count-too-large': (0, ['256'], 0),
    'count-is-length': (1, ['%view.fill.bytes'], 0),
    'recursive-same-view': (1, ['%view.fill.bytes'], 0),
    'recursive-helper': (0, ['256'], 0),
    'field-access': (1, ['%view.fill.bytes'], 0),
    'copied-in': (0, ['256'], 0),
    'nested-helper': (1, ['%view.fill.bytes'], 0),
    'escaping-pointer': (0, ['256'], 0),
    'address-compare': (0, ['256'], 0),
    'address-escape': (1, ['%view.fill.bytes'], 0),
    'volatile-store': (0, ['256'], 0),
    'declared-helper': (0, ['256'], 0),
    'slice-from-zero': (1, ['%view.fill.bytes'], 0),
    'byte-buffer': (1, ['%view.fill.bytes'], 0),
    'two-buffers': (2, ['%view.fill.bytes', '%view.fill.bytes1'], 0),
    'optnone': (0, ['256'], 0),
}
