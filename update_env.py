#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import re

REPO_MAP = {
    # Services
    "SRCREV_alarm_service": "https://github.com/librescoot/alarm-service",
    "SRCREV_battery_service": "https://github.com/librescoot/battery-service",
    "SRCREV_bluetooth_service": "https://github.com/librescoot/bluetooth-service",
    "SRCREV_boot_animation": "https://github.com/librescoot/boot-animation",
    "SRCREV_carplay_service": "https://github.com/librescoot/carplay-service",
    "SRCREV_data_server": "https://github.com/librescoot/data-server",
    "SRCREV_dbc_backlight_service": "https://github.com/librescoot/dbc-backlight-service",
    "SRCREV_dbc_dispatcher": "https://github.com/librescoot/dbc-dispatcher",
    "SRCREV_ecu_service": "https://github.com/librescoot/ecu-service",
    "SRCREV_keycard_service": "https://github.com/librescoot/keycard-service",
    "SRCREV_lsc": "https://github.com/librescoot/lsc",
    "SRCREV_modem_service": "https://github.com/librescoot/modem-service",
    "SRCREV_pm_service": "https://github.com/librescoot/pm-service",
    "SRCREV_radio_gaga": "https://github.com/rescoot/radio-gaga",
    "SRCREV_scootui_qt": "https://github.com/librescoot/scootui-qt",
    "SRCREV_scootui_tui": "https://github.com/librescoot/scootui-tui",
    "SRCREV_settings_service": "https://github.com/librescoot/settings-service",
    "SRCREV_ums_service": "https://github.com/librescoot/ums-service",
    "SRCREV_update_service": "https://github.com/librescoot/update-service",
    "SRCREV_uplink_service": "https://github.com/librescoot/uplink-service",
    "SRCREV_vehicle_service": "https://github.com/librescoot/vehicle-service",
    "SRCREV_version_service": "https://github.com/librescoot/version-service",
}

LAYER_REPO_MAP = {
    "LAYER_VERSION_meta_librescoot": "https://github.com/librescoot/meta-librescoot",
}

def get_latest_commit(url, branch="HEAD"):
    """Fetches the latest commit hash for a given URL and branch."""
    try:
        # Use git ls-remote to get the hash without cloning
        result = subprocess.run(
            ["git", "ls-remote", url, branch],
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        output = result.stdout.strip()
        if not output:
            print(f"Warning: No output from git ls-remote for {url}")
            return None
        
        # Output format: <hash>\t<ref>
        # We just want the hash
        commit_hash = output.split()[0]
        return commit_hash
    except subprocess.CalledProcessError as e:
        print(f"Error fetching {url}: {e}")
        return None
    except subprocess.TimeoutExpired:
        print(f"Timeout fetching {url}")
        return None

def update_env_file(filepath, target_mode, allowed_keys):
    """Updates the env file with latest commits."""
    print(f"Updating {filepath} for target: {target_mode}...")

    # Merge both maps for lookup
    all_repos = {**REPO_MAP, **LAYER_REPO_MAP}

    with open(filepath, 'r') as f:
        lines = f.readlines()

    new_lines = []
    updated_count = 0

    for line in lines:
        # Check if line is a variable assignment we care about
        match = re.match(r'^([A-Z_]+[a-z0-9_]*)=', line)
        if match:
            key = match.group(1)
            if key in all_repos and key in allowed_keys:
                current_val_match = re.match(r'^[A-Z_]+[a-z0-9_]*="(.*)"$', line.strip())
                current_val = current_val_match.group(1) if current_val_match else ""

                # Use the branch from DISTRO_CODENAME-aware default for layers
                branch = "HEAD"
                if key in LAYER_REPO_MAP:
                    # If current value looks like a branch name (not a hex hash), use it as the ref
                    if current_val and not re.match(r'^[0-9a-f]{40}$', current_val):
                        branch = current_val

                print(f"Fetching latest for {key} ({all_repos[key]})...")
                latest_hash = get_latest_commit(all_repos[key], branch)

                if latest_hash:
                    new_line = f'{key}="{latest_hash}"\n'
                    if new_line != line:
                        print(f"  Updated {key}: {current_val[:7]}... -> {latest_hash[:7]}...")
                        new_lines.append(new_line)
                        updated_count += 1
                    else:
                        print(f"  {key} is already up to date.")
                        new_lines.append(line)
                else:
                    print(f"  Skipping {key} (fetch failed).")
                    new_lines.append(line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    with open(filepath, 'w') as f:
        f.writelines(new_lines)

    print(f"Done. Updated {updated_count} variables in {filepath}.")

def main():
    parser = argparse.ArgumentParser(description="Update env files with latest git commits.")
    parser.add_argument("--target", choices=["stable", "nightly"], required=True, help="Target environment to update.")
    parser.add_argument("services", nargs="*", help="Specific services or layers to update (e.g. ums-service, meta-librescoot)")
    parser.add_argument("--all", action="store_true", help="Update all services and layers")
    parser.add_argument("--layers", action="store_true", help="Update all layer versions")

    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_file = os.path.join(base_dir, f"{args.target}.env")

    if not os.path.exists(env_file):
        print(f"Error: File {env_file} does not exist.")
        sys.exit(1)

    allowed_keys = set()
    if args.all:
        allowed_keys = set(REPO_MAP.keys()) | set(LAYER_REPO_MAP.keys())
    else:
        if args.layers:
            allowed_keys |= set(LAYER_REPO_MAP.keys())

        if args.services:
            for s in args.services:
                # Normalize name to env var key
                # e.g. ums-service -> SRCREV_ums_service
                # e.g. meta-librescoot -> LAYER_VERSION_meta_librescoot
                key_suffix = s.replace("-", "_")

                srcrev_key = f"SRCREV_{key_suffix}"
                layer_key = f"LAYER_VERSION_{key_suffix}"

                if srcrev_key in REPO_MAP:
                    allowed_keys.add(srcrev_key)
                elif layer_key in LAYER_REPO_MAP:
                    allowed_keys.add(layer_key)
                else:
                    print(f"Warning: '{s}' not found in service or layer configuration.")

    if not allowed_keys:
        print("Error: Please specify services/layers to update, use --layers, or use --all.")
        sys.exit(1)

    update_env_file(env_file, args.target, allowed_keys)

if __name__ == "__main__":
    main()
