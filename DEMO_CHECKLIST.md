# Real-Device Demonstration Checklist
### FILDZA MOD ROUTER — NX205 Firmware Analysis & Network Diagnostics Workstation

A practical, safe checklist for a live demo with the physical TP-Link Archer
NX205(EU) V1. **Read-only:** nothing here flashes, downgrades, reconfigures, or
changes device identity. Do not change any router setting during the demo.

Primary launch (interactive workstation):
```powershell
cd D:\NX205-Firmware-Analysis
python workstation.py            # auto-detects gateway, opens the UI at :8787
```
In the UI: **Network → Run diagnostics**, then **Firmware Studio**, then
**Evidence → Export**. The sections below are the hardware steps around it.

## A. Prepare the hardware
- [ ] Power off the router. Insert the **Nano SIM** into the SIM slot (PIN lock
      disabled, or PIN known). Re-seat the two SMA antennas.
- [ ] Power on. Wait ~1–2 min for the 5G/LTE and Wi-Fi LEDs to settle.
- [ ] Note the label: model `Archer NX205`, HW `EU/1.0`, default admin URL.

## B. Connect this PC to the router
- [ ] On Windows, join the router's Wi-Fi SSID (on the sticker) **or** plug into
      a LAN port. You should get an IP in the router's subnet (usually
      `192.168.1.x`).
- [ ] Confirm which network you're on:
      ```powershell
      netsh wlan show interfaces
      ipconfig
      ```
      > During prototype development this PC was on a different Wi-Fi
      > (`vivo 1906`, gateway `192.168.93.82`), so `192.168.1.1` showed
      > **100% loss / UNAVAILABLE**. That is expected until you actually join
      > the NX205. Re-run the tools once connected.

## C. Open the router admin page (manual, in a browser)
- [ ] Browse to `http://192.168.1.1` (or `http://tplinkmodem.net`).
- [ ] Log in with your own admin credentials. Read-only: just **view** the
      status page (firmware version, SIM/5G status, WAN IP). Do **not** change
      settings for this demo.
- [ ] Record the on-screen firmware build and compare with the label
      (`Build 251223` reported) and the official package (`Build 250731`).

## D. Capture real connectivity (automated, read-only)
Run from the project folder once connected to the NX205. The dashboard now
**auto-detects your default gateway** (via `ipconfig`) — you do not need to type
the router IP, and it is never assumed to be `192.168.1.1`:
```powershell
python dashboard.py --open
```
The console prints the detected gateway, e.g. `Auto-detected default gateway:
192.168.1.1 (source: ipconfig)`, then probes it.

If your router/admin page is on a different IP, port, or HTTPS, override any of
these (the flags still work exactly as before):
```powershell
python dashboard.py --router 192.168.1.1 --port 443 --scheme https --open
```
Console view (also read-only):
```powershell
python main.py
```
- [ ] **Live Network Diagnostics** shows five independent readings, each badged
      `REAL` / `UNAVAILABLE` / `ERROR`:
      Router ICMP · Internet ICMP · DNS · Admin-port TCP · Admin-page HTTP.
      Once you are on the NX205 the router rows flip to `REAL`.
- [ ] A `401/403` on *Admin page HTTP* means the admin UI **is present but
      needs login** — that is expected and correct; the tool never logs in.
- [ ] Optional manual spot checks (replace the IP with your detected gateway):
      ```powershell
      ipconfig                      # read your real Default Gateway
      ping -n 10 <gateway>
      ping -n 10 8.8.8.8
      nslookup www.tp-link.com
      ```

## E. Record what you observed (does not touch the router)
Log genuine observations into the connectivity log (JSON):
```powershell
python -c "from src.connectivity_tests import ConnectivityLog; \
l=ConnectivityLog('data/connectivity_log.json'); \
l.record('LAN web UI reachable','pass',interface='LAN',detail='status page loaded',approved_by='YOURNAME'); \
l.save(); print('saved', l.summary())"
```
- [ ] Re-run `python dashboard.py` — your real rows replace the `PLACEHOLDER`
      examples.

## F. Honest interpretation (important)
- [ ] A reachable internet with 0% loss proves **ordinary connectivity only**.
- [ ] It does **NOT** prove unrestricted hotspot/tethering, and this demo does
      **not** test or bypass any carrier hotspot limit. Hotspot policy is set by
      the carrier/SIM plan, not by this tool.
- [ ] Custom firmware / replacing the web UI is **not supported** for this exact
      device (see the dashboard's Feasibility section). Do not attempt a flash.

## G. Safety sign-off
- [ ] Original firmware files in the extracted package are unchanged.
- [ ] No firmware was flashed, downgraded, or generated.
- [ ] No router setting or device identifier was modified.

## H. Troubleshooting (fast)
| Symptom | Likely cause | Fix |
|---|---|---|
| `Could not auto-detect the default gateway` | Not joined to any network, or only a virtual adapter is up | Join the NX205 Wi-Fi/LAN, then run `ipconfig` and use `python dashboard.py --router <gateway>` |
| Detected gateway is **not** the router (e.g. a phone hotspot like `192.168.93.x`) | PC is on another network | Connect to the NX205 first, or pass `--router <router-ip>` explicitly |
| Router **ICMP UNAVAILABLE** but you are connected | Router firewall blocks ping | Check *Admin-port TCP* / *Admin-page HTTP* rows instead; open `http://<gateway>` in a browser |
| *Admin page HTTP* shows **401/403** | Admin UI needs login (normal) | Expected — the page exists; log in **manually** in your browser, not via this tool |
| *Admin page HTTP* **UNAVAILABLE / refused** but ICMP REAL | Admin UI is on HTTPS or another port | Try `--port 443 --scheme https` |
| Router rows show **ERROR** | No target was determined (detection failed, no `--router`) | Supply `--router <gateway>`; ERROR means "check could not run", not "router down" |
| `python` not found | Python not on PATH | Use `py dashboard.py ...` or reinstall Python 3 with "Add to PATH" |
| Firmware hash step is slow | 141 MB image is being hashed | Add `--no-firmware` for a fast diagnostics-only run |

> Reminder: everything here is read-only. If a step would require logging in,
> changing a setting, downgrading, or flashing — stop. That is out of scope and
> risks the device.
