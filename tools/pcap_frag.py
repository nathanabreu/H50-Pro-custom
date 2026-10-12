"""Lista os pacotes IPv4 de/para um IP num .pcapng, mostrando fragmentação (só biblioteca padrão).



    py tools/pcap_frag.py data/p7.pcapng <IP_DO_ROBO>

"""



import ipaddress

import struct

import sys





def blocks(data: bytes):

    off, endian = 0, "<"

    while off + 12 <= len(data):

        btype, blen = struct.unpack_from(endian + "II", data, off)

        if btype == 0x0A0D0D0A:  # Section Header: detecta endianness

            endian = "<" if data[off + 8 : off + 12] == b"\x4d\x3c\x2b\x1a" else ">"

            btype, blen = struct.unpack_from(endian + "II", data, off)

        yield btype, data[off + 8 : off + blen - 4], endian

        off += blen





def packets(path):

    links = []

    for btype, body, e in blocks(open(path, "rb").read()):

        if btype == 1:  # Interface Description

            links.append(struct.unpack_from(e + "H", body)[0])

        elif btype == 6:  # Enhanced Packet

            iface, _th, _tl, caplen, _olen = struct.unpack_from(e + "IIIII", body)

            yield links[iface] if iface < len(links) else 1, body[20 : 20 + caplen]





def dot11_ip(frame):
    """Quadro de dados 802.11 (Wi-Fi) -> pacote IPv4. O pktmon marca o link como Ethernet mesmo no Wi-Fi."""
    if len(frame) < 32 or frame[0] & 0x0C != 0x08:      # type 2 = dados
        return None
    hdr = 24 + (6 if frame[1] & 0x03 == 0x03 else 0)     # addr4 quando ToDS+FromDS
    if frame[0] & 0x80:                                  # subtype QoS
        hdr += 2
    if frame[1] & 0x80:                                  # campo +HTC
        hdr += 4
    llc = frame[hdr:hdr + 8]
    if llc[:3] == bytes.fromhex("aaaa03") and llc[6:8] == bytes.fromhex("0800"):
        return frame[hdr + 8:]
    return None


def ipv4(link, frame):
    if frame and frame[0] & 0x0C == 0x08 and len(frame) > 14 and frame[12:14] != bytes.fromhex("0800"):
        ip = dot11_ip(frame)
        if ip is not None:
            return ip
    if link == 1:  # Ethernet

        etype, off = struct.unpack_from(">H", frame, 12)[0], 14

        if etype == 0x8100:

            etype, off = struct.unpack_from(">H", frame, 16)[0], 18

        return frame[off:] if etype == 0x0800 else None

    if link in (101, 228):  # raw IP

        return frame if frame and frame[0] >> 4 == 4 else None

    return None





def main(path, ip):

    target = ipaddress.ip_address(ip).packed

    n = 0

    for link, frame in packets(path):

        pkt = ipv4(link, frame)

        if not pkt or len(pkt) < 20 or target not in (pkt[12:16], pkt[16:20]):

            continue

        n += 1

        tot, ident, flags_off = struct.unpack_from(">HHH", pkt, 2)

        mf, df, frag = bool(flags_off & 0x2000), bool(flags_off & 0x4000), (flags_off & 0x1FFF) * 8

        src, dst = ipaddress.ip_address(pkt[12:16]), ipaddress.ip_address(pkt[16:20])

        ihl = (pkt[0] & 0x0F) * 4

        ports = ""

        if pkt[9] == 17 and frag == 0:

            sp, dp, ulen = struct.unpack_from(">HHH", pkt, ihl)

            ports = f" udp {sp}->{dp} len={ulen}"

        print(f"{src} -> {dst} ip_len={tot} id={ident} DF={df:d} MF={mf:d} off={frag}{ports}")

    print(f"{n} pacotes envolvendo {ip}")





if __name__ == "__main__":

    if len(sys.argv) != 3:
        sys.exit("uso: py tools/pcap_frag.py arquivo.pcapng IP_DO_ROBO")
    main(sys.argv[1], sys.argv[2])

