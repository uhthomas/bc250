// Ghidra script: print actual caller functions for the pinned BC250 SMU image.
// Import output/video-decode-20260922/results/smu-sram.bin as Xtensa LE at
// base 0, analyze it, then run this script with one output-file argument.
// The output distinguishes a direct call from a merely nearby mailbox handler.
// @category BC250
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.FileWriter;

public class Bc250SmuPowerXrefs extends GhidraScript {
    private static final long[] TARGETS = {
        0x23b14, 0x2362c, 0x23744, 0x246a8, 0x246c8,
        0x24748, 0x24764, 0x246f4, 0x247e8
    };

    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1)
            throw new IllegalArgumentException("output path required");
        var functions = currentProgram.getFunctionManager();
        var references = currentProgram.getReferenceManager();
        var listing = currentProgram.getListing();
        try (FileWriter writer = new FileWriter(arguments[0], false)) {
            for (long target : TARGETS) {
                writer.write("\n=== TARGET 0x" + Long.toHexString(target) + " " +
                    functions.getFunctionAt(toAddr(target)) + " ===\n");
                for (Reference reference : references.getReferencesTo(toAddr(target))) {
                    var at = reference.getFromAddress();
                    Function owner = functions.getFunctionContaining(at);
                    writer.write(at + " type=" + reference.getReferenceType() +
                        " owner=" + owner + " ins=" + listing.getInstructionAt(at) + "\n");
                }
            }
        }
    }
}
