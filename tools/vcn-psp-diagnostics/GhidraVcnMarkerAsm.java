// Assemble a small VCN VCPU write-and-loop diagnostic at BO offset 0xf208.
// Import the pinned raw VCN payload at base 0 as Xtensa:LE:32:default.
// This only generates bytes for an opt-in GPU-buffer trial.
// @category BC250
import ghidra.app.plugin.assembler.Assembler;
import ghidra.app.plugin.assembler.Assemblers;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class GhidraVcnMarkerAsm extends GhidraScript {
    @Override
    public void run() throws Exception {
        if (currentProgram.getMemory().getSize() != 0x630c0)
            throw new IllegalStateException("unexpected VCN payload size");
        Address entry = toAddr(0xf208);
        Assembler assembler = Assemblers.getAssembler(currentProgram);
        assembler.assemble(entry,
            "l32r a2,0x0000e200",
            "l32r a3,0x0000e204",
            "s32i a3,a2,0x0",
            "j 0x0000f211");
        byte[] bytes = new byte[12];
        currentProgram.getMemory().getBytes(entry, bytes);
        StringBuilder hex = new StringBuilder();
        for (byte value : bytes)
            hex.append(String.format("%02x", value & 0xff));
        println("VCN_MARKER_BYTES " + hex);
        for (int i = 0; i < 4; ++i) {
            Instruction instruction = currentProgram.getListing().getInstructionAt(entry);
            if (instruction == null)
                throw new IllegalStateException("missing assembled instruction " + entry);
            println("VCN_MARKER_INSN " + entry + " " + instruction);
            entry = entry.add(instruction.getLength());
        }
    }
}
