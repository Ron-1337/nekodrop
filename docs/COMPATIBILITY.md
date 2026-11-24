# Wi-Fi Card Compatibility

English · [简体中文](COMPATIBILITY.zh-CN.md) · [Back to README](../README.md) · [Architecture & Driver Roadmap](HARDWARE.md)

nekodrop drives the Wi-Fi chip directly from user mode so Windows can speak Apple's AWDL protocol natively. As nekodrop expands beyond Intel into multi-vendor cards, every card family uses a modular backend behind `CardCatalog` and `radio_backend.h`:

- **Built-in native support (no hidden experimental switches)**: once a card family's backend passes CI build and offline self-tests, it ships built-in so users can install and use it out of the box.
- **Auto-detection first, manual selection fallback**: nekodrop automatically detects supported PCIe Wi-Fi cards; multi-NIC / unmatched-ID manual selection at install time and in Settings is actively being rolled out.
- **Honest verification status**: we distinguish **Author-tested**, **User-reported working**, **Built-in (untested)**, and **In development / Planned**.

## Networking Modes by Capability

| Mode | What it does | Required radio capability |
|---|---|---|
| **Wi-Fi + AirDrop together (Concurrent)** | nekodrop runs both your Wi-Fi connection and AWDL on one card. | Backend includes a user-mode Wi-Fi station (`supports_station = true`). |
| **On-Demand** | Windows' native driver runs Wi-Fi normally; nekodrop takes the card only while sending/receiving AirDrop and hands it right back. | Core AWDL listener/injector only (works for cards without a user-mode Wi-Fi station). |

---

## Intel (`VEN_8086`) — `iwx` backend

| Card / Family | PCI Device IDs | Firmware | Modes | Status |
|---|---|---|---|---|
| **Intel Wi-Fi 6 AX201** 160 MHz (CNVi) | `02F0` `06F0` `34F0` `3DF0` `4DF0` `43F0` `A0F0` | `Qu/QuZ-hr-b0-68` | Concurrent & On-Demand | ✅ **Author-tested** (`43F0` QuZ) |
| **Intel Wi-Fi 6 AX200** (discrete) | `2723` | `cc-a0-68` | Concurrent & On-Demand | ✅ **User-reported working** ([#1](../../../issues/1), [#4](../../../issues/4)) |
| **Intel Wi-Fi 6E AX210** (discrete) | `2725` | `ty-a0-gf-a0-68` + PNVM | Concurrent & On-Demand | ✅ **User-reported working** ([#14](../../../issues/14), [#18](../../../issues/18), [#11](../../../issues/11)) |
| **Intel Wi-Fi 6E AX211** (CNVi, 12th gen+) | `7AF0` `7A70` `51F0` `51F1` `54F0` `7F70` | `so-a0-gf-a0-68` + PNVM | Concurrent & On-Demand | ✅ **User-reported working** ([#9](../../../issues/9)); discovery tuning ([#16](../../../issues/16)) |
| Intel Wireless-AC 9560 / 9462 / 9461 (Qu/QuZ CNVi) | same as AX201 | `Qu/QuZ-jf-b0-68` | Concurrent & On-Demand | ⚠️ Built-in, untested |
| Intel Wi-Fi 6E AX411 / Killer AX1690 (CNVi) | same as AX211 | `so-a0-gf4-a0-68` + PNVM | Concurrent & On-Demand | ⚠️ Built-in, untested ([#7](../../../issues/7)) |
| Intel Wi-Fi 6 AX203 / 9560 (So CNVi) | same as AX211 | `so-a0-hr/jf-b0-68` | Concurrent & On-Demand | ⚠️ Built-in, untested |
| Intel Meteor Lake `Ma` / `SnJ` | `7E40` `2729` `2726` | `ma-b0` (`linux-firmware`) | Concurrent & On-Demand | 🚧 Planned (high priority) |
| Intel Wi-Fi 7 BE200 / BE201 (`bz`) | `272B` `A840` `E440` | API 86+ MLD/Link | Concurrent & On-Demand | 🗓️ Planned (longer-term) |
| Legacy Intel 9260 (`2526`) / 8th–9th gen 9560 (`9DF0`/`A370`) | `2526` `9DF0` `A370` | `iwm` legacy FH DMA | — | ❌ Not supported (`hal_iwm` has no AWDL) |

---

## Realtek (`VEN_10EC`) — `devourer` backend

| Card / Family | PCI Device IDs | Modes | Status |
|---|---|---|---|
| **Realtek RTL8852CE** | `C852` | On-Demand (native Wi-Fi kept by Windows) | ⚠️ **Built-in, untested inside nekodrop** (ships native `nekodrop-radio-rtl.exe` from [winawdl](https://github.com/raph559/winawdl)/`devourer` with A-MPDU; compiled and offline-tested in CI, awaiting real-hardware confirmation inside nekodrop; Intel default behavior unchanged) |
| **Realtek RTL8852BE** | `B852` `B85B` | On-Demand (native Wi-Fi kept by Windows) | ⚠️ **Built-in, experimental bring-up** (32-bit DMA + single-BDRAM `KESTREL_8852B` PCIe path inside `nekodrop-radio-rtl.exe`; compiled and offline-tested in CI, awaiting hardware verification) |
| Realtek RTL8851BE / RTL8852AE / RTL8922AE | `B851` `8852` `8922` | On-Demand | 🗓️ Planned |

---

## MediaTek (`VEN_14C3`) — `mt76` backend (`nekodrop-radio-mt.exe`, MT7902 first)

| Card / Family | PCI Device IDs | Modes | Status |
|---|---|---|---|
| **MediaTek MT7902** | `7902` | On-Demand | ⚠️ user-mode mt76/mt7921 port (`mtradio/`). AirDrop both ways verified on one card (ASUS desktop, `SUBSYS_60401A3B`, iPhone on 5 GHz ch 44): A-MPDU both ways, ~15 MB/s receive, ~5 MB/s send. On 2.4 GHz frames needing an ACK never complete, so it sends without ACK there. Needs linux-firmware's `WIFI_*_MT7902*` (the Windows driver's copy ignores UNI commands) |
| **MediaTek MT7921 / RZ608** | `7961` `0608` | On-Demand (Concurrent feasible later) | 🗓️ Planned (BAR0 1 MiB ready in `regproxy`; WFDMA architecture is AWE-friendly) |
| **MediaTek MT7922 / RZ616** | `7922` `0616` | On-Demand (Concurrent feasible later) | 🗓️ Planned (shares ~95% code with MT7921) |
| MediaTek MT7925 | `7925` | On-Demand | 🗓️ Planned |

---

## Qualcomm (`VEN_17CB`) & Broadcom (`VEN_14E4`)

| Vendor / Family | Status | Notes |
|---|---|---|
| Qualcomm WCN6855 / QCNFA765 / WCN7850 (`ath11k`/`ath12k`) | ❌ Not currently feasible in user mode | Requires MHI + QMI + large contiguous MSA memory + 36-bit DMA limits. |
| Broadcom BCM43xx | ❌ Not supported | Apple's Broadcom AWDL runs inside proprietary closed-source firmware. |

---

## How to Check Your Card

Run the standalone diagnostic script without installing nekodrop:

```powershell
powershell -ExecutionPolicy Bypass -File installer\report.ps1
```

It reports every wireless card's PCI ID, chip family, bound driver, and compatibility status. Please attach the redacted report in an [Issue](../../../issues) if your card is not yet supported.
