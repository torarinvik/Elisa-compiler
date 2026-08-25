import loadWasm from "../../build/wasm-browser/elisa-demo.mjs";

const wasm = await loadWasm();
const answer: number = wasm.add_wasm(40, 2);
const echoed: string = wasm.wasm_echo_text("typed Elisa");
const buffer = wasm.writeBytes(Uint8Array.of(answer));
const copied: Uint8Array = wasm.readBytes(buffer.pointer, buffer.length);
wasm.free(buffer.pointer);

console.log(echoed, copied);
