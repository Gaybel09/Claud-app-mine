/// Intenção de input de UM lutador neste frame -- alimentada tanto pelos
/// controles touch (jogador) quanto pelo AiController (oponente), lidas por
/// Fighter.update() e depois zeradas (os campos "Queued" são eventos de um
/// frame só, não estado contínuo).
///
/// Sobre as combinações pedidas (avançar+soco, avançar+chute, recuar+defesa):
/// não são "golpes especiais" novos -- são só a garantia de que mover e
/// atacar/bloquear ao mesmo tempo funciona (moveDir e blockHeld continuam
/// valendo junto com um ataque em andamento/logo antes dele). A única
/// combinação que produz um resultado DIFERENTE é pular+soco (vira
/// AttackType.aerialPunch em vez de punch -- ver Fighter._chooseAttack).
class FighterInputState {
  /// -1 (esquerda) .. 1 (direita), em coordenadas absolutas do mundo -- o
  /// próprio Fighter decide se isso é "avançar" ou "recuar" comparando com
  /// pra que lado ele está de frente (ver Fighter.facing).
  double moveDir = 0;

  /// Segurado, não um evento -- guarda vale enquanto o botão estiver
  /// pressionado.
  bool blockHeld = false;

  bool jumpQueued = false;
  bool punchQueued = false;
  bool kickQueued = false;

  void consumeJump() => jumpQueued = false;
  void consumePunch() => punchQueued = false;
  void consumeKick() => kickQueued = false;
}
