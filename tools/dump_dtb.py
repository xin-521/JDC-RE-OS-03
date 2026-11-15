#!/usr/bin/env python3
"""Dump a flattened device tree (DTB) back to .dts source.

    python tools/dump_dtb.py reference/oem/board.dtb > /tmp/board.dts

Used on 2026-10-14 to read the OEM board.dtb: it is the authority for the
LED/button GPIOs, the WAN ge_phy wiring, the QCN6122 board data offsets and the
deliberate absence of qcom,dac-preset-short-cable.  A ready dump is committed as
reference/oem/board.dts.
"""
import struct, sys

FDT_BEGIN_NODE=1
FDT_END_NODE=2
FDT_PROP=3
FDT_NOP=4
FDT_END=9

def cstr(b, off):
    e=b.index(b'\0', off)
    return b[off:e].decode('utf-8','replace'), e+1

def read_u32(b, off):
    return struct.unpack('>I', b[off:off+4])[0], off+4

def main(path):
    d=open(path,'rb').read()
    magic=struct.unpack('>I',d[:4])[0]
    assert magic==0xd00dfeed, hex(magic)
    off_struct,off_strings,off_rsvmap,ver,lastcomp,boot,size_str,size_str=struct.unpack('>8I',d[8:40])
    strings=d[off_strings:]
    pos=off_struct
    depth=0
    lines=[]
    def ind(n): return '\t'*n
    while True:
        tok,pos=read_u32(d,pos)
        if tok==FDT_BEGIN_NODE:
            name,pos=cstr(d,pos)
            pos=(pos+3)&~3
            lines.append(ind(depth)+'%s {'%(name or '/'))
            depth+=1
        elif tok==FDT_END_NODE:
            depth-=1
            lines.append(ind(depth)+'};')
        elif tok==FDT_PROP:
            ln,pos=read_u32(d,pos)
            nameoff,pos=read_u32(d,pos)
            name,_=cstr(strings,nameoff)
            val=d[pos:pos+ln]; pos=(pos+ln+3)&~3
            if ln==0:
                lines.append(ind(depth)+'%s;'%name)
            elif ln%4==0 and ln<=16:
                vals=struct.unpack('>%dI'%(ln//4),val)
                # decide hex vs decimal
                lines.append(ind(depth)+'%s = <%s>;'%(name,' '.join('0x%x'%v for v in vals)))
            else:
                if all(32<=c<127 or c in (9,10,13,0) for c in val):
                    s=val.rstrip(b'\0').decode('utf-8','replace')
                    # multi-string properties carry interior NULs; escape them so
                    # the dump stays plain text (no NUL bytes, greppable, diffable)
                    s=s.replace('\\','\\\\').replace('"','\\"').replace('\x00','\\0')
                    lines.append(ind(depth)+'%s = "%s";'%(name,s))
                else:
                    lines.append(ind(depth)+'%s = [%s];'%(name,' '.join('%02x'%c for c in val)))
        elif tok==FDT_NOP:
            pass
        elif tok==FDT_END:
            break
    # write bytes so Windows does not turn every LF into CRLF
    sys.stdout.buffer.write(('\n'.join(lines) + '\n').encode('utf-8'))

main(sys.argv[1])
