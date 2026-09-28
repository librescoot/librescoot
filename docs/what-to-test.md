# Next Librescoot testing build — what to test

Candidate changes since [`testing-20260927T212059`](https://github.com/librescoot/librescoot/releases/tag/testing-20260927T212059). This checklist applies only after a new testing build is published with the prepared `stable.env` revisions. Record the new build ID, MDB/DBC board, steps, expected and observed results, and a photo or log bundle if possible.

## Regional offline maps and route recovery

- On a test scooter with its existing single-region map, update without installing a regional pack. The map, offline routing and built-in map updater should still work. Do not remove a working map just to test an error case.
- On a **bench/test installation**, enter USB Update Mode and install two matching `maps/tiles_<slug>.mbtiles` and `maps/valhalla_tiles_<slug>.tar[.zst]` pairs. Verify both packs remain installed and the dashboard selects the region containing a recent GPS fix; check display, routing and address search for each region. Repeat after replacing one pack and after a restart. Region selection uses rectangular map bounds; heavily overlapping regions may switch late, and cross-region routes are not supported.
- For a single named pair on a legacy stick, check that it still installs as the single-region map. To opt into regional installation of just one pair, add an empty `maps/regional-packs` marker. **Do not migrate a working scooter just for this test:** an existing regular `/data/valhalla/tiles.tar` is preserved and must be migrated deliberately before automatic routing switching is enabled. See the [navigation setup guide](https://librescoot.org/docs/dev/navigation.html).
- On a safe parked setup with an unfinished multi-stop route, restart the dashboard and check that guidance resumes when the routing engine is available. Leave ready-to-drive, then enter parked: an unfinished route should be recoverable without selecting the destination again. Do not operate menus while riding.

## ECU communication and optional cloud client

- During normal use, watch for spurious `E20` communication-loss reports during a quiet but healthy controller period, and verify that the controller's existing faults do not remain displayed as current after a genuine communication outage. Report the CAN link state and logs if a fault occurs. **Do not disconnect controller power or CAN on a road-going scooter to trigger E20.** On a bench, confirm that sustained communication or a reply to a recovery probe clears E20; a single unrelated frame should not suffice.
- If the optional cloud client is installed, confirm ordinary telemetry and remote commands still work. Check that a reported ECU firmware identification is accurate when the controller provides it. Invalid commands and bad persisted configuration should be rejected without crashing the client; exercise malformed inputs only in a controlled test environment.

The earlier [testing checklist](https://github.com/librescoot/librescoot/releases/tag/testing-20260927T212059) still applies: dashboard route choices, web management and update estimates, NFC/battery reporting and MDB networking. Keep a working physical keycard as backup. Do not install an update merely to test the upload form.
