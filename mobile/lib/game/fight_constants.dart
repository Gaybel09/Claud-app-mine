/// Todos os números "de balanceamento" do minigame de luta (Fase 1) num só
/// lugar, pra ajustar sem caçar mágica espalhada pelo resto do módulo.
class FightConstants {
  FightConstants._();

  // --- Arena --------------------------------------------------------------

  static const double arenaWidth = 3000;
  static const double groundY = 500;
  static const double arenaHeight = 700;

  // --- Física cinemática (sem motor de física -- ver decisão registrada
  // na conversa: Box2D deixa a resposta imprecisa demais pra um jogo de
  // luta) ---------------------------------------------------------------

  static const double gravity = 1800; // unidades/s², sempre pra baixo
  static const double groundFriction = 2400; // desaceleração ao soltar o movimento

  // --- Atributos base (Fase 1: os dois lutadores começam idênticos) -----

  static const int baseHealth = 100;
  static const int baseEnergy = 100;
  static const int baseAttack = 10;
  static const int baseDefense = 5;
  static const double baseSpeed = 320; // unidades/s de deslocamento horizontal
  static const double baseJumpPower = 780; // velocidade vertical inicial do pulo

  // --- Dimensões do lutador (retângulo de colisão -- ver Fighter.hurtbox) -

  static const double fighterWidth = 70;
  static const double fighterHeight = 180;

  /// Distância horizontal mínima entre os dois lutadores -- sem isso, os
  /// dois conseguem andar um através do outro (nenhuma colisão corpo a
  /// corpo), o que parece um bug visual (a ordem esquerda/direita "troca"
  /// no meio da luta) e não é como jogos de luta normalmente se comportam.
  static const double minFighterSeparation = fighterWidth * 0.9;

  // --- Ataques: janelas de tempo (segundos) ------------------------------
  // startup: não acerta nada ainda (aviso visual antes do golpe).
  // active: janela em que o hitbox realmente existe.
  // recovery: lutador fica vulnerável/parado terminando o movimento.

  static const double punchStartup = 0.08;
  static const double punchActive = 0.07;
  static const double punchRecovery = 0.12;

  static const double kickStartup = 0.12;
  static const double kickActive = 0.08;
  static const double kickRecovery = 0.18;

  static const double aerialPunchStartup = 0.06;
  static const double aerialPunchActive = 0.10;
  static const double aerialPunchRecovery = 0.10;

  static double get punchTotal => punchStartup + punchActive + punchRecovery;
  static double get kickTotal => kickStartup + kickActive + kickRecovery;
  static double get aerialPunchTotal => aerialPunchStartup + aerialPunchActive + aerialPunchRecovery;

  // --- Ataques: alcance/dano/custo de energia -----------------------------
  // Dano final = baseDamage + attacker.attack*attackScale - defender.defense*defenseScale,
  // nunca abaixo de minDamage (ver combat.dart:resolveDamage).

  static const double punchRange = 90;
  static const double punchBaseDamage = 4;
  static const double punchAttackScale = 0.6;
  static const int punchEnergyCost = 10;

  static const double kickRange = 110;
  static const double kickBaseDamage = 8;
  static const double kickAttackScale = 0.9;
  static const int kickEnergyCost = 18;

  static const double aerialPunchRange = 95;
  static const double aerialPunchBaseDamage = 6;
  static const double aerialPunchAttackScale = 0.7;
  static const int aerialPunchEnergyCost = 12;

  static const double defenseScale = 0.5;
  static const double minDamage = 1;

  // Bloqueio: reduz o dano recebido (não zera -- guarda sempre "custa" algo,
  // senão bloquear vira estratégia dominante sem trade-off nenhum).
  static const double blockDamageMultiplier = 0.15;
  static const double blockEnergyDrainPerSecond = 8;
  // Energia mínima pra CONTINUAR bloqueando -- abaixo disso a guarda "quebra"
  // (força o jogador a esperar regenerar antes de guardar de novo).
  static const double blockBreakEnergyThreshold = 5;

  static const double energyRegenPerSecond = 15;

  // --- Reação a dano -------------------------------------------------------

  static const double hitStunBase = 0.18;
  static const double hitStunPerDamage = 0.008; // golpes mais fortes atordoam mais

  // --- IA simples (ver ai_controller.dart) ---------------------------------

  static const double aiEngageRange = 260; // distância em que a IA passa a avançar
  static const double aiAttackRange = 130; // distância em que a IA tenta atacar
  static const double aiTooCloseRange = 70; // distância em que a IA às vezes recua
  static const double aiDecisionCooldown = 0.35; // intervalo mínimo entre decisões da IA
  static const double aiBlockChanceOnOpponentAttack = 0.45;
  static const double aiRetreatChanceWhenTooClose = 0.3;
  static const double aiKickChance = 0.35; // vs. soco, quando decide atacar

  // --- Fim de partida -------------------------------------------------------

  /// Atraso entre a vida chegar a zero e o overlay de resultado aparecer --
  /// só pra dar tempo da pose de derrota (ver fighter_rig.dart) ser vista
  /// em vez de cortar pra tela de resultado instantaneamente.
  static const double matchEndDelaySeconds = 1.2;
}
