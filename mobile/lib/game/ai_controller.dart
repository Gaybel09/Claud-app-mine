import 'dart:math' as math;

import 'fight_constants.dart';
import 'fighter.dart';
import 'fighter_state.dart';

/// Resultado de uma decisão da IA -- puro dado, sem nenhuma referência a
/// Fighter/Flame, pra decideAiAction (abaixo) dar pra testar isolado.
class AiDecision {
  const AiDecision({required this.moveDir, required this.block, required this.punch, required this.kick});

  /// -1 (recuar) .. 1 (avançar) -- já em "world space", quem chama
  /// (AiController) só repassa pro FighterInputState.
  final double moveDir;
  final bool block;
  final bool punch;
  final bool kick;

  static const idle = AiDecision(moveDir: 0, block: false, punch: false, kick: false);
}

/// IA simples baseada em distância (Fase 1: sem previsão de frame, sem
/// aprendizado) -- decide uma vez a cada FightConstants.aiDecisionCooldown
/// segundos: aproxima se longe, ataca (soco ou chute, sorteado) se no
/// alcance, às vezes recua se colado demais, às vezes bloqueia se o
/// adversário está atacando e está perto o suficiente pra isso importar.
AiDecision decideAiAction({
  required double selfX,
  required double opponentX,
  required bool opponentAttacking,
  required math.Random random,
}) {
  final distance = (opponentX - selfX).abs();
  final towardOpponent = opponentX >= selfX ? 1.0 : -1.0;

  if (opponentAttacking &&
      distance <= FightConstants.aiAttackRange * 1.3 &&
      random.nextDouble() < FightConstants.aiBlockChanceOnOpponentAttack) {
    return const AiDecision(moveDir: 0, block: true, punch: false, kick: false);
  }

  if (distance <= FightConstants.aiTooCloseRange && random.nextDouble() < FightConstants.aiRetreatChanceWhenTooClose) {
    return AiDecision(moveDir: -towardOpponent, block: false, punch: false, kick: false);
  }

  if (distance <= FightConstants.aiAttackRange) {
    final useKick = random.nextDouble() < FightConstants.aiKickChance;
    return AiDecision(moveDir: 0, block: false, punch: !useKick, kick: useKick);
  }

  if (distance <= FightConstants.aiEngageRange) {
    return AiDecision(moveDir: towardOpponent, block: false, punch: false, kick: false);
  }

  // Fora do alcance de engajamento -- ainda assim caminha na direção do
  // adversário (a arena não é infinita, mas não faz sentido ficar parado
  // só porque está "longe" segundo o limiar).
  return AiDecision(moveDir: towardOpponent, block: false, punch: false, kick: false);
}

/// Wrapper com estado que liga [decideAiAction] a um [Fighter] de verdade --
/// só ele sabe sobre Fighter/tempo; a decisão em si é sempre pura.
///
/// IMPORTANTE (bug já evitado aqui): moveDir/block são "grudentos" --
/// reaplicados TODO frame até a próxima decisão, senão a IA nunca sustenta
/// movimento/guarda por mais de 1 frame. punch/kick são o oposto -- disparam
/// só no frame exato da decisão (dentro do `if (_cooldown <= 0)`), nunca
/// reaplicados depois -- se ficassem "grudentos" como moveDir, o
/// FighterInputState.punchQueued permaneceria true por vários frames
/// seguidos, inclusive DEPOIS do soco atual terminar (já que o Fighter só
/// consome a flag quando sai do estado travado), e a IA acabaria
/// enfileirando um segundo soco imediatamente ao destravar -- um loop de
/// spam não intencional.
class AiController {
  AiController({required this.fighter, required this.opponent, math.Random? random}) : _random = random ?? math.Random();

  final Fighter fighter;
  final Fighter opponent;
  final math.Random _random;

  double _cooldown = 0;
  AiDecision _current = AiDecision.idle;

  void update(double dt) {
    if (fighter.isDefeated || opponent.isDefeated) {
      _current = AiDecision.idle;
      _applyMovementAndBlock();
      return;
    }

    if (!lockedStates.contains(fighter.state)) {
      _cooldown -= dt;
      if (_cooldown <= 0) {
        _cooldown = FightConstants.aiDecisionCooldown;
        _current = decideAiAction(
          selfX: fighter.position.x,
          opponentX: opponent.position.x,
          opponentAttacking: opponent.state == FighterState.punch ||
              opponent.state == FighterState.kick ||
              opponent.state == FighterState.aerialPunch,
          random: _random,
        );
        if (_current.punch) fighter.input.punchQueued = true;
        if (_current.kick) fighter.input.kickQueued = true;
      }
    }

    _applyMovementAndBlock();
  }

  void _applyMovementAndBlock() {
    fighter.input.moveDir = _current.moveDir;
    fighter.input.blockHeld = _current.block;
  }
}
