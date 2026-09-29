// Disassemble candidate VCN 2.0 bootstrap addresses in the pinned raw ucode.
// Import only the firmware payload (after the 0x100 common header) at base 0
// as Xtensa:LE:32:default, with autoanalysis disabled for this focused probe.
// @category BC250
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class GhidraVcnEntryProbe extends GhidraScript {
    @Override
    public void run() throws Exception {
        if (currentProgram.getMemory().getSize() != 0x630c0)
            throw new IllegalStateException("unexpected VCN payload size");
        for (long pc : new long[] {0, 0x100, 0x200, 0x240, 0x280,
                                   0x2a0, 0x2c0, 0x300, 0x320,
                                   0x340, 0x3f0, 0x400, 0x440, 0x480,
                                   0x4c0, 0x500, 0x540, 0x580,
                                   0x1b40, 0xf208, 0xf31b}) {
            Address entry = toAddr(pc);
            boolean ok = disassemble(entry);
            println("VCN_ENTRY " + entry + " disassembled=" + ok);
            Instruction instruction = currentProgram.getListing().getInstructionAt(entry);
            int limit = pc == 0x280 ? 220 : 12;
            long end = pc == 0x280 ? 0x500 : pc + 0x25;
            for (int i = 0; i < limit && instruction != null &&
                            instruction.getAddress().getOffset() < end;
                            ++i) {
                println("VCN_INSN " + instruction.getAddress() + " " + instruction);
                instruction = instruction.getNext();
            }
        }
    }
}
