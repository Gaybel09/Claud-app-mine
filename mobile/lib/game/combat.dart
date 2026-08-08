import 'fight_constants.dart';
import 'fighter_state.dart';

/// Especificação de tempo/alcance/dano de um tipo de ataque -- ver
/// FightConstants pros valores numéricos. Função pura, sem estado, fácil de
/// testar isolada do resto do jogo (nenhuma dependência de Flame aqui).
class AttackSpec {
  const AttackSpec({
    required this.startup,
    required this.active,
    required this.recovery,
    required this.range,
    required this.baseDamage,
    required this.attackScale,
    required this.energyCost,
  });

  final double startup;
  final double active;
  final double recovery;
  final double range;
  final double baseDamage;
  final double attackScale;
  final int energyCost;

  double get total => startup + active + recovery;

  static const punch = AttackSpec(
    startup: FightConstants.punchStartup,
    active: FightConstants.punchActive,
    recovery: FightConstants.punchRecovery,
    range: FightConstants.punchRange,
    baseDamage: FightConstants.punchBaseDamage,
    attackScale: FightConstants.punchAttackScale,
    energyCost: FightConstants.punchEnergyCost,
  );

  static const kick = AttackSpec(
    startup: FightConstants.kickStartup,
    active: FightConstants.kickActive,
    recovery: FightConstants.kickRecovery,
    range: FightConstants.kickRange,
    baseDamage: FightConstants.kickBaseDamage,
    attackScale: FightConstants.kickAttackScale,
    energyCost: FightConstants.kickEnergyCost,
  );

  static const aerialPunch = AttackSpec(
    startup: FightConstants.aerialPunchStartup,
    active: FightConstants.aerialPunchActive,
    recovery: FightConstants.aerialPunchRecovery,
    range: FightConstants.aerialPunchRange,
    baseDamage: FightConstants.aerialPunchBaseDamage,
    attackScale: FightConstants.aerialPunchAttackScale,
    energyCost: FightConstants.aerialPunchEnergyCost,
  );

  static AttackSpec of(AttackType type) => switch (type) {
    AttackType.punch => punch,
    AttackType.kick => kick,
    AttackType.aerialPunch => aerialPunch,
  };
}

/// dano = baseDamage + attacker.attack*attackScale - defender.defense*defenseScale,
/// nunca abaixo de FightConstants.minDamage -- e reduzido a
/// blockDamageMultiplier se [blocked] (guarda nunca zera o dano de todo,
/// senão bloquear vira estratégia sem trade-off nenhum).
int resolveDamage({
  required AttackType type,
  required int attackerAttack,
  required int defenderDefense,
  required bool blocked,
}) {
  final spec = AttackSpec.of(type);
  var damage = spec.baseDamage + attackerAttack * spec.attackScale - defenderDefense * FightConstants.defenseScale;
  if (blocked) {
    damage *= FightConstants.blockDamageMultiplier;
  }
  damage = damage.clamp(FightConstants.minDamage, double.infinity);
  return damage.round();
}

/// Duração do hit-stun (trava de ação ao levar um golpe) -- golpes mais
/// fortes atordoam um pouco mais, dentro de um teto razoável.
double hitStunDuration(int damageTaken) {
  return FightConstants.hitStunBase + damageTaken * FightConstants.hitStunPerDamage;
}
