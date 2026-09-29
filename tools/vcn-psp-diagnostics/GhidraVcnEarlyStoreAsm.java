// Check the three-byte self-loop at the instruction after the firmware's
// early bootstrap store. Import the pinned VCN payload at base 0 as
// Xtensa:LE:32:default. This changes only the temporary Ghidra import.
// @category BC250
import ghidra.app.plugin.assembler.Assembler;
import ghidra.app.plugin.assembler.Assemblers;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class GhidraVcnEarlyStoreAsm extends GhidraScript {
    @Override
    public void run() throws Exception {
        if (currentProgram.getMemory().getSize() != 0x630c0)
            throw new IllegalStateException("unexpected VCN payload size");
        Address entry = toAddr(0x456);
        Assembler assembler = Assemblers.getAssembler(currentProgram);
        assembler.assemble(entry, "j 0x00000456");
        byte[] bytes = new byte[3];
        currentProgram.getMemory().getBytes(entry, bytes);
        StringBuilder hex = new StringBuilder();
        for (byte value : bytes)
            hex.append(String.format("%02x", value & 0xff));
        Instruction instruction = currentProgram.getListing().getInstructionAt(entry);
        if (!"06ffff".equals(hex.toString()) || instruction == null ||
            !"j 0x00000456".equals(instruction.toString()))
            throw new IllegalStateException("early self-loop encoding changed: " +
                                            hex + " " + instruction);
        println("VCN_EARLY_LOOP_BYTES " + hex);
        println("VCN_EARLY_LOOP_INSN " + entry + " " + instruction);
    }
}
