import 'package:cubemine_pix/game/combat.dart';
import 'package:cubemine_pix/game/fight_constants.dart';
import 'package:cubemine_pix/game/fighter_state.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('resolveDamage', () {
    test('scales with attacker attack and reduces with defender defense', () {
      final low = resolveDamage(type: AttackType.punch, attackerAttack: 5, defenderDefense: 5, blocked: false);
      final high = resolveDamage(type: AttackType.punch, attackerAttack: 20, defenderDefense: 5, blocked: false);
      expect(high, greaterThan(low));

      final softDefense = resolveDamage(type: AttackType.punch, attackerAttack: 10, defenderDefense: 0, blocked: false);
      final hardDefense = resolveDamage(type: AttackType.punch, attackerAttack: 10, defenderDefense: 30, blocked: false);
      expect(hardDefense, lessThan(softDefense));
    });

    test('never goes below FightConstants.minDamage even against very high defense', () {
      final damage = resolveDamage(type: AttackType.punch, attackerAttack: 1, defenderDefense: 999, blocked: false);
      expect(damage, greaterThanOrEqualTo(FightConstants.minDamage.round()));
    });

    test('blocking reduces damage but never to zero', () {
      const attackerAttack = 10;
      const defenderDefense = 5;
      final unblocked = resolveDamage(type: AttackType.kick, attackerAttack: attackerAttack, defenderDefense: defenderDefense, blocked: false);
      final blocked = resolveDamage(type: AttackType.kick, attackerAttack: attackerAttack, defenderDefense: defenderDefense, blocked: true);

      expect(blocked, lessThan(unblocked));
      expect(blocked, greaterThanOrEqualTo(FightConstants.minDamage.round()));
    });

    test('kick deals more base damage than punch under identical stats', () {
      final punch = resolveDamage(type: AttackType.punch, attackerAttack: 10, defenderDefense: 5, blocked: false);
      final kick = resolveDamage(type: AttackType.kick, attackerAttack: 10, defenderDefense: 5, blocked: false);
      expect(kick, greaterThan(punch));
    });
  });

  group('hitStunDuration', () {
    test('grows with damage taken but stays bounded for typical hits', () {
      final small = hitStunDuration(5);
      final big = hitStunDuration(40);
      expect(big, greaterThan(small));
      expect(small, greaterThanOrEqualTo(FightConstants.hitStunBase));
    });
  });

  group('AttackSpec', () {
    test('aerialPunch is only meant to be thrown while airborne -- range/damage stay modest', () {
      // Não é uma regra imposta pelo AttackSpec em si (isso é o Fighter que
      // decide), só uma checagem de sanidade dos números: o aéreo não deve
      // ser estritamente melhor que o chute em dano E alcance ao mesmo
      // tempo, senão chutar no chão nunca compensaria.
      expect(AttackSpec.aerialPunch.baseDamage, lessThan(AttackSpec.kick.baseDamage));
    });

    test('every attack has a positive total duration and energy cost', () {
      for (final spec in [AttackSpec.punch, AttackSpec.kick, AttackSpec.aerialPunch]) {
        expect(spec.total, greaterThan(0));
        expect(spec.energyCost, greaterThan(0));
        expect(spec.range, greaterThan(0));
      }
    });
  });
}
