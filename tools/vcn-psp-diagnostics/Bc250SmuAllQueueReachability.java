// Audit direct static calls from all BC250 SMU queue handlers to domain-6 code.
// Import the pinned 256 KiB smu-sram.bin as Xtensa LE at base zero and analyze.
// Run this script read-only with one output-file argument.
// Dynamic dispatch, data-dependent callbacks, and writes through function
// pointers are outside this static-call audit.
// @category BC250
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Reference;
import java.io.FileWriter;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.Map;
import java.util.Set;
import java.security.MessageDigest;

public class Bc250SmuAllQueueReachability extends GhidraScript {
    private static final String IMAGE_SHA256 =
        "b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0";
    private static final long[] TABLES = {0x706c, 0x725c, 0x72e4, 0x7464, 0x7464};
    private static final int[] COUNTS = {0x3e, 0x11, 0x30, 0xa9, 0xa9};
    private static final long[] TARGETS = {
        0x23b14, // generic power-domain transition
        0x2362c, // generic slot clock programming, may power up a domain
        0x23744, // restore a slot's remembered clock
        0x2375c, // slot divider/deep-sleep programming
        0x24764  // domain-6 shutdown
    };

    private static class Edge {
        final long callee;
        final long at;
        Edge(long callee, long at) { this.callee = callee; this.at = at; }
    }

    @Override
    public void run() throws Exception {
        if (getScriptArgs().length != 1)
            throw new IllegalArgumentException("output path required");
        Memory memory = currentProgram.getMemory();
        if (memory.getSize() != 262144)
            throw new IllegalStateException("expected 256 KiB SMU SRAM");
        byte[] image = new byte[262144];
        if (memory.getBytes(toAddr(0), image) != image.length ||
            !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(image))
                .equals(IMAGE_SHA256))
            throw new IllegalStateException("SMU image hash changed");
        long dispatchMeta = Integer.toUnsignedLong(memory.getInt(toAddr(0xb88)));
        long countMeta = Integer.toUnsignedLong(memory.getInt(toAddr(0xb84)));
        for (int q = 0; q < TABLES.length; q++) {
            if (Integer.toUnsignedLong(memory.getInt(toAddr(dispatchMeta + 0x1fc + q * 4))) != TABLES[q] ||
                Short.toUnsignedInt(memory.getShort(toAddr(countMeta + 0xfc + q * 2))) != COUNTS[q])
                throw new IllegalStateException("Queue-" + q + " dispatch layout changed");
        }
        if (Integer.toUnsignedLong(memory.getInt(toAddr(TABLES[0] + 0x0c * 8))) != 0x22ab4 ||
            Integer.toUnsignedLong(memory.getInt(toAddr(TABLES[3] + 0x09 * 8))) != 0)
            throw new IllegalStateException("known Queue-0/3 entries changed");
        var functions = currentProgram.getFunctionManager();
        var references = currentProgram.getReferenceManager();
        try (FileWriter out = new FileWriter(getScriptArgs()[0], false)) {
            out.write("BC250 SMU all-queue direct static-call reachability\n");
            out.write("program=" + currentProgram.getName() +
                " bytes=" + memory.getSize() + " sha256=" + IMAGE_SHA256 + "\n");
            for (int q = 0; q < TABLES.length; q++)
                out.write(String.format("queue=%d table=0x%05x count=0x%x\n",
                    q, TABLES[q], COUNTS[q]));
            for (long target : TARGETS) {
                var seen = new HashSet<Long>();
                var next = new ArrayDeque<Long>();
                var edges = new HashMap<Long, Edge>();
                seen.add(target);
                next.add(target);
                while (!next.isEmpty()) {
                    long callee = next.removeFirst();
                    for (Reference ref : references.getReferencesTo(toAddr(callee))) {
                        if (!ref.getReferenceType().isCall()) continue;
                        Address from = ref.getFromAddress();
                        Function caller = functions.getFunctionContaining(from);
                        if (caller == null) continue;
                        long entry = caller.getEntryPoint().getOffset();
                        if (seen.add(entry)) {
                            edges.put(entry, new Edge(callee, from.getOffset()));
                            next.addLast(entry);
                        }
                    }
                }
                out.write(String.format("\nTARGET 0x%05x static_ancestors=%d\n", target, seen.size() - 1));
                int matches = 0;
                for (int q = 0; q < TABLES.length; q++) {
                    for (int msg = 1; msg < COUNTS[q]; msg++) {
                        long at = TABLES[q] + (long)msg * 8;
                        long handler = Integer.toUnsignedLong(memory.getInt(toAddr(at)));
                        long flags = Integer.toUnsignedLong(memory.getInt(toAddr(at + 4)));
                        if (!seen.contains(handler) || handler == 0) continue;
                        matches++;
                        out.write(String.format("queue=%d message=0x%02x handler=0x%05x flags=0x%x",
                            q, msg, handler, flags));
                        long path = handler;
                        Set<Long> guard = new HashSet<>();
                        while (path != target && guard.add(path)) {
                            Edge edge = edges.get(path);
                            if (edge == null) {
                                out.write(" -> unresolved");
                                break;
                            }
                            out.write(String.format(" --call@0x%05x--> 0x%05x", edge.at, edge.callee));
                            path = edge.callee;
                        }
                        out.write("\n");
                    }
                }
                out.write("matching_messages=" + matches + "\n");
            }
        }
    }
}
