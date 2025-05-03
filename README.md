[![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

# LibreScoot

⚠️ **WARNING: EXTREMELY EXPERIMENTAL - DO NOT USE ON REAL HARDWARE** ⚠️

This project aims to create a free and open source firmware for iMX6-based electric scooters. It is currently in early development stages and **might brick your scooter** if installed. This is a research project and should not be used on any real hardware yet.

## Requirements
- Any Linux distribution
- Docker

## Quick Start
```bash
git clone https://github.com/librescoot/librescoot.git
cd librescoot
./build.sh mdb
# OR for the DBC
# ./build.sh dbc
```

The compiled firmware will be located at:
```
yocto/build/tmp-glibc/deploy/images/librescoot-mdb/*.sdimg
```
for MDB (Middle Driver Board) or
```
yocto/build/tmp/deploy/images/librescoot-dbc/*.sdimg
```
for DBC (Dashboard Controller).

## Build System Documentation

### Build Script (build.sh)

The `build.sh` script automates the build process using Docker containers to ensure a consistent build environment.

**Usage:**
```bash
./build.sh <target> [branch]
```

**Parameters:**
- `<target>`: Required. Specifies the target board:
  - `mdb`: Middle Driver Board
  - `dbc`: Dashboard Controller
- `[branch]`: Optional. Git branch to use for meta-librescoot layer (defaults to "scarthgap")

**Example:**
```bash
./build.sh mdb                  # Build MDB firmware using default branch
./build.sh dbc feature-branch   # Build DBC firmware using a custom branch
```

The script performs the following operations:
1. Creates a Docker image for the build environment
2. Mounts the local yocto directory into the container
3. Runs the container with the specified target and branch parameters

### Docker Entrypoint (docker/entrypoint.sh)

The Docker entrypoint script handles the Yocto build process inside the container:

1. **Environment Setup**:
   - Configures Git with default identity
   - Initializes repo for NXP's imx-manifest
   - Syncs repositories

2. **Layer Management**:
   - Clones necessary Yocto layers:
     - meta-mender: For OTA updates
     - meta-flutter: For Flutter app support
     - meta-librescoot: LibreScoot-specific layer
     - meta-openjdk-temurin: Java support

3. **Build Configuration**:
   - Sets up build environment with DISTRO=librescoot-mdb
   - Configures bblayers.conf and local.conf based on target (mdb/dbc)
   - Sets various build variables, including:
     - MACHINE (librescoot-mdb or librescoot-dbc)
     - DISTRO (librescoot-mdb or librescoot-dbc)
     - Mender configuration for OTA updates
     - Kernel and U-Boot versions
     - Timezone settings
   - Note: The LIBRESCOOT_VERSION is determined from the meta-librescoot layer using `git describe --tags --dirty`, which captures the current tag, any additional commits, and whether there are uncommitted changes

4. **Build Process**:
   - Executes bitbake to build the image for the specified target

### Target Differences

#### MDB (Middle Driver Board)
- Based on iMX6 platform
- Uses Linux kernel 5.4.24
- Default configuration in meta-librescoot

#### DBC (Dashboard Controller Board)
- Based on iMX6 platform
- Uses newer Linux kernel 6.6.3
- Additional layers for multimedia and UI support

## Flashing Instructions
To flash the firmware to the Middle Driver Board (MDB):
1. Connect the MDB via mini-USB
2. Power the MDB with a stable 12V power supply
3. Ensure the MDB is in mass-storage mode
4. Flash using:
```bash
gunzip -c *.sdimg.gz | sudo dd of=/dev/sdX bs=4M oflag=direct status=progress
```
Replace `/dev/sdX` with your actual device path.

For DBC firmware:
1. Connect the DBC via USB
2. Ensure the DBC is in mass-storage mode
3. Flash using:
```bash
gunzip -c *.sdimg.gz | sudo dd of=/dev/sdX bs=4M oflag=direct status=progress
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
