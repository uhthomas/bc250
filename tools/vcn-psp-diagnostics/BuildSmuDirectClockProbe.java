// Assemble the read-only or write-only direct SMU-core diagnostic offline.
// Import the pinned BC250 SMU SRAM image at base zero as Xtensa:LE:32:default.
// @category BC250
import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.assembler.Assembler;
import ghidra.app.plugin.assembler.Assemblers;
import java.io.ByteArrayOutputStream;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import com.google.gson.GsonBuilder;

public class BuildSmuDirectClockProbe extends GhidraScript {
    static final long BASE = 0x240, LITERAL = 0x230;
    static final String SOURCE_SHA = "b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0";

    String hex(long value) { return String.format("0x%08x", value); }
    void require(boolean condition, String message) throws Exception {
        if (!condition) throw new Exception(message);
    }

    @Override
    public void run() throws Exception {
        Path root = Path.of(getScriptArgs()[0]);
        Path outDir = Path.of(getScriptArgs()[1]);
        String mode = getScriptArgs().length > 2 ? getScriptArgs()[2] : "read";
        require(mode.equals("read") || mode.equals("write"), "unknown build mode");
        String stem = mode.equals("read") ? "smu-direct-clock-probe" : "smu-direct-clock-write";
        byte[] source = Files.readAllBytes(root.resolve("output/video-decode-20260922/results/smu-sram.bin"));
        String sourceSha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(source));
        require(source.length == 0x40000 && sourceSha.equals(SOURCE_SHA), "wrong SMU image");
        byte[] imported = new byte[source.length];
        currentProgram.getMemory().getBytes(toAddr(0), imported);
        require(Arrays.equals(imported, source), "Ghidra program differs from source");
        require(Arrays.equals(Arrays.copyOfRange(source, (int)LITERAL, 0x2f8), new byte[0xc8]),
                "temporary-code gap is not zero");

        List<String> instructions = new ArrayList<>();
        Map<String,Long> labels = new LinkedHashMap<>();
        long cursor = BASE;
        for (String raw : Files.readAllLines(root.resolve("tools/vcn-psp-diagnostics/" + stem + ".asm"))) {
            String line = raw.strip();
            if (line.isEmpty() || line.startsWith("#")) continue;
            if (line.endsWith(":")) {
                require(labels.put(line.substring(0, line.length()-1), cursor) == null, "duplicate label");
                continue;
            }
            instructions.add(line);
            cursor += line.split(" ")[0].endsWith(".n") ? 2 : 3;
        }
        require(cursor <= 0x2f8, "probe exceeds audited gap");
        Assembler assembler = Assemblers.getAssembler(currentProgram);
        ByteArrayOutputStream binary = new ByteArrayOutputStream();
        StringBuilder listing = new StringBuilder();
        cursor = BASE;
        for (String instruction : instructions) {
            String resolved = instruction;
            for (var label : labels.entrySet())
                resolved = resolved.replace("@" + label.getKey(), hex(label.getValue()));
            require(!resolved.contains("@"), "unresolved label");
            byte[] bytes;
            try {
                bytes = assembler.assembleLine(toAddr(cursor), resolved);
            } catch (Exception error) {
                throw new Exception("assembly failed at " + hex(cursor) + ": " + resolved, error);
            }
            int expected = resolved.split(" ")[0].endsWith(".n") ? 2 : 3;
            require(bytes.length == expected, "unexpected instruction length: " + resolved);
            binary.write(bytes);
            listing.append(hex(cursor)).append("  ").append(HexFormat.of().formatHex(bytes))
                   .append("  ").append(resolved).append('\n');
            cursor += bytes.length;
        }
        byte[] body = binary.toByteArray();
        Files.createDirectories(outDir);
        Files.write(outDir.resolve(stem + ".bin"), body);
        Files.writeString(outDir.resolve(stem + "-assembly.txt"), listing.toString());
        Map<String,Object> report = new LinkedHashMap<>();
        report.put("source_sha256", sourceSha);
        report.put("body_sha256", HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body)));
        report.put("body_size", body.length);
        report.put("mode", mode);
        report.put("entry", hex(BASE));
        report.put("literal_address", hex(LITERAL));
        report.put("literal_value", hex(0x0116f200));
        report.put("labels", labels);
        report.put("installed", false);
        Files.writeString(outDir.resolve(stem + "-build.json"),
                new GsonBuilder().setPrettyPrinting().create().toJson(report) + "\n");
        println("SMU_DIRECT_CLOCK_PROBE_BUILT " + body.length + " bytes");
    }
}
