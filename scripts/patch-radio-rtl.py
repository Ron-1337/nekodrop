# Applies nekodrop's changes to winawdl's RTL8852CE radio daemon sources
# (radio/winawdl_radio.cpp) before they are built.
# Usage: python patch-radio-rtl.py <winawdl folder>
#
# - The radio reports the iPhone's 5 GHz AWDL channel (#32).  nekodrop starts
#   every card on channel 6 and moves to the phone's 44 or 149 when the radio
#   says "event: peer-channel N", as the Intel and MediaTek radios do.  This
#   radio never said it, so the RTL8852CE stayed on 2.4 GHz channel 6 at
#   20 MHz, where the phone spends only a few slots: 1 MB to an iPhone took
#   about 30 s and often failed.  winawdl itself runs this card on channel 44
#   (9-14 MB/s sending).  The channel comes from the sequence in the phone's
#   AWDL frames (TLV 18), by the rule of iwxradio/src/awdl_policy.h
#   peer_channel(); the receive thread notes it, the pipe thread logs it.
#
# Idempotent; exits with an error when the source no longer matches.
import pathlib
import sys

NL = chr(10)
radio = pathlib.Path(sys.argv[1]) / 'radio' / 'winawdl_radio.cpp'
text = radio.read_text(encoding='utf-8')
MARKER = 'nekodrop (#32, 8852BE)'

HELPER = NL.join([
    '/* nekodrop (#32, 8852BE): the phone\'s 5 GHz AWDL channel, 44 or 149 (0 if neither),',
    ' * from the channel sequence (TLV 18, or TLV 4 fallback) of an AWDL action frame.',
    ' * Slots 6, 7, 14 and 15 are the phone\'s own Wi-Fi; 44 wins over 149 when not',
    ' * Wi-Fi-only, and both 44 and 149 fall back to wifi_too=true when the phone\'s',
    ' * router shares its AWDL channel (common on channel 149 in CN). The receive',
    ' * thread notes a change and logs the first sequence once via the pipe thread. */',
    'namespace nekodrop {',
    'std::atomic<unsigned> peer_channel_news{0};',
    'std::atomic<bool> peer_seq_logged{false};',
    'std::atomic<bool> peer_seq_ready{false};',
    'uint8_t peer_seq_sample[16] = {};',
    'uint8_t peer_seq_enc = 0;',
    'unsigned peer_seq_ch = 0;',
    'unsigned peer_channel_told = 0; /* receive thread only */',
    '',
    'bool extract_chanseq(const uint8_t *v, size_t len, uint8_t out[16], uint8_t &enc) {',
    '  if (len < 6) return false;',
    '  enc = v[1];',
    '  if (enc == 0) {',
    '    if (len < 6 + 16) return false;',
    '    for (size_t n = 0; n < 16; ++n) out[n] = v[6 + n];',
    '    return true;',
    '  }',
    '  if (enc == 1 || enc == 3) {',
    '    if (len < 6 + 32) return false;',
    '    for (size_t n = 0; n < 16; ++n)',
    '      out[n] = (enc == 1) ? v[6 + 2 * n + 1] : v[6 + 2 * n];',
    '    return true;',
    '  }',
    '  return false;',
    '}',
    '',
    'unsigned peer_channel(std::span<const uint8_t> f) {',
    '  if (f.size() < 40 || f[0] != 0xd0 || f[24] != 0x7f || f[25] != 0x00 ||',
    '      f[26] != 0x17 || f[27] != 0xf2 || f[28] != 0x08)',
    '    return 0;',
    '  uint8_t seq[16] = {};',
    '  uint8_t enc = 0;',
    '  bool found = false;',
    '  for (size_t i = 40; i + 3 <= f.size();) {',
    '    const size_t value = size_t(f[i + 1]) | size_t(f[i + 2]) << 8;',
    '    if (i + 3 + value > f.size()) break;',
    '    if (f[i] == 18 && extract_chanseq(f.data() + i + 3, value, seq, enc)) {',
    '      found = true;',
    '      break;',
    '    }',
    '    if (f[i] == 4 && value >= 33 + 6 && !found) {',
    '      if (extract_chanseq(f.data() + i + 3 + 33, value - 33, seq, enc))',
    '        found = true;',
    '    }',
    '    i += 3 + value;',
    '  }',
    '  if (!found) return 0;',
    '  const auto names = [&seq](unsigned ch, bool wifi_too) {',
    '    const auto at = [&seq](size_t n) { return unsigned(seq[n]); };',
    '    if (!wifi_too && (at(6) == ch || at(7) == ch || at(14) == ch || at(15) == ch))',
    '      return false;',
    '    for (size_t n = 0; n < 16; ++n)',
    '      if ((n & 7) < 6 && at(n) == ch) return true;',
    '    return false;',
    '  };',
    '  const bool names149 = names(149, false);',
    '  unsigned chosen = 0;',
    '  if (names(44, !names149)) chosen = 44;',
    '  else if (names149 || names(149, true)) chosen = 149;',
    '  if (!peer_seq_logged.exchange(true)) {',
    '    for (size_t n = 0; n < 16; ++n) peer_seq_sample[n] = seq[n];',
    '    peer_seq_enc = enc;',
    '    peer_seq_ch = chosen;',
    '    peer_seq_ready.store(true, std::memory_order_release);',
    '  }',
    '  return chosen;',
    '}',
    '} // namespace nekodrop',
    '',
    '',
])

RX_OLD = '  if (packet.RxAtrib.crc_err) return;' + NL + '  note_station(frame, session);' + NL
RX_NEW = NL.join([
    '  if (packet.RxAtrib.crc_err) return;',
    '  const auto awdl_frame = (packet.RxAtrib.fcs_present && frame.size() > 4)',
    '                              ? frame.first(frame.size() - 4)',
    '                              : frame;',
    '  if (const unsigned ch = nekodrop::peer_channel(awdl_frame);',
    '      ch && ch != nekodrop::peer_channel_told) { /* nekodrop (#32) */',
    '    nekodrop::peer_channel_told = ch;',
    '    nekodrop::peer_channel_news = ch;',
    '  }',
    '  note_station(frame, session);',
    '',
])

LOOP_OLD = '    messages++;' + NL + '    untold++;' + NL
LOOP_NEW = NL.join([
    '    messages++;',
    '    untold++;',
    '    /* winawdl_radio lowers the logger to Warn while serving a client,',
    '     * so these lines must be logged at warn level or they are dropped. */',
    '    if (nekodrop::peer_seq_ready.exchange(false, std::memory_order_acquire)) {',
    '      std::string s;',
    '      for (size_t n = 0; n < 16; ++n)',
    '        s += (n ? "," : "") + std::to_string(nekodrop::peer_seq_sample[n]);',
    '      logger->warn("radio: peer chanseq enc={} [{}] -> ch {}",',
    '                   nekodrop::peer_seq_enc, s, nekodrop::peer_seq_ch);',
    '    }',
    '    if (const unsigned ch = nekodrop::peer_channel_news.exchange(0)) /* nekodrop (#32) */',
    '      logger->warn("radio: event: peer-channel {}", ch);',
    '',
])

FWD = 'void forward_received(const Packet &packet, PipeServer &pipe, Session &session,'

if MARKER in text:
    print('winawdl_radio.cpp: already patched')
    sys.exit(0)
for what, old in (('forward_received', FWD), ('the receive check', RX_OLD), ('the pipe loop', LOOP_OLD)):
    if text.count(old) != 1:
        sys.exit(f'winawdl_radio.cpp: {what} moved; update patch-radio-rtl.py')
text = text.replace(FWD, HELPER + FWD).replace(RX_OLD, RX_NEW).replace(LOOP_OLD, LOOP_NEW)
radio.write_text(text, encoding='utf-8')
print('winawdl_radio.cpp: the radio reports the phone\'s 5 GHz AWDL channel')
