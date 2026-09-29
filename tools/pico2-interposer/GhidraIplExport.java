// Export decompiled functions from a private, read-only IPL Ghidra project.
// Headless: -postScript GhidraIplExport.java /tmp/ipl-decompile.txt
// @category BC250
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.FileWriter;

public class GhidraIplExport extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) throw new IllegalArgumentException("pass one local output path");
        var functions = currentProgram.getFunctionManager();
        println("IPL_FUNCTION_COUNT=" + functions.getFunctionCount());
        for (long address : new long[] {0, 0x3c0, 0x44cd})
            println("IPL_FUNCTION_AT_" + Long.toHexString(address) + "=" +
                    functions.getFunctionContaining(toAddr(address)));

        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (FileWriter writer = new FileWriter(arguments[0], false)) {
            FunctionIterator iterator = functions.getFunctions(true);
            while (iterator.hasNext()) {
                Function function = iterator.next();
                DecompileResults result = decompiler.decompileFunction(function, 15, monitor);
                writer.write("\n/* " + function.getEntryPoint() + " " + function.getName() + " */\n");
                if (result.decompileCompleted() && result.getDecompiledFunction() != null)
                    writer.write(result.getDecompiledFunction().getC());
                else
                    writer.write("/* decompile failed: " + result.getErrorMessage() + " */\n");
            }
        } finally {
            decompiler.dispose();
        }
    }
}
