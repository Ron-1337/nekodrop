# Applies nekodrop's RTL8852BE (10EC:B852 / 10EC:B85B) PCIe support patches to
# winawdl's radio CMake/tests and upstream devourer sources before building.
# Usage: python patch-devourer-8852be.py <winawdl folder>
#
# Upstream devourer already implements the 8852B Kestrel HAL (USB: firmware,
# halbb_8852b, halrf_8852b, TX/RX descriptors, channel tuning, calibrations)
# and the 8852CE (V1) PCIe HAXI plane. This patch adds the 8852BE (non-V1)
# PCIe delta verified against Linux rtw89 (pci.c, rtw8852b.c, rtw8852be.c):
#   - 32-bit DMA mask + 4 KiB RX buffers (6 MiB total slab below 4 GiB, so
#     Windows AWE can fall back cleanly to single 4 KiB pages without PCI
#     config-space DAC enable)
#   - 7 active TX channels (ACH0..3, CH8, CH9, CH12) and single-BDRAM table
#   - 24-byte WD body, 8-byte addr_info_v0, RPQ drv_info_unit=8
#   - 8852B PCIe power-on deltas, pre-init (MDIO/LBC/SIC/DBG/BDRAM), post-init,
#     deinit, DLFW/NIC HFC and NIC DLE PCIe quotas
#   - pcieprobe support for 10EC:B852 / 10EC:B85B bring-up verification
#
# Idempotent; exits with an error if an upstream anchor no longer matches.
import pathlib
import sys

MARKER = 'nekodrop (8852BE)'


def patch_file(path: pathlib.Path, replacements: list[tuple[str, str, str]]) -> None:
    text = path.read_text(encoding='utf-8')
    if MARKER in text:
        print(f'{path.name}: already patched')
        return
    # Normalize CRLF to LF for matching, preserving original line endings on write
    crlf = '\r\n' in text
    norm = text.replace('\r\n', '\n')
    for label, old, new in replacements:
        cnt = norm.count(old)
        if cnt != 1:
            sys.exit(
                f'{path}: anchor "{label}" matched {cnt} times (expected 1); '
                f'update patch-devourer-8852be.py'
            )
        norm = norm.replace(old, new, 1)
    if crlf:
        norm = norm.replace('\n', '\r\n')
    path.write_text(norm, encoding='utf-8')
    print(f'{path.name}: patched for RTL8852BE')


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: patch-devourer-8852be.py <winawdl folder>')
    winawdl = pathlib.Path(sys.argv[1])
    devourer = winawdl / 'upstream' / 'devourer'

    # 1. winawdl/radio/CMakeLists.txt: enable DEVOURER_KESTREL_8852B alongside 8852C
    patch_file(
        winawdl / 'radio' / 'CMakeLists.txt',
        [
            (
                'enable KESTREL_8852B',
                '''# Only the RTL8852C, over the Windows register proxy.
foreach(chip JAGUAR1 8814 JAGUAR2_8822B JAGUAR2_8821C JAGUAR3_8822C
             JAGUAR3_8822E 8733B KESTREL_8852B)
    set(DEVOURER_${chip} OFF CACHE BOOL "" FORCE)
endforeach()
set(DEVOURER_KESTREL_8852C ON CACHE BOOL "" FORCE)''',
                '''# RTL8852CE and RTL8852BE over the Windows register proxy (nekodrop (8852BE)).
foreach(chip JAGUAR1 8814 JAGUAR2_8822B JAGUAR2_8821C JAGUAR3_8822C
             JAGUAR3_8822E 8733B)
    set(DEVOURER_${chip} OFF CACHE BOOL "" FORCE)
endforeach()
set(DEVOURER_KESTREL_8852B ON CACHE BOOL "" FORCE)
set(DEVOURER_KESTREL_8852C ON CACHE BOOL "" FORCE)''',
            ),
        ],
    )

    # 2. devourer/CMakeLists.txt: allow DEVOURER_KESTREL (8852B or 8852C) for PCIe
    patch_file(
        devourer / 'CMakeLists.txt',
        [
            (
                'WIN32 KESTREL guard',
                '''    if(WIN32)
        if(NOT DEVOURER_KESTREL_8852C)
            message(FATAL_ERROR
                "DEVOURER_PCIE=ON on Windows requires DEVOURER_KESTREL_8852C=ON: "
                "only the AX plane is ported there (the 88xx plane waits on an "
                "eventfd).")
        endif()''',
                '''    if(WIN32)
        if(NOT DEVOURER_KESTREL) # nekodrop (8852BE)
            message(FATAL_ERROR
                "DEVOURER_PCIE=ON on Windows requires DEVOURER_KESTREL_8852B=ON or "
                "DEVOURER_KESTREL_8852C=ON: only the AX plane is ported there.")
        endif()''',
            ),
            (
                'PCIE chip guard',
                '    if(NOT DEVOURER_JAGUAR2_8821C AND NOT DEVOURER_KESTREL_8852C)',
                '    if(NOT DEVOURER_JAGUAR2_8821C AND NOT DEVOURER_KESTREL)',
            ),
            (
                'PcieDmaAx target_sources',
                '''    if(DEVOURER_KESTREL_8852C)
        target_sources(devourer PRIVATE src/PcieDmaAx.cpp src/PcieDmaAx.h)
    endif()''',
                '''    if(DEVOURER_KESTREL)
        target_sources(devourer PRIVATE src/PcieDmaAx.cpp src/PcieDmaAx.h)
    endif()''',
            ),
        ],
    )

    # 3. devourer/src/kestrel/KestrelUsbIds.h: add 10ec:b85b alternate PCI ID
    patch_file(
        devourer / 'src' / 'kestrel' / 'KestrelUsbIds.h',
        [
            (
                'kKestrelPciIds',
                '''inline constexpr KestrelPciId kKestrelPciIds[] = {
    {0x10ec, 0xc852, ChipVariant::C8852C}, /* RTL8852CE */
    {0x10ec, 0xb852, ChipVariant::C8852B}, /* RTL8852BE (unported) */
};''',
                '''inline constexpr KestrelPciId kKestrelPciIds[] = {
    {0x10ec, 0xc852, ChipVariant::C8852C}, /* RTL8852CE */
    {0x10ec, 0xb852, ChipVariant::C8852B}, /* RTL8852BE — nekodrop (8852BE) */
    {0x10ec, 0xb85b, ChipVariant::C8852B}, /* RTL8852BE (alt PCI ID) */
};''',
            ),
        ],
    )

    # 4. devourer/src/WiFiDriver.cpp: allow C8852B in CreateRadioPcie
    patch_file(
        devourer / 'src' / 'WiFiDriver.cpp',
        [
            (
                'CreateRadioPcie 8852B',
                '''  if (auto kvariant = kestrel::variant_for_pci_id(transport->pci_vendor_id(),
                                                  transport->pci_device_id())) {
    if (*kvariant != kestrel::ChipVariant::C8852C) {
      _logger->error("PCI {:04x}:{:04x} at {} is an RTL8852BE: its PCIe power "
                     "sequence is unported — refusing rather than running the "
                     "USB one",
                     transport->pci_vendor_id(), transport->pci_device_id(),
                     transport->bdf());
      return nullptr;
    }
#if defined(DEVOURER_HAVE_KESTREL_8852C)
    _logger->info("Creating RtlKestrelDevice C8852C over PCIe ({}; PCI "
                  "{:04x}:{:04x})",
                  transport->bdf(), transport->pci_vendor_id(),
                  transport->pci_device_id());
    return std::make_unique<RtlKestrelDevice>(
        RtlAdapter(std::move(transport), _logger, cfg), _logger,
        kestrel::ChipVariant::C8852C, cfg);
#else
    _logger->error("RTL8852CE detected but 8852C support not compiled in "
                   "(DEVOURER_KESTREL_8852C=OFF)");
    return nullptr;
#endif
  }''',
                '''  if (auto kvariant = kestrel::variant_for_pci_id(transport->pci_vendor_id(),
                                                  transport->pci_device_id())) {
    /* nekodrop (8852BE): support both C8852C and C8852B over PCIe. */
    const bool is_8852b = (*kvariant == kestrel::ChipVariant::C8852B);
#if !defined(DEVOURER_HAVE_KESTREL_8852B)
    if (is_8852b) {
      _logger->error("RTL8852BE detected but 8852B support not compiled in "
                     "(DEVOURER_KESTREL_8852B=OFF)");
      return nullptr;
    }
#endif
#if !defined(DEVOURER_HAVE_KESTREL_8852C)
    if (!is_8852b) {
      _logger->error("RTL8852CE detected but 8852C support not compiled in "
                     "(DEVOURER_KESTREL_8852C=OFF)");
      return nullptr;
    }
#endif
#if defined(DEVOURER_HAVE_KESTREL)
    _logger->info("Creating RtlKestrelDevice {} over PCIe ({}; PCI "
                  "{:04x}:{:04x})",
                  is_8852b ? "C8852B" : "C8852C",
                  transport->bdf(), transport->pci_vendor_id(),
                  transport->pci_device_id());
    return std::make_unique<RtlKestrelDevice>(
        RtlAdapter(std::move(transport), _logger, cfg), _logger,
        *kvariant, cfg);
#else
    _logger->error("Kestrel PCIe chip detected but Kestrel support not compiled in");
    return nullptr;
#endif
  }''',
            ),
        ],
    )

    # 5. devourer/src/PcieTransport.cpp: select PcieDmaAx(is_v1=false) for 0xB852/0xB85B
    patch_file(
        devourer / 'src' / 'PcieTransport.cpp',
        [
            (
                'include PcieDmaAx',
                '''#if defined(DEVOURER_HAVE_KESTREL_8852C)
#include "PcieDmaAx.h"
#endif''',
                '''#if defined(DEVOURER_HAVE_KESTREL)
#include "PcieDmaAx.h"
#endif''',
            ),
            (
                'PCI DID constants',
                '''constexpr uint16_t kPciDidRtl8852ce = 0xC852;
constexpr uint16_t kPciDidRtl8852be = 0xB852;''',
                '''constexpr uint16_t kPciDidRtl8852ce = 0xC852;
constexpr uint16_t kPciDidRtl8852be = 0xB852;
constexpr uint16_t kPciDidRtl8852beAlt = 0xB85B; /* nekodrop (8852BE) */''',
            ),
            (
                'select_dma_plane 8852BE',
                '''  case kPciDidRtl8852be:
    _logger->error("PcieTransport: RTL8852BE ({:04x}:{:04x}) is not ported "
                   "(its PCIe power sequence and single-BDRAM ring table are "
                   "unported; the 8852CE is)",
                   _pci_vid, _pci_did);
    return false;''',
                '''  case kPciDidRtl8852be:
  case kPciDidRtl8852beAlt:
#if defined(DEVOURER_HAVE_KESTREL_8852B)
    _dma = std::make_unique<PcieDmaAx>(*this, _logger, _cfg.rx_poll_us,
                                       _cfg.tx_quick_submit, /*is_v1=*/false);
    return true;
#else
    _logger->error("PcieTransport: RTL8852BE ({:04x}:{:04x}) needs "
                   "DEVOURER_KESTREL_8852B=ON",
                   _pci_vid, _pci_did);
    return false;
#endif''',
            ),
        ],
    )

    # 6. devourer/src/PcieTransportWin.cpp: support all-head single-page fallback when need == low_need
    patch_file(
        devourer / 'src' / 'PcieTransportWin.cpp',
        [
            (
                'init_dma single-page fallback when low_need == need',
                '''  const size_t head_pages = low_need * kPagesPerBlock;
  if (_os->blocks.empty() && low_need) {
    for (size_t request : requests) {
      std::vector<ULONG_PTR> frames = allocate_blocks(request);
      _os->blocks = take_lowest_blocks(frames, need - low_need, kPagesPerBlock,
                                       limit_frame);
      free_blocks(frames);
      if (!_os->blocks.empty())
        break;
    }
    _logger->info("PcieTransport: no 2 MiB block is free below 4 GiB; {} of "
                  "the {} other blocks found",
                  _os->blocks.size(), need - low_need);
    for (size_t request : kPageRequests) {
      if (_os->blocks.empty() || !_os->head.empty())
        break;
      std::vector<ULONG_PTR> frames = allocate_pages(request);
      const auto low = std::count_if(
          frames.begin(), frames.end(),
          [](ULONG_PTR frame) { return frame < kFrameAt4GiB; });
      _logger->info("PcieTransport: of {} single pages, {} are below 4 GiB "
                    "({} wanted)",
                    frames.size(), low, head_pages);
      _os->head = take_lowest_blocks(frames, head_pages, 1, kFrameAt4GiB);
      free_blocks(frames);
    }
    if (_os->head.empty())
      free_blocks(_os->blocks);
  }
  if (_os->blocks.empty()) {''',
                '''  const size_t head_pages = low_need * kPagesPerBlock;
  if (_os->blocks.empty() && low_need) {
    /* nekodrop (8852BE): when low_need == need (32-bit DMA plane), the whole
     * slab can fall back to single 4 KiB pages below 4 GiB with zero 2 MiB
     * high blocks. */
    const size_t high_need = need - low_need;
    if (high_need) {
      for (size_t request : requests) {
        std::vector<ULONG_PTR> frames = allocate_blocks(request);
        _os->blocks = take_lowest_blocks(frames, high_need, kPagesPerBlock,
                                         limit_frame);
        free_blocks(frames);
        if (!_os->blocks.empty())
          break;
      }
      _logger->info("PcieTransport: no 2 MiB block is free below 4 GiB; {} of "
                    "the {} other blocks found",
                    _os->blocks.size(), high_need);
    } else {
      _logger->info("PcieTransport: no {} locked 2 MiB blocks free below 4 GiB; "
                    "falling back to {} single pages below 4 GiB",
                    low_need, head_pages);
    }
    for (size_t request : kPageRequests) {
      if ((high_need && _os->blocks.empty()) || !_os->head.empty())
        break;
      std::vector<ULONG_PTR> frames = allocate_pages(request);
      const auto low = std::count_if(
          frames.begin(), frames.end(),
          [](ULONG_PTR frame) { return frame < kFrameAt4GiB; });
      _logger->info("PcieTransport: of {} single pages, {} are below 4 GiB "
                    "({} wanted)",
                    frames.size(), low, head_pages);
      _os->head = take_lowest_blocks(frames, head_pages, 1, kFrameAt4GiB);
      free_blocks(frames);
    }
    if (_os->head.empty())
      free_blocks(_os->blocks);
  }
  if (_os->blocks.empty() && _os->head.empty()) {''',
            ),
            (
                'init_dma log empty chunk_iova guard',
                '''  _logger->info("PcieTransport: DMA slab is {} locked 2 MiB blocks, physical "
                "0x{:x}..0x{:x}, and {} single pages below 4 GiB, used as bus "
                "addresses",
                _os->blocks.size(), _slab.chunk_iova.front(),
                _slab.chunk_iova.back() + kBlockBytes, _os->head.size());''',
                '''  if (!_slab.chunk_iova.empty()) {
    _logger->info("PcieTransport: DMA slab is {} locked 2 MiB blocks, physical "
                  "0x{:x}..0x{:x}, and {} single pages below 4 GiB, used as bus "
                  "addresses",
                  _os->blocks.size(), _slab.chunk_iova.front(),
                  _slab.chunk_iova.back() + kBlockBytes, _os->head.size());
  } else {
    _logger->info("PcieTransport: DMA slab is {} single pages below 4 GiB "
                  "(physical 0x{:x}..0x{:x}), used as bus addresses",
                  _os->head.size(), _slab.head_iova.front(),
                  _slab.head_iova.back() + kPageBytes);
  }''',
            ),
        ],
    )

    # 7. devourer/src/PcieDmaAxDesc.h: add 8-byte addr_info_write_v0 for 8852B
    patch_file(
        devourer / 'src' / 'PcieDmaAxDesc.h',
        [
            (
                'addr_info_write_v0',
                '''inline void addr_info_write(uint8_t *entry, uint32_t length, bool last,
                            uint64_t dma) {
  const uint16_t length_opt =
      static_cast<uint16_t>((length & kAddrInfoLengthMask) |
                            (address_high(dma) << kAddrInfoAddressHighShift) |
                            (last ? kAddrInfoLast : 0));
  entry[0] = static_cast<uint8_t>(length_opt);
  entry[1] = static_cast<uint8_t>(length_opt >> 8);
  entry[2] = static_cast<uint8_t>(dma);
  entry[3] = static_cast<uint8_t>(dma >> 8);
  entry[4] = static_cast<uint8_t>(dma >> 16);
  entry[5] = static_cast<uint8_t>(dma >> 24);
}''',
                '''inline void addr_info_write(uint8_t *entry, uint32_t length, bool last,
                            uint64_t dma) {
  const uint16_t length_opt =
      static_cast<uint16_t>((length & kAddrInfoLengthMask) |
                            (address_high(dma) << kAddrInfoAddressHighShift) |
                            (last ? kAddrInfoLast : 0));
  entry[0] = static_cast<uint8_t>(length_opt);
  entry[1] = static_cast<uint8_t>(length_opt >> 8);
  entry[2] = static_cast<uint8_t>(dma);
  entry[3] = static_cast<uint8_t>(dma >> 8);
  entry[4] = static_cast<uint8_t>(dma >> 16);
  entry[5] = static_cast<uint8_t>(dma >> 24);
}

/* nekodrop (8852BE): One non-V1 addr_info_32 entry of a WD page (8852A/8852B,
 * rtw89_pci_fill_txaddr_info): {le16 length, le16 option, le32 dma}. Option
 * carries MSDU_LS (bit 15), addr_info count (1 in [5:0]) and dma[35:32] in
 * [13:6]. */
constexpr uint32_t kAddrInfoV0Bytes = 8;
constexpr uint16_t kAddrInfoV0MsduLs = 1u << 15;

inline void addr_info_write_v0(uint8_t *entry, uint32_t length, uint64_t dma) {
  const uint16_t len16 = static_cast<uint16_t>(length);
  const uint16_t opt = static_cast<uint16_t>(
      kAddrInfoV0MsduLs | 1u | (address_high(dma) << kBdOptAddressHighShift));
  entry[0] = static_cast<uint8_t>(len16);
  entry[1] = static_cast<uint8_t>(len16 >> 8);
  entry[2] = static_cast<uint8_t>(opt);
  entry[3] = static_cast<uint8_t>(opt >> 8);
  entry[4] = static_cast<uint8_t>(dma);
  entry[5] = static_cast<uint8_t>(dma >> 8);
  entry[6] = static_cast<uint8_t>(dma >> 16);
  entry[7] = static_cast<uint8_t>(dma >> 24);
}''',
            ),
        ],
    )

    # 8. winawdl/radio/tests/dma_address_test.cpp: test addr_info_write_v0 and all-head DmaSlab
    patch_file(
        winawdl / 'radio' / 'tests' / 'dma_address_test.cpp',
        [
            (
                'test all-head slab',
                '''  std::vector<uintptr_t> pages = {0x180000, 0x9, 0x100005, 0x7, 0xFFFFF};
  const auto low = take_lowest_blocks(pages, 3, 1, kFrameAt4GiB);
  expect(low == std::vector<uintptr_t>{0x7, 0x9, 0xFFFFF} && pages.size() == 2,
         "single pages below 4 GiB are picked like blocks of one frame");
}''',
                '''  std::vector<uintptr_t> pages = {0x180000, 0x9, 0x100005, 0x7, 0xFFFFF};
  const auto low = take_lowest_blocks(pages, 3, 1, kFrameAt4GiB);
  expect(low == std::vector<uintptr_t>{0x7, 0x9, 0xFFFFF} && pages.size() == 2,
         "single pages below 4 GiB are picked like blocks of one frame");

  /* nekodrop (8852BE): a 32-bit-only plane may live entirely in single pages. */
  devourer::DmaSlab all_head;
  all_head.head_bytes = 0x2000;
  all_head.head_chunk_bytes = 0x1000;
  all_head.head_iova = {0x20000, 0x50000};
  expect(all_head.iova(0x123) == 0x20123 && all_head.iova(0x1456) == 0x50456,
         "an all-head slab resolves without 2 MiB blocks");
}''',
            ),
            (
                'test addr_info_write_v0',
                '''  ax::addr_info_write(entry, 2044, /*last=*/true, 0x9'1234'5678);
  const uint8_t high[] = {0xFC, 0xCF, 0x78, 0x56, 0x34, 0x12};
  expect(same_bytes(entry, high),
         "bits 35:32 go to bits 14:11 beside the length and last flag");
}''',
                '''  ax::addr_info_write(entry, 2044, /*last=*/true, 0x9'1234'5678);
  const uint8_t high[] = {0xFC, 0xCF, 0x78, 0x56, 0x34, 0x12};
  expect(same_bytes(entry, high),
         "bits 35:32 go to bits 14:11 beside the length and last flag");

  uint8_t entry_v0[8] = {};
  ax::addr_info_write_v0(entry_v0, 1500, 0x0ABC'D000);
  const uint8_t v0_low[] = {0xDC, 0x05, 0x01, 0x80, 0x00, 0xD0, 0xBC, 0x0A};
  expect(same_bytes(entry_v0, v0_low),
         "8852B addr_info_v0 encodes length, MSDU_LS|num=1 and 32-bit DMA");
}''',
            ),
        ],
    )

    # 9. devourer/src/PcieDmaAx.h: add is_v1 parameter & 8852B RX buffer constants
    patch_file(
        devourer / 'src' / 'PcieDmaAx.h',
        [
            (
                'kRxBufSizeV0 and constructor',
                '''  static constexpr uint32_t kRxBufStride = 16384;
  static constexpr uint32_t kFwcmdSlotStride = 4096;

  PcieDmaAx(PcieTransport &t, Logger_t logger, int rx_poll_us,
            bool quick_submit = false);

  const char *name() const override { return "ax-haxi"; }''',
                '''  static constexpr uint32_t kRxBufStride = 16384;
  /* nekodrop (8852BE): 4 KiB RX buffers keep every object <= 1 page so the
   * entire 32-bit DMA slab (6 MiB) can fall back to single pages below 4 GiB. */
  static constexpr uint32_t kRxBufSizeV0 = 4096;
  static constexpr uint32_t kRxBufStrideV0 = 4096;
  static constexpr uint32_t kFwcmdSlotStride = 4096;

  PcieDmaAx(PcieTransport &t, Logger_t logger, int rx_poll_us,
            bool quick_submit = false, bool is_v1 = true);

  const char *name() const override { return _is_v1 ? "ax-haxi" : "ax-pcie"; }''',
            ),
            (
                'rx_buf helpers and _is_v1 member',
                '''  PcieTransport &_t;
  Logger_t _logger;
  int _rx_poll_us;
  bool _quick_submit; /* PcieTransport::Config::tx_quick_submit */
  std::atomic<bool> _kick_deferred{false};''',
                '''  uint32_t rx_buf_size() const { return _is_v1 ? kRxBufSize : kRxBufSizeV0; }
  uint32_t rx_buf_stride() const { return _is_v1 ? kRxBufStride : kRxBufStrideV0; }

  PcieTransport &_t;
  Logger_t _logger;
  int _rx_poll_us;
  bool _quick_submit; /* PcieTransport::Config::tx_quick_submit */
  bool _is_v1;        /* true = 8852C (HAXI V1), false = 8852B (AX PCIe) */
  std::atomic<bool> _kick_deferred{false};''',
            ),
        ],
    )

    # 10. devourer/src/PcieDmaAx.cpp: 8852B (non-V1) rings, 32-bit DMA, 24B WD, addr_info_v0, drv_info_unit=8
    patch_file(
        devourer / 'src' / 'PcieDmaAx.cpp',
        [
            (
                '8852B ring tables and regs',
                '''constexpr uint16_t R_RXQ_NUM = 0x1210, R_RXQ_IDX = 0x1218, R_RXQ_DESA_L = 0x1220;
constexpr uint16_t R_RPQ_NUM = 0x1212, R_RPQ_IDX = 0x121C, R_RPQ_DESA_L = 0x1228;
/* Interrupt masks this plane could enable (unused: polling). */
constexpr uint16_t R_AX_HAXI_HIMR00 = 0x10B0;
constexpr uint16_t R_AX_PCIE_HIMR00_V1 = 0x30B0;''',
                '''/* nekodrop (8852BE): non-V1 ring register map + rtw89_bd_ram_table_single.
 * Masked channels (ACH4..7, CH10..11) have num=0 and are never programmed. */
constexpr TxChRegs kTxCh8852b[PcieDmaAx::kTxChannels] = {
    {0x1024, 0x1058, 0x1200, 0x1110, 0, 5, 2},   /* ACH0 */
    {0x1026, 0x105C, 0x1204, 0x1118, 5, 5, 2},   /* ACH1 */
    {0x1028, 0x1060, 0x1208, 0x1120, 10, 5, 2},  /* ACH2 */
    {0x102A, 0x1064, 0x120C, 0x1128, 15, 5, 2},  /* ACH3 */
    {0, 0, 0, 0, 0, 0, 0},                       /* ACH4 (masked) */
    {0, 0, 0, 0, 0, 0, 0},                       /* ACH5 (masked) */
    {0, 0, 0, 0, 0, 0, 0},                       /* ACH6 (masked) */
    {0, 0, 0, 0, 0, 0, 0},                       /* ACH7 (masked) */
    {0x1034, 0x1078, 0x1220, 0x1150, 20, 4, 1},  /* CH8  B0MG */
    {0x1036, 0x107C, 0x1224, 0x1158, 24, 4, 1},  /* CH9  B0HI */
    {0, 0, 0, 0, 0, 0, 0},                       /* CH10 (masked) */
    {0, 0, 0, 0, 0, 0, 0},                       /* CH11 (masked) */
    {0x1038, 0x1080, 0x1228, 0x1160, 28, 4, 1},  /* CH12 FWCMD */
};
constexpr uint16_t R_RXQ_NUM = 0x1210, R_RXQ_IDX = 0x1218, R_RXQ_DESA_L = 0x1220;
constexpr uint16_t R_RPQ_NUM = 0x1212, R_RPQ_IDX = 0x121C, R_RPQ_DESA_L = 0x1228;
constexpr uint16_t R_RXQ_NUM_V0 = 0x1020, R_RXQ_IDX_V0 = 0x1050, R_RXQ_DESA_L_V0 = 0x1100;
constexpr uint16_t R_RPQ_NUM_V0 = 0x1022, R_RPQ_IDX_V0 = 0x1054, R_RPQ_DESA_L_V0 = 0x1108;
/* Interrupt masks this plane could enable (unused: polling). */
constexpr uint16_t R_AX_HAXI_HIMR00 = 0x10B0;
constexpr uint16_t R_AX_PCIE_HIMR10 = 0x13B0;
constexpr uint16_t R_AX_PCIE_HIMR00_V1 = 0x30B0;''',
            ),
            (
                'WD_BODY_LEN_V0 and DRV_INFO_UNIT_8852B',
                '''constexpr uint32_t WD_BODY_LEN_V1 = 32; /* 8852C wd_body_t_v1 */
constexpr uint32_t WD_INFO_LEN = 24;
constexpr uint16_t DRV_INFO_UNIT_8852C = 16;''',
                '''constexpr uint32_t WD_BODY_LEN_V0 = 24; /* 8852B wd_body_t */
constexpr uint32_t WD_BODY_LEN_V1 = 32; /* 8852C wd_body_t_v1 */
constexpr uint32_t WD_INFO_LEN = 24;
constexpr uint16_t DRV_INFO_UNIT_8852B = 8;
constexpr uint16_t DRV_INFO_UNIT_8852C = 16;''',
            ),
            (
                'layout(bool is_v1)',
                '''Layout layout() {
  size_t end = 0;
  auto area = [&end](size_t stride, size_t count) {
    const size_t align = stride > PAGE_SZ ? stride : PAGE_SZ;
    const size_t start = (end + align - 1) & ~(align - 1);
    end = start + stride * count;
    return start;
  };
  Layout l{};
  /* First, so that it gets the slab's lowest memory: see low_slab_bytes. */
  l.payload = area(PcieDmaAx::kPayloadSize, PcieDmaAx::kWdPages);
  l.txbd = area(RING_BYTES, PcieDmaAx::kTxChannels);
  l.rxq_bd = area(RING_BYTES, 1);
  l.rpq_bd = area(RING_BYTES, 1);
  l.rxq_buf = area(PcieDmaAx::kRxBufStride, PcieDmaAx::kBdLen);
  l.rpq_buf = area(PcieDmaAx::kRxBufStride, PcieDmaAx::kBdLen);
  l.wd = area(PcieDmaAx::kWdPageSize, PcieDmaAx::kWdPages);
  l.fwcmd = area(PcieDmaAx::kFwcmdSlotStride, PcieDmaAx::kBdLen);
  l.total = page_align(end);
  return l;
}''',
                '''Layout layout(bool is_v1) {
  const size_t rx_stride =
      is_v1 ? PcieDmaAx::kRxBufStride : PcieDmaAx::kRxBufStrideV0;
  size_t end = 0;
  auto area = [&end](size_t stride, size_t count) {
    const size_t align = stride > PAGE_SZ ? stride : PAGE_SZ;
    const size_t start = (end + align - 1) & ~(align - 1);
    end = start + stride * count;
    return start;
  };
  Layout l{};
  /* First, so that it gets the slab's lowest memory: see low_slab_bytes. */
  l.payload = area(PcieDmaAx::kPayloadSize, PcieDmaAx::kWdPages);
  l.txbd = area(RING_BYTES, PcieDmaAx::kTxChannels);
  l.rxq_bd = area(RING_BYTES, 1);
  l.rpq_bd = area(RING_BYTES, 1);
  l.rxq_buf = area(rx_stride, PcieDmaAx::kBdLen);
  l.rpq_buf = area(rx_stride, PcieDmaAx::kBdLen);
  l.wd = area(PcieDmaAx::kWdPageSize, PcieDmaAx::kWdPages);
  l.fwcmd = area(PcieDmaAx::kFwcmdSlotStride, PcieDmaAx::kBdLen);
  l.total = page_align(end);
  return l;
}''',
            ),
            (
                'ctor, slab_bytes, dma_address_bits, low_slab_bytes, quiesce_ops, attach',
                '''PcieDmaAx::PcieDmaAx(PcieTransport &t, Logger_t logger, int rx_poll_us,
                     bool quick_submit)
    : _t(t), _logger(std::move(logger)), _rx_poll_us(rx_poll_us),
      _quick_submit(quick_submit) {
  static_assert(WD_BODY_LEN_V1 + WD_INFO_LEN + WP_INFO_SZ +
                        ADDR_INFO_NR_MAX * ADDR_INFO_SZ <=
                    kWdPageSize,
                "WD page overflow");
  static_assert(ADDR_INFO_NR_MAX * ADDR_INFO_LEN_MAX >= kPayloadSize,
                "payload bounce not addressable by addr_info");
}

size_t PcieDmaAx::slab_bytes() const { return layout().total; }

unsigned PcieDmaAx::dma_address_bits() const { return pcie_ax::kAddressBits; }

/* The frame payloads. Unlike everything else they must stay below 4 GiB: the
 * chip does not follow the high address bits of a WD page's entries. */
size_t PcieDmaAx::low_slab_bytes() const {
  const Layout l = layout();
  return l.payload + static_cast<size_t>(kPayloadSize) * kWdPages;
}

std::vector<DmaQuiesceOp> PcieDmaAx::quiesce_ops() const {
  /* HalKestrel::pcie_ctrl_dma_all(false), then the stop bit of every channel. */
  namespace r = kestrel::reg;
  return {
      {r::R_AX_HAXI_INIT_CFG1, r::B_AX_STOP_AXI_MST, true},
      {r::R_AX_HAXI_INIT_CFG1, r::B_AX_TXHCI_EN_V1 | r::B_AX_RXHCI_EN_V1, false},
      {r::R_AX_HAXI_DMA_STOP1,
       r::HAXI_DMA_STOP1_CHANS | r::B_AX_STOP_WPDMA | r::B_AX_STOP_PCIEIO, true},
      {r::R_AX_HAXI_DMA_STOP2, r::HAXI_DMA_STOP2_CHANS, true},
  };
}

bool PcieDmaAx::attach(const DmaSlab &dma) {
  const Layout l = layout();
  if (dma.len < l.total ||
      (dma.chunk_bytes && dma.chunk_bytes % kRxBufStride != 0)) {
    _logger->error("PcieDmaAx: DMA slab unusable ({} B in {} B chunks, need {} "
                   "B in multiples of {} B)",
                   dma.len, dma.chunk_bytes, l.total, kRxBufStride);
    return false;
  }
  /* Only the frame payloads may sit in a head of smaller chunks. */
  if (dma.head_bytes && (dma.head_bytes != low_slab_bytes() ||
                         dma.head_chunk_bytes % kPayloadSize != 0)) {
    _logger->error("PcieDmaAx: DMA slab head unusable ({} B in {} B chunks)",
                   dma.head_bytes, dma.head_chunk_bytes);
    return false;
  }
  const size_t chunk_span = dma.chunk_bytes ? dma.chunk_bytes : dma.len;
  for (const uint64_t base : dma.chunk_iova) {
    if (base + chunk_span > pcie_ax::kAddressLimit) {
      _logger->error("PcieDmaAx: DMA slab at 0x{:x} is beyond the {} address "
                     "bits the descriptors carry",
                     base, pcie_ax::kAddressBits);
      return false;
    }
  }
  for (uint32_t page = 0; page < kWdPages; page++) {
    const uint64_t at =
        dma.iova(l.payload + static_cast<size_t>(page) * kPayloadSize);
    if (at + kPayloadSize > pcie_ax::kLowAddressLimit) {
      _logger->error("PcieDmaAx: frame payload at 0x{:x} is not below 4 GiB",
                     at);
      return false;
    }
  }
  _slab = dma;
  uint8_t *const slab = dma.va;
  for (uint32_t ch = 0; ch < kTxChannels; ch++) {
    TxRing &r = _tx[ch];
    const size_t off = l.txbd + static_cast<size_t>(ch) * RING_BYTES;
    r.bd = slab + off;
    r.bd_iova = dma.iova(off);
    r.wp = 0;
    r.hw_seen = 0;
    r.told = 0;
    r.reg_num = kTxCh[ch].num;
    r.reg_idx = kTxCh[ch].idx;
    r.reg_bdram = kTxCh[ch].bdram;
    r.reg_desa_l = kTxCh[ch].desa_l;
    r.bdram = kTxCh[ch].bd_start | (static_cast<uint32_t>(kTxCh[ch].bd_max) << 8) |
              (static_cast<uint32_t>(kTxCh[ch].bd_min) << 16);
  }
  _rxq.bd = slab + l.rxq_bd;
  _rxq.bd_iova = dma.iova(l.rxq_bd);
  _rxq.bufs = slab + l.rxq_buf;
  _rxq.bufs_off = l.rxq_buf;
  _rxq.reg_num = R_RXQ_NUM;
  _rxq.reg_idx = R_RXQ_IDX;
  _rxq.reg_desa_l = R_RXQ_DESA_L;
  _rpq.bd = slab + l.rpq_bd;
  _rpq.bd_iova = dma.iova(l.rpq_bd);
  _rpq.bufs = slab + l.rpq_buf;
  _rpq.bufs_off = l.rpq_buf;
  _rpq.reg_num = R_RPQ_NUM;
  _rpq.reg_idx = R_RPQ_IDX;
  _rpq.reg_desa_l = R_RPQ_DESA_L;''',
                '''PcieDmaAx::PcieDmaAx(PcieTransport &t, Logger_t logger, int rx_poll_us,
                     bool quick_submit, bool is_v1)
    : _t(t), _logger(std::move(logger)), _rx_poll_us(rx_poll_us),
      _quick_submit(quick_submit), _is_v1(is_v1) {
  static_assert(WD_BODY_LEN_V1 + WD_INFO_LEN + WP_INFO_SZ +
                        ADDR_INFO_NR_MAX * ADDR_INFO_SZ <=
                    kWdPageSize,
                "WD page overflow");
  static_assert(WD_BODY_LEN_V0 + WD_INFO_LEN + WP_INFO_SZ +
                        pcie_ax::kAddrInfoV0Bytes <=
                    kWdPageSize,
                "8852B WD page overflow");
  static_assert(ADDR_INFO_NR_MAX * ADDR_INFO_LEN_MAX >= kPayloadSize,
                "payload bounce not addressable by addr_info");
}

size_t PcieDmaAx::slab_bytes() const { return layout(_is_v1).total; }

unsigned PcieDmaAx::dma_address_bits() const {
  return _is_v1 ? pcie_ax::kAddressBits : 32u;
}

/* The frame payloads on 8852C (and the entire slab on 8852B, since enabling
 * 36-bit DAC on 8852B requires PCI config-space writes unavailable through
 * Windows regproxy) must stay below 4 GiB. */
size_t PcieDmaAx::low_slab_bytes() const {
  const Layout l = layout(_is_v1);
  if (!_is_v1)
    return l.total;
  return l.payload + static_cast<size_t>(kPayloadSize) * kWdPages;
}

std::vector<DmaQuiesceOp> PcieDmaAx::quiesce_ops() const {
  /* HalKestrel::pcie_ctrl_dma_all(false), then the stop bit of every channel. */
  namespace r = kestrel::reg;
  if (!_is_v1) {
    return {
        {r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_PCIEIO, true},
        {r::R_AX_HAXI_INIT_CFG1, r::B_AX_TXHCI_EN_8852B | r::B_AX_RXHCI_EN_8852B,
         false},
        {r::R_AX_HAXI_DMA_STOP1,
         r::PCIE_DMA_STOP1_CHANS_8852B | r::B_AX_STOP_WPDMA | r::B_AX_STOP_PCIEIO,
         true},
    };
  }
  return {
      {r::R_AX_HAXI_INIT_CFG1, r::B_AX_STOP_AXI_MST, true},
      {r::R_AX_HAXI_INIT_CFG1, r::B_AX_TXHCI_EN_V1 | r::B_AX_RXHCI_EN_V1, false},
      {r::R_AX_HAXI_DMA_STOP1,
       r::HAXI_DMA_STOP1_CHANS | r::B_AX_STOP_WPDMA | r::B_AX_STOP_PCIEIO, true},
      {r::R_AX_HAXI_DMA_STOP2, r::HAXI_DMA_STOP2_CHANS, true},
  };
}

bool PcieDmaAx::attach(const DmaSlab &dma) {
  const Layout l = layout(_is_v1);
  const size_t rx_stride = rx_buf_stride();
  if (dma.len < l.total ||
      (dma.chunk_bytes && dma.chunk_bytes % rx_stride != 0)) {
    _logger->error("PcieDmaAx: DMA slab unusable ({} B in {} B chunks, need {} "
                   "B in multiples of {} B)",
                   dma.len, dma.chunk_bytes, l.total, rx_stride);
    return false;
  }
  if (_is_v1) {
    /* Only the frame payloads may sit in a head of smaller chunks. */
    if (dma.head_bytes && (dma.head_bytes != low_slab_bytes() ||
                           dma.head_chunk_bytes % kPayloadSize != 0)) {
      _logger->error("PcieDmaAx: DMA slab head unusable ({} B in {} B chunks)",
                     dma.head_bytes, dma.head_chunk_bytes);
      return false;
    }
  } else {
    /* On 8852B every object is <= 4 KiB, so an all-head single-page slab works. */
    if (dma.head_bytes && (dma.head_bytes < l.total ||
                           dma.head_chunk_bytes % rx_stride != 0)) {
      _logger->error("PcieDmaAx: 8852B DMA slab head unusable ({} B in {} B chunks)",
                     dma.head_bytes, dma.head_chunk_bytes);
      return false;
    }
  }
  const uint64_t addr_limit =
      _is_v1 ? pcie_ax::kAddressLimit : pcie_ax::kLowAddressLimit;
  const size_t chunk_span = dma.chunk_bytes ? dma.chunk_bytes : dma.len;
  for (const uint64_t base : dma.chunk_iova) {
    if (base + chunk_span > addr_limit) {
      _logger->error("PcieDmaAx: DMA slab at 0x{:x} is beyond the {} address "
                     "bits this chip can address",
                     base, dma_address_bits());
      return false;
    }
  }
  for (const uint64_t base : dma.head_iova) {
    if (base + dma.head_chunk_bytes > pcie_ax::kLowAddressLimit) {
      _logger->error("PcieDmaAx: DMA slab head page at 0x{:x} is not below 4 GiB",
                     base);
      return false;
    }
  }
  for (uint32_t page = 0; page < kWdPages; page++) {
    const uint64_t at =
        dma.iova(l.payload + static_cast<size_t>(page) * kPayloadSize);
    if (at + kPayloadSize > pcie_ax::kLowAddressLimit) {
      _logger->error("PcieDmaAx: frame payload at 0x{:x} is not below 4 GiB",
                     at);
      return false;
    }
  }
  _slab = dma;
  uint8_t *const slab = dma.va;
  const TxChRegs *const tx_tbl = _is_v1 ? kTxCh : kTxCh8852b;
  for (uint32_t ch = 0; ch < kTxChannels; ch++) {
    TxRing &r = _tx[ch];
    r.wp = 0;
    r.hw_seen = 0;
    r.told = 0;
    r.reg_num = tx_tbl[ch].num;
    r.reg_idx = tx_tbl[ch].idx;
    r.reg_bdram = tx_tbl[ch].bdram;
    r.reg_desa_l = tx_tbl[ch].desa_l;
    r.bdram = tx_tbl[ch].bd_start |
              (static_cast<uint32_t>(tx_tbl[ch].bd_max) << 8) |
              (static_cast<uint32_t>(tx_tbl[ch].bd_min) << 16);
    if (r.reg_num == 0) {
      r.bd = nullptr;
      r.bd_iova = 0;
      continue;
    }
    const size_t off = l.txbd + static_cast<size_t>(ch) * RING_BYTES;
    r.bd = slab + off;
    r.bd_iova = dma.iova(off);
  }
  _rxq.bd = slab + l.rxq_bd;
  _rxq.bd_iova = dma.iova(l.rxq_bd);
  _rxq.bufs = slab + l.rxq_buf;
  _rxq.bufs_off = l.rxq_buf;
  _rxq.reg_num = _is_v1 ? R_RXQ_NUM : R_RXQ_NUM_V0;
  _rxq.reg_idx = _is_v1 ? R_RXQ_IDX : R_RXQ_IDX_V0;
  _rxq.reg_desa_l = _is_v1 ? R_RXQ_DESA_L : R_RXQ_DESA_L_V0;
  _rpq.bd = slab + l.rpq_bd;
  _rpq.bd_iova = dma.iova(l.rpq_bd);
  _rpq.bufs = slab + l.rpq_buf;
  _rpq.bufs_off = l.rpq_buf;
  _rpq.reg_num = _is_v1 ? R_RPQ_NUM : R_RPQ_NUM_V0;
  _rpq.reg_idx = _is_v1 ? R_RPQ_IDX : R_RPQ_IDX_V0;
  _rpq.reg_desa_l = _is_v1 ? R_RPQ_DESA_L : R_RPQ_DESA_L_V0;''',
            ),
            (
                'arm_rx_bd',
                '''void PcieDmaAx::arm_rx_bd(RxRing &r, uint32_t idx) {
  bd_write(r.bd + static_cast<size_t>(idx) * BD_SZ,
           static_cast<uint16_t>(kRxBufSize), 0,
           _slab.iova(r.bufs_off + static_cast<size_t>(idx) * kRxBufStride));
}''',
                '''void PcieDmaAx::arm_rx_bd(RxRing &r, uint32_t idx) {
  bd_write(r.bd + static_cast<size_t>(idx) * BD_SZ,
           static_cast<uint16_t>(rx_buf_size()), 0,
           _slab.iova(r.bufs_off + static_cast<size_t>(idx) * rx_buf_stride()));
}''',
            ),
            (
                'setup_rings skip masked TX channels',
                '''  for (uint32_t ch = 0; ch < kTxChannels; ch++) {
    TxRing &r = _tx[ch];
    r.wp = 0;
    r.hw_seen = 0;
    r.told = 0;
    _t.mmio_write<uint16_t>(r.reg_num, static_cast<uint16_t>(kBdLen & IDX_MASK));
    _t.mmio_write<uint32_t>(r.reg_bdram, r.bdram);
    write_ring_base(r.reg_desa_l, r.bd_iova);
  }''',
                '''  for (uint32_t ch = 0; ch < kTxChannels; ch++) {
    TxRing &r = _tx[ch];
    r.wp = 0;
    r.hw_seen = 0;
    r.told = 0;
    if (r.reg_num == 0)
      continue;
    _t.mmio_write<uint16_t>(r.reg_num, static_cast<uint16_t>(kBdLen & IDX_MASK));
    _t.mmio_write<uint32_t>(r.reg_bdram, r.bdram);
    write_ring_base(r.reg_desa_l, r.bd_iova);
  }''',
            ),
            (
                'setup_rings log',
                '''  _logger->info("PcieDmaAx: rings programmed (13 TX × {} BDs, RXQ/RPQ {} × "
                "{} B, {} WD pages @ IOVA 0x{:x})",
                kBdLen, kBdLen, kRxBufSize, kWdPages, _slab.iova(_wd_off));''',
                '''  _logger->info("PcieDmaAx: rings programmed ({} TX × {} BDs, RXQ/RPQ {} × "
                "{} B, {} WD pages @ IOVA 0x{:x})",
                _is_v1 ? 13 : 7, kBdLen, kBdLen, rx_buf_size(), kWdPages,
                _slab.iova(_wd_off));''',
            ),
            (
                'tx_submit masked check',
                '''  if (hint >= kTxChannels) {
    _logger->error("PcieDmaAx: tx on unknown DMA channel {}", hint);
    return -1;
  }''',
                '''  if (hint >= kTxChannels || _tx[hint].reg_num == 0) {
    _logger->error("PcieDmaAx: tx on unknown/inactive DMA channel {}", hint);
    return -1;
  }''',
            ),
            (
                'submit_wd body length',
                '''  if (len < WD_BODY_LEN_V1) {
    _logger->error("PcieDmaAx: WD buffer too short ({})", len);
    return -1;
  }
  uint32_t dw0 = rd_le32(buf);
  const uint32_t wd_len =
      WD_BODY_LEN_V1 + ((dw0 & WD_BODY0_WDINFO_EN) ? WD_INFO_LEN : 0);''',
                '''  const uint32_t wd_body_len = _is_v1 ? WD_BODY_LEN_V1 : WD_BODY_LEN_V0;
  if (len < wd_body_len) {
    _logger->error("PcieDmaAx: WD buffer too short ({})", len);
    return -1;
  }
  uint32_t dw0 = rd_le32(buf);
  const uint32_t wd_len =
      wd_body_len + ((dw0 & WD_BODY0_WDINFO_EN) ? WD_INFO_LEN : 0);''',
            ),
            (
                'submit_wd addr_info and wd_body patch',
                '''  /* addr_info_v1 ×n over the payload bounce (rtw89_pci_fill_txaddr_info_v1). */
  uint8_t *ai = wp + WP_INFO_SZ;
  uint32_t remain = flen, n = 0;
  uint64_t dma = pl_iova;
  for (; n < ADDR_INFO_NR_MAX && remain; n++) {
    const uint32_t chunk = remain > ADDR_INFO_LEN_MAX ? ADDR_INFO_LEN_MAX : remain;
    remain -= chunk;
    addr_info_write(ai, chunk, /*last=*/remain == 0, dma);
    dma += chunk;
    ai += ADDR_INFO_SZ;
  }
  const uint32_t page_len = wd_len + WP_INFO_SZ + n * ADDR_INFO_SZ;

  /* wd_body patch: this is a WD page (not an inline frame), no USB
   * store-and-forward, and the addr_info count. WP_OFFSET stays as the HAL
   * set it (rtw89 uses a non-zero offset only for a security header). */
  dw0 = (dw0 | WD_BODY0_WD_PAGE) & ~WD_BODY0_STF_MODE;
  wr_le32(pg + 0, dw0);
  uint32_t dw1 = rd_le32(pg + 4);
  dw1 = (dw1 & ~(WD_BODY1_ADDR_INFO_NUM_MSK << WD_BODY1_ADDR_INFO_NUM_SH)) |
        ((n & WD_BODY1_ADDR_INFO_NUM_MSK) << WD_BODY1_ADDR_INFO_NUM_SH);
  wr_le32(pg + 4, dw1);''',
                '''  /* addr_info: 6-byte v1 entries on 8852C; one 8-byte v0 entry on 8852B. */
  uint8_t *ai = wp + WP_INFO_SZ;
  uint32_t n = 0;
  uint32_t ai_bytes = 0;
  if (_is_v1) {
    uint32_t remain = flen;
    uint64_t dma = pl_iova;
    for (; n < ADDR_INFO_NR_MAX && remain; n++) {
      const uint32_t chunk = remain > ADDR_INFO_LEN_MAX ? ADDR_INFO_LEN_MAX : remain;
      remain -= chunk;
      addr_info_write(ai, chunk, /*last=*/remain == 0, dma);
      dma += chunk;
      ai += ADDR_INFO_SZ;
    }
    ai_bytes = n * ADDR_INFO_SZ;
  } else {
    pcie_ax::addr_info_write_v0(ai, flen, pl_iova);
    n = 1;
    ai_bytes = pcie_ax::kAddrInfoV0Bytes;
  }
  const uint32_t page_len = wd_len + WP_INFO_SZ + ai_bytes;

  /* wd_body patch: this is a WD page (not an inline frame), no USB
   * store-and-forward. ADDR_INFO_NUM in dword1 is V1-only (on 8852B v0 the
   * count sits inside addr_info_32.option and body dword1 stays 0). */
  dw0 = (dw0 | WD_BODY0_WD_PAGE) & ~WD_BODY0_STF_MODE;
  wr_le32(pg + 0, dw0);
  if (_is_v1) {
    uint32_t dw1 = rd_le32(pg + 4);
    dw1 = (dw1 & ~(WD_BODY1_ADDR_INFO_NUM_MSK << WD_BODY1_ADDR_INFO_NUM_SH)) |
          ((n & WD_BODY1_ADDR_INFO_NUM_MSK) << WD_BODY1_ADDR_INFO_NUM_SH);
    wr_le32(pg + 4, dw1);
  }''',
            ),
            (
                'reap_rpq_locked rx_buf_stride/size and drv_info_unit',
                '''    const uint8_t *buf = _rpq.bufs + static_cast<size_t>(_rpq.wp) * kRxBufStride;
    const uint32_t info = rd_le32(buf);
    const uint32_t blen = info & RXBD_INFO_LEN_MSK;
    const bool fs = info & RXBD_INFO_FS, ls = info & RXBD_INFO_LS;
    if (fs && ls && blen > 4 && blen <= kRxBufSize) {
      /* rxd (16/32 B) + drv_info, then 4-byte RPP words to the end. */
      kestrel::KestrelRxFrame f{};
      if (kestrel::parse_rx_8852b(buf + 4, blen - 4, f, DRV_INFO_UNIT_8852C)) {''',
                '''    const uint8_t *buf = _rpq.bufs + static_cast<size_t>(_rpq.wp) * rx_buf_stride();
    const uint32_t info = rd_le32(buf);
    const uint32_t blen = info & RXBD_INFO_LEN_MSK;
    const bool fs = info & RXBD_INFO_FS, ls = info & RXBD_INFO_LS;
    if (fs && ls && blen > 4 && blen <= rx_buf_size()) {
      /* rxd (16/32 B) + drv_info, then 4-byte RPP words to the end. */
      kestrel::KestrelRxFrame f{};
      if (kestrel::parse_rx_8852b(buf + 4, blen - 4, f,
                                  _is_v1 ? DRV_INFO_UNIT_8852C : DRV_INFO_UNIT_8852B)) {''',
            ),
            (
                'reap_rxq rx_buf_stride/size',
                '''    const uint8_t *buf = _rxq.bufs + static_cast<size_t>(_rxq.wp) * kRxBufStride;
    const uint32_t info = rd_le32(buf);
    const uint32_t blen = info & RXBD_INFO_LEN_MSK;
    const bool fs = info & RXBD_INFO_FS, ls = info & RXBD_INFO_LS;
    if (blen > 4 && blen <= kRxBufSize) {''',
                '''    const uint8_t *buf = _rxq.bufs + static_cast<size_t>(_rxq.wp) * rx_buf_stride();
    const uint32_t info = rd_le32(buf);
    const uint32_t blen = info & RXBD_INFO_LEN_MSK;
    const bool fs = info & RXBD_INFO_FS, ls = info & RXBD_INFO_LS;
    if (blen > 4 && blen <= rx_buf_size()) {''',
            ),
            (
                'irq_mask and tx_kick',
                '''void PcieDmaAx::irq_mask() {
  _t.mmio_write<uint32_t>(R_AX_PCIE_HIMR00_V1, 0);
  _t.mmio_write<uint32_t>(R_AX_HAXI_HIMR00, 0);
}

void PcieDmaAx::set_tx_kick_deferred(bool deferred) {
  _kick_deferred = deferred;
  if (!deferred) tx_kick();
}

bool PcieDmaAx::tx_kick() {
  bool any = false;
  for (uint32_t ch = 0; ch < kTxChannels; ch++) {
    if (ch == kFwcmdCh) continue;
    std::lock_guard<std::mutex> lk(_tx_mu[ch]);
    TxRing &r = _tx[ch];
    if (r.told == r.wp) continue;''',
                '''void PcieDmaAx::irq_mask() {
  if (_is_v1) {
    _t.mmio_write<uint32_t>(R_AX_PCIE_HIMR00_V1, 0);
    _t.mmio_write<uint32_t>(R_AX_HAXI_HIMR00, 0);
  } else {
    _t.mmio_write<uint32_t>(R_AX_HAXI_HIMR00, 0);
    _t.mmio_write<uint32_t>(R_AX_PCIE_HIMR10, 0);
  }
}

void PcieDmaAx::set_tx_kick_deferred(bool deferred) {
  _kick_deferred = deferred;
  if (!deferred) tx_kick();
}

bool PcieDmaAx::tx_kick() {
  bool any = false;
  for (uint32_t ch = 0; ch < kTxChannels; ch++) {
    if (ch == kFwcmdCh) continue;
    std::lock_guard<std::mutex> lk(_tx_mu[ch]);
    TxRing &r = _tx[ch];
    if (r.reg_num == 0 || r.told == r.wp) continue;''',
            ),
        ],
    )

    # 11. devourer/src/kestrel/MacRegAx.h: add 8852B PCIe registers, bits, DLE & HFC constants
    patch_file(
        devourer / 'src' / 'kestrel' / 'MacRegAx.h',
        [
            (
                '8852B PCIe constants',
                '''constexpr uint32_t S_AX_PTCL_TO_2MS = 0x3f;
constexpr uint32_t B_AX_PTCL_TX_ARB_TO_MODE = 1u << 6;

/* SET_CLR_WORD(orig, val, FIELD) — replace FIELD bits with val. */''',
                '''constexpr uint32_t S_AX_PTCL_TO_2MS = 0x3f;
constexpr uint32_t B_AX_PTCL_TX_ARB_TO_MODE = 1u << 6;

/* ---- PCIe host interface (RTL8852BE — nekodrop (8852BE)) ----
 * Register-level contract from Linux rtw89 (pci.h, reg.h, rtw8852b.c,
 * rtw8852be.c). Shares 0x1000/0x1010/0x1014/0x101C with 8852C but uses the
 * non-V1 field layout and 7 active TX channels (ACH0..3, CH8, CH9, CH12). */
constexpr uint16_t R_AX_SPS_ANA_ON_CTRL2 = 0x0228;
constexpr uint16_t RTL8852B_DEFAULT_SPS_ANA = 0x4F42;
constexpr uint16_t R_AX_HCI_LDO_CTRL = 0x007A;
constexpr uint16_t B_AX_R_AX_VADJ_MSK = 0xFu;
constexpr uint32_t B_AX_PCIE_CALIB_EN_8852B = 1u << 12;      /* R_AX_SYS_SDIO_CTRL */
constexpr uint32_t B_AX_PCIE_DIS_L2_CTRL_LDO_HCI_8852B = 1u << 15;
constexpr uint32_t B_AX_PCIE_DIS_WLSUS_AFT_PDN = 1u << 14;   /* R_AX_SYS_SDIO_CTRL */
constexpr uint32_t B_AX_HOST_CHKSUM_EN = 1u << 14;           /* R_AX_SYS_PW_CTRL (APHY PWRCUT) */
constexpr uint16_t R_AX_PCIE_INIT_CFG2 = 0x1004;
constexpr uint16_t R_AX_PCIE_PS_CTRL = 0x1008;
constexpr uint32_t B_AX_L1OFF_PWR_OFF_EN = 1u << 5;
constexpr uint32_t B_AX_TXHCI_EN_8852B = 1u << 11;           /* R_AX_PCIE_INIT_CFG1 */
constexpr uint32_t B_AX_RXHCI_EN_8852B = 1u << 13;
constexpr uint32_t B_AX_LATENCY_CONTROL = 1u << 12;          /* multi-tag enable */
constexpr uint32_t B_AX_RXBD_MODE_8852B = 1u << 18;          /* 0 = RXBD_PKT */
constexpr uint32_t B_AX_EN_STUCK_DBG = 1u << 22;
constexpr uint32_t B_AX_EN_KEEP_REG = 1u << 23;
constexpr uint8_t B_AX_PCIE_MAX_TXDMA_SH = 8;                /* [10:8] */
constexpr uint32_t B_AX_PCIE_MAX_TXDMA_MSK = 0x7;
constexpr uint8_t B_AX_PCIE_MAX_RXDMA_SH = 14;               /* [16:14] */
constexpr uint32_t B_AX_PCIE_MAX_RXDMA_MSK = 0x7;
constexpr uint32_t MAC_AX_TX_BURST_2048B = 7;
constexpr uint32_t MAC_AX_RX_BURST_128B = 3;
constexpr uint8_t B_AX_WD_ITVL_IDLE_8852B_SH = 24;           /* R_AX_PCIE_INIT_CFG2 [27:24] */
constexpr uint32_t B_AX_WD_ITVL_IDLE_8852B_MSK = 0xF;
constexpr uint8_t B_AX_WD_ITVL_ACT_8852B_SH = 16;            /* R_AX_PCIE_INIT_CFG2 [19:16] */
constexpr uint32_t B_AX_WD_ITVL_ACT_8852B_MSK = 0xF;
constexpr uint32_t PCIE_DMA_STOP1_CHANS_8852B = 0x70F00u;    /* ACH0..3, CH8, CH9, CH12 */
constexpr uint32_t PCIE_DMA_BUSY1_CHANS_8852B = 0x70F00u;
constexpr uint32_t PCIE_DMA_BUSY1_RX_8852B = 0x3u;           /* RXQ | RPQ in 0x101C */
constexpr uint32_t TXBD_RWPTR_CLR1_8852B = 0x70Fu;           /* ACH0..3, CH8, CH9, CH12 */
constexpr uint16_t R_AX_RXBD_RWPTR_CLR_8852B = 0x1018;
constexpr uint16_t R_AX_MDIO_CFG = 0x10A0;
constexpr uint16_t R_AX_MDIO_WDATA = 0x10A4;
constexpr uint16_t R_AX_MDIO_RDATA = 0x10A6;
constexpr uint16_t B_AX_MDIO_WFLAG = 1u << 8;
constexpr uint16_t B_AX_MDIO_RFLAG = 1u << 9;
constexpr uint16_t B_AX_MDIO_PHY_ADDR_SH = 12;
constexpr uint16_t B_AX_MDIO_PHY_ADDR_MSK = 0x3;
constexpr uint16_t R_AX_PCIE_DBG_CTRL = 0x11C0;
constexpr uint32_t B_AX_ASFF_FULL_NO_STK = 1u << 1;
constexpr uint32_t B_AX_EN_STUCK_DBG_11C0 = 1u << 0;
constexpr uint16_t R_AX_LBC_WATCHDOG = 0x11D8;
constexpr uint32_t B_AX_LBC_EN = 1u << 0;
constexpr uint32_t B_AX_LBC_FLAG = 1u << 1;
constexpr uint8_t B_AX_LBC_TIMER_SH = 4;
constexpr uint32_t B_AX_LBC_TIMER_MSK = 0xF;
constexpr uint32_t MAC_AX_LBC_TMR_2MS = 8;
constexpr uint16_t R_AX_PCIE_EXP_CTRL = 0x13F0;
constexpr uint32_t B_AX_SIC_EN_FORCE_CLKREQ = 1u << 4;
constexpr uint8_t B_AX_MAX_TAG_NUM_8852B_SH = 16;            /* [18:16] */
constexpr uint32_t B_AX_MAX_TAG_NUM_8852B_MSK = 0x7;
constexpr uint8_t B_AX_EN_DBG_PCIE_SH = 0;                   /* [1:0] */
constexpr uint32_t B_AX_EN_DBG_PCIE_MSK = 0x3;
/* 8852B LTR (rtw89_pci_ltr_set). */
constexpr uint32_t B_AX_LTR_EN_8852B = 1u << 1;
constexpr uint32_t B_AX_LTR_WD_NOEMP_CHK_8852B = 1u << 6;
constexpr uint8_t B_AX_LTR_SPACE_IDX_8852B_SH = 12;          /* [13:12] */
constexpr uint32_t B_AX_LTR_SPACE_IDX_8852B_MSK = 0x3;
constexpr uint16_t R_AX_LTR_IDLE_LATENCY_8852B = 0x8418;
constexpr uint16_t R_AX_LTR_ACTIVE_LATENCY_8852B = 0x841C;
/* 8852B PCIe SCC (NIC) DLE quota (rtw8852b_dle_mem_pcie[RTW89_QTA_SCC]). */
constexpr uint16_t PCIE_SCC_WDE_LNK_PAGE_8852B = 510;
constexpr uint16_t PCIE_SCC_WDE_UNLNK_PAGE_8852B = 2;
constexpr uint16_t PCIE_SCC_PLE_LNK_PAGE_8852B = 496;
constexpr uint16_t PCIE_SCC_WDE_QT_HIF_8852B = 446;
constexpr uint16_t PCIE_SCC_WDE_QT_WCPU_8852B = 48;
constexpr uint16_t PCIE_SCC_WDE_QT_CPU_IO_8852B = 16;
constexpr uint16_t PCIE_SCC_PLE_MIN_8852B[11] = {147, 0, 16, 20, 17, 13,
                                                 89, 0, 32, 14, 8};
constexpr uint16_t PCIE_SCC_PLE_MAX_8852B[11] = {147, 0, 16, 20, 157, 13,
                                                 229, 0, 172, 14, 24};
/* 8852B PCIe SCC (NIC) HFC quota (rtw8852b_hfc_param_ini_pcie[RTW89_QTA_SCC]). */
constexpr uint16_t HFC_PCIE_CH01_MIN_8852B = 5;
constexpr uint16_t HFC_PCIE_CH01_MAX_8852B = 341;
constexpr uint16_t HFC_PCIE_CH_OTHER_MIN_8852B = 4;
constexpr uint16_t HFC_PCIE_CH_OTHER_MAX_8852B = 342;
constexpr uint16_t HFC_PCIE_PUB_G0_8852B = 446;
constexpr uint16_t HFC_PCIE_PUB_G1_8852B = 0;
constexpr uint16_t HFC_PCIE_PUB_MAX_8852B = 446;

/* SET_CLR_WORD(orig, val, FIELD) — replace FIELD bits with val. */''',
            ),
        ],
    )

    # 12. devourer/src/kestrel/KestrelFw.cpp: 8852B PCIe DLFW HFC precharge (40, X1)
    patch_file(
        devourer / 'src' / 'kestrel' / 'KestrelFw.cpp',
        [
            (
                'hfc_init_dlfw 8852B PCIe',
                '''  const uint16_t h2c_prec =
      _pcie ? r::HFC_PCIE_DLFW_H2C_PREC_8852C : r::HFC_USB_H2C_PREC_8852B;
  _device.rtw_write32(
      page_ctrl, (static_cast<uint32_t>(h2c_prec & r::B_AX_PREC_PAGE_CH12_MSK)
                  << r::B_AX_PREC_PAGE_CH12_SH));
  _device.rtw_write32(
      fc_ctrl,
      r::set_clr_word(_device.rtw_read32(fc_ctrl), r::HFC_FULL_COND_X2,
                      r::B_AX_HCI_FC_CH12_FULL_COND_MSK,
                      r::B_AX_HCI_FC_CH12_FULL_COND_SH));''',
                '''  /* nekodrop (8852BE): 8852B PCIe uses h2c_prec=40 + FULL_COND_X1. */
  const uint16_t h2c_prec =
      _pcie ? (c ? r::HFC_PCIE_DLFW_H2C_PREC_8852C : r::HFC_PCIE_H2C_PREC)
            : r::HFC_USB_H2C_PREC_8852B;
  const uint8_t h2c_cond =
      (_pcie && !c) ? r::HFC_FULL_COND_X1 : r::HFC_FULL_COND_X2;
  _device.rtw_write32(
      page_ctrl, (static_cast<uint32_t>(h2c_prec & r::B_AX_PREC_PAGE_CH12_MSK)
                  << r::B_AX_PREC_PAGE_CH12_SH));
  _device.rtw_write32(
      fc_ctrl,
      r::set_clr_word(_device.rtw_read32(fc_ctrl), h2c_cond,
                      r::B_AX_HCI_FC_CH12_FULL_COND_MSK,
                      r::B_AX_HCI_FC_CH12_FULL_COND_SH));''',
            ),
        ],
    )

    # 13. devourer/src/kestrel/HalKestrel.h: declare pcie_mdio_write16_mask helper
    patch_file(
        devourer / 'src' / 'kestrel' / 'HalKestrel.h',
        [
            (
                'pcie_mdio_write16_mask decl',
                '  bool pcie_ltr_silence();',
                '''  bool pcie_ltr_silence();
  bool pcie_mdio_write16_mask(uint8_t addr, uint16_t mask, uint16_t data,
                              uint8_t speed); /* nekodrop (8852BE) */''',
            ),
        ],
    )

    # 14. devourer/src/kestrel/HalKestrel.cpp: 8852B PCIe pre/post/deinit, power_on, DLE, HFC
    patch_file(
        devourer / 'src' / 'kestrel' / 'HalKestrel.cpp',
        [
            (
                'pcie helpers and pre/post/deinit for 8852B',
                '''void HalKestrel::pcie_ctrl_dma_all(bool enable) {
  /* rtw89_pci_ctrl_dma_all: STOP_AXI_MST + the TX/RX HCI enables. */
  if (enable) {
    clr32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_STOP_AXI_MST);
    set32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_TXHCI_EN_V1 | r::B_AX_RXHCI_EN_V1);
  } else {
    set32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_STOP_AXI_MST);
    clr32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_TXHCI_EN_V1 | r::B_AX_RXHCI_EN_V1);
  }
}

bool HalKestrel::pcie_poll_dma_idle() {
  /* rtw89_pci_poll_dma_all_idle: TX channel busy (BUSY1 [18:8], BUSY2 CH10/
   * 11), then RX (BUSY3 RXQ/RPQ). 10 us × 10 = the rtw89 100 us window. */
  auto idle = [&](uint16_t reg, uint32_t mask, const char *what) {
    for (int i = 0; i < 10; i++) {
      if ((_device.rtw_read32(reg) & mask) == 0)
        return true;
      delay_us(10);
    }
    _logger->error("Kestrel PCIe: {} DMA busy (0x{:04x}=0x{:08x})", what, reg,
                   _device.rtw_read32(reg));
    return false;
  };
  return idle(r::R_AX_HAXI_DMA_BUSY1, r::HAXI_DMA_BUSY1_CHANS, "txdma ch") &&
         idle(r::R_AX_HAXI_DMA_BUSY2, r::HAXI_DMA_BUSY2_CHANS, "txdma ch10/11") &&
         idle(r::R_AX_HAXI_DMA_BUSY3, r::HAXI_DMA_BUSY3_RX, "rxdma");
}

void HalKestrel::pcie_clr_idx_all() {
  /* rtw89_pci_clr_idx_all_ax (8852C): every TX channel incl. ACH4-7 and
   * CH10/11, plus RXQ + RPQ. */
  set32(r::R_AX_TXBD_RWPTR_CLR1, r::TXBD_RWPTR_CLR1_ALL);
  set32(r::R_AX_TXBD_RWPTR_CLR2_V1, r::TXBD_RWPTR_CLR2_ALL);
  set32(r::R_AX_RXBD_RWPTR_CLR_V1, r::RXBD_RWPTR_CLR_ALL);
}

void HalKestrel::pcie_mode_op() {
  /* rtw89_pci_mode_op, 8852C (rtw8852c_pci_info): BD trunc mode needs no
   * write here; RXBD_PKT (one packet per BD); TX burst 256 B / RX burst
   * 128 B (V1 encodings); 8 DMA tags; WD DMA intervals 256 ns; and the
   * TRUNC-mode address-info selects (host 8-byte addr-info select set, WD
   * addr-info length clear — rtw89 does this even though the 8852C fills
   * 6-byte v1 entries). */
  clr32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_RXBD_MODE_V1);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_TX_BURST_V1_256B,
          r::B_AX_HAXI_MAX_TXDMA_MSK, r::B_AX_HAXI_MAX_TXDMA_SH);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_RX_BURST_V1_128B,
          r::B_AX_HAXI_MAX_RXDMA_MSK, r::B_AX_HAXI_MAX_RXDMA_SH);
  field32(r::R_AX_HAXI_EXP_CTRL, r::MAC_AX_TAG_NUM_8, r::B_AX_MAX_TAG_NUM_V1_MSK,
          r::B_AX_MAX_TAG_NUM_V1_SH);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_WD_DMA_INTVL_256NS,
          r::B_AX_WD_ITVL_IDLE_V1_MSK, r::B_AX_WD_ITVL_IDLE_V1_SH);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_WD_DMA_INTVL_256NS,
          r::B_AX_WD_ITVL_ACT_V1_MSK, r::B_AX_WD_ITVL_ACT_V1_SH);
  set32(r::R_AX_TX_ADDRESS_INFO_MODE_SETTING, r::B_AX_HOST_ADDR_INFO_8B_SEL);
  clr32(r::R_AX_PKTIN_SETTING, r::B_AX_WD_ADDR_INFO_LENGTH);
}

bool HalKestrel::pcie_rst_bdram() {
  set32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_RST_BDRAM);
  for (int i = 0; i < 100; i++) {
    if (!(_device.rtw_read32(r::R_AX_HAXI_INIT_CFG1) & r::B_AX_RST_BDRAM))
      return true;
    delay_us(1);
  }
  _logger->error("Kestrel PCIe: BDRAM reset did not clear (0x1000=0x{:08x})",
                 _device.rtw_read32(r::R_AX_HAXI_INIT_CFG1));
  return false;
}

void HalKestrel::pcie_ctrl_txdma_ch(bool enable) {
  /* rtw89_pci_ctrl_txdma_ch_ax: every TX channel's STOP bit (STOP1 [18:8],
   * STOP2 CH10/11). */
  if (enable) {
    clr32(r::R_AX_HAXI_DMA_STOP1, r::HAXI_DMA_STOP1_CHANS);
    clr32(r::R_AX_HAXI_DMA_STOP2, r::HAXI_DMA_STOP2_CHANS);
  } else {
    set32(r::R_AX_HAXI_DMA_STOP1, r::HAXI_DMA_STOP1_CHANS);
    set32(r::R_AX_HAXI_DMA_STOP2, r::HAXI_DMA_STOP2_CHANS);
  }
}

/* A register reading 0xFFFFFFFF/0xEAEAEAEA means the LTR block is unreachable
 * — refuse rather than program (or write back) garbage. */
static bool ltr_reg_unreadable(uint32_t v) {
  return v == 0xFFFFFFFFu || v == 0xEAEAEAEAu;
}

bool HalKestrel::pcie_ltr_set(bool enable) {
  /* rtw89_pci_ltr_set_v1. */
  for (uint16_t reg : {r::R_AX_LTR_CTRL_0, r::R_AX_LTR_CTRL_1, r::R_AX_LTR_DEC_CTRL,
                       r::R_AX_LTR_LATENCY_IDX3, r::R_AX_LTR_LATENCY_IDX0}) {
    if (ltr_reg_unreadable(_device.rtw_read32(reg))) {
      _logger->error("Kestrel PCIe: LTR register 0x{:04x} unreadable", reg);
      return false;
    }
  }
  uint32_t dec = _device.rtw_read32(r::R_AX_LTR_DEC_CTRL);
  if (!enable) {
    dec &= ~(r::B_AX_LTR_HW_DEC_EN | r::B_AX_LTR_FW_DEC_EN | r::B_AX_LTR_DRV_DEC_EN |
             (r::B_AX_LTR_IDX_DRV_MSK << r::B_AX_LTR_IDX_DRV_SH));
    dec |= (r::PCIE_LTR_IDX_IDLE << r::B_AX_LTR_IDX_DRV_SH) | r::B_AX_LTR_REQ_DRV;
  } else {
    dec |= r::B_AX_LTR_HW_DEC_EN;
  }
  dec = r::set_clr_word(dec, r::PCI_LTR_SPC_500US, r::B_AX_LTR_SPACE_IDX_V1_MSK,
                        r::B_AX_LTR_SPACE_IDX_V1_SH);
  if (enable)
    set32(r::R_AX_LTR_CTRL_0, r::B_AX_LTR_WD_NOEMP_CHK_V1 | r::B_AX_LTR_HW_EN);
  field32(r::R_AX_LTR_CTRL_0, r::PCI_LTR_IDLE_TIMER_3_2MS,
          r::B_AX_LTR_IDLE_TIMER_IDX_MSK, r::B_AX_LTR_IDLE_TIMER_IDX_SH);
  field32(r::R_AX_LTR_CTRL_1, r::LTR_RX_TH_8852C, r::B_AX_LTR_RX0_TH_MSK,
          r::B_AX_LTR_RX0_TH_SH);
  field32(r::R_AX_LTR_CTRL_1, r::LTR_RX_TH_8852C, r::B_AX_LTR_RX1_TH_MSK,
          r::B_AX_LTR_RX1_TH_SH);
  _device.rtw_write32(r::R_AX_LTR_DEC_CTRL, dec);
  _device.rtw_write32(r::R_AX_LTR_LATENCY_IDX3, r::LTR_IDLE_LATENCY_8852C);
  _device.rtw_write32(r::R_AX_LTR_LATENCY_IDX0, r::LTR_ACTIVE_LATENCY_8852C);
  return true;
}

bool HalKestrel::pcie_ltr_silence() {
  const uint32_t ctrl0 = _device.rtw_read32(r::R_AX_LTR_CTRL_0);
  const uint32_t dec = _device.rtw_read32(r::R_AX_LTR_DEC_CTRL);
  if (ltr_reg_unreadable(ctrl0) || ltr_reg_unreadable(dec)) {
    _logger->error("Kestrel PCIe: LTR registers unreadable (CTRL_0=0x{:08x} "
                   "DEC_CTRL=0x{:08x}) — cannot silence LTR",
                   ctrl0, dec);
    return false;
  }
  _device.rtw_write32(r::R_AX_LTR_CTRL_0, ctrl0 & ~r::B_AX_LTR_HW_EN);
  _device.rtw_write32(r::R_AX_LTR_DEC_CTRL,
                      dec & ~(r::B_AX_LTR_HW_DEC_EN | r::B_AX_LTR_FW_DEC_EN |
                              r::B_AX_LTR_DRV_DEC_EN | r::B_AX_LTR_REQ_DRV));
  _logger->info("Kestrel PCIe: LTR silenced — host has LTR disabled for this "
                "function (DEVCTL2 LTR_EN=0: a port on the path lacks LTR); "
                "was CTRL_0=0x{:08x} DEC_CTRL=0x{:08x}",
                ctrl0, dec);
  return true;
}

bool HalKestrel::pcie_pre_init() {
  /* rtw89_pci_ops_mac_pre_init_ax, the 8852C branches in order. Runs after
   * dmac_pre_init (HAXI DMA_MODE=PCIE_1B, HCI enables) and before FWDL. */
  if (_variant != ChipVariant::C8852C) {
    _logger->error("Kestrel PCIe: pre-init is ported for the 8852C only");
    return false;
  }
  /* Before anything can arm it: a chip the host forbids LTR must never send
   * one (an Unsupported Request behind a non-LTR switch → AER link reset). */
  if (!_device.ltr_allowed())
    pcie_ltr_silence();
  pcie_disable_eq();
  /* deglitch: clear RAC_ANA24[11:8] on both PHYs (16-bit registers). */
  for (uint16_t phy : {r::R_RAC_DIRECT_OFFSET_G1, r::R_RAC_DIRECT_OFFSET_G2}) {
    const uint16_t reg = phy + r::RAC_ANA24 * r::RAC_MULT;
    _device.rtw_write16(reg, _device.rtw_read16(reg) & ~r::B_AX_DEGLITCH);
  }
  clr32(r::R_AX_SYS_SDIO_CTRL, r::B_AX_PCIE_DIS_L2_CTRL_LDO_HCI); /* hci_ldo */
  set32(r::R_AX_HCI_OPT_CTRL, r::B_AX_WAKE_CTRL);                 /* power_wake */
  set32(r::R_AX_PCIE_BG_CLR, r::B_AX_BG_CLR_ASYNC_M3);            /* autoload_hang */
  clr32(r::R_AX_PCIE_BG_CLR, r::B_AX_BG_CLR_ASYNC_M3);
  /* l12_vmain / gen2_force_ib are CAV-cut only; the plugged modules are cut 1
   * (CBV), so they are deliberately not transcribed. */
  clr32(r::R_AX_PCIE_PS_CTRL_V1, r::B_AX_SEL_REQ_ENTR_L1);        /* l1_ent_lat */
  set32(r::R_AX_PCIE_PS_CTRL_V1, r::B_AX_DMAC0_EXIT_L1_EN);       /* wd_exit_l1 */
  /* set_io_rcy: 6 ms analog watchdogs on M1/M2/E0, S1 off. */
  _device.rtw_write32(r::R_AX_PCIE_WDT_TIMER_M1, r::MAC_AX_IO_RCY_ANA_TMR_6MS);
  _device.rtw_write32(r::R_AX_PCIE_WDT_TIMER_M2, r::MAC_AX_IO_RCY_ANA_TMR_6MS);
  _device.rtw_write32(r::R_AX_PCIE_WDT_TIMER_E0, r::MAC_AX_IO_RCY_ANA_TMR_6MS);
  set32(r::R_AX_PCIE_IO_RCY_M1, r::B_AX_PCIE_IO_RCY_WDT_MODE);
  set32(r::R_AX_PCIE_IO_RCY_M2, r::B_AX_PCIE_IO_RCY_WDT_MODE);
  set32(r::R_AX_PCIE_IO_RCY_E0, r::B_AX_PCIE_IO_RCY_WDT_MODE);
  clr32(r::R_AX_PCIE_IO_RCY_S1, r::B_AX_PCIE_IO_RCY_WDT_MODE);

  set32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_WPDMA);
  pcie_ctrl_dma_all(false);
  if (!pcie_poll_dma_idle())
    return false;
  pcie_clr_idx_all();
  pcie_mode_op();
  /* Ring base/num/BDRAM registers + host indices — the transport's memory. */
  _device.hci_setup();
  if (!pcie_rst_bdram())
    return false;
  /* Only the FWCMD channel open until the firmware is up. */
  pcie_ctrl_txdma_ch(false);
  clr32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_CH12);
  pcie_ctrl_dma_all(true);
  _logger->info("Kestrel PCIe: HAXI pre-init done (DMA up, CH12 open)");
  return true;
}

void HalKestrel::pcie_init() {
  /* rtw89_pci_ops_mac_post_init_ax: LTR on, every TX channel open, release
   * the WPDMA + PCIe IO stops. */
  /* Report what actually happened, not the permission bit. */
  const bool allowed = _device.ltr_allowed();
  const bool ok = allowed ? pcie_ltr_set(true) : pcie_ltr_silence();
  const char *ltr = ok ? (allowed ? "on" : "silenced") : "FAILED";
  if (!ok)
    _logger->warn("Kestrel PCIe: LTR could not be {} — registers unreadable",
                  allowed ? "enabled" : "silenced");
  pcie_ctrl_txdma_ch(true);
  clr32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_WPDMA | r::B_AX_STOP_PCIEIO);
  _logger->info("Kestrel PCIe: post-init done (LTR {}, all TX channels open)",
                ltr);
}

void HalKestrel::pcie_deinit() {
  /* rtw89_pci_ops_deinit: LTR off, DMA stopped, indices cleared. The rtw89
   * off path itself requests an idle LTR, so a host-forbidden function is
   * silenced instead. */
  if (_device.ltr_allowed())
    pcie_ltr_set(false);
  else
    pcie_ltr_silence();
  pcie_ctrl_dma_all(false);
  pcie_clr_idx_all();
  _logger->info("Kestrel PCIe: HAXI DMA stopped");
}''',
                '''bool HalKestrel::pcie_mdio_write16_mask(uint8_t addr, uint16_t mask,
                                        uint16_t data, uint8_t speed) {
  /* nekodrop (8852BE): rtw89_write16_mdio_mask (pci.c:2120..2201). */
  auto check_mdio = [&](uint16_t rw_bit) -> bool {
    _device.rtw_write8(r::R_AX_MDIO_CFG, static_cast<uint8_t>(addr & 0x1Fu));
    uint16_t v = _device.rtw_read16(r::R_AX_MDIO_CFG);
    const uint16_t pg = static_cast<uint16_t>((speed ? 2u : 0u) + (addr < 0x20 ? 0u : 1u));
    v = static_cast<uint16_t>(
        (v & ~(r::B_AX_MDIO_PHY_ADDR_MSK << r::B_AX_MDIO_PHY_ADDR_SH)) |
        ((pg & r::B_AX_MDIO_PHY_ADDR_MSK) << r::B_AX_MDIO_PHY_ADDR_SH));
    _device.rtw_write16(r::R_AX_MDIO_CFG, v);
    _device.rtw_write16(r::R_AX_MDIO_CFG, static_cast<uint16_t>(v | rw_bit));
    for (int i = 0; i < 200; i++) {
      if ((_device.rtw_read16(r::R_AX_MDIO_CFG) & rw_bit) == 0)
        return true;
      delay_us(10);
    }
    return false;
  };
  if (!check_mdio(r::B_AX_MDIO_RFLAG)) {
    _logger->warn("Kestrel PCIe: MDIO R16 0x{:02x} timeout", addr);
    return false;
  }
  uint16_t val = _device.rtw_read16(r::R_AX_MDIO_RDATA);
  uint16_t shift = 0;
  uint16_t m = mask;
  while (m && (m & 1u) == 0) {
    m >>= 1;
    shift++;
  }
  val = static_cast<uint16_t>((val & ~mask) | ((data << shift) & mask));
  _device.rtw_write16(r::R_AX_MDIO_WDATA, val);
  if (!check_mdio(r::B_AX_MDIO_WFLAG)) {
    _logger->warn("Kestrel PCIe: MDIO W16 0x{:02x}=0x{:04x} timeout", addr, val);
    return false;
  }
  return true;
}

void HalKestrel::pcie_ctrl_dma_all(bool enable) {
  if (_variant != ChipVariant::C8852C) {
    /* 8852B (rtw89_pci_ctrl_dma_all): dma_io_stop is 0x1010[20], TRX in 0x1000[11,13]. */
    if (enable) {
      clr32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_PCIEIO);
      set32(r::R_AX_HAXI_INIT_CFG1,
            r::B_AX_TXHCI_EN_8852B | r::B_AX_RXHCI_EN_8852B);
    } else {
      set32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_PCIEIO);
      clr32(r::R_AX_HAXI_INIT_CFG1,
            r::B_AX_TXHCI_EN_8852B | r::B_AX_RXHCI_EN_8852B);
    }
    return;
  }
  /* rtw89_pci_ctrl_dma_all (8852C): STOP_AXI_MST + the TX/RX HCI enables. */
  if (enable) {
    clr32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_STOP_AXI_MST);
    set32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_TXHCI_EN_V1 | r::B_AX_RXHCI_EN_V1);
  } else {
    set32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_STOP_AXI_MST);
    clr32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_TXHCI_EN_V1 | r::B_AX_RXHCI_EN_V1);
  }
}

bool HalKestrel::pcie_poll_dma_idle() {
  /* rtw89_pci_poll_dma_all_idle. 10 us × 10 = the rtw89 100 us window. */
  auto idle = [&](uint16_t reg, uint32_t mask, const char *what) {
    for (int i = 0; i < 10; i++) {
      if ((_device.rtw_read32(reg) & mask) == 0)
        return true;
      delay_us(10);
    }
    _logger->error("Kestrel PCIe: {} DMA busy (0x{:04x}=0x{:08x})", what, reg,
                   _device.rtw_read32(reg));
    return false;
  };
  if (_variant != ChipVariant::C8852C) {
    return idle(r::R_AX_HAXI_DMA_BUSY1, r::PCIE_DMA_BUSY1_CHANS_8852B, "txdma ch") &&
           idle(r::R_AX_HAXI_DMA_BUSY1, r::PCIE_DMA_BUSY1_RX_8852B, "rxdma");
  }
  return idle(r::R_AX_HAXI_DMA_BUSY1, r::HAXI_DMA_BUSY1_CHANS, "txdma ch") &&
         idle(r::R_AX_HAXI_DMA_BUSY2, r::HAXI_DMA_BUSY2_CHANS, "txdma ch10/11") &&
         idle(r::R_AX_HAXI_DMA_BUSY3, r::HAXI_DMA_BUSY3_RX, "rxdma");
}

void HalKestrel::pcie_clr_idx_all() {
  if (_variant != ChipVariant::C8852C) {
    set32(r::R_AX_TXBD_RWPTR_CLR1, r::TXBD_RWPTR_CLR1_8852B);
    set32(r::R_AX_RXBD_RWPTR_CLR_8852B, r::RXBD_RWPTR_CLR_ALL);
    return;
  }
  /* rtw89_pci_clr_idx_all_ax (8852C): every TX channel incl. ACH4-7 and
   * CH10/11, plus RXQ + RPQ. */
  set32(r::R_AX_TXBD_RWPTR_CLR1, r::TXBD_RWPTR_CLR1_ALL);
  set32(r::R_AX_TXBD_RWPTR_CLR2_V1, r::TXBD_RWPTR_CLR2_ALL);
  set32(r::R_AX_RXBD_RWPTR_CLR_V1, r::RXBD_RWPTR_CLR_ALL);
}

void HalKestrel::pcie_mode_op() {
  if (_variant != ChipVariant::C8852C) {
    /* rtw89_pci_mode_op, 8852B (rtw8852b_pci_info): RXBD_PKT, TX burst 2048 B,
     * RX burst 128 B, multi-tag (8 tags), WD intervals 256 ns, TRUNC addr-info. */
    clr32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_RXBD_MODE_8852B);
    field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_TX_BURST_2048B,
            r::B_AX_PCIE_MAX_TXDMA_MSK, r::B_AX_PCIE_MAX_TXDMA_SH);
    field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_RX_BURST_128B,
            r::B_AX_PCIE_MAX_RXDMA_MSK, r::B_AX_PCIE_MAX_RXDMA_SH);
    set32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_LATENCY_CONTROL);
    field32(r::R_AX_PCIE_EXP_CTRL, r::MAC_AX_TAG_NUM_8,
            r::B_AX_MAX_TAG_NUM_8852B_MSK, r::B_AX_MAX_TAG_NUM_8852B_SH);
    field32(r::R_AX_PCIE_INIT_CFG2, r::MAC_AX_WD_DMA_INTVL_256NS,
            r::B_AX_WD_ITVL_IDLE_8852B_MSK, r::B_AX_WD_ITVL_IDLE_8852B_SH);
    field32(r::R_AX_PCIE_INIT_CFG2, r::MAC_AX_WD_DMA_INTVL_256NS,
            r::B_AX_WD_ITVL_ACT_8852B_MSK, r::B_AX_WD_ITVL_ACT_8852B_SH);
    set32(r::R_AX_TX_ADDRESS_INFO_MODE_SETTING, r::B_AX_HOST_ADDR_INFO_8B_SEL);
    clr32(r::R_AX_PKTIN_SETTING, r::B_AX_WD_ADDR_INFO_LENGTH);
    return;
  }
  /* rtw89_pci_mode_op, 8852C (rtw8852c_pci_info): BD trunc mode needs no
   * write here; RXBD_PKT (one packet per BD); TX burst 256 B / RX burst
   * 128 B (V1 encodings); 8 DMA tags; WD DMA intervals 256 ns; and the
   * TRUNC-mode address-info selects (host 8-byte addr-info select set, WD
   * addr-info length clear — rtw89 does this even though the 8852C fills
   * 6-byte v1 entries). */
  clr32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_RXBD_MODE_V1);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_TX_BURST_V1_256B,
          r::B_AX_HAXI_MAX_TXDMA_MSK, r::B_AX_HAXI_MAX_TXDMA_SH);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_RX_BURST_V1_128B,
          r::B_AX_HAXI_MAX_RXDMA_MSK, r::B_AX_HAXI_MAX_RXDMA_SH);
  field32(r::R_AX_HAXI_EXP_CTRL, r::MAC_AX_TAG_NUM_8, r::B_AX_MAX_TAG_NUM_V1_MSK,
          r::B_AX_MAX_TAG_NUM_V1_SH);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_WD_DMA_INTVL_256NS,
          r::B_AX_WD_ITVL_IDLE_V1_MSK, r::B_AX_WD_ITVL_IDLE_V1_SH);
  field32(r::R_AX_HAXI_INIT_CFG1, r::MAC_AX_WD_DMA_INTVL_256NS,
          r::B_AX_WD_ITVL_ACT_V1_MSK, r::B_AX_WD_ITVL_ACT_V1_SH);
  set32(r::R_AX_TX_ADDRESS_INFO_MODE_SETTING, r::B_AX_HOST_ADDR_INFO_8B_SEL);
  clr32(r::R_AX_PKTIN_SETTING, r::B_AX_WD_ADDR_INFO_LENGTH);
}

bool HalKestrel::pcie_rst_bdram() {
  set32(r::R_AX_HAXI_INIT_CFG1, r::B_AX_RST_BDRAM);
  for (int i = 0; i < 100; i++) {
    if (!(_device.rtw_read32(r::R_AX_HAXI_INIT_CFG1) & r::B_AX_RST_BDRAM))
      return true;
    delay_us(1);
  }
  _logger->error("Kestrel PCIe: BDRAM reset did not clear (0x1000=0x{:08x})",
                 _device.rtw_read32(r::R_AX_HAXI_INIT_CFG1));
  return false;
}

void HalKestrel::pcie_ctrl_txdma_ch(bool enable) {
  if (_variant != ChipVariant::C8852C) {
    if (enable)
      clr32(r::R_AX_HAXI_DMA_STOP1, r::PCIE_DMA_STOP1_CHANS_8852B);
    else
      set32(r::R_AX_HAXI_DMA_STOP1, r::PCIE_DMA_STOP1_CHANS_8852B);
    return;
  }
  /* rtw89_pci_ctrl_txdma_ch_ax: every TX channel's STOP bit (STOP1 [18:8],
   * STOP2 CH10/11). */
  if (enable) {
    clr32(r::R_AX_HAXI_DMA_STOP1, r::HAXI_DMA_STOP1_CHANS);
    clr32(r::R_AX_HAXI_DMA_STOP2, r::HAXI_DMA_STOP2_CHANS);
  } else {
    set32(r::R_AX_HAXI_DMA_STOP1, r::HAXI_DMA_STOP1_CHANS);
    set32(r::R_AX_HAXI_DMA_STOP2, r::HAXI_DMA_STOP2_CHANS);
  }
}

/* A register reading 0xFFFFFFFF/0xEAEAEAEA means the LTR block is unreachable
 * — refuse rather than program (or write back) garbage. */
static bool ltr_reg_unreadable(uint32_t v) {
  return v == 0xFFFFFFFFu || v == 0xEAEAEAEAu;
}

bool HalKestrel::pcie_ltr_set(bool enable) {
  if (_variant != ChipVariant::C8852C) {
    /* rtw89_pci_ltr_set (8852B). */
    if (!enable)
      return true;
    for (uint16_t reg : {r::R_AX_LTR_CTRL_0, r::R_AX_LTR_CTRL_1,
                         r::R_AX_LTR_IDLE_LATENCY_8852B,
                         r::R_AX_LTR_ACTIVE_LATENCY_8852B}) {
      if (ltr_reg_unreadable(_device.rtw_read32(reg))) {
        _logger->error("Kestrel PCIe: 8852B LTR register 0x{:04x} unreadable", reg);
        return false;
      }
    }
    set32(r::R_AX_LTR_CTRL_0,
          r::B_AX_LTR_HW_EN | r::B_AX_LTR_EN_8852B | r::B_AX_LTR_WD_NOEMP_CHK_8852B);
    field32(r::R_AX_LTR_CTRL_0, r::PCI_LTR_SPC_500US,
            r::B_AX_LTR_SPACE_IDX_8852B_MSK, r::B_AX_LTR_SPACE_IDX_8852B_SH);
    field32(r::R_AX_LTR_CTRL_0, r::PCI_LTR_IDLE_TIMER_3_2MS,
            r::B_AX_LTR_IDLE_TIMER_IDX_MSK, r::B_AX_LTR_IDLE_TIMER_IDX_SH);
    field32(r::R_AX_LTR_CTRL_1, r::LTR_RX_TH_8852C, r::B_AX_LTR_RX0_TH_MSK,
            r::B_AX_LTR_RX0_TH_SH);
    field32(r::R_AX_LTR_CTRL_1, r::LTR_RX_TH_8852C, r::B_AX_LTR_RX1_TH_MSK,
            r::B_AX_LTR_RX1_TH_SH);
    _device.rtw_write32(r::R_AX_LTR_IDLE_LATENCY_8852B, r::LTR_IDLE_LATENCY_8852C);
    _device.rtw_write32(r::R_AX_LTR_ACTIVE_LATENCY_8852B, r::LTR_ACTIVE_LATENCY_8852C);
    return true;
  }
  /* rtw89_pci_ltr_set_v1. */
  for (uint16_t reg : {r::R_AX_LTR_CTRL_0, r::R_AX_LTR_CTRL_1, r::R_AX_LTR_DEC_CTRL,
                       r::R_AX_LTR_LATENCY_IDX3, r::R_AX_LTR_LATENCY_IDX0}) {
    if (ltr_reg_unreadable(_device.rtw_read32(reg))) {
      _logger->error("Kestrel PCIe: LTR register 0x{:04x} unreadable", reg);
      return false;
    }
  }
  uint32_t dec = _device.rtw_read32(r::R_AX_LTR_DEC_CTRL);
  if (!enable) {
    dec &= ~(r::B_AX_LTR_HW_DEC_EN | r::B_AX_LTR_FW_DEC_EN | r::B_AX_LTR_DRV_DEC_EN |
             (r::B_AX_LTR_IDX_DRV_MSK << r::B_AX_LTR_IDX_DRV_SH));
    dec |= (r::PCIE_LTR_IDX_IDLE << r::B_AX_LTR_IDX_DRV_SH) | r::B_AX_LTR_REQ_DRV;
  } else {
    dec |= r::B_AX_LTR_HW_DEC_EN;
  }
  dec = r::set_clr_word(dec, r::PCI_LTR_SPC_500US, r::B_AX_LTR_SPACE_IDX_V1_MSK,
                        r::B_AX_LTR_SPACE_IDX_V1_SH);
  if (enable)
    set32(r::R_AX_LTR_CTRL_0, r::B_AX_LTR_WD_NOEMP_CHK_V1 | r::B_AX_LTR_HW_EN);
  field32(r::R_AX_LTR_CTRL_0, r::PCI_LTR_IDLE_TIMER_3_2MS,
          r::B_AX_LTR_IDLE_TIMER_IDX_MSK, r::B_AX_LTR_IDLE_TIMER_IDX_SH);
  field32(r::R_AX_LTR_CTRL_1, r::LTR_RX_TH_8852C, r::B_AX_LTR_RX0_TH_MSK,
          r::B_AX_LTR_RX0_TH_SH);
  field32(r::R_AX_LTR_CTRL_1, r::LTR_RX_TH_8852C, r::B_AX_LTR_RX1_TH_MSK,
          r::B_AX_LTR_RX1_TH_SH);
  _device.rtw_write32(r::R_AX_LTR_DEC_CTRL, dec);
  _device.rtw_write32(r::R_AX_LTR_LATENCY_IDX3, r::LTR_IDLE_LATENCY_8852C);
  _device.rtw_write32(r::R_AX_LTR_LATENCY_IDX0, r::LTR_ACTIVE_LATENCY_8852C);
  return true;
}

bool HalKestrel::pcie_ltr_silence() {
  const uint32_t ctrl0 = _device.rtw_read32(r::R_AX_LTR_CTRL_0);
  if (_variant != ChipVariant::C8852C) {
    if (ltr_reg_unreadable(ctrl0)) {
      _logger->error("Kestrel PCIe: 8852B LTR_CTRL_0 unreadable (0x{:08x})", ctrl0);
      return false;
    }
    _device.rtw_write32(r::R_AX_LTR_CTRL_0,
                        ctrl0 & ~(r::B_AX_LTR_HW_EN | r::B_AX_LTR_EN_8852B));
    _logger->info("Kestrel PCIe: 8852B LTR silenced (was CTRL_0=0x{:08x})", ctrl0);
    return true;
  }
  const uint32_t dec = _device.rtw_read32(r::R_AX_LTR_DEC_CTRL);
  if (ltr_reg_unreadable(ctrl0) || ltr_reg_unreadable(dec)) {
    _logger->error("Kestrel PCIe: LTR registers unreadable (CTRL_0=0x{:08x} "
                   "DEC_CTRL=0x{:08x}) — cannot silence LTR",
                   ctrl0, dec);
    return false;
  }
  _device.rtw_write32(r::R_AX_LTR_CTRL_0, ctrl0 & ~r::B_AX_LTR_HW_EN);
  _device.rtw_write32(r::R_AX_LTR_DEC_CTRL,
                      dec & ~(r::B_AX_LTR_HW_DEC_EN | r::B_AX_LTR_FW_DEC_EN |
                              r::B_AX_LTR_DRV_DEC_EN | r::B_AX_LTR_REQ_DRV));
  _logger->info("Kestrel PCIe: LTR silenced — host has LTR disabled for this "
                "function (DEVCTL2 LTR_EN=0: a port on the path lacks LTR); "
                "was CTRL_0=0x{:08x} DEC_CTRL=0x{:08x}",
                ctrl0, dec);
  return true;
}

bool HalKestrel::pcie_pre_init() {
  /* Before anything can arm it: a chip the host forbids LTR must never send
   * one (an Unsupported Request behind a non-LTR switch -> AER link reset). */
  if (!_device.ltr_allowed())
    pcie_ltr_silence();

  if (_variant != ChipVariant::C8852C) {
    /* rtw89_pci_ops_mac_pre_init_ax, 8852B branches in order (pci.c:3070..3144). */
    clr32(r::R_AX_PCIE_PS_CTRL, r::B_AX_L1OFF_PWR_OFF_EN);          /* l1off_pwroff */
    clr32(r::R_AX_SYS_PW_CTRL, r::B_AX_HOST_CHKSUM_EN);             /* aphy_pwrcut */
    set32(r::R_AX_SYS_SDIO_CTRL, r::B_AX_PCIE_DIS_L2_CTRL_LDO_HCI_8852B); /* hci_ldo */
    clr32(r::R_AX_SYS_SDIO_CTRL, r::B_AX_PCIE_DIS_WLSUS_AFT_PDN);
    pcie_mdio_write16_mask(0x1B, 0xF000u, 1u, /*GEN1=*/0);          /* dphy_delay */
    set32(r::R_AX_HCI_OPT_CTRL, r::B_AX_WAKE_CTRL);                 /* power_wake */
    clr32(r::R_AX_PCIE_EXP_CTRL, r::B_AX_SIC_EN_FORCE_CLKREQ);      /* set_sic */
    field32(r::R_AX_LBC_WATCHDOG, r::MAC_AX_LBC_TMR_2MS,
            r::B_AX_LBC_TIMER_MSK, r::B_AX_LBC_TIMER_SH);           /* set_lbc */
    set32(r::R_AX_LBC_WATCHDOG, r::B_AX_LBC_FLAG | r::B_AX_LBC_EN);
    set32(r::R_AX_PCIE_DBG_CTRL,
          r::B_AX_ASFF_FULL_NO_STK | r::B_AX_EN_STUCK_DBG_11C0);    /* set_dbg */
    field32(r::R_AX_PCIE_EXP_CTRL, 1u,
            r::B_AX_EN_DBG_PCIE_MSK, r::B_AX_EN_DBG_PCIE_SH);
    set32(r::R_AX_HAXI_INIT_CFG1,
          r::B_AX_EN_STUCK_DBG | r::B_AX_EN_KEEP_REG);              /* set_keep_reg */

    set32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_WPDMA);
    pcie_ctrl_dma_all(false);
    if (!pcie_poll_dma_idle())
      return false;
    pcie_clr_idx_all();
    pcie_mode_op();
    _device.hci_setup();
    if (!pcie_rst_bdram())
      return false;
    pcie_ctrl_txdma_ch(false);
    clr32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_CH12);
    pcie_ctrl_dma_all(true);
    _logger->info("Kestrel PCIe: 8852B pre-init done (DMA up, CH12 open)");
    return true;
  }

  /* rtw89_pci_ops_mac_pre_init_ax, the 8852C branches in order. Runs after
   * dmac_pre_init (HAXI DMA_MODE=PCIE_1B, HCI enables) and before FWDL. */
  pcie_disable_eq();
  /* deglitch: clear RAC_ANA24[11:8] on both PHYs (16-bit registers). */
  for (uint16_t phy : {r::R_RAC_DIRECT_OFFSET_G1, r::R_RAC_DIRECT_OFFSET_G2}) {
    const uint16_t reg = phy + r::RAC_ANA24 * r::RAC_MULT;
    _device.rtw_write16(reg, _device.rtw_read16(reg) & ~r::B_AX_DEGLITCH);
  }
  clr32(r::R_AX_SYS_SDIO_CTRL, r::B_AX_PCIE_DIS_L2_CTRL_LDO_HCI); /* hci_ldo */
  set32(r::R_AX_HCI_OPT_CTRL, r::B_AX_WAKE_CTRL);                 /* power_wake */
  set32(r::R_AX_PCIE_BG_CLR, r::B_AX_BG_CLR_ASYNC_M3);            /* autoload_hang */
  clr32(r::R_AX_PCIE_BG_CLR, r::B_AX_BG_CLR_ASYNC_M3);
  /* l12_vmain / gen2_force_ib are CAV-cut only; the plugged modules are cut 1
   * (CBV), so they are deliberately not transcribed. */
  clr32(r::R_AX_PCIE_PS_CTRL_V1, r::B_AX_SEL_REQ_ENTR_L1);        /* l1_ent_lat */
  set32(r::R_AX_PCIE_PS_CTRL_V1, r::B_AX_DMAC0_EXIT_L1_EN);       /* wd_exit_l1 */
  /* set_io_rcy: 6 ms analog watchdogs on M1/M2/E0, S1 off. */
  _device.rtw_write32(r::R_AX_PCIE_WDT_TIMER_M1, r::MAC_AX_IO_RCY_ANA_TMR_6MS);
  _device.rtw_write32(r::R_AX_PCIE_WDT_TIMER_M2, r::MAC_AX_IO_RCY_ANA_TMR_6MS);
  _device.rtw_write32(r::R_AX_PCIE_WDT_TIMER_E0, r::MAC_AX_IO_RCY_ANA_TMR_6MS);
  set32(r::R_AX_PCIE_IO_RCY_M1, r::B_AX_PCIE_IO_RCY_WDT_MODE);
  set32(r::R_AX_PCIE_IO_RCY_M2, r::B_AX_PCIE_IO_RCY_WDT_MODE);
  set32(r::R_AX_PCIE_IO_RCY_E0, r::B_AX_PCIE_IO_RCY_WDT_MODE);
  clr32(r::R_AX_PCIE_IO_RCY_S1, r::B_AX_PCIE_IO_RCY_WDT_MODE);

  set32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_WPDMA);
  pcie_ctrl_dma_all(false);
  if (!pcie_poll_dma_idle())
    return false;
  pcie_clr_idx_all();
  pcie_mode_op();
  /* Ring base/num/BDRAM registers + host indices — the transport's memory. */
  _device.hci_setup();
  if (!pcie_rst_bdram())
    return false;
  /* Only the FWCMD channel open until the firmware is up. */
  pcie_ctrl_txdma_ch(false);
  clr32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_CH12);
  pcie_ctrl_dma_all(true);
  _logger->info("Kestrel PCIe: HAXI pre-init done (DMA up, CH12 open)");
  return true;
}

void HalKestrel::pcie_init() {
  /* rtw89_pci_ops_mac_post_init_ax: LTR on, every TX channel open, release
   * the WPDMA + PCIe IO stops. */
  const bool allowed = _device.ltr_allowed();
  const bool ok = allowed ? pcie_ltr_set(true) : pcie_ltr_silence();
  const char *ltr = ok ? (allowed ? "on" : "silenced") : "FAILED";
  if (!ok)
    _logger->warn("Kestrel PCIe: LTR could not be {} — registers unreadable",
                  allowed ? "enabled" : "silenced");
  if (_variant != ChipVariant::C8852C) {
    /* Ensure 8-byte host addr-info select stays set after DMAC/TRX init. */
    set32(r::R_AX_TX_ADDRESS_INFO_MODE_SETTING, r::B_AX_HOST_ADDR_INFO_8B_SEL);
    clr32(r::R_AX_PKTIN_SETTING, r::B_AX_WD_ADDR_INFO_LENGTH);
  }
  pcie_ctrl_txdma_ch(true);
  clr32(r::R_AX_HAXI_DMA_STOP1, r::B_AX_STOP_WPDMA | r::B_AX_STOP_PCIEIO);
  _logger->info("Kestrel PCIe: post-init done (LTR {}, all TX channels open)",
                ltr);
}

void HalKestrel::pcie_deinit() {
  /* rtw89_pci_ops_deinit: power wake off (8852B), LTR off, DMA stopped, indices cleared. */
  if (_variant != ChipVariant::C8852C)
    clr32(r::R_AX_HCI_OPT_CTRL, r::B_AX_WAKE_CTRL);
  if (_device.ltr_allowed())
    pcie_ltr_set(false);
  else
    pcie_ltr_silence();
  pcie_ctrl_dma_all(false);
  pcie_clr_idx_all();
  _logger->info("Kestrel PCIe: {} DMA stopped",
                _variant == ChipVariant::C8852C ? "HAXI" : "8852B");
}''',
            ),
            (
                'power_on allow 8852B PCIe',
                '''  /* USB for both dies; PCIe for the 8852C only (mac_pwr_on_nic_pcie_8852c —
   * three deltas inside power_on_8852c). The 8852B PCIe sequence is unported
   * and untested, so keep refusing it rather than run the USB one. */
  if (!_device.is_usb() && _variant != ChipVariant::C8852C) {
    _logger->error("Kestrel: PCIe power-on is ported for the 8852C only");
    return false;
  }''',
                '''  /* USB and PCIe for both 8852B and 8852C. */''',
            ),
            (
                'power_on 8852B PCIe sps_ana',
                '''  /* mac_pwr_on_usb_8852b, transcribed verbatim (pwr_seq_func_8852b.c:419). */
  clr32(r::R_AX_SYS_PW_CTRL,''',
                '''  /* mac_pwr_on_{usb,pcie}_8852b (pwr_seq_func_8852b.c / rtw8852b.c). */
  if (_pcie)
    _device.rtw_write16(r::R_AX_SPS_ANA_ON_CTRL2, r::RTL8852B_DEFAULT_SPS_ANA);
  clr32(r::R_AX_SYS_PW_CTRL,''',
            ),
            (
                'power_on 8852B PCIe calib_en',
                '''  plat(false);
  plat(true);

  /* 0x18[6]=1 then XTAL_SI ANAPAR_WL[6]=1 */''',
                '''  plat(false);
  plat(true);
  if (_pcie)
    clr32(r::R_AX_SYS_SDIO_CTRL, r::B_AX_PCIE_CALIB_EN_8852B);

  /* 0x18[6]=1 then XTAL_SI ANAPAR_WL[6]=1 */''',
            ),
            (
                'power_on 8852B PCIe CBV HCI LDO VADJ',
                '''  if (pwr_k != r::PWR_K_CHK_VALUE) {
    field32(r::R_AX_SPS_DIG_ON_CTRL0, 0x9, r::B_AX_VOL_L1_MSK, r::B_AX_VOL_L1_SH);
    field32(r::R_AX_SPS_DIG_ON_CTRL0, 0xA, r::B_AX_VREFPFM_L_MSK,
            r::B_AX_VREFPFM_L_SH);
  }''',
                '''  if (pwr_k != r::PWR_K_CHK_VALUE) {
    field32(r::R_AX_SPS_DIG_ON_CTRL0, 0x9, r::B_AX_VOL_L1_MSK, r::B_AX_VOL_L1_SH);
    field32(r::R_AX_SPS_DIG_ON_CTRL0, 0xA, r::B_AX_VREFPFM_L_MSK,
            r::B_AX_VREFPFM_L_SH);
    if (_pcie && read_cut() == 1 /* CHIP_CBV */) {
      set32(r::R_AX_PMC_DBG_CTRL2, r::B_AX_SYSON_DIS_PMCR_AX_WRMSK);
      uint16_t ldo = _device.rtw_read16(r::R_AX_HCI_LDO_CTRL);
      ldo = static_cast<uint16_t>((ldo & ~r::B_AX_R_AX_VADJ_MSK) | 0xAu);
      _device.rtw_write16(r::R_AX_HCI_LDO_CTRL, ldo);
      clr32(r::R_AX_PMC_DBG_CTRL2, r::B_AX_SYSON_DIS_PMCR_AX_WRMSK);
    }
  }''',
            ),
            (
                'dle_init_nic 8852B PCIe quota',
                '''  const bool pc = c && _pcie;
  const uint16_t wde_lnk = pc  ? r::PCIE_SCC_WDE_LNK_PAGE_8852C
                           : c ? r::SCC_WDE_LNK_PAGE_8852C
                               : r::SCC_WDE_LNK_PAGE;
  const uint16_t wde_unlnk = pc  ? r::PCIE_SCC_WDE_UNLNK_PAGE_8852C
                             : c ? r::SCC_WDE_UNLNK_PAGE_8852C
                                 : r::SCC_WDE_UNLNK_PAGE;
  const uint16_t ple_lnk = pc  ? r::PCIE_SCC_PLE_LNK_PAGE_8852C
                           : c ? r::SCC_PLE_LNK_PAGE_8852C
                               : r::SCC_PLE_LNK_PAGE;
  const uint16_t wde_hif = pc  ? r::PCIE_SCC_WDE_QT_HIF_8852C
                           : c ? r::SCC_WDE_QT_HIF_8852C
                               : r::SCC_WDE_QT_HIF;
  const uint16_t wde_wcpu = pc  ? r::PCIE_SCC_WDE_QT_WCPU_8852C
                            : c ? r::SCC_WDE_QT_WCPU_8852C
                                : r::SCC_WDE_QT_WCPU;
  const uint16_t wde_cpuio = pc  ? r::PCIE_SCC_WDE_QT_CPU_IO_8852C
                             : c ? r::SCC_WDE_QT_CPU_IO_8852C
                                 : r::SCC_WDE_QT_CPU_IO;
  /* The 8852C has a DEDICATED USB2 DLE quota (dle.c selects dle_mem_usb2_8852c
   * vs dle_mem_usb3_8852c by get_usb_mode). On a USB2 8832CU the USB3 quota
   * caps the RX-DMA PLE pool and wedges RX (burst-then-idle). Detect the live
   * mode the same way usb_init does (USB_STATUS_V1: R_USB2_SEL=SuperSpeed,
   * else MODE_HS=USB2). */
  bool usb2 = false;
  if (c && !_pcie) {
    const uint32_t st = _device.rtw_read32(r::R_AX_USB_STATUS_V1);
    usb2 = !(st & r::B_AX_R_USB2_SEL) && (st & r::B_AX_MODE_HS);
  }
  const uint16_t *ple_min = !c   ? r::SCC_PLE_MIN
                            : pc   ? r::PCIE_SCC_PLE_MIN_8852C
                            : usb2 ? r::SCC_PLE_MIN_8852C_USB2
                                   : r::SCC_PLE_MIN_8852C;
  const uint16_t *ple_max = !c   ? r::SCC_PLE_MAX
                            : pc   ? r::PCIE_SCC_PLE_MAX_8852C
                            : usb2 ? r::SCC_PLE_MAX_8852C_USB2
                                   : r::SCC_PLE_MAX_8852C;
  const int ple_qn = c ? 12 : 11; /* 8852C writes through Q11 (tx_rpt) */
  if (c)
    _logger->info("Kestrel DLE: 8852C SCC quota = {} (RX-DMA Q6 max {})",
                  pc ? "PCIe" : usb2 ? "USB2" : "USB3",
                  pc ? 1199 : usb2 ? 1646 : 178);''',
                '''  const bool pc = c && _pcie;
  const bool pb = !c && _pcie;
  const uint16_t wde_lnk = pc   ? r::PCIE_SCC_WDE_LNK_PAGE_8852C
                           : pb ? r::PCIE_SCC_WDE_LNK_PAGE_8852B
                           : c  ? r::SCC_WDE_LNK_PAGE_8852C
                                : r::SCC_WDE_LNK_PAGE;
  const uint16_t wde_unlnk = pc   ? r::PCIE_SCC_WDE_UNLNK_PAGE_8852C
                             : pb ? r::PCIE_SCC_WDE_UNLNK_PAGE_8852B
                             : c  ? r::SCC_WDE_UNLNK_PAGE_8852C
                                  : r::SCC_WDE_UNLNK_PAGE;
  const uint16_t ple_lnk = pc   ? r::PCIE_SCC_PLE_LNK_PAGE_8852C
                           : pb ? r::PCIE_SCC_PLE_LNK_PAGE_8852B
                           : c  ? r::SCC_PLE_LNK_PAGE_8852C
                                : r::SCC_PLE_LNK_PAGE;
  const uint16_t wde_hif = pc   ? r::PCIE_SCC_WDE_QT_HIF_8852C
                           : pb ? r::PCIE_SCC_WDE_QT_HIF_8852B
                           : c  ? r::SCC_WDE_QT_HIF_8852C
                                : r::SCC_WDE_QT_HIF;
  const uint16_t wde_wcpu = pc   ? r::PCIE_SCC_WDE_QT_WCPU_8852C
                            : pb ? r::PCIE_SCC_WDE_QT_WCPU_8852B
                            : c  ? r::SCC_WDE_QT_WCPU_8852C
                                 : r::SCC_WDE_QT_WCPU;
  const uint16_t wde_cpuio = pc   ? r::PCIE_SCC_WDE_QT_CPU_IO_8852C
                             : pb ? r::PCIE_SCC_WDE_QT_CPU_IO_8852B
                             : c  ? r::SCC_WDE_QT_CPU_IO_8852C
                                  : r::SCC_WDE_QT_CPU_IO;
  /* The 8852C has a DEDICATED USB2 DLE quota (dle.c selects dle_mem_usb2_8852c
   * vs dle_mem_usb3_8852c by get_usb_mode). On a USB2 8832CU the USB3 quota
   * caps the RX-DMA PLE pool and wedges RX (burst-then-idle). Detect the live
   * mode the same way usb_init does (USB_STATUS_V1: R_USB2_SEL=SuperSpeed,
   * else MODE_HS=USB2). */
  bool usb2 = false;
  if (c && !_pcie) {
    const uint32_t st = _device.rtw_read32(r::R_AX_USB_STATUS_V1);
    usb2 = !(st & r::B_AX_R_USB2_SEL) && (st & r::B_AX_MODE_HS);
  }
  const uint16_t *ple_min = pb   ? r::PCIE_SCC_PLE_MIN_8852B
                            : !c ? r::SCC_PLE_MIN
                            : pc ? r::PCIE_SCC_PLE_MIN_8852C
                            : usb2 ? r::SCC_PLE_MIN_8852C_USB2
                                   : r::SCC_PLE_MIN_8852C;
  const uint16_t *ple_max = pb   ? r::PCIE_SCC_PLE_MAX_8852B
                            : !c ? r::SCC_PLE_MAX
                            : pc ? r::PCIE_SCC_PLE_MAX_8852C
                            : usb2 ? r::SCC_PLE_MAX_8852C_USB2
                                   : r::SCC_PLE_MAX_8852C;
  const int ple_qn = c ? 12 : 11; /* 8852C writes through Q11 (tx_rpt) */
  if (c)
    _logger->info("Kestrel DLE: 8852C SCC quota = {} (RX-DMA Q6 max {})",
                  pc ? "PCIe" : usb2 ? "USB2" : "USB3",
                  pc ? 1199 : usb2 ? 1646 : 178);
  else if (pb)
    _logger->info("Kestrel DLE: 8852B SCC quota = PCIe (WDE {} HIF {}, PLE {})",
                  wde_lnk, wde_hif, ple_lnk);''',
            ),
            (
                'hfc_init_nic 8852B PCIe quota',
                '''  const bool pc = c && _pcie;
  const uint16_t ch_min = pc  ? r::HFC_PCIE_CH_MIN_8852C
                          : c ? r::HFC_NIC_CH_MIN_8852C
                              : r::HFC_NIC_CH_MIN;
  const uint16_t ch_max = pc  ? r::HFC_PCIE_CH_MAX_8852C
                          : c ? r::HFC_NIC_CH_MAX_8852C
                              : r::HFC_NIC_CH_MAX;
  const uint16_t pub_g0 = pc  ? r::HFC_PCIE_PUB_G0_8852C
                          : c ? r::HFC_NIC_PUB_G0_8852C
                              : r::HFC_NIC_PUB_G0;
  const uint16_t pub_g1 = pc ? r::HFC_PCIE_PUB_G1_8852C : r::HFC_NIC_PUB_G1;
  const uint16_t pub_max = pc  ? r::HFC_PCIE_PUB_MAX_8852C
                           : c ? r::HFC_NIC_PUB_MAX_8852C
                               : r::HFC_NIC_PUB_MAX;
  const uint16_t wp07 = pc  ? r::HFC_PCIE_WP_PREC
                        : c ? r::HFC_NIC_WP_CH07_PREC_8852C
                            : r::HFC_NIC_WP_CH07_PREC;
  const uint16_t wp811 = pc  ? r::HFC_PCIE_WP_PREC
                         : c ? r::HFC_NIC_WP_CH811_PREC_8852C
                             : r::HFC_NIC_WP_CH811_PREC;
  const uint16_t ch011_prec = pc ? r::HFC_PCIE_CH011_PREC : r::HFC_NIC_CH011_PREC;
  const uint16_t h2c_prec = pc ? r::HFC_PCIE_H2C_PREC : r::HFC_USB_H2C_PREC_8852B;
  const uint8_t h2c_cond = pc ? r::HFC_FULL_COND_X1 : r::HFC_FULL_COND_X2;
  const uint8_t wp_cond = pc ? r::HFC_FULL_COND_X1 : r::HFC_FULL_COND_X2;
  const uint32_t fc_mode = pc ? r::MAC_AX_HCIFC_POH : 1u /* MAC_AX_HCIFC_STF */;

  /* set_fc_func_en(0, 0): disable FC + CH12 while reprogramming. */
  clr32(fc_ctrl, r::B_AX_HCI_FC_EN | r::B_AX_HCI_FC_CH12_EN);

  /* Per-channel page ctrl: ACH0-3 + B0MGQ(8) + B0HIQ(9) = {min,max,grp0};
   * on PCIe also ACH4-7 + B1MGQ(10) + B1HIQ(11) in group 1. */
  const uint32_t ch = min_max_grp(ch_min, ch_max);
  w(ach0, ch);
  w(ach1, ch);
  w(ach2, ch);
  w(ach3, ch);
  w(ch8, ch);
  w(ch9, ch);''',
                '''  const bool pc = c && _pcie;
  const bool pb = !c && _pcie;
  const uint16_t ch_min = pc   ? r::HFC_PCIE_CH_MIN_8852C
                          : pb ? r::HFC_PCIE_CH_OTHER_MIN_8852B
                          : c  ? r::HFC_NIC_CH_MIN_8852C
                               : r::HFC_NIC_CH_MIN;
  const uint16_t ch_max = pc   ? r::HFC_PCIE_CH_MAX_8852C
                          : pb ? r::HFC_PCIE_CH_OTHER_MAX_8852B
                          : c  ? r::HFC_NIC_CH_MAX_8852C
                               : r::HFC_NIC_CH_MAX;
  const uint16_t pub_g0 = pc   ? r::HFC_PCIE_PUB_G0_8852C
                          : pb ? r::HFC_PCIE_PUB_G0_8852B
                          : c  ? r::HFC_NIC_PUB_G0_8852C
                               : r::HFC_NIC_PUB_G0;
  const uint16_t pub_g1 = pc   ? r::HFC_PCIE_PUB_G1_8852C
                          : pb ? r::HFC_PCIE_PUB_G1_8852B
                               : r::HFC_NIC_PUB_G1;
  const uint16_t pub_max = pc   ? r::HFC_PCIE_PUB_MAX_8852C
                           : pb ? r::HFC_PCIE_PUB_MAX_8852B
                           : c  ? r::HFC_NIC_PUB_MAX_8852C
                                : r::HFC_NIC_PUB_MAX;
  const uint16_t wp07 = _pcie ? r::HFC_PCIE_WP_PREC
                        : c   ? r::HFC_NIC_WP_CH07_PREC_8852C
                              : r::HFC_NIC_WP_CH07_PREC;
  const uint16_t wp811 = _pcie ? r::HFC_PCIE_WP_PREC
                         : c   ? r::HFC_NIC_WP_CH811_PREC_8852C
                               : r::HFC_NIC_WP_CH811_PREC;
  const uint16_t ch011_prec = _pcie ? r::HFC_PCIE_CH011_PREC : r::HFC_NIC_CH011_PREC;
  const uint16_t h2c_prec = _pcie ? r::HFC_PCIE_H2C_PREC : r::HFC_USB_H2C_PREC_8852B;
  const uint8_t h2c_cond = _pcie ? r::HFC_FULL_COND_X1 : r::HFC_FULL_COND_X2;
  const uint8_t wp_cond = _pcie ? r::HFC_FULL_COND_X1 : r::HFC_FULL_COND_X2;
  const uint32_t fc_mode = _pcie ? r::MAC_AX_HCIFC_POH : 1u /* MAC_AX_HCIFC_STF */;

  /* set_fc_func_en(0, 0): disable FC + CH12 while reprogramming. */
  clr32(fc_ctrl, r::B_AX_HCI_FC_EN | r::B_AX_HCI_FC_CH12_EN);

  /* Per-channel page ctrl: ACH0-3 + B0MGQ(8) + B0HIQ(9) = {min,max,grp0};
   * on 8852B PCIe ACH0/ACH1 use {5,341} and ACH2/3/CH8/9 use {4,342};
   * on 8852C PCIe also ACH4-7 + B1MGQ(10) + B1HIQ(11) in group 1. */
  const uint32_t ch = min_max_grp(ch_min, ch_max);
  const uint32_t ch01 =
      pb ? min_max_grp(r::HFC_PCIE_CH01_MIN_8852B, r::HFC_PCIE_CH01_MAX_8852B)
         : ch;
  w(ach0, ch01);
  w(ach1, ch01);
  w(ach2, ch);
  w(ach3, ch);
  w(ch8, ch);
  w(ch9, ch);''',
            ),
        ],
    )

    # 15. devourer/src/kestrel/RtlKestrelDevice.cpp: allow C8852B PCIe in SetStationIdentity
    patch_file(
        devourer / 'src' / 'kestrel' / 'RtlKestrelDevice.cpp',
        [
            (
                'SetStationIdentity allow C8852B PCIe',
                '''  if (!_tx_up || _variant != kestrel::ChipVariant::C8852C || _device.is_usb()) {
    _logger->error("Kestrel: SetStationIdentity needs an RTL8852CE after "
                   "InitWrite");
    return false;
  }''',
                '''  if (!_tx_up || _device.is_usb()) { /* nekodrop (8852BE) */
    _logger->error("Kestrel: SetStationIdentity needs a PCIe Kestrel card after "
                   "InitWrite");
    return false;
  }''',
            ),
        ],
    )

    # 16. devourer/examples/pcieprobe/main.cpp: support 10EC:B852 and 10EC:B85B
    patch_file(
        devourer / 'examples' / 'pcieprobe' / 'main.cpp',
        [
            (
                'include kestrel headers for either variant',
                '''#if defined(DEVOURER_HAVE_KESTREL_8852C)
#include "kestrel/ChipVariant.h"
#include "kestrel/HalKestrel.h"
#endif

#if defined(DEVOURER_HAVE_KESTREL_8852C)''',
                '''#if defined(DEVOURER_HAVE_KESTREL)
#include "kestrel/ChipVariant.h"
#include "kestrel/HalKestrel.h"
#endif

#if defined(DEVOURER_HAVE_KESTREL)''',
            ),
            (
                'probe_kestrel supports both 8852C and 8852B',
                '''static int probe_8852c(RtlAdapter &adapter, Logger_t logger, int want) {
  const uint8_t die_id = adapter.rtw_read8(0x00FC);
  kestrel::HalKestrel hal(adapter, logger, kestrel::ChipVariant::C8852C);
  const uint8_t cut = hal.read_cut();
  const bool id_ok = die_id == 0x52;
  logger->info("M0 (8852C): die-id=0x{:02x} (want 0x52) cut={}", die_id, cut);
  devourer::Ev(logger->events(), "pcie.id")
      .f("ok", id_ok)
      .f("chip", "8852c")
      .hexf("chip_id", die_id, 2)
      .f("cut", static_cast<int>(cut));
  if (!id_ok || want < 1)
    return id_ok ? 0 : 1;

  bool power_ok = false;
  kestrel::EfuseInfo ef;
  try {
    power_ok = hal.power_on() && hal.read_efuse(ef);
  } catch (const std::exception &e) {
    logger->error("M1 (8852C): power-on failed: {}", e.what());
  }
  char mac[18];
  snprintf(mac, sizeof(mac), "%02x:%02x:%02x:%02x:%02x:%02x", ef.mac[0],
           ef.mac[1], ef.mac[2], ef.mac[3], ef.mac[4], ef.mac[5]);
  const bool ids_ok = ef.pci_vid == 0x10EC && ef.pci_did == 0xC852;
  const bool ok = power_ok && ef.autoload_ok && ids_ok;
  logger->info("M1 (8852C): power_ok={} autoload={} efuse pci={:04x}:{:04x} "
               "MAC(0x400)={} rfe={} xtal=0x{:02x}",
               power_ok, ef.autoload_ok, ef.pci_vid, ef.pci_did, mac,
               ef.rfe_type, ef.xtal_cap);''',
                '''static int probe_kestrel(RtlAdapter &adapter, Logger_t logger, int want,
                         kestrel::ChipVariant variant) {
  /* nekodrop (8852BE): probe both 8852C (die-id 0x52) and 8852B (die-id 0x51). */
  const bool is_b = (variant == kestrel::ChipVariant::C8852B);
  const char *tag = is_b ? "8852B" : "8852C";
  const uint8_t want_die = is_b ? 0x51 : 0x52;
  const uint8_t die_id = adapter.rtw_read8(0x00FC);
  kestrel::HalKestrel hal(adapter, logger, variant);
  const uint8_t cut = hal.read_cut();
  const bool id_ok = die_id == want_die;
  logger->info("M0 ({}): die-id=0x{:02x} (want 0x{:02x}) cut={}",
               tag, die_id, want_die, cut);
  devourer::Ev(logger->events(), "pcie.id")
      .f("ok", id_ok)
      .f("chip", is_b ? "8852b" : "8852c")
      .hexf("chip_id", die_id, 2)
      .f("cut", static_cast<int>(cut));
  if (!id_ok || want < 1)
    return id_ok ? 0 : 1;

  bool power_ok = false;
  kestrel::EfuseInfo ef;
  try {
    power_ok = hal.power_on() && hal.read_efuse(ef);
  } catch (const std::exception &e) {
    logger->error("M1 ({}): power-on failed: {}", tag, e.what());
  }
  char mac[18];
  snprintf(mac, sizeof(mac), "%02x:%02x:%02x:%02x:%02x:%02x", ef.mac[0],
           ef.mac[1], ef.mac[2], ef.mac[3], ef.mac[4], ef.mac[5]);
  const bool ids_ok = is_b || (ef.pci_vid == 0x10EC && ef.pci_did == 0xC852);
  const bool ok = power_ok && ef.autoload_ok && ids_ok;
  logger->info("M1 ({}): power_ok={} autoload={} efuse pci={:04x}:{:04x} "
               "MAC(0x400)={} rfe={} xtal=0x{:02x}",
               tag, power_ok, ef.autoload_ok, ef.pci_vid, ef.pci_did, mac,
               ef.rfe_type, ef.xtal_cap);''',
            ),
            (
                'main dispatch for 8852CE and 8852BE',
                '''  if (pci_did == 0xC852) {
#if defined(DEVOURER_HAVE_KESTREL_8852C)
    return probe_8852c(adapter, logger, want);
#else
    logger->error("RTL8852CE found but 8852C support not compiled in");
    return 1;
#endif
  }''',
                '''  if (pci_did == 0xC852) {
#if defined(DEVOURER_HAVE_KESTREL_8852C)
    return probe_kestrel(adapter, logger, want, kestrel::ChipVariant::C8852C);
#else
    logger->error("RTL8852CE found but 8852C support not compiled in");
    return 1;
#endif
  }
  if (pci_did == 0xB852 || pci_did == 0xB85B) {
#if defined(DEVOURER_HAVE_KESTREL_8852B)
    return probe_kestrel(adapter, logger, want, kestrel::ChipVariant::C8852B);
#else
    logger->error("RTL8852BE found but 8852B support not compiled in");
    return 1;
#endif
  }''',
            ),
        ],
    )


if __name__ == '__main__':
    main()
