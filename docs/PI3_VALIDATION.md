# Pi3 On-Device Validation Checklist

Use this checklist on the PiDog hardware before declaring Pi3 complete.

## Sensors
- [ ] Ultrasonic distance reads are stable (no spikes at rest).
- [ ] Touch sensor updates are reliable (debounce acceptable).
- [ ] Sound detection and direction work in normal room noise.
- [ ] IMU readings are stable; heading integration does not drift excessively.

## Scanning
- [ ] Three-way scan returns valid left/right/forward values.
- [ ] Sweep scan covers full range and returns head to center.
- [ ] Scan interval matches settings; no stuttering.

## Navigation
- [ ] Obstacle avoidance selects sensible turns.
- [ ] Stuck recovery triggers and completes.
- [ ] Clear-path streak reduces scan jitter.

## Safety
- [ ] Emergency stop triggers at configured distance.
- [ ] Tilt protection triggers and cooldown behaves.
- [ ] Watchdog triggers on stale sensors/scans and recovers.
- [ ] Safe mode throttles speeds and scan cadence as expected.

## Mapping
- [ ] Openings and safe paths appear in logs.
- [ ] Home map is saved when enabled.

## Logging
- [ ] Event log JSONL files are created.
- [ ] Navigation decision snapshots appear when enabled.

## Tools
- [ ] `tools/hardware_checkup.py` passes basic checks.
- [ ] `tools/smoke_test.py` completes with no errors.
