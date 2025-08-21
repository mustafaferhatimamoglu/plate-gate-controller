Test Scenarios

- ROI inclusion: Detections whose center lies inside configured ROI trigger decisions; detections outside do not notify nor actuate.
- Distance filter (small boxes): Detections with bbox area below `notify_filters.min_box_area_px` are ignored (treat as very far vehicles).
- Distance filter (large boxes): If `notify_filters.max_box_area_px` is set and bbox area exceeds it, ignore (protect against close-up noise).
- Ignored plates: Plates listed in `data/ignored.csv` are skipped entirely (no notifications, no actuators).
- Readable plate flow: Plate in `allowed.csv` opens gate; in `denied.csv` triggers alarm; in `watchlist.csv` notifies without actuators; unknown only notifies (if configured) without actuators.
- Unreadable vehicle inside ROI: If `notify.telegram.notify_unreadable` is true and hit accumulation passes, send photo respecting routing and filters (ROI, direction, min_box_area_px).
- Direction gating: With `direction.enabled` and `require_line_cross: true`, only notify/act when crossing gate line; with `notify_filters.only_in_direction: true`, only inbound emits.

How To Dry-Run Locally (no camera/network)

- Run `python tools/simulator.py` to simulate several detections and print notifications/actuator events.
- Tune `min_box_area_px` and `roi_rect` inside the script to mirror your scene.

