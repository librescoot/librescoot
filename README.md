[![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

# LibreScoot

⚠️ **WARNING: EXTREMELY EXPERIMENTAL - DO NOT USE ON REAL HARDWARE** ⚠️

This project aims to create a free and open source firmware for iMX6-based electric scooters. It is currently in early development stages and **will brick your scooter** if installed. This is a research project and should not be used on any real hardware yet.

## Requirements
- Any Linux distribution
- Docker

## Quick Start
```bash
git clone https://github.com/librescoot/librescoot.git
cd librescoot
./build.sh
```

The compiled firmware will be located at:
```
yocto/build/tmp-glibc/deploy/images/librescoot-mdb/*.sdimg
```
for MDB or
```
yocto/build/tmp/deploy/images/librescoot-dbc/*.sdimg
```
for DBC.

## Flashing Instructions
To flash the firmware to the Middle Driver Board (MDB):
1. Connect the MDB via mini-USB
2. Power the MDB with a stable 12V power supply
3. Ensure the MDB is in mass-storage mode
4. Flash using:
```bash
gunzip -c firmware.wic.gz | sudo dd of=/dev/sdX bs=4M oflag=direct status=progress
```
Replace `/dev/sdX` with your actual device path.

For DBC firmware:
1. Connect the DBC via USB
2. Power the DBC with appropriate power supply
3. Ensure the DBC is in mass-storage mode
4. Flash using:
```bash
unzstd -c firmware.zst | sudo dd of=/dev/sdX bs=4M oflag=direct status=progress
```
Replace `/dev/sdX` with your actual device path.

## Current Status
This is heavily work-in-progress. The codebase is unstable and changing rapidly. At this stage, the project is for development and research purposes only.

## Goals
- Create a fully open source scooter firmware
- Improve safety through transparency
- Enable community-driven development and customization

## Contributing
While we welcome contributions, please note that this project is not ready for production use. Feel free to open issues for discussion or submit PRs for review.

## License
This work is licensed under a
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License][cc-by-nc-sa].

[![CC BY-NC-SA 4.0][cc-by-nc-sa-image]][cc-by-nc-sa]

[cc-by-nc-sa]: http://creativecommons.org/licenses/by-nc-sa/4.0/
[cc-by-nc-sa-image]: https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png
[cc-by-nc-sa-shield]: https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg
