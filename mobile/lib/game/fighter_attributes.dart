import 'fight_constants.dart';

/// Os 6 atributos pedidos: vida, energia, ataque, defesa, velocidade, pulo.
/// Imutável -- um Fighter guarda um [FighterAttributes] (os máximos/taxas)
/// separado do estado mutável de vida/energia atuais (ver Fighter).
class FighterAttributes {
  const FighterAttributes({
    required this.maxHealth,
    required this.maxEnergy,
    required this.attack,
    required this.defense,
    required this.speed,
    required this.jumpPower,
  });

  final int maxHealth;
  final int maxEnergy;
  final int attack;
  final int defense;
  final double speed;
  final double jumpPower;

  /// Fase 1: os dois lutadores começam idênticos e balanceados (decisão
  /// confirmada com o usuário) -- sem vantagem de nenhum dos dois lados.
  static const balanced = FighterAttributes(
    maxHealth: FightConstants.baseHealth,
    maxEnergy: FightConstants.baseEnergy,
    attack: FightConstants.baseAttack,
    defense: FightConstants.baseDefense,
    speed: FightConstants.baseSpeed,
    jumpPower: FightConstants.baseJumpPower,
  );
}
