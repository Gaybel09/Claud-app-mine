import 'dart:math';

import 'package:cubemine_pix/game/ai_controller.dart';
import 'package:cubemine_pix/game/fight_constants.dart';
import 'package:flutter_test/flutter_test.dart';

/// Random determinístico -- sempre devolve o mesmo valor, pra testar os
/// ramos de decisão que dependem de sorteio (bloquear/recuar/chutar) sem
/// depender de sorte.
class _FixedRandom implements Random {
  _FixedRandom(this.value);
  final double value;

  @override
  double nextDouble() => value;

  @override
  int nextInt(int max) => 0;

  @override
  bool nextBool() => false;
}

void main() {
  group('decideAiAction', () {
    test('approaches the opponent when far away', () {
      final decision = decideAiAction(
        selfX: 0,
        opponentX: 1000,
        opponentAttacking: false,
        random: _FixedRandom(0.99), // nunca sorteia nada probabilístico
      );
      expect(decision.moveDir, 1.0);
      expect(decision.punch, isFalse);
      expect(decision.kick, isFalse);
    });

    test('approaches when the opponent is to the left too (direction-agnostic)', () {
      final decision = decideAiAction(
        selfX: 1000,
        opponentX: 0,
        opponentAttacking: false,
        random: _FixedRandom(0.99),
      );
      expect(decision.moveDir, -1.0);
    });

    test('attacks (punch or kick) when within attack range and not distracted by other rolls', () {
      final decision = decideAiAction(
        selfX: 0,
        opponentX: FightConstants.aiAttackRange - 1,
        opponentAttacking: false,
        random: _FixedRandom(0.99), // acima de aiKickChance -> escolhe soco
      );
      expect(decision.moveDir, 0);
      expect(decision.punch, isTrue);
      expect(decision.kick, isFalse);
    });

    test('picks kick instead of punch when the roll is below aiKickChance', () {
      final decision = decideAiAction(
        selfX: 0,
        opponentX: FightConstants.aiAttackRange - 1,
        opponentAttacking: false,
        random: _FixedRandom(0.0), // sempre abaixo de qualquer limiar
      );
      expect(decision.kick, isTrue);
      expect(decision.punch, isFalse);
    });

    test('blocks when the opponent is attacking, in range, and the roll favors it', () {
      final decision = decideAiAction(
        selfX: 0,
        opponentX: FightConstants.aiAttackRange,
        opponentAttacking: true,
        random: _FixedRandom(0.0), // abaixo de aiBlockChanceOnOpponentAttack
      );
      expect(decision.block, isTrue);
      expect(decision.punch, isFalse);
      expect(decision.kick, isFalse);
    });

    test('does not block when the roll does not favor it, even if the opponent is attacking', () {
      final decision = decideAiAction(
        selfX: 0,
        opponentX: FightConstants.aiAttackRange,
        opponentAttacking: true,
        random: _FixedRandom(0.99), // acima de aiBlockChanceOnOpponentAttack
      );
      expect(decision.block, isFalse);
    });

    test('retreats sometimes when the opponent is too close and the roll favors it', () {
      final decision = decideAiAction(
        selfX: 0,
        opponentX: FightConstants.aiTooCloseRange - 1,
        opponentAttacking: false,
        random: _FixedRandom(0.0), // abaixo de aiRetreatChanceWhenTooClose
      );
      expect(decision.moveDir, -1.0);
      expect(decision.block, isFalse);
      expect(decision.punch, isFalse);
    });

    test('stays idle (does nothing) at rest when nothing calls for action', () {
      expect(AiDecision.idle.moveDir, 0);
      expect(AiDecision.idle.block, isFalse);
      expect(AiDecision.idle.punch, isFalse);
      expect(AiDecision.idle.kick, isFalse);
    });
  });
}
