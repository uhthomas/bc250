// Seed the entry of the hash-pinned, decompressed BC250 ABL3 image.
// Import the raw body at 0x54000 as ARM:LE:32:v7 before this pre-script.
// @category BC250
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class GhidraAbl3Seed extends GhidraScript {
    @Override
    public void run() throws Exception {
        Address entry = toAddr(0x54000);
        if (currentProgram.getMemory().getSize() != 85200)
            throw new IllegalStateException("unexpected ABL3 body size");
        if (!disassemble(entry))
            throw new IllegalStateException("could not disassemble ABL3 entry");
        if (getFunctionAt(entry) == null)
            createFunction(entry, "ABL3Entry");
        println("ABL3_SEED_COMPLETE " + entry);
    }
}
