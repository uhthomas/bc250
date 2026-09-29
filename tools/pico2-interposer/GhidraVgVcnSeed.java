// Seed the Van Gogh SMU's VCN power path in the pinned raw firmware image.
// Import at address zero as Xtensa:LE:32:default before this pre-script.
// @category BC250
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class GhidraVgVcnSeed extends GhidraScript {
    @Override
    public void run() throws Exception {
        if (currentProgram.getMemory().getSize() != 524800)
            throw new IllegalStateException("unexpected Van Gogh SMU image size");
        for (long pc : new long[] {0x2bf30, 0x26984}) {
            Address entry = toAddr(pc);
            if (!disassemble(entry))
                throw new IllegalStateException("could not disassemble " + entry);
            if (getFunctionAt(entry) == null)
                createFunction(entry, "VCN_Path_" + Long.toHexString(pc));
            println("VG_VCN_SEED " + entry);
        }
    }
}
