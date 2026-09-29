// Exercise assembled SMU read/write probes and the native queue ABI offline.
// @category BC250
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.listing.Instruction;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import com.google.gson.*;

public class TestSmuDirectClockProbe extends GhidraScript {
    static final long BASE = 0x240, TARGET = 0x0116f200, STACK = 0x800000;
    static final String BODY_SHA = "96a04591f18bf0e2a9d04b15ee757afd1501fbdd2e93a97c26f55cf78d598cd6";
    static final String WRITE_SHA = "eafebd45e986ab1cc1f48cfe33054942cf794ab6e27caa2d7b00f06b9957283c";
    byte[] source, body;
    List<Map<String,Object>> cases = new ArrayList<>();
    Map<Long,Instruction> instructions = new HashMap<>();

    String hex(long value) { return String.format("0x%08x", value & 0xffffffffL); }
    void require(boolean condition, String message) throws Exception {
        if (!condition) throw new Exception(message);
    }
    long reg(EmulatorHelper e, int n) { return e.readRegister("a"+n).longValue() & 0xffffffffL; }
    void reg(EmulatorHelper e, int n, long value) { e.writeRegister("a"+n, value & 0xffffffffL); }
    long word(EmulatorHelper e, long address) {
        byte[] b = e.readMemory(toAddr(address), 4);
        return (b[0]&255L)|((b[1]&255L)<<8)|((b[2]&255L)<<16)|((b[3]&255L)<<24);
    }
    void word(EmulatorHelper e, long address, long value) {
        e.writeMemory(toAddr(address), new byte[]{(byte)value,(byte)(value>>8),(byte)(value>>16),(byte)(value>>24)});
    }
    void pc(EmulatorHelper e, long address) {
        e.writeRegister(currentProgram.getLanguage().getProgramCounter(), address);
    }
    Instruction instruction(long address) throws Exception {
        Instruction i = instructions.get(address);
        if (i != null) return i;
        i = getInstructionAt(toAddr(address));
        if (i == null) { disassemble(toAddr(address)); i = getInstructionAt(toAddr(address)); }
        require(i != null, "missing instruction at " + hex(address));
        instructions.put(address, i);
        return i;
    }
    class Frame {
        long[] saved = new long[16]; long next;
        Frame(EmulatorHelper e, long address) {
            next = address;
            for (int n=0;n<16;n++) saved[n] = reg(e,n);
        }
    }
    void runCase(String name, int queue, long argument, long targetValue,
                 long expectedStatus, long expectedResult, long expectedTarget) throws Exception {
        EmulatorHelper e = new EmulatorHelper(currentProgram);
        Deque<Frame> frames = new ArrayDeque<>();
        List<String> calls = new ArrayList<>();
        try {
            e.writeMemory(toAddr(0), source);
            e.writeMemory(toAddr(BASE), body);
            word(e,0x230,TARGET);
            word(e,TARGET,targetValue);
            e.writeMemory(toAddr(STACK-0x10000),new byte[0x10000]);
            for(int n=0;n<5;n++) {
                long task=0x600000+n*0x100;
                e.writeMemory(toAddr(task),new byte[0x100]);
                word(e,0xaec8+n*4,task);
                e.writeMemory(toAddr(task+0x28),new byte[]{1,3,3});
            }
            word(e,0xaec0,0x600000);
            long arg=word(e,0x7000+queue*12+12), rsp=word(e,0x7000+queue*12+16);
            word(e,arg,argument);word(e,rsp,0);
            for(int n=0;n<16;n++)reg(e,n,0);
            reg(e,1,STACK);reg(e,2,queue);e.writeRegister("PS",0x40020);pc(e,BASE);
            boolean returned=false;int steps=0;
            for(;steps<3000;steps++) {
                long address=e.getExecutionAddress().getOffset();
                Instruction i=instruction(address);String op=i.getMnemonicString();long next=address+i.getLength();
                if(op.equals("entry")) { reg(e,1,reg(e,1)-i.getScalar(1).getUnsignedValue());pc(e,next);continue; }
                if(op.equals("memw")) {pc(e,next);continue;}
                if(op.equals("call8")) {
                    long target=i.getAddress(0).getOffset();
                    require(Set.of(0xffcL,0xfe4L,0xfa8L).contains(target),"unexpected native call");
                    calls.add(hex(target));Frame f=new Frame(e,next);frames.push(f);
                    for(int n=0;n<8;n++)reg(e,n,f.saved[n+8]);
                    reg(e,0,0x80000000L|next);reg(e,1,f.saved[1]);
                    for(int n=8;n<16;n++)reg(e,n,0);
                    pc(e,target);continue;
                }
                if(op.startsWith("retw")) {
                    if(frames.isEmpty()) { returned=true;break; }
                    long[] ret=new long[8];for(int n=0;n<8;n++)ret[n]=reg(e,n);
                    Frame f=frames.pop();
                    for(int n=0;n<8;n++)reg(e,n,f.saved[n]);
                    for(int n=0;n<8;n++)reg(e,n+8,ret[n]);
                    pc(e,f.next);continue;
                }
                require(!op.startsWith("call")&&!op.startsWith("loop"),"unmodeled instruction");
                require(e.step(monitor),"emulation failed at " + hex(address) + ": " + e.getLastError());
            }
            require(returned,"handler did not return");
            require(word(e,rsp)==expectedStatus && word(e,arg)==expectedResult,
                    name + ": wrong queue result " + hex(word(e,rsp)) + "/" + hex(word(e,arg)));
            require(word(e,TARGET)==expectedTarget,"wrong target result");
            require(word(e,0x230)==TARGET,"probe modified literal");
            require(e.readRegister("PS").longValue()==0x40020,"processor state changed");
            require(calls.equals(queue==3 ? List.of(hex(0xffc),hex(0xfe4),hex(0xfa8)) :
                    List.of(hex(0xfe4),hex(0xfa8))),
                    "unexpected native call sequence");
            Map<String,Object> row=new LinkedHashMap<>();
            row.put("case",name);row.put("queue",queue);row.put("argument",hex(argument));
            row.put("target_before",hex(targetValue));row.put("target_after",hex(word(e,TARGET)));
            row.put("result",hex(word(e,arg)));
            row.put("steps",steps);row.put("calls",calls);row.put("passed",true);
            cases.add(row);println("PASS " + name);
        } finally { e.dispose(); }
    }
    @Override
    public void run() throws Exception {
        Path root=Path.of(getScriptArgs()[0]);Path out=Path.of(getScriptArgs()[1]);
        String mode=getScriptArgs().length>2?getScriptArgs()[2]:"read";
        require(mode.equals("read")||mode.equals("write"),"invalid test mode");
        String stem=mode.equals("read")?"smu-direct-clock-probe":"smu-direct-clock-write";
        source=Files.readAllBytes(root.resolve("output/video-decode-20260922/results/smu-sram.bin"));
        body=Files.readAllBytes(out.resolve(stem+".bin"));
        String bodySha=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
        require(bodySha.equals(mode.equals("read")?BODY_SHA:WRITE_SHA) &&
                body.length==(mode.equals("read")?72:90),"unexpected probe binary");
        byte[] imported=new byte[source.length];currentProgram.getMemory().getBytes(toAddr(0),imported);
        require(Arrays.equals(imported,source),"wrong Ghidra source");
        clearListing(toAddr(BASE),toAddr(BASE+body.length-1));
        currentProgram.getMemory().setBytes(toAddr(BASE),body);disassemble(toAddr(BASE));
        runCase("signature",3,0x40,0,1,0x02500016L,0);
        if(mode.equals("read")) {
            runCase("read-zero",3,0x41,0,1,0,0);
            runCase("read-one",3,0x41,1,1,1,1);
            runCase("read-all-ones",3,0x41,0xffffffffL,1,0xffffffffL,0xffffffffL);
        } else {
            runCase("write-zero-idempotent",3,0x42,0,1,0,0);
            runCase("write-one",3,0x43,0,1,1,1);
            runCase("write-zero-from-one",3,0x42,1,1,0,0);
        }
        runCase("reject-other",3,0x106,0,0xff,0xffffffffL,0);
        runCase("reject-queue",4,mode.equals("read")?0x41:0x43,0,0xff,0xffffffffL,0);
        Map<String,Object> report=new LinkedHashMap<>();
        report.put("body_sha256",bodySha);report.put("mode",mode);report.put("cases",cases);
        report.put("installed",false);report.put("silicon_access_modeled",false);
        Files.writeString(out.resolve(stem+"-tests.json"),
                new GsonBuilder().setPrettyPrinting().create().toJson(report)+"\n");
        println("SMU_DIRECT_CLOCK_PROBE_TESTS_COMPLETE " + cases.size());
    }
}
