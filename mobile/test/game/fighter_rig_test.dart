import 'package:cubemine_pix/game/fighter_rig.dart';
import 'package:cubemine_pix/game/fighter_state.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('computePose', () {
    test('idle keeps limbs close to resting position (no dramatic swing)', () {
      final pose = computePose(state: FighterState.idle, stateProgress: 0, grounded: true, idleClock: 0);
      expect(pose.frontArmAngle.abs(), lessThan(0.3));
      expect(pose.backArmAngle.abs(), lessThan(0.3));
      expect(pose.crouch, 0);
    });

    test('punch extends the front arm further as the swing progresses', () {
      final early = computePose(state: FighterState.punch, stateProgress: 0.05, grounded: true, idleClock: 0);
      final late = computePose(state: FighterState.punch, stateProgress: 0.5, grounded: true, idleClock: 0);
      expect(late.frontArmAngle, greaterThan(early.frontArmAngle));
    });

    test('kick extends the front leg further as the swing progresses', () {
      final early = computePose(state: FighterState.kick, stateProgress: 0.05, grounded: true, idleClock: 0);
      final late = computePose(state: FighterState.kick, stateProgress: 0.5, grounded: true, idleClock: 0);
      expect(late.frontLegAngle, greaterThan(early.frontLegAngle));
    });

    test('block crouches and raises both arms defensively', () {
      final pose = computePose(state: FighterState.block, stateProgress: 0, grounded: true, idleClock: 0);
      expect(pose.crouch, greaterThan(0));
      expect(pose.frontArmAngle, lessThan(0));
      expect(pose.backArmAngle, lessThan(0));
    });

    test('defeated pose intensifies (falls further) as stateProgress advances', () {
      final justHit = computePose(state: FighterState.defeated, stateProgress: 0, grounded: true, idleClock: 0);
      final fallen = computePose(state: FighterState.defeated, stateProgress: 1.0, grounded: true, idleClock: 0);
      expect(fallen.crouch, greaterThan(justHit.crouch));
      expect(fallen.torsoAngle.abs(), greaterThan(justHit.torsoAngle.abs()));
    });

    test('grounded flag does not throw for any state (smoke test for the full enum)', () {
      for (final state in FighterState.values) {
        expect(() => computePose(state: state, stateProgress: 0.5, grounded: false, idleClock: 3), returnsNormally);
      }
    });
  });

  group('FighterPose.lerp', () {
    test('t=0 returns a, t=1 returns b, t=0.5 is the midpoint', () {
      const a = FighterPose(torsoAngle: 0, frontArmAngle: 0, crouch: 0);
      const b = FighterPose(torsoAngle: 1, frontArmAngle: 2, crouch: 1);

      final start = FighterPose.lerp(a, b, 0);
      final end = FighterPose.lerp(a, b, 1);
      final mid = FighterPose.lerp(a, b, 0.5);

      expect(start.torsoAngle, a.torsoAngle);
      expect(end.torsoAngle, b.torsoAngle);
      expect(mid.torsoAngle, closeTo(0.5, 1e-9));
      expect(mid.frontArmAngle, closeTo(1.0, 1e-9));
      expect(mid.crouch, closeTo(0.5, 1e-9));
    });
  });
}
